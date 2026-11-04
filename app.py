import html
import json
import secrets
import sqlite3
from datetime import datetime, time, timedelta

import folium
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from streamlit_folium import st_folium

import core
import security as sec
from uploads import save_image

st.set_page_config(page_title="양산캠퍼스 분실물", layout="wide", initial_sidebar_state="collapsed")
try:
    core.init_db()
except Exception:
    st.error("저장소를 열지 못했습니다. 프로그램을 다시 실행하거나 로컬 관리자에게 문의해 주세요.")
    st.stop()
PLACES = core.places()
st.session_state.setdefault("actor_id", secrets.token_urlsafe(24))
PAGES = ["처음", "분실물 찾기", "습득물 등록", "분실 신고 · 추천", "등록 내역"]
LABELS = dict(zip(PAGES, ["처음", "물건 찾기", "주운 물건 등록", "분실 신고", "내 등록·인증 내역"]))
if st.session_state.get("page") not in PAGES:
    st.session_state["page"] = "처음"

st.markdown("""<style>
.block-container{max-width:1140px;padding-top:3.7rem}
h1{font-size:1.7rem!important;letter-spacing:-.04em}h2{font-size:1.25rem!important}h3{font-size:1.05rem!important}
.st-key-page{border-bottom:1px solid color-mix(in srgb,currentColor 18%,transparent);padding-bottom:.4rem;margin-bottom:1rem}
.st-key-page [role='radiogroup']{gap:1.4rem}.st-key-page [data-baseweb='radio']>div:first-child,.st-key-page [data-testid='stRadioOption']>div>div:first-child{display:none}
.st-key-page label{padding:.4rem .1rem;border-bottom:2px solid transparent}.st-key-page label:has(input:checked){border-color:#1ed760;font-weight:700}
.st-key-page label:focus-within{outline:2px solid #1ed760;outline-offset:3px}
button[kind='primary']{background:#1ed760!important;border-color:#1ed760!important;color:#06170c!important;border-radius:5px!important}
button[kind='primary']:hover{background:#3ee67b!important}
[class*='st-key-item_']{border:1px solid color-mix(in srgb,currentColor 13%,transparent);background:color-mix(in srgb,currentColor 3%,transparent);padding:1rem;border-radius:7px}
.photo-empty{height:96px;display:flex;align-items:center;justify-content:center;background:color-mix(in srgb,currentColor 7%,transparent);font-size:.8rem;color:inherit}
.item-status{font-size:.75rem;color:#08783b;background:#ddf7e8;padding:3px 7px;border-radius:3px}
</style>""", unsafe_allow_html=True)

if st.session_state["page"] == "처음":
    st.markdown("<style>.block-container{max-width:none;padding:0}[data-testid='stHeader']{display:none}</style>", unsafe_allow_html=True)
    landing = components.declare_component("campus_start", path=str(core.BASE / "landing" / "dist"))
    result = landing(key="start_" + str(st.session_state.get("start_generation", 0)), default=None)
    if result in ("lost", "found"):
        st.session_state["page"] = "분실 신고 · 추천" if result == "lost" else "습득물 등록"
        st.session_state["start_generation"] = st.session_state.get("start_generation", 0) + 1
        st.rerun()
    st.stop()


def guard(function, *args, **kwargs):
    try:
        return True, function(*args, **kwargs)
    except sec.SecurityError as exc:
        st.error(str(exc))
    except Exception:
        # No exception details or user content are sent to the browser.
        try:
            with core.connect() as con:
                sec.event(con, core.now(), "operation_error", outcome="error")
        except sqlite3.Error:
            pass
        st.error("처리를 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.")
    return False, None


def adopt_current_role(token, default="recipient"):
    if st.session_state.get("demo_active_role"):
        return
    role="registrant" if not core.owner_items(token).empty else "recipient" if not core.owner_reports(token).empty else default
    st.session_state["demo_active_role"]=role
    st.session_state[f"demo_{role}_session"]=token
    for name in ("issued_code","issued_otp"):
        st.session_state[f"demo_{role}_{name}"]=st.session_state.get(name)


