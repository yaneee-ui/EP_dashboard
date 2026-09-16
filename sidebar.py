"""좌측 사이드바: 조회 단위(콤팩트) + 데이터 업로드."""
import streamlit as st


def render_sidebar():
    st.sidebar.markdown("### 📊 EP 실적 대시보드")
    st.sidebar.divider()

    # --- 조회 단위 (콤팩트 한 줄) ---
    st.sidebar.markdown(
        "<style>"
        "div[data-testid='stSidebar'] .stRadio > div {gap: 0.15rem; flex-wrap: nowrap;}"
        "div[data-testid='stSidebar'] .stRadio label {"
        "  font-size: 0.72rem; padding: 0.15rem 0.35rem; white-space: nowrap;"
        "}"
        "div[data-testid='stSidebar'] .stRadio label p {font-size: 0.72rem;}"
        "</style>",
        unsafe_allow_html=True,
    )
    st.sidebar.markdown("**조회 단위**")
    view_unit = st.sidebar.radio(
        "조회 단위", ["일별", "주별", "월별", "월마감"], index=0,
        horizontal=True, label_visibility="collapsed",
        help="월별: 진행 중인 달 포함(전년 동요일 비교) / 월마감: 완료된 달만(전년 동월 비교)",
    )

    st.sidebar.divider()

    # --- 메뉴 (페이지 선택) ---
    st.sidebar.markdown("**메뉴**")
    _menu_emoji = {
        "1": "📊", "2": "🗂️", "3": "🧭",
        "4": "📋", "5": "🏷️",
        "6": "📅", "7": "👤", "8": "✨",
        "9": "🎟️", "10": "📈", "11": "📑", "12": "🎉",
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
    _menu_groups = [
        ["1. 실적 요약", "2. 카테고리 실적 요약", "3. 종합 요약"],
        ["4. 누적 데이터", "5. 누적 데이터 (카테고리)"],
        ["6. 전체 실적 (주차별)", "7. 회원 실적 (주차별)", "8. 신규 실적 (주차별)"],
        ["9. 쿠폰 비용 분석", "10. 마감 예상 실적", "11. 주간보고용", "12. 행사 기간 비교"],
    ]
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

    # --- 데이터 업로드 ---
    st.sidebar.markdown("**📁 데이터 업로드**")
    st.sidebar.caption("변환기에서 만든 CSV를 올리면 바로 반영됩니다.")
    ep_channel_file = st.sidebar.file_uploader(
        "EP채널 (ep_data_long.csv)", type=["csv", "xlsx", "xls"],
        key="ep_channel_upload",
    )
    ep_traffic_file = st.sidebar.file_uploader(
        "EP실적 (ep_traffic.csv)", type=["csv"],
        key="ep_traffic_upload",
    )
    ep_category_file = st.sidebar.file_uploader(
        "카테고리별 (ep_category.csv)", type=["csv"],
        key="ep_category_upload",
    )
    ep_product_file = st.sidebar.file_uploader(
        "상품별 (ep_product.csv)", type=["csv"],
        key="ep_product_upload",
        help="날짜/BPU/카테고리/브랜드/상품코드/상품명/거래액 컬럼의 상품 단위 데이터예요. "
             "'카테고리별 실적' 탭에서 카테고리별 상위 상품 랭킹에 쓰여요.",
    )
    ep_coupon_daily_file = st.sidebar.file_uploader(
        "쿠폰 데이터 (ep_coupon_daily.csv)", type=["csv"],
        key="ep_coupon_daily_upload",
        help="일자별 쿠폰 원본 하나로 월별/일별/주별 조회가 모두 계산돼요.",
    )

    st.sidebar.markdown("**🔄 새로고침**")
    st.sidebar.caption("업로드가 반영 안 될 때 눌러주세요.")
    refresh = st.sidebar.button("다시 읽기", use_container_width=True)

    st.sidebar.divider()
    st.sidebar.markdown("**🤖 AI 인사이트**")
    st.sidebar.caption(
        "실적 요약 화면의 'AI 인사이트' 버튼으로 자동 요약을 볼 수 있어요. "
        "Streamlit Cloud의 Settings → Secrets에 `GEMINI_API_KEY`를 등록하면 활성화돼요 "
        "(aistudio.google.com에서 무료 발급)."
    )

    return {
        "view_unit": view_unit,
        "page": page,
        "ep_channel_file": ep_channel_file,
        "ep_traffic_file": ep_traffic_file,
        "ep_category_file": ep_category_file,
        "ep_product_file": ep_product_file,
        "ep_coupon_daily_file": ep_coupon_daily_file,
        "refresh": refresh,
    }


def render_sidebar_data_status(items):
    """사이드바 맨 아래에 데이터셋별 반영 현황(기간·일수)을 표시한다.
    items: (라벨, 시작일str 또는 None, 종료일str 또는 None, 일수 또는 None) 튜플 리스트.
    시작일이 None이면 '데이터 없음'으로 표시한다.
    """
    st.sidebar.divider()
    st.sidebar.markdown("**📅 데이터 반영 현황**")
    rows_html = ""
    for label, d_min, d_max, n_days in items:
        if d_min is None:
            rows_html += (
                f"<div style='font-size:0.74rem;color:#9ca3af;margin-bottom:3px;'>"
                f"{label}: 데이터 없음</div>"
            )
        else:
            day_txt = f" · {n_days:,}일" if n_days is not None else ""
            rows_html += (
                f"<div style='font-size:0.74rem;color:#374151;margin-bottom:3px;'>"
                f"{label}: {d_min} ~ {d_max}{day_txt}</div>"
            )
    st.sidebar.markdown(rows_html, unsafe_allow_html=True)


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
