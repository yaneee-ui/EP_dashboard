"""좌측 사이드바: 조회 단위(콤팩트) + 보기 기준 + 메뉴 + 데이터 반영 현황(맨 아래)."""
import streamlit as st

# 화면에 보이는 그룹 순서: 홈/실적 요약 -> 쿠폰/마감예상/주간보고 등 -> 주차별 실적 -> 누적 데이터
# (메뉴 번호는 페이지 구분용 내부 키라 순서와 무관하고 화면에는 안 보인다)
MENU_GROUPS = [
    ["0. 홈", "1. 실적 요약", "2. 카테고리 실적 요약", "3. 종합 요약"],
    ["9. 쿠폰 비용 분석", "10. 마감 예상 실적", "11. 주간보고용", "12. 행사 기간 비교", "13. 명품 채널별 실적", "14. 전체 채널별 전년비"],
    ["6. 전체 실적 (주차별)", "7. 회원 실적 (주차별)", "8. 신규 실적 (주차별)"],
    ["4. 누적 데이터", "5. 누적 데이터 (카테고리)"],
]


def goto_page(page):
    """홈 화면의 바로가기 버튼용 — 버튼 on_click 콜백에서 호출해서 메뉴를 해당 페이지로 옮긴다.
    (메뉴가 그룹별 라디오 4개라서, 해당 그룹의 값을 세팅하고 나머지 그룹은 해제해야 함)"""
    st.session_state["menu_page"] = page
    for gi, group in enumerate(MENU_GROUPS):
        st.session_state[f"menu_group_{gi}"] = page if page in group else None


def render_sidebar():
    st.sidebar.markdown("### 📊 EP 실적 대시보드")
    st.sidebar.divider()

    # --- 조회 단위 (콤팩트 한 줄) ---
    # 참고: data-testid='stSidebar'가 붙는 실제 태그는 <div>가 아니라 <section>이라서,
    # 예전에 "div[data-testid='stSidebar'] ..." 형태로 쓴 선택자는 전부 매치가 안 되고
    # 있었음(조용히 no-op) — 태그명을 아예 빼고 속성만으로 지정해서 향후 태그가 바뀌어도
    # 안전하게 함.
    st.sidebar.markdown(
        "<style>"
        "[data-testid='stSidebar'] .stRadio > div {gap: 0.15rem;}"
        "[data-testid='stSidebar'] .stRadio label {"
        "  font-size: 0.72rem; padding: 0.15rem 0.35rem; white-space: nowrap;"
        "}"
        "[data-testid='stSidebar'] .stRadio label p {font-size: 0.72rem;}"
        "[data-testid='stSidebar'] hr {margin: 8px 0;}"
        "</style>",
        unsafe_allow_html=True,
    )
    st.sidebar.markdown("**조회 단위**")
    view_unit = st.sidebar.radio(
        "조회 단위", ["일별", "주별", "월별", "월마감"], index=0,
        horizontal=True, label_visibility="collapsed",
        help="월별: 진행 중인 달 포함(전년 동요일 비교) / 월마감: 완료된 달만(전년 동월 비교)",
    )

    # --- EP + 쇼핑검색광고 APP 합산 보기 (11/19부터 EP APP 실적 일부가 쇼검 APP로 분리 집계) ---
    st.sidebar.markdown("**보기 기준**")
    ep_ad_app = st.sidebar.toggle(
        "EP + 쇼검 APP 합산 (11/19~)", key="ep_ad_app_on", value=False,
        help="11/19부터 EP APP 실적 일부가 쇼핑검색광고(APP)로 나뉘어 집계되고 있어요. "
             "켜면 11/19 이후 EP 거래액·구매객수에 쇼핑검색광고 APP 거래액·주문고객수를 더해서 "
             "전년 EP와 같은 기준으로 비교해요(전년은 EP 그대로). "
             "BPU·회원구분·카테고리 구분이 없는 데이터라 'BPU 전체 · 회원구분 전체' 실적에만 반영돼요.",
    )

    st.sidebar.divider()

    # --- 메뉴 (페이지 선택) ---
    st.sidebar.markdown("**메뉴**")
    _menu_emoji = {
        "0": "🏠", "1": "📊", "2": "🗂️", "3": "🧭",
        "4": "📋", "5": "🏷️",
        "6": "📅", "7": "👤", "8": "✨",
        "9": "🎟️", "10": "📈", "11": "📑", "12": "🎉", "13": "💎", "14": "📡",
    }

    def _menu_display(opt):
        _num, _label = opt.split(". ", 1)
        return f"{_menu_emoji.get(_num, '•')} {_label}"

    # 그룹(실적요약/종합요약 · 누적데이터 · 주차별 실적 · 쿠폰/마감예상/주간보고) 사이에
    # 구분선을 넣는다. 예전엔 라디오 옵션 12개를 한 위젯에 다 넣고 CSS
    # border-top(nth-of-type)으로 구분선을 흉내냈는데, 이게 Streamlit의 내부 DOM
    # 구조(라디오 그룹이 align-items:flex-start라 각 label이 글자 폭만큼만 차지)에
    # 기대는 방식이라 버전에 따라(로컬 1.63 vs Streamlit Cloud 1.64) 렌더링이
    # 달라져서 계속 안 보이는 문제가 있었음. 대신 그룹별로 라디오를 4개 따로 만들고
    # 그 사이에 진짜 st.sidebar.divider()(항상 확실히 보이는 네이티브 컴포넌트)를
    # 넣는 방식으로 바꿨다 — 선택 상태는 session_state로 그룹 간에 동기화한다
    # (한 그룹에서 고르면 다른 그룹들의 선택은 자동으로 풀어서, 항상 딱 하나만
    # '선택됨'으로 보이게 함).
    _menu_groups = MENU_GROUPS
    _default_page = _menu_groups[0][0]
    if "menu_page" not in st.session_state:
        st.session_state["menu_page"] = _default_page

    def _on_menu_group_change(group_idx):
        _picked = st.session_state.get(f"menu_group_{group_idx}")
        if _picked is not None:
            st.session_state["menu_page"] = _picked
            for j in range(len(_menu_groups)):
                if j != group_idx:
                    st.session_state[f"menu_group_{j}"] = None

    for _gi, _group in enumerate(_menu_groups):
        _cur_page = st.session_state["menu_page"]
        _idx = _group.index(_cur_page) if _cur_page in _group else None
        st.sidebar.radio(
            f"메뉴 {_gi}", _group, index=_idx,
            format_func=_menu_display, label_visibility="collapsed",
            key=f"menu_group_{_gi}",
            on_change=_on_menu_group_change, args=(_gi,),
        )
        if _gi < len(_menu_groups) - 1:
            st.sidebar.divider()

    page = st.session_state["menu_page"]

    st.sidebar.divider()
    st.sidebar.markdown("**🤖 AI 인사이트**")
    st.sidebar.caption(
        "실적 요약 화면의 'AI 인사이트' 버튼으로 자동 요약을 볼 수 있어요. "
        "Streamlit Cloud의 Settings → Secrets에 `GEMINI_API_KEY`를 등록하면 활성화돼요 "
        "(aistudio.google.com에서 무료 발급)."
    )

    # 데이터 반영 현황(사이드바 맨 아래) — 내용은 데이터를 다 읽은 뒤 app.py에서 채운다.
    st.sidebar.divider()
    status_slot = st.sidebar.container()

    return {
        "view_unit": view_unit,
        "page": page,
        "ep_ad_app": ep_ad_app,
        "status_slot": status_slot,
    }