def ensure_owner(role="recipient"):
    token = st.session_state.get("owner_session")
    if token:
        core.owner_items(token)
    else:
        code, token = core.create_owner(st.session_state["actor_id"])
        st.session_state["owner_session"] = token
        st.session_state["issued_code"] = code
    adopt_current_role(token,role)
    if st.session_state["demo_active_role"]!=role:
        change_demo_role(role,navigate=False)
    return st.session_state["owner_session"]


def change_demo_role(role, item_id=None, *, navigate=True):
    """Keep both locally created sessions for a one-browser classroom demo."""
    if role not in ("registrant","recipient"):
        raise sec.SecurityError("역할을 확인해 주세요.")
    current = st.session_state.get("owner_session")
    if not current:
        raise sec.SecurityError("확인 코드로 먼저 연결해 주세요.")
    adopt_current_role(current)
    if item_id is not None:
        mine = core.owner_items(current)
        if item_id not in mine.id.tolist():
            raise sec.SecurityError("이 물건의 등록자 연결을 먼저 확인해 주세요.")
        st.session_state["demo_registrant_session"] = current
        st.session_state["demo_active_role"] = "registrant"
    active = st.session_state.get("demo_active_role")
    if active:
        for name in ("issued_code", "issued_otp"):
            st.session_state[f"demo_{active}_{name}"] = st.session_state.get(name)
    target = st.session_state.get(f"demo_{role}_session")
    if target==current and active!=role:
        target=None
    if not target:
        code, target = core.create_owner(st.session_state["actor_id"])
        st.session_state[f"demo_{role}_session"] = target
        st.session_state[f"demo_{role}_issued_code"] = code
    core.owner_items(target)
    st.session_state["owner_session"] = target
    st.session_state["demo_active_role"] = role
    for name in ("issued_code", "issued_otp"):
        value = st.session_state.get(f"demo_{role}_{name}")
        if value:
            st.session_state[name] = value
        else:
            st.session_state.pop(name, None)
    if navigate:
        st.session_state["page"] = "분실물 찾기" if role=="recipient" else "등록 내역"


def role_action(role, item_id=None):
    guard(change_demo_role, role, item_id)


def clear_demo_roles():
    for key in list(st.session_state):
        if key.startswith("demo_"):
            del st.session_state[key]


st.caption("부산대학교 · 양산캠퍼스")
st.title("캠퍼스 분실물")
page = st.radio("메뉴", PAGES, format_func=LABELS.get, horizontal=True, label_visibility="collapsed", key="page")
if page == "처음":
    st.rerun()
if st.session_state.get("owner_session") and not st.session_state.get("demo_active_role"):
    try:adopt_current_role(st.session_state["owner_session"])
    except sec.SecurityError:pass
if st.session_state.get("owner_session"):
    a, b, c = st.columns([2, 1, 1])
    active = st.session_state.get("demo_active_role")
    a.caption("한 브라우저 시연 · 현재 " + ("등록자(주운 사람)" if active == "registrant" else "분실자(수령자)" if active=="recipient" else "역할 선택 필요"))
    b.button("등록자 역할로", on_click=role_action, args=("registrant",), disabled=active == "registrant")
    c.button("분실자 역할로", on_click=role_action, args=("recipient",), disabled=active == "recipient")
flash = st.session_state.pop("notice", "")
if flash:
    st.success(flash)
if st.session_state.pop("receipt_completed", False):
    st.toast("수령 완료로 처리했습니다. 물건 찾기 목록에서 제외했습니다.")


def show_access_code(key):
    if not st.session_state.get("issued_code"):
        return
    with st.expander("내역 확인 코드", expanded=False):
        st.caption("내 등록·인증 내역을 다시 열 때 사용하는 짧은 코드입니다.")
        st.code(st.session_state["issued_code"], language=None)
        st.download_button("코드 파일로 저장", st.session_state["issued_code"], "campus-code.txt", "text/plain", key=key+"_savecode")
        if st.button("코드를 보관했어요", key=key+"_hidecode"):
            del st.session_state["issued_code"]
            st.rerun()


