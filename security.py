"""Server-side capability sessions, bounded input, and security event recording.

No identity-provider claims are made: these are possession credentials for a prototype.
"""
import hashlib
import hmac
import re
import secrets
import unicodedata
from datetime import timedelta
from pathlib import Path


class SecurityError(ValueError):
    pass


ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def new_owner_code():
    return "PNU-" + "".join(secrets.choice(ALPHABET) for _ in range(4))


def normalize_code(value):
    value = unicodedata.normalize("NFKC", str(value)).strip(" \t\r\n\ufeff\u200b")
    if len(value) > 128:
        raise SecurityError("확인 코드를 확인해 주세요.")
    compact = re.sub(r"[\s-]", "", value).upper()
    if compact == "PNUDEMO":
        return "PNU-DEMO"
    if len(compact) == 7 and compact.startswith("PNU") and all(c in ALPHABET for c in compact[3:]):
        return "PNU-" + compact[3:]
    if len(compact) == 27 and compact.startswith("PNU") and all(c in ALPHABET for c in compact[3:]):
        return "PNU-" + "-".join(compact[i:i + 4] for i in range(3, 27, 4))
    # Previous URL-safe codes are case sensitive. Never lowercase them.
    return value


def digest(value):
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def clean(value, label, maximum=1000, minimum=0):
    if not isinstance(value, str):
        raise SecurityError(f"{label}을 확인해 주세요.")
    value = unicodedata.normalize("NFC", value).strip()
    if not minimum <= len(value) <= maximum or any(ord(c) < 32 and c not in "\n\t\r" for c in value):
        raise SecurityError(f"{label}: {minimum}~{maximum}자로 입력해 주세요.")
    return value


def positive_id(value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise SecurityError("항목을 확인해 주세요.")
    return value


def event(con, now, action, subject=None, outcome="ok"):
    # Do not record codes, OTPs, evidence, or user-provided messages.
    con.execute("INSERT INTO security_events(created_at,action,subject_id,outcome) VALUES (?,?,?,?)",
                (now.isoformat(), action, subject, outcome))


def limited(con, now, bucket, limit=10, seconds=300):
    cutoff = (now - timedelta(seconds=seconds)).isoformat()
    con.execute("DELETE FROM attempts WHERE created_at<?", ((now - timedelta(days=1)).isoformat(),))
    key = digest(bucket)
    count = con.execute("SELECT COUNT(*) FROM attempts WHERE bucket=? AND created_at>=?", (key, cutoff)).fetchone()[0]
    if count >= limit:
        raise SecurityError("시도가 많습니다. 잠시 후 다시 시도해 주세요.")
    con.execute("INSERT INTO attempts(bucket,created_at) VALUES (?,?)", (key, now.isoformat()))


def otp_digest(code, salt):
    return hashlib.pbkdf2_hmac("sha256", str(code).encode(), bytes.fromhex(salt), 200_000).hex()


def same(a, b):
    return hmac.compare_digest(str(a), str(b))


def image_path(data_dir, relative):
    if not relative or not re.fullmatch(r"images/[a-f0-9]{32}\.jpg", str(relative)):
        return None
    base = (Path(data_dir) / "images").resolve()
    if base.parent != Path(data_dir).resolve():
        return None
    path = (Path(data_dir) / relative).resolve()
    return path if path.parent == base and path.is_file() else None


def safe_csv(frame):
    result = frame.copy()
    for name in result.select_dtypes(include=["object", "str", "string"]).columns:
        result[name] = result[name].map(lambda v: "'" + v if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@")) else v)
    return result.to_csv(index=False).encode("utf-8-sig")