def render_sidebar_data_status(items, slot=None):
    """사이드바 맨 아래에 데이터셋별 '며칠까지 반영됐는지'를 표시한다.
    items: (라벨, 마지막 날짜 Timestamp 또는 None) 리스트. 가장 최신 날짜보다 늦은 데이터는 주황색으로.
    slot: render_sidebar()가 맨 아래에 잡아둔 컨테이너 (없으면 사이드바 현재 위치)."""
    import pandas as pd
    box = slot if slot is not None else st.sidebar
    wk = ["월", "화", "수", "목", "금", "토", "일"]
    dates = [pd.Timestamp(d) for _, d in items if d is not None and not pd.isna(d)]
    latest = max(dates) if dates else None
    rows = ""
    for label, d in items:
        if d is None or pd.isna(d):
            val, color = "데이터 없음", "#9ca3af"
        else:
            d = pd.Timestamp(d)
            lag = (latest - d).days if latest is not None else 0
            val = f"~{d:%m/%d}({wk[d.weekday()]})" + (f" · {lag}일 늦음" if lag > 0 else "")
            color = "#c2410c" if lag > 0 else "#111827"
        rows += (
            "<div style='display:flex;justify-content:space-between;gap:8px;font-size:0.74rem;line-height:1.5;'>"
            f"<span style='color:#6b7280;'>{label}</span><span style='color:{color};font-weight:600;'>{val}</span></div>"
        )
    box.markdown(
        "<div style='background:#f3f4f6;border:1px solid #e5e7eb;border-radius:8px;padding:7px 10px;margin-top:2px;'>"
        "<div style='font-size:0.76rem;font-weight:700;color:#374151;margin-bottom:3px;'>🗓️ 데이터 반영 현황</div>"
        f"{rows}</div>",
        unsafe_allow_html=True,
    )


def render_combo_filter(df, bpu, key_prefix=""):
    """원부매칭여부 / 최저가여부만 선택 (BPU는 메뉴에서 이미 결정됨)."""
    from utils import COL_MATCH, COL_LOWEST

    match_options = [v for v in ["Total", "매칭", "비매칭"] if v in df[COL_MATCH].unique()]
    lowest_options = [v for v in ["Total", "최저가", "비최저가"] if v in df[COL_LOWEST].unique()]

    c1, c2 = st.columns(2)
    with c1:
        match_status = st.selectbox("원부매칭여부", match_options, index=0, key=f"{key_prefix}_match")
    with c2:
        lowest_status = st.selectbox("최저가여부", lowest_options, index=0, key=f"{key_prefix}_lowest")

    return {"bpu": bpu, "match_status": match_status, "lowest_status": lowest_status}