def show_pickup_status(record, key):
    from semantic_ai import THRESHOLD
    expired = pd.Timestamp(record.expires_at) <= pd.Timestamp(core.now())
    if record.status == "반환 완료":
        st.success("수령 완료")
        return True
    if expired:
        st.warning("수령 인증 시간이 만료됐습니다. 답변을 다시 확인해 주세요.")
        return False
    if pd.notna(record.verification_score):
        st.caption(f"로컬 AI 의미 유사도 {record.verification_score*100:.1f} / 100 · 통과 기준 {THRESHOLD*100:.0f} (소유 확률 아님)")
    if record.status == "소유 확인 완료" and pd.notna(record.storage):
        st.success("특징 확인 완료 · 아직 수령 전입니다.")
        st.markdown("**수령 위치**")
        st.text(record.storage)
        st.caption("위 장소에서 실제로 물건을 받은 뒤 아래의 수령 완료를 눌러 주세요.")
        known = st.session_state.get("pickup_codes", {}).get(str(record.id))
        if not known and st.session_state.get("recent_pickup_request") == record.id:
            known = st.session_state.get("issued_otp")
        if known:
            with st.expander("수령 인증번호", expanded=st.session_state.get("renewed_pickup_id")==int(record.id)):
                st.code(known, language=None)
        st.caption("번호를 잊었거나 5회 잘못 입력했다면 다시 받으세요. 이전 번호는 사용할 수 없고 유효시간은 늘어나지 않습니다.")
        if st.button("수령번호 다시 받기",key=key+"_renew_otp"):
            ok,new_otp=guard(core.renew_pickup_otp,int(record.id),st.session_state.get("owner_session"))
            if ok:
                st.session_state.setdefault("pickup_codes",{})[str(record.id)]=new_otp
                st.session_state["issued_otp"]=new_otp
                st.session_state["recent_pickup_request"]=int(record.id)
                st.session_state["renewed_pickup_id"]=int(record.id)
                st.rerun()
        show_access_code(key)
        with st.form(key+"_receipt"):
            otp = known or st.text_input("저장한 8자리 수령 인증번호", type="password", max_chars=8)
            actual = st.checkbox("안내된 장소에서 실제로 물건을 받았습니다.")
            done = st.form_submit_button("수령 완료", type="primary")
        if done:
            ok, _ = guard(core.confirm_received, int(record.id), st.session_state.get("owner_session"), otp, received=actual)
            if ok:
                st.session_state["receipt_completed"] = True
                st.session_state.pop("pickup_item", None)
                st.session_state.pop("recent_pickup_request", None)
                st.session_state.setdefault("pickup_codes", {}).pop(str(record.id), None)
                st.rerun()
        return True
    if record.verification_engine == "unavailable":
        st.warning(record.verification_reason)
    elif record.status == "확인 대기":
        st.warning("자동 확인되지 않았습니다. 답변을 다시 입력하거나 등록자의 확인을 기다려 주세요.")
        if record.verification_reason:
            st.caption(record.verification_reason)
    return False


@st.fragment(run_every="10s")
def notifications():
    token = st.session_state.get("owner_session")
    if token:
        try:
            mine = core.owner_items(token)
            unread = mine.loc[mine.picked_up_at.notna() & mine.seen_at.isna()]
            requests = core.pickup_requests(token)
            pending = requests.loc[requests.status.eq("확인 대기") & pd.to_datetime(requests.expires_at).gt(pd.Timestamp(core.now()))]
            if len(unread):
                st.success(f"등록한 물건 {len(unread)}건이 반환 완료됐습니다. 내 등록·인증 내역에서 확인하세요.")
            if len(pending):
                st.info(f"소유 확인을 기다리는 건이 {len(pending)}건 있습니다. 내 등록·인증 내역에서 검토하세요.")
        except sec.SecurityError:
            st.caption("내역 연결이 만료됐습니다. 확인 코드로 다시 연결해 주세요.")


notifications()


def route_input(prefix):
    st.caption("이동 순서대로 선택하세요. ‘없음’은 제외합니다.")
    names = ["없음"] + list(PLACES.index)
    route = []
    count = st.session_state.get(prefix + "_stops", 3)
    for offset in range(0, count, 3):
        cols = st.columns(3)
        for i in range(offset, min(offset + 3, count)):
            selected = cols[i - offset].selectbox(f"{i + 1}번째 장소", names, key=f"{prefix}_{i}")
            if selected != "없음":
                route.append(selected)
    if count < 6 and st.button("장소 추가", key=prefix + "_add"):
        st.session_state[prefix + "_stops"] = count + 1
        st.rerun()
    radius = st.select_slider("경로에서 검색할 거리 (m)", [50, 100, 200], value=100, disabled=not route, key=prefix + "radius")
    st.caption(" → ".join(route) if route else "장소 조건 없음 · 캠퍼스 전체")
    return route, radius


