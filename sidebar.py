"""좌측 사이드바: 조회 단위(콤팩트) + 메뉴(BPU별) + 데이터 업로드."""
import streamlit as st


def render_sidebar():
    st.sidebar.markdown("### 📊 EP 실적 대시보드")
    st.sidebar.divider()

    # --- 조회 단위 (콤팩트 한 줄) ---
    st.sidebar.markdown(
        "<style>"
        "div[data-testid='stSidebar'] .stRadio > div {gap: 0.3rem;}"
        "div[data-testid='stSidebar'] .stRadio label {font-size: 0.85rem; padding: 0.2rem 0.5rem;}"
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

    # --- 메뉴 (Total + 개별 BPU) ---
    st.sidebar.markdown("**메뉴**")
    page = st.sidebar.radio(
        "메뉴",
        [
            "01. 실적 요약",
            "a. e-영업1 실적",
            "b. e-영업2 실적",
            "c. e-영업3 실적",
            "d. e-영업4 실적",
            "e. 자사 실적 (1+2)",
            "f. 입점 실적 (3+4)",
        ],
        label_visibility="collapsed",
    )

    st.sidebar.divider()

    # --- 데이터 업로드 ---
    st.sidebar.markdown("**데이터 업로드**")
    st.sidebar.caption("변환기에서 만든 CSV를 올리면 바로 반영됩니다.")
    ep_channel_file = st.sidebar.file_uploader(
        "EP채널 (ep_data_long.csv)", type=["csv", "xlsx", "xls"],
        key="ep_channel_upload",
    )
    ep_traffic_file = st.sidebar.file_uploader(
        "EP실적 (ep_traffic.csv)", type=["csv"],
        key="ep_traffic_upload",
    )
    refresh = st.sidebar.button("🔄 새로고침 (다시 읽기)", use_container_width=True)

    # 메뉴에서 BPU 자동 결정
    page_bpu_map = {
        "01. 실적 요약": "Total",
        "a. e-영업1 실적": "e-영업1",
        "b. e-영업2 실적": "e-영업2",
        "c. e-영업3 실적": "e-영업3",
        "d. e-영업4 실적": "e-영업4",
        "e. 자사 실적 (1+2)": "자사",
        "f. 입점 실적 (3+4)": "입점",
    }

    return {
        "view_unit": view_unit,
        "page": page,
        "bpu": page_bpu_map.get(page, "Total"),
        "ep_channel_file": ep_channel_file,
        "ep_traffic_file": ep_traffic_file,
        "refresh": refresh,
    }


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
