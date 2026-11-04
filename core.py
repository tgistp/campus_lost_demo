"""Pandas 검색 및 캠퍼스 규모의 경로 거리 계산. 좌표는 (위도, 경도)."""
import math
import hashlib
import secrets
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import security as sec
from semantic_ai import judge_answer,ModelUnavailable

BASE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("CAMPUS_DATA_DIR", str(BASE / "data")))
CATEGORIES = ["지갑", "전자기기", "카드·학생증", "가방", "의류", "우산", "기타"]
COLORS = ["검정", "흰색", "회색", "파랑", "빨강", "초록", "갈색", "노랑", "분홍", "보라", "베이지", "민트", "기타"]
KST = timezone(timedelta(hours=9))


def now():
    return datetime.now(KST).replace(tzinfo=None, microsecond=0)


@contextmanager
def connect():
    DATA.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DATA / "campus.db", timeout=15)
    try:
        con.execute("PRAGMA foreign_keys=ON")
        with con:
            yield con
    finally:
        con.close()


def init_db():
    with connect() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY, title TEXT NOT NULL, category TEXT NOT NULL,
            color TEXT NOT NULL, description TEXT NOT NULL, place TEXT NOT NULL,
            lat REAL, lon REAL, found_at TEXT NOT NULL,
            storage TEXT NOT NULL, image TEXT NOT NULL DEFAULT '',
            private_hint TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT '습득물 등록');
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY, title TEXT NOT NULL, category TEXT NOT NULL,
            color TEXT NOT NULL, keywords TEXT NOT NULL, start_at TEXT NOT NULL,
            end_at TEXT NOT NULL, route TEXT NOT NULL, radius INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS claims (
            id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL REFERENCES items(id),
            alias TEXT NOT NULL, evidence TEXT NOT NULL, created_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT '접수');
        CREATE TABLE IF NOT EXISTS registrations (
            item_id INTEGER PRIMARY KEY REFERENCES items(id), code_hash TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS pickups (
            id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL UNIQUE REFERENCES items(id),
            note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, seen_at TEXT);
        CREATE TABLE IF NOT EXISTS owners (code_hash TEXT PRIMARY KEY, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS owner_aliases (
            alias_hash TEXT PRIMARY KEY, owner_hash TEXT NOT NULL REFERENCES owners(code_hash));
        CREATE TABLE IF NOT EXISTS owner_sessions (
            token_hash TEXT PRIMARY KEY, owner_hash TEXT NOT NULL REFERENCES owners(code_hash),
            expires_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS report_owners (
            report_id INTEGER PRIMARY KEY REFERENCES reports(id), owner_hash TEXT NOT NULL REFERENCES owners(code_hash));
        CREATE TABLE IF NOT EXISTS pickup_requests (
            id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL REFERENCES items(id),
            requester_hash TEXT NOT NULL REFERENCES owners(code_hash), evidence TEXT NOT NULL,
            note TEXT NOT NULL, otp_hash TEXT NOT NULL, otp_salt TEXT NOT NULL,
            expires_at TEXT NOT NULL, created_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT '확인 대기');
        CREATE TABLE IF NOT EXISTS attempts (bucket TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS attempts_lookup ON attempts(bucket,created_at);
        CREATE TABLE IF NOT EXISTS security_events (
            id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, action TEXT NOT NULL, subject_id INTEGER, outcome TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS app_metadata (key TEXT PRIMARY KEY,value TEXT NOT NULL);
        """)
        con.execute("INSERT OR IGNORE INTO owners SELECT DISTINCT code_hash, ? FROM registrations", (now().isoformat(),))
        con.commit()
        # 기존 버전의 좌표 필수 제약만 해제합니다. 등록물과 반환 요청은 유지합니다.
        columns = {r[1]: r for r in con.execute("PRAGMA table_info(items)")}
        if columns["lat"][3] or columns["lon"][3]:
            backup = sqlite3.connect(DATA / "campus-before-optional-location.db")
            try:
                con.backup(backup)
            finally:
                backup.close()
            con.execute("PRAGMA foreign_keys=OFF")
            con.execute("BEGIN IMMEDIATE")
            con.execute("""CREATE TABLE items_optional_location (
                id INTEGER PRIMARY KEY, title TEXT NOT NULL, category TEXT NOT NULL,
                color TEXT NOT NULL, description TEXT NOT NULL, place TEXT NOT NULL,
                lat REAL, lon REAL, found_at TEXT NOT NULL,
                storage TEXT NOT NULL, image TEXT NOT NULL DEFAULT '',
                private_hint TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT '습득물 등록')""")
            fields = "id,title,category,color,description,place,lat,lon,found_at,storage,image,private_hint,status"
            con.execute(f"INSERT INTO items_optional_location ({fields}) SELECT {fields} FROM items")
            con.execute("DROP TABLE items")
            con.execute("ALTER TABLE items_optional_location RENAME TO items")
            if con.execute("PRAGMA foreign_key_check").fetchall():
                raise RuntimeError("데이터 연결을 확인할 수 없어 변경을 취소했습니다.")
        if "is_demo_image" not in {r[1] for r in con.execute("PRAGMA table_info(items)")}:
            con.execute("ALTER TABLE items ADD COLUMN is_demo_image INTEGER NOT NULL DEFAULT 0")
        if "verification_question" not in {r[1] for r in con.execute("PRAGMA table_info(items)")}:
            con.execute("ALTER TABLE items ADD COLUMN verification_question TEXT NOT NULL DEFAULT ''")
        if "demo_key" not in {r[1] for r in con.execute("PRAGMA table_info(items)")}:
            con.execute("ALTER TABLE items ADD COLUMN demo_key TEXT")
            con.execute("CREATE UNIQUE INDEX IF NOT EXISTS items_demo_key ON items(demo_key)")
        request_columns={r[1] for r in con.execute("PRAGMA table_info(pickup_requests)")}
        for field,kind in {"verification_score":"REAL","verification_engine":"TEXT","verification_reason":"TEXT"}.items():
            if field not in request_columns:con.execute(f"ALTER TABLE pickup_requests ADD COLUMN {field} {kind}")
        policy=con.execute("SELECT value FROM app_metadata WHERE key='answer_policy'").fetchone()
        if not policy or policy[0]!="state-checks-v0.12":
            # Previously exposed places cannot be recalled, but stale automatic
            # approvals must not authorize new handovers under the old policy.
            con.execute("""UPDATE pickup_requests SET status='확인 대기',verification_score=NULL,
                verification_reason='인증 기준이 업데이트되었습니다. 답변을 다시 확인해 주세요.'
                WHERE status='소유 확인 완료' AND verification_engine='local-minilm-onnx' AND expires_at>?""",
                (now().isoformat(),))
            con.execute("INSERT OR REPLACE INTO app_metadata VALUES ('answer_policy','state-checks-v0.12')")
        con.commit()
        version=hashlib.sha256((BASE/"places.csv").read_bytes()).hexdigest()
        previous=con.execute("SELECT value FROM app_metadata WHERE key='place_coordinates'").fetchone()
        if not previous or previous[0]!=version:
            if con.execute("SELECT 1 FROM items LIMIT 1").fetchone() and not (DATA/"campus-before-coordinate-update.db").exists():
                backup=sqlite3.connect(DATA/"campus-before-coordinate-update.db")
                try:con.backup(backup)
                finally:backup.close()
            for name,p in places().iterrows():
                con.execute("UPDATE items SET lat=?,lon=? WHERE place=?",(float(p.lat),float(p.lon),name))
            con.execute("INSERT OR REPLACE INTO app_metadata VALUES ('place_coordinates',?)",(version,))


def inventory_revision():
    with connect() as con:
        return (tuple(con.execute("SELECT id,status FROM items ORDER BY id").fetchall()),
                tuple(con.execute("SELECT id,status FROM pickup_requests ORDER BY id").fetchall()))


def read(table):
    if table != "items":
        raise sec.SecurityError("비공개 자료는 인증 후 조회해야 합니다.")
    with connect() as con:
        return pd.read_sql_query("""SELECT id,title,category,color,description,place,lat,lon,
            found_at,image,status,is_demo_image,verification_question FROM items ORDER BY id DESC""", con)


def insert(table, values, owner_session=None):
    allowed = {
        "items": {"title", "category", "color", "description", "place", "lat", "lon", "found_at", "storage", "image", "private_hint", "verification_question"},
        "reports": {"title", "category", "color", "keywords", "start_at", "end_at", "route", "radius"},
    }
    if table not in allowed or not set(values).issubset(allowed[table]):
        raise sec.SecurityError("허용되지 않는 필드입니다.")
    values = dict(values)
    for name, maximum in {"title":80,"description":1000,"storage":250,"private_hint":500,"verification_question":200,"keywords":200}.items():
        if name in values:
            values[name] = sec.clean(values[name], name, maximum, 1 if name in {"title","description","storage"} else 0)
    if values.get("category") not in CATEGORIES or values.get("color") not in COLORS:
        raise sec.SecurityError("종류와 색상을 확인해 주세요.")
    if table == "items":
        place = values.get("place")
        p = places()
        if place not in ["없음"] + list(p.index):
            raise sec.SecurityError("발견 장소를 확인해 주세요.")
        values["lat"] = None if place == "없음" else float(p.loc[place, "lat"])
        values["lon"] = None if place == "없음" else float(p.loc[place, "lon"])
        if pd.Timestamp(values.get("found_at")) > pd.Timestamp(now()) or pd.isna(pd.Timestamp(values.get("found_at"))):
            raise sec.SecurityError("발견 시각을 확인해 주세요.")
        if values.get("image") and not sec.image_path(DATA, values["image"]):
            raise sec.SecurityError("저장한 사진을 확인해 주세요.")
    else:
        try:
            route = __import__("json").loads(values["route"])
            if not isinstance(route, list) or len(route) > 6 or any(n not in places().index for n in route):
                raise ValueError()
            start, end = pd.Timestamp(values["start_at"]), pd.Timestamp(values["end_at"])
            if pd.isna(start) or pd.isna(end) or start > end or end > pd.Timestamp(now()) or values["radius"] not in (50,100,200):
                raise ValueError()
        except (ValueError, TypeError, KeyError):
            raise sec.SecurityError("분실 시간과 경로를 확인해 주세요.") from None
    with connect() as con:
        owner_hash = require_session(con, owner_session)
        sec.limited(con, now(), "create:" + owner_hash, limit=20, seconds=3600)
        keys = ",".join(values)
        marks = ",".join("?" for _ in values)
        item_id = con.execute(f"INSERT INTO {table} ({keys}) VALUES ({marks})", list(values.values())).lastrowid
        if table == "items":
            con.execute("INSERT INTO registrations (item_id,code_hash) VALUES (?,?)", (item_id, owner_hash))
        else:
            con.execute("INSERT INTO report_owners (report_id,owner_hash) VALUES (?,?)", (item_id, owner_hash))
        sec.event(con, now(), "create_" + table, item_id)
        return item_id


def code_hash(code):
    return sec.digest(sec.normalize_code(code))


def require_session(con, token):
    if not isinstance(token, str) or not 20 <= len(token) <= 128:
        raise sec.SecurityError("확인 코드로 다시 연결해 주세요.")
    row = con.execute("SELECT owner_hash FROM owner_sessions WHERE token_hash=? AND expires_at>?",
                      (sec.digest(token), now().isoformat())).fetchone()
    if not row:
        raise sec.SecurityError("연결이 만료됐습니다. 확인 코드로 다시 연결해 주세요.")
    return row[0]


def issue_session(con, owner_hash):
    token = secrets.token_urlsafe(32)
    con.execute("DELETE FROM owner_sessions WHERE expires_at<=?", (now().isoformat(),))
    con.execute("INSERT INTO owner_sessions VALUES (?,?,?)", (sec.digest(token), owner_hash, (now() + timedelta(hours=1)).isoformat()))
    return token


def create_owner(actor):
    with connect() as con:
        sec.limited(con, now(), "new-owner:" + str(actor), limit=10, seconds=3600)
        sec.limited(con, now(), "new-owner-global", limit=100, seconds=3600)
        code = "PNU-DEMO" if not con.execute("SELECT 1 FROM owners LIMIT 1").fetchone() else sec.new_owner_code()
        hashed = code_hash(code)
        while con.execute("SELECT 1 FROM owners WHERE code_hash=? UNION SELECT 1 FROM owner_aliases WHERE alias_hash=?", (hashed,hashed)).fetchone():
            code = sec.new_owner_code()
            hashed = code_hash(code)
        con.execute("INSERT INTO owners VALUES (?,?)", (hashed, now().isoformat()))
        token = issue_session(con, hashed)
        sec.event(con, now(), "owner_created")
    return code, token


def authenticate_owner(code, actor):
    hashed = code_hash(code)
    # Attempt counters are committed independently of the authentication result.
    with connect() as con:
        sec.limited(con, now(), "auth-global", 100, 60)
        sec.limited(con, now(), "auth-actor:" + str(actor), 10, 300)
        sec.limited(con, now(), "auth-target:" + hashed, 10, 300)
    with connect() as con:
        allowed = con.execute("SELECT owner_hash FROM owner_aliases WHERE alias_hash=?", (hashed,)).fetchone()
        if not allowed:
            allowed = con.execute("SELECT code_hash FROM owners WHERE code_hash=?", (hashed,)).fetchone()
        if allowed:
            token = issue_session(con, allowed[0])
        sec.event(con, now(), "owner_login", outcome="ok" if allowed else "denied")
    if not allowed:
        raise sec.SecurityError("코드를 확인할 수 없습니다. 이전 버전 등록물은 로컬 복구 도구를 이용해 주세요.")
    return token


def logout(token):
    with connect() as con:
        con.execute("DELETE FROM owner_sessions WHERE token_hash=?", (sec.digest(token),))
        sec.event(con, now(), "logout")


def owner_items(token):
    with connect() as con:
        owner_hash = require_session(con, token)
        return pd.read_sql_query("""SELECT i.*, p.created_at AS picked_up_at, p.note AS pickup_note, p.seen_at
            FROM items i JOIN registrations r ON r.item_id=i.id
            LEFT JOIN pickups p ON p.item_id=i.id WHERE r.code_hash=? ORDER BY i.id DESC""",
            con, params=[owner_hash])


def owner_reports(token):
    with connect() as con:
        owner_hash = require_session(con, token)
        return pd.read_sql_query("SELECT p.* FROM reports p JOIN report_owners r ON r.report_id=p.id WHERE r.owner_hash=? ORDER BY p.id DESC",
                                 con, params=[owner_hash])


def delete_report(report_id, token):
    report_id = sec.positive_id(report_id)
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        owner_hash = require_session(con, token)
        if not con.execute("SELECT 1 FROM report_owners WHERE report_id=? AND owner_hash=?",
                           (report_id, owner_hash)).fetchone():
            raise sec.SecurityError("본인이 등록한 분실 신고만 삭제할 수 있습니다. 이미 삭제된 신고인지 확인해 주세요.")
        con.execute("DELETE FROM report_owners WHERE report_id=? AND owner_hash=?", (report_id, owner_hash))
        con.execute("DELETE FROM reports WHERE id=?", (report_id,))
        sec.event(con, now(), "delete_report", report_id)


def mark_collected(item_id, note=""):
    raise sec.SecurityError("등록자 승인과 일회용 수령번호 확인이 필요합니다.")


def acknowledge_pickup(item_id, token):
    with connect() as con:
        owner_hash = require_session(con, token)
        return con.execute("""UPDATE pickups SET seen_at=? WHERE item_id=? AND seen_at IS NULL
            AND EXISTS (SELECT 1 FROM registrations r WHERE r.item_id=pickups.item_id AND r.code_hash=?)""",
            (now().isoformat(), item_id, owner_hash)).rowcount > 0


def request_pickup(item_id, token, evidence, note=""):
    item_id = sec.positive_id(item_id)
    evidence = sec.clean(evidence, "확인 질문의 답변", 1000, 1)
    note = sec.clean(note, "메시지", 500)
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        requester = require_session(con, token)
        row = con.execute("SELECT i.status,r.code_hash,i.private_hint,i.verification_question FROM items i JOIN registrations r ON r.item_id=i.id WHERE i.id=?", (item_id,)).fetchone()
        if not row or row[0] == "반환 완료":
            raise sec.SecurityError("수령 인증을 접수할 수 없습니다. 등록자 연결과 처리 상태를 확인해 주세요.")
        if row[1] == requester:
            raise sec.SecurityError("등록자와 수령자는 서로 다른 확인 코드로 연결해야 합니다.")
        sec.limited(con, now(), "request:" + requester, 10, 3600)
        existing = con.execute("SELECT id,status FROM pickup_requests WHERE item_id=? AND requester_hash=? AND status IN ('확인 대기','소유 확인 완료') AND expires_at>? ORDER BY id DESC LIMIT 1",
                               (item_id, requester, now().isoformat())).fetchone()
        if existing and existing[1] == "소유 확인 완료":
            raise sec.SecurityError("이미 본인 확인이 완료됐습니다. 내 수령 인증에서 보관 장소를 확인해 주세요.")
        sec.limited(con, now(), f"answer:{item_id}:{requester}", 5, 3600)
        otp = f"{secrets.randbelow(100_000_000):08d}"
        salt = secrets.token_hex(16)
        judgement={"passed":False,"score":None,"engine":"manual","reason":"등록자가 확인할 질문·정답을 설정하지 않았습니다."}
        if row[3] and row[2]:
            try:judgement=judge_answer(row[2],evidence,row[3])
            except ModelUnavailable:
                judgement.update(engine="unavailable",reason="로컬 AI 모델을 불러오지 못했습니다. 모델 파일과 라이브러리를 확인해 주세요.")
        status = "소유 확인 완료" if judgement["passed"] else "확인 대기"
        if existing:
            rid = existing[0]
            con.execute("""UPDATE pickup_requests SET evidence=?,note=?,otp_hash=?,otp_salt=?,expires_at=?,status=? WHERE id=?""",
                (evidence, note, sec.otp_digest(otp, salt), salt, (now() + timedelta(hours=1)).isoformat(), status, rid))
        else:
            rid = con.execute("""INSERT INTO pickup_requests
                (item_id,requester_hash,evidence,note,otp_hash,otp_salt,expires_at,created_at,status) VALUES (?,?,?,?,?,?,?,?,?)""",
                (item_id, requester, evidence, note, sec.otp_digest(otp, salt), salt,
                 (now() + timedelta(hours=1)).isoformat(), now().isoformat(), status)).lastrowid
        sec.event(con, now(), "pickup_requested", item_id)
        if status == "소유 확인 완료":
            sec.event(con, now(), "ownership_auto_approved", rid)
        con.execute("UPDATE pickup_requests SET verification_score=?,verification_engine=?,verification_reason=? WHERE id=?",
                    (judgement["score"],judgement["engine"],judgement["reason"],rid))
    return rid, otp


def pickup_requests(token, received=True):
    with connect() as con:
        owner_hash = require_session(con, token)
        condition = "r.code_hash=?" if received else "p.requester_hash=?"
        return pd.read_sql_query(f"""SELECT p.id,p.item_id,p.evidence,p.note,p.expires_at,p.created_at,p.status,i.title,
            p.verification_score,p.verification_engine,p.verification_reason,
            CASE WHEN p.status='반환 완료' OR (p.status='소유 확인 완료' AND p.expires_at>?) THEN i.storage ELSE NULL END AS storage
            FROM pickup_requests p JOIN items i ON i.id=p.item_id JOIN registrations r ON r.item_id=p.item_id
            WHERE {condition} ORDER BY p.id DESC""", con, params=[now().isoformat(), owner_hash])


def approve_ownership(request_id, token):
    with connect() as con:
        owner_hash = require_session(con, token)
        changed = con.execute("""UPDATE pickup_requests SET status='소유 확인 완료'
            WHERE id=? AND status='확인 대기' AND expires_at>?
            AND EXISTS (SELECT 1 FROM registrations r JOIN items i ON i.id=r.item_id
                WHERE r.item_id=pickup_requests.item_id AND r.code_hash=? AND i.status<>'반환 완료')""",
            (sec.positive_id(request_id), now().isoformat(), owner_hash)).rowcount
        if not changed:
            raise sec.SecurityError("권한 또는 인증 유효시간을 확인해 주세요.")
        sec.event(con, now(), "ownership_approved", request_id)


def renew_pickup_otp(request_id, token):
    """Only the verified claimant may replace a live pickup code."""
    request_id=sec.positive_id(request_id)
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        requester=require_session(con,token)
        row=con.execute("""SELECT p.otp_hash,p.otp_salt FROM pickup_requests p JOIN items i ON i.id=p.item_id
            WHERE p.id=? AND p.requester_hash=? AND p.status='소유 확인 완료' AND p.expires_at>?
            AND i.status<>'반환 완료'""",(request_id,requester,now().isoformat())).fetchone()
        if not row:
            raise sec.SecurityError("수령자 연결과 인증 유효시간을 확인해 주세요. 만료됐다면 특징을 다시 인증해 주세요.")
        sec.limited(con,now(),f"renew-otp:{request_id}",3,3600)
        otp=f"{secrets.randbelow(100_000_000):08d}"
        while sec.same(sec.otp_digest(otp,row[1]),row[0]):
            otp=f"{secrets.randbelow(100_000_000):08d}"
        salt=secrets.token_hex(16)
        con.execute("UPDATE pickup_requests SET otp_hash=?,otp_salt=? WHERE id=?",
                    (sec.otp_digest(otp,salt),salt,request_id))
        sec.event(con,now(),"pickup_otp_renewed",request_id)
    return otp


def complete_pickup(request_id, token, otp, handoff=False, *, as_recipient=False):
    request_id = sec.positive_id(request_id)
    if handoff is not True or not isinstance(otp, str) or not __import__("re").fullmatch(r"[0-9]{8}", otp.strip()):
        raise sec.SecurityError("실제 전달을 확인하고 8자리 수령 인증번호를 입력해 주세요.")
    with connect() as con:
        owner_hash = require_session(con, token)
        scope = "p.requester_hash=?" if as_recipient is True else "r.code_hash=?"
        row = con.execute(f"""SELECT p.item_id,p.otp_hash,p.otp_salt,p.note FROM pickup_requests p
            JOIN registrations r ON r.item_id=p.item_id JOIN items i ON i.id=p.item_id
            WHERE p.id=? AND {scope} AND p.status='소유 확인 완료' AND p.expires_at>? AND i.status<>'반환 완료'""",
            (request_id, owner_hash, now().isoformat())).fetchone()
        if not row:
            raise sec.SecurityError("권한 또는 인증 유효시간을 확인해 주세요.")
        sec.limited(con, now(), f"otp:{request_id}:{row[1]}", 5, 3600)
    correct = sec.same(sec.otp_digest(otp.strip(), row[2]), row[1])
    with connect() as con:
        sec.event(con, now(), "pickup_otp", request_id, "ok" if correct else "denied")
    if not correct:
        raise sec.SecurityError("수령 인증번호를 확인해 주세요. 5회 실패했다면 수령자가 ‘수령번호 다시 받기’를 눌러 주세요.")
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        # Recheck the session, expiry, status, and owner inside the final transaction.
        owner_hash = require_session(con, token)
        scope = "requester_hash=?" if as_recipient is True else "EXISTS (SELECT 1 FROM registrations r WHERE r.item_id=pickup_requests.item_id AND r.code_hash=?)"
        changed = con.execute(f"""UPDATE pickup_requests SET status='반환 완료' WHERE id=? AND status='소유 확인 완료'
            AND expires_at>? AND {scope} AND otp_hash=?""",
            (request_id, now().isoformat(), owner_hash, row[1])).rowcount
        if not changed or not con.execute("UPDATE items SET status='반환 완료' WHERE id=? AND status<>'반환 완료'", (row[0],)).rowcount:
            raise sec.SecurityError("이미 처리됐거나 인증이 만료됐습니다.")
        con.execute("INSERT INTO pickups(item_id,note,created_at) VALUES (?,?,?)", (row[0], row[3], now().isoformat()))
        con.execute("UPDATE pickup_requests SET status='종료' WHERE item_id=? AND id<>? AND status IN ('확인 대기','소유 확인 완료')", (row[0], request_id))
        con.execute("UPDATE claims SET status='종료' WHERE item_id=? AND status IN ('접수','확인 중')", (row[0],))
        sec.event(con, now(), "pickup_completed_by_recipient" if as_recipient is True else "pickup_completed", row[0])


def confirm_received(request_id, token, otp, received=False):
    """Authenticated, ownership-verified claimant acknowledges actual collection."""
    return complete_pickup(request_id, token, otp, handoff=received, as_recipient=True)


def reject_pickup(request_id, token):
    with connect() as con:
        owner_hash = require_session(con, token)
        changed = con.execute("""UPDATE pickup_requests SET status='반려' WHERE id=? AND status IN ('확인 대기','소유 확인 완료')
            AND EXISTS (SELECT 1 FROM registrations r WHERE r.item_id=pickup_requests.item_id AND r.code_hash=?)""",
            (sec.positive_id(request_id), owner_hash)).rowcount
        if not changed:
            raise sec.SecurityError("권한 또는 처리 상태를 확인해 주세요.")
        sec.event(con, now(), "pickup_rejected", request_id)


def places():
    return pd.read_csv(BASE / "places.csv").set_index("name")


def route_coords(names):
    p = places()
    return [tuple(p.loc[n, ["lat", "lon"]].astype(float)) for n in names if n in p.index]


def route_distance(point, route):
    """국소 평면 근사. 선분 내부와 양 끝점을 모두 고려하며 단위는 미터."""
    if not route:
        raise ValueError("경로가 비어 있습니다")
    lat0, lon0 = point
    def xy(p):
        return ((p[1] - lon0) * math.pi / 180 * 6371000 * math.cos(math.radians(lat0)),
                (p[0] - lat0) * math.pi / 180 * 6371000)
    points = [xy(p) for p in route]
    best = min(math.hypot(*p) for p in points)
    for (ax, ay), (bx, by) in zip(points, points[1:]):
        dx, dy = bx - ax, by - ay
        norm = dx * dx + dy * dy
        t = max(0, min(1, -(ax * dx + ay * dy) / norm)) if norm else 0
        best = min(best, math.hypot(ax + t * dx, ay + t * dy))
    return best


def search(items, category="전체", color="전체", keywords="", route=None,
           radius=100, start=None, end=None, strict=True):
    result = items.loc[items.status.ne("반환 완료")].copy()
    parts = ["category_score", "color_score", "keyword_score", "location_score"]
    for part in parts:
        result[part] = 0.0
    if category != "전체":
        result["category_score"] = result.category.eq(category) * 40.0
        if strict:
            result = result.loc[result.category.eq(category)].copy()
    if color != "전체":
        result["color_score"] = result.color.eq(color) * 20.0
        if strict:
            result = result.loc[result.color.eq(color)].copy()
    text = (result.title + " " + result.description + " " + result.color + " " + result.category).str.casefold()
    tokens = list(dict.fromkeys(keywords.casefold().split()))
    for token in tokens:
        hit = text.str.contains(token, regex=False)
        result["keyword_score"] += hit * (20 / len(tokens))
        if strict:
            result = result.loc[hit].copy()
    if route:
        result = result.dropna(subset=["lat", "lon"]).copy()
        distances = [route_distance((r.lat, r.lon), route) for r in result.itertuples()]
        result["distance_m"] = pd.Series(distances, index=result.index, dtype=float)
        result = result.loc[result.distance_m.le(radius)].copy()
        result["location_score"] = (1 - result.distance_m / radius) * 20
    if start is not None:
        result = result.loc[pd.to_datetime(result.found_at).ge(pd.Timestamp(start))].copy()
    if end is not None:
        result = result.loc[pd.to_datetime(result.found_at).le(pd.Timestamp(end))].copy()
    result["score"] = result[parts].sum(axis=1)
    if not strict:
        result = result.loc[result.score.gt(0)].copy()
    result = result.sort_values(["score", "found_at"], ascending=False)
    result.attrs["score_max"] = (40 if category != "전체" else 0) + (20 if color != "전체" else 0) + (20 if tokens else 0) + (20 if route else 0)
    result.attrs["score_limits"] = dict(zip(parts, (40 if category != "전체" else 0,
        20 if color != "전체" else 0, 20 if tokens else 0, 20 if route else 0)))
    return result


def seed_demo():
    if os.getenv("CAMPUS_ALLOW_DEMO") != "1":
        raise sec.SecurityError("예시 데이터 생성은 로컬 개발 모드에서만 사용할 수 있습니다.")
    p = places()
    with connect() as con:
        if con.execute("SELECT COUNT(*) FROM items").fetchone()[0]:
            return False
        samples = [
            ("검정 반지갑", "지갑", "검정", "가죽 재질, 작은 은색 로고", "의생명과학도서관"),
            ("흰색 무선 이어폰", "전자기기", "흰색", "투명 케이스, 별 스티커", "간호대학"),
            ("파란 장우산", "우산", "파랑", "나무 손잡이, 긴 우산", "나래관"),
            ("회색 후드 집업", "의류", "회색", "앞주머니, 면 소재", "경암공학관"),
        ]
        for i, (title, category, color, desc, place) in enumerate(samples):
            con.execute("""INSERT INTO items
                (title,category,color,description,place,lat,lon,found_at,storage,private_hint)
                VALUES (?,?,?,?,?,?,?,?,?,?)""", (title, category, color, desc, place,
                float(p.loc[place, "lat"]), float(p.loc[place, "lon"]),
                (now() - timedelta(hours=i + 1)).isoformat(), "데모 보관함 (실제 보관처 아님)",
                "데모 확인 특징: 안쪽에 별 표시"))
            item_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
            con.execute("INSERT INTO registrations (item_id,code_hash) VALUES (?,?)", (item_id, code_hash("PNU-DEMO")))
        con.execute("INSERT OR IGNORE INTO owners VALUES (?,?)", (code_hash("PNU-DEMO"), now().isoformat()))
    from demo_photos import install_demo_photos
    install_demo_photos()
    return True