def draw_map(results, route, radius):
    m = folium.Map(location=PLACES[["lat", "lon"]].mean().tolist(), zoom_start=16)
    geometry_path=core.BASE/"assets/campus/yangsan-buildings.geojson"
    if geometry_path.is_file():
        geometry=json.loads(geometry_path.read_text(encoding="utf-8"))
        for feature in geometry["features"]:
            feature["properties"]["name"]=html.escape(feature["properties"]["name"])
        folium.GeoJson(geometry,name="건물 위치",
            style_function=lambda _:dict(color="#648679",weight=1,fillColor="#17a957",fillOpacity=.06),
            tooltip=folium.GeoJsonTooltip(fields=["code","name"],aliases=["건물 번호","건물명"])).add_to(m)
    for name, p in PLACES.iterrows():
        folium.CircleMarker([p.lat, p.lon], radius=4, color="#638878", tooltip=html.escape(name)).add_to(m)
    if len(route) > 1:
        folium.PolyLine(route, color="#17a957", weight=4).add_to(m)
    for p in route:
        folium.Circle(p, radius=radius, color="#17a957", weight=1, fill=True, fill_opacity=.06).add_to(m)
    for row in results.dropna(subset=["lat", "lon"]).head(200).itertuples():
        folium.Marker([row.lat, row.lon], tooltip=html.escape(row.title), popup=html.escape(f"#{row.id} · {row.place}")).add_to(m)
    bounds=PLACES[["lat","lon"]]
    m.fit_bounds([[float(bounds.lat.min()),float(bounds.lon.min())],[float(bounds.lat.max()),float(bounds.lon.max())]],padding=[18,18],max_zoom=17)
    st_folium(m, height=340, use_container_width=True, returned_objects=[])
    st.caption("OpenStreetMap 건물 중심 좌표를 사용합니다. 경암공학관은 부지 중심이며 경로는 직선 연결입니다. 출입구·실제 보행로 기준의 정밀 길찾기는 아닙니다.")


def report_delete_button(report_id, title, token, key):
    with st.popover("분실 신고 삭제"):
        st.text(f'“{title}” 신고를 삭제할까요?')
        st.caption("이 신고와 추천 연결이 사라집니다. 주운 물건 등록에는 영향을 주지 않습니다.")
        if st.button("삭제하기", key=key, type="primary"):
            ok, _ = guard(core.delete_report, int(report_id), token)
            if ok:
                st.session_state.pop("selected_report", None)
                st.session_state["notice"] = "분실 신고를 삭제했습니다."
                st.rerun(scope="app")


def display_scores(result, key):
    if result.empty:
        return
    from matching_charts import score_charts
    st.caption("종류 최대 40점 · 색상/특징/위치 각각 최대 20점. 입력하지 않은 조건은 배점에서 제외합니다. 추천 점수는 소유 확률이나 측정된 정확도가 아닙니다.")
    ok, plots = guard(score_charts, result)
    if ok and plots:
        total_tab, parts_tab = st.tabs(["추천 점수 비교", "항목별 점수"])
        with total_tab:
            st.image(plots[0], use_container_width=True)
            st.download_button("점수 그래프 PNG 저장", plots[0], "matching-scores.png", "image/png", key=key+"_png")
        with parts_tab:
            st.image(plots[1], use_container_width=True)
        columns = ["id", "title", "category_score", "color_score", "keyword_score", "location_score", "score"]
        table = result[columns].rename(columns={"id":"번호", "title":"물건", "score":"총점", "category_score":"종류", "color_score":"색상", "keyword_score":"특징", "location_score":"위치"})
        if "distance_m" in result:
            table["동선 거리(m)"] = result.distance_m
        st.caption("그래프는 추천 점수가 높은 순서로 최대 10건을 표시합니다.")
        with st.expander("점수 계산 내역"):
            st.dataframe(table.round(1), hide_index=True)
            st.download_button("항목별 점수 CSV 저장", sec.safe_csv(table), "matching-scores.csv", "text/csv", key=key+"_csv")


