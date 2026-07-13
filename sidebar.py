"""좌측 사이드바: 보기 단위 + 페이지 선택 + 데이터 업로드(전체교체/최근추가)."""
import streamlit as st


def render_sidebar():
    st.sidebar.markdown("### 📊 EP 실적 대시보드")
    st.sidebar.divider()

    # --- 보기 단위 ---
    st.sidebar.markdown("**조회 단위**")
    view_unit = st.sidebar.radio(
        "조회 단위", ["일별", "주별", "월별"], index=1,
        horizontal=True, label_visibility="collapsed",
    )

    st.sidebar.divider()

    # --- 페이지 선택 ---
    st.sidebar.markdown("**메뉴**")
    page = st.sidebar.radio(
        "메뉴", ["01. 실적 요약", "02. BPU별 실적"],
        label_visibility="collapsed",
    )

    st.sidebar.divider()

    # --- 데이터 업로드 (전체 교체 방식) ---
    st.sidebar.markdown("**데이터 업로드**")
    st.sidebar.caption("사내에서 받은 **Data.xlsx**(전체 기간)를 그대로 올리면 자동 변환됩니다.")
    uploaded_file = st.sidebar.file_uploader(
        "Data.xlsx 업로드", type=["xlsx", "xls", "csv"], label_visibility="collapsed",
    )
    refresh = st.sidebar.button("🔄 새로고침 (다시 읽기)", use_container_width=True)

    return {
        "view_unit": view_unit,
        "page": page,
        "uploaded_file": uploaded_file,
        "refresh": refresh,
    }


def render_combo_filter(df, key_prefix=""):
    """본문 상단의 BPU/원부매칭여부/최저가여부 선택 (실적 요약 탭용)."""
    from utils import COL_BPU, COL_MATCH, COL_LOWEST

    bpu_options = ["Total"] + sorted(v for v in df[COL_BPU].unique() if v != "Total")
    match_options = [v for v in ["Total", "매칭", "비매칭"] if v in df[COL_MATCH].unique()]
    lowest_options = [v for v in ["Total", "최저가", "비최저가"] if v in df[COL_LOWEST].unique()]

    c1, c2, c3 = st.columns(3)
    with c1:
        bpu = st.selectbox("BPU", bpu_options, index=0, key=f"{key_prefix}_bpu")
    with c2:
        match_status = st.selectbox("원부매칭여부", match_options, index=0, key=f"{key_prefix}_match")
    with c3:
        lowest_status = st.selectbox("최저가여부", lowest_options, index=0, key=f"{key_prefix}_lowest")

    return {"bpu": bpu, "match_status": match_status, "lowest_status": lowest_status}