def cards(results, prefix="search"):
    if results.empty:
        st.info("조건에 맞는 물건이 없습니다.")
        return
    requests = {}
    own_ids = set()
    token = st.session_state.get("owner_session")
    if token:
        try:
            sent = core.pickup_requests(token, received=False)
            requests = {int(r.item_id): r for r in sent.drop_duplicates("item_id", keep="first").itertuples()}
            own_ids = set(core.owner_items(token).id.tolist())
        except sec.SecurityError:
            pass
    total_pages = max(1, (len(results) + 9) // 10)
    page_key = prefix+"_page"
    result_ids = tuple(int(value) for value in results.id)
    if st.session_state.get(prefix+"_page_results") != result_ids:
        st.session_state.pop(page_key,None)
        st.session_state[prefix+"_page_results"] = result_ids
    number = min(max(1, st.session_state.get(page_key, 1)), total_pages)
    for row in results.iloc[(number-1)*10:number*10].itertuples():
        record = requests.get(int(row.id))
        with st.container(key=f"item_{row.id}"):
            a,b,c = st.columns([1,4,1.2])
            with a:
                path = sec.image_path(core.DATA,row.image)
                if path:
                    st.image(str(path),width=135)
                    if row.is_demo_image: st.caption("시연용 사진")
                else: st.markdown('<div class="photo-empty">사진 없음</div>',unsafe_allow_html=True)
            with b:
                st.text(row.title)
                if prefix=="recommendations":
                    st.markdown(f"**추천 점수 {row.score:.1f} / {results.attrs.get('score_max',100)}점**")
                st.caption(f"{row.category} · {row.color} · {row.place if row.place!='없음' else '장소 미등록'} · #{row.id}")
                st.text(row.description)
                st.caption(f"{pd.Timestamp(row.found_at).strftime('%m.%d %H:%M')} 습득")
                if hasattr(row,"distance_m"): st.caption(f"경로에서 {row.distance_m:.0f}m")
                if record and record.status=="소유 확인 완료":st.caption("특징 확인됨 · 수령 대기")
            with c:
                label="수령 위치 보기" if record and record.status=="소유 확인 완료" else "수령 인증"
                if st.button(label,key=f"pickup_{row.id}",type="primary"):
                    st.session_state["pickup_item"]=int(row.id)
            if st.session_state.get("pickup_item") != int(row.id):continue
            if int(row.id) in own_ids:
                st.info("현재 등록자로 연결되어 있습니다. 혼자 시연하려면 분실자 역할로 전환하세요.")
                st.button("분실자 역할로 전환",key=f"switch_recipient_{row.id}",type="primary",on_click=role_action,args=("recipient",int(row.id)))
                continue
            if record and show_pickup_status(record,f"{prefix}_{row.id}"):
                continue
            st.markdown("**물건 확인 질문**")
            st.text(row.verification_question or "공개 사진에 보이지 않는 특징 한 가지를 알려주세요.")
            st.caption("로컬 AI가 답변의 의미를 비교합니다. 표현이 달라도 의미가 유사하면 이 물건 아래에 수령 위치를 안내합니다.")
            with st.form(f"proof_{row.id}"):
                evidence=st.text_input("질문에 대한 답변",max_chars=1000,key=f"answer_{row.id}")
                note=st.text_input("등록자에게 남길 말 (선택)",max_chars=500)
                submit=st.form_submit_button("답변 확인 · 수령 위치 보기",type="primary")
            if submit:
                def request():return core.request_pickup(int(row.id),ensure_owner(),evidence,note)
                with st.spinner("로컬 AI가 답변 의미를 비교하고 있습니다…"):
                    ok,result=guard(request)
                if ok:
                    st.session_state["issued_otp"]=result[1]
                    st.session_state["recent_pickup_request"]=int(result[0])
                    st.session_state.setdefault("pickup_codes",{})[str(result[0])]=result[1]
                    st.rerun()
            if st.button("닫기",key=f"cancel_{row.id}"):
                st.session_state.pop("pickup_item",None);st.rerun()
    with st.container(horizontal=True, horizontal_alignment="center"):
        st.pagination(total_pages, max_visible_pages=10, width=600, key=page_key)


items = core.read("items")
items = items.loc[items.status.ne("반환 완료")].copy()
snapshot = core.inventory_revision()


@st.fragment(run_every="5s")
def watch_inventory():
    if core.inventory_revision() != snapshot:
        st.rerun()


watch_inventory()
if page == "분실물 찾기":
    st.subheader("주인을 찾고 있는 물건")
    a, b, c = st.columns([3, 1, 1])
    query = a.text_input("물건 이름이나 특징", max_chars=200, placeholder="예: 검정 가죽 지갑")
    category = b.selectbox("종류", ["전체"] + core.CATEGORIES)
    color = c.selectbox("색상", ["전체"] + core.COLORS)
    route, radius, start, end = [], 100, None, None
    with st.expander("장소·시간으로 좁히기"):
        if st.checkbox("이동한 장소로 찾기"):
            names, radius = route_input("search")
            route = core.route_coords(names)
        if st.checkbox("습득 시간 범위 지정"):
            d1 = st.date_input("습득 시작일", core.now().date() - timedelta(days=7))
            d2 = st.date_input("습득 종료일", core.now().date())
            start, end = datetime.combine(d1, time.min), datetime.combine(d2, time.max)
    if start and start > end:
        st.error("날짜 범위를 확인해 주세요.")
    else:
        result = core.search(items, category, color, query, route, radius, start, end).sort_values("found_at", ascending=False)
        st.write(f"{len(result)}건")
        with st.expander("지도에서 보기", expanded=bool(route)):
            draw_map(result, route, radius)
        if route:
            st.subheader("동선 매칭 점수")
            display_scores(result, "route_scores")
        cards(result)
        public = ["id", "title", "category", "color", "place", "found_at", "status"]
        st.download_button("검색 결과 저장", sec.safe_csv(result[public]), "search_results.csv", "text/csv")

elif page == "습득물 등록":
    st.subheader("주운 물건 등록")
    show_access_code("found")
    st.caption("사진에 학생증 번호나 연락처가 보이지 않게 해 주세요. 별표(*)는 필수 항목입니다.")
    with st.form("found"):
        left, right = st.columns(2, gap="large")
        with left:
            title = st.text_input("물건 이름 *", max_chars=80)
            a, b = st.columns(2)
            category = a.selectbox("종류", core.CATEGORIES)
            color = b.selectbox("색상", core.COLORS)
            upload = st.file_uploader("사진 (선택 · JPG/PNG · 최대 5MB)", type=["jpg", "jpeg", "png"])
            description = st.text_area("공개할 특징 *", max_chars=1000)
        with right:
            place = st.selectbox("발견 장소", ["없음"] + list(PLACES.index))
            a, b = st.columns(2)
            date = a.date_input("발견 날짜", core.now().date())
            clock = b.time_input("발견 시각", core.now().time())
            storage = st.text_input("보관 장소 / 반환 안내 *", max_chars=250)
            question = st.text_input("소유 확인 질문 (선택)", max_chars=200, placeholder="예: 지갑 안쪽에는 어떤 모양의 표시가 있나요?")
            private = st.text_input("질문의 정답 (비공개)", max_chars=500, placeholder="예: 안쪽 별 모양")
            st.caption("질문에는 정답을 쓰지 마세요. 로컬 AI가 답변 의미를 비교합니다. 필요하면 정답에 대체 답변을 |로 구분해 넣을 수 있습니다. 둘 다 비워두면 수동 확인합니다.")
        submitted = st.form_submit_button("습득물 등록", type="primary")
    if submitted:
        def register():
            token = ensure_owner("registrant")
            # Validate required fields before parsing or writing the uploaded file.
            sec.clean(title, "물건 이름", 80, 1)
            sec.clean(description, "공개 특징", 1000, 1)
            sec.clean(storage, "보관 장소", 250, 1)
            if bool(question.strip()) != bool(private.strip()):
                raise sec.SecurityError("소유 확인 질문과 비공개 정답을 함께 입력해 주세요.")
            image = save_image(upload, core.DATA)
            try:
                return core.insert("items", dict(title=title, category=category, color=color, description=description,
                    place=place, found_at=datetime.combine(date, clock).isoformat(), storage=storage, private_hint=private,
                    verification_question=question, image=image), owner_session=token)
            except Exception:
                path = sec.image_path(core.DATA, image)
                if path:
                    path.unlink()
                raise
        ok, iid = guard(register)
        if ok:
            st.session_state["notice"] = f"#{iid} 등록했습니다. 확인 코드를 보관해 주세요."
            st.rerun()

elif page == "분실 신고 · 추천":
    st.subheader("분실 신고")
    show_access_code("report")
    st.caption("잃어버린 물건의 특징을 남기고 비슷한 습득물을 확인하세요.")
    st.caption("이미 등록된 물건을 먼저 보려면 상단의 ‘물건 찾기’를 선택하세요.")
    names, radius = route_input("report")
    with st.form("report"):
        title = st.text_input("분실물 이름 *", max_chars=80)
        a, b = st.columns(2)
        category = a.selectbox("분실물 종류", core.CATEGORIES)
        color = b.selectbox("분실물 색상", core.COLORS)
        keywords = st.text_input("기억나는 특징", max_chars=200)
        a, b = st.columns(2)
        d1 = a.date_input("분실 추정 시작 날짜", core.now().date())
        t1 = a.time_input("분실 추정 시작 시각", time.min)
        d2 = b.date_input("분실 추정 종료 날짜", core.now().date())
        t2 = b.time_input("분실 추정 종료 시각", core.now().time())
        sent = st.form_submit_button("분실 신고 저장", type="primary")
    if sent:
        def report():
            return core.insert("reports", dict(title=title, category=category, color=color, keywords=keywords,
                start_at=datetime.combine(d1,t1).isoformat(), end_at=datetime.combine(d2,t2).isoformat(),
                route=json.dumps(names, ensure_ascii=False), radius=radius), owner_session=ensure_owner())
        ok, _ = guard(report)
        if ok:
            st.session_state["notice"] = "분실 신고를 저장했습니다."
            st.rerun()
    if st.session_state.get("owner_session"):
        ok, reports = guard(core.owner_reports, st.session_state["owner_session"])
        if ok and not reports.empty:
            indexed = reports.set_index("id")
            rid = st.selectbox("내 분실 신고", list(indexed.index), format_func=lambda i: f"#{i} {indexed.loc[i,'title']}", key="selected_report")
            r = indexed.loc[rid]
            report_delete_button(rid, r.title, st.session_state["owner_session"], f"delete_report_{rid}")
            result = core.search(items.loc[items.category.eq(r.category)], r.category, r.color, r.keywords,
                core.route_coords(json.loads(r.route)), int(r.radius), r.start_at, strict=False)
            st.subheader("비슷한 습득물")
            st.caption("종류·색상·특징·동선 거리를 비교한 추천입니다. 사진 인식은 아직 적용하지 않았습니다.")
            display_scores(result, "recommendation_scores")
            cards(result, "recommendations")
        elif ok:
            st.info("저장한 분실 신고가 없습니다.")

else:
    st.subheader("내 등록·인증 내역")
    show_access_code("records")
    with st.expander("확인 코드로 연결", expanded=not bool(st.session_state.get("owner_session"))):
        st.caption("새 코드의 대소문자·띄어쓰기·하이픈은 자동 정리합니다. 이전 버전의 URL형 코드는 대소문자를 구분합니다.")
        with st.form("login", clear_on_submit=True):
            entered = st.text_input("확인 코드", type="password", key="login_code", max_chars=128)
            load = st.form_submit_button("내역 불러오기")
        if load:
            ok, token = guard(core.authenticate_owner, entered, st.session_state["actor_id"])
            if ok:
                clear_demo_roles()
                st.session_state["owner_session"] = token
                st.session_state.pop("issued_code", None)
                st.rerun()
        st.caption("코드 없이 등록된 이전 물건은 이 컴퓨터의 recover_registration.py로 연결할 수 있습니다.")
    token = st.session_state.get("owner_session")
    if token and st.button("내역 연결 해제"):
        tokens = {token, st.session_state.get("demo_registrant_session"), st.session_state.get("demo_recipient_session")}
        for saved in tokens - {None}:
            guard(core.logout, saved)
        clear_demo_roles()
        for key in ("owner_session", "issued_code", "issued_otp"):
            st.session_state.pop(key, None)
        st.rerun()

    @st.fragment(run_every="10s")
    def my_records():
        token = st.session_state.get("owner_session")
        if not token:
            st.info("확인 코드로 연결하면 등록한 물건과 수령 인증 내역을 볼 수 있습니다.")
            return
        ok, mine = guard(core.owner_items, token)
        if not ok:
            return
        ok, received = guard(core.pickup_requests, token)
        if not ok:
            return
        st.caption("앱이 열려 있는 동안 10초마다 갱신됩니다. 연결은 1시간 뒤 만료됩니다.")
        ok, reports = guard(core.owner_reports, token)
        if ok and not reports.empty:
            st.subheader("내 분실 신고")
            for report in reports.itertuples():
                with st.container(border=True):
                    st.text(f"#{report.id} {report.title}")
                    st.caption(f"{report.category} · {report.color}")
                    report_delete_button(report.id, report.title, token, f"record_delete_report_{report.id}")
        if not mine.empty:
            st.subheader("내가 등록한 주운 물건")
        for row in mine.itertuples():
            with st.container(border=True):
                st.text(f"#{row.id} {row.title}")
                if pd.notna(row.picked_up_at):
                    st.success("등록하신 물건이 반환 완료됐습니다.")
                    st.caption(f"{row.picked_up_at.replace('T',' ')}")
                    if row.pickup_note:
                        st.text(row.pickup_note)
                    if pd.isna(row.seen_at) and st.button("알림 확인", key=f"seen_{row.id}"):
                        guard(core.acknowledge_pickup, int(row.id), token)
                        st.rerun()
                else:
                    st.caption(row.status)
                st.text("보관 안내: " + row.storage)
                if row.private_hint:
                    with st.expander("비공개 특징"):
                        st.text(row.private_hint)
                for request in received.loc[received.item_id.eq(row.id) & received.status.isin(["확인 대기", "소유 확인 완료"])].itertuples():
                    if pd.Timestamp(request.expires_at) <= pd.Timestamp(core.now()):
                        continue
                    st.markdown("**소유 확인 접수**" if request.status == "확인 대기" else "**소유 확인 완료 · 수령 대기**")
                    st.text(request.evidence)
                    if request.status == "확인 대기":
                        a, b = st.columns(2)
                        if a.button("소유 확인 승인 · 장소 안내", key=f"disclose_{request.id}", type="primary"):
                            ok, _ = guard(core.approve_ownership, int(request.id), token)
                            if ok:
                                st.rerun()
                        if b.button("소유 근거 불일치 · 반려", key=f"deny_{request.id}"):
                            ok, _ = guard(core.reject_pickup, int(request.id), token)
                            if ok:
                                st.rerun()
                        continue
                    with st.form(f"approve_{request.id}"):
                        otp = st.text_input("수령자가 제시한 8자리 인증번호", type="password", max_chars=8)
                        checked = st.checkbox("현장에서 소유 특징을 확인했고 실제로 물건을 전달했습니다.")
                        approve = st.form_submit_button("확인 후 반환 완료", type="primary")
                        reject = st.form_submit_button("소유 근거 불일치 · 반려")
                    if approve:
                        ok, _ = guard(core.complete_pickup, int(request.id), token, otp, handoff=checked)
                        if ok:
                            st.rerun()
                    if reject:
                        ok, _ = guard(core.reject_pickup, int(request.id), token)
                        if ok:
                            st.rerun()
        ok, sent = guard(core.pickup_requests, token, received=False)
        if ok and not sent.empty:
            st.subheader("내 수령 인증")
            for r in sent.itertuples():
                status = "유효시간 만료" if r.status in ("확인 대기", "소유 확인 완료") and pd.Timestamp(r.expires_at) <= pd.Timestamp(core.now()) else r.status
                st.text(f"#{r.item_id} {r.title} · {status}")
                with st.container(border=True):
                    show_pickup_status(r,f"record_{r.id}")
    my_records()
