"""상단 필터바 렌더링 (사이드바가 아닌 헤더 아래 가로 배치)."""
import streamlit as st

from utils import COL_BPU, COL_MATCH, COL_LOWEST


def render_filter_bar(df):
    bpu_options = ["Total"] + sorted(v for v in df[COL_BPU].unique() if v != "Total")
    match_options = [v for v in ["Total", "매칭", "비매칭"] if v in df[COL_MATCH].unique()]
    lowest_options = [v for v in ["Total", "최저가", "비최저가"] if v in df[COL_LOWEST].unique()]

    c1, c2, c3, c4, c5 = st.columns([2, 2, 2, 3, 1.3])

    with c1:
        bpu = st.selectbox("BPU", bpu_options, index=0)
    with c2:
        match_status = st.selectbox("원부매칭여부", match_options, index=0)
    with c3:
        lowest_status = st.selectbox("최저가여부", lowest_options, index=0)
    with c4:
        view_unit = st.radio("보기 단위", ["일별", "주별", "월별"], index=0, horizontal=True, label_visibility="collapsed")
    with c5:
        uploaded_file = None
        with st.popover("📁 데이터 업로드", use_container_width=True):
            st.caption("사내에서 받은 **Data.xlsx**를 그대로 올리면 자동 변환됩니다.")
            uploaded_file = st.file_uploader("Data.xlsx 업로드", type=["xlsx", "xls", "csv"], label_visibility="collapsed")

    return {
        "bpu": bpu,
        "match_status": match_status,
        "lowest_status": lowest_status,
        "view_unit": view_unit,
        "uploaded_file": uploaded_file,
    }


def filter_by_combo(df, bpu, match_status, lowest_status):
    return df[
        (df[COL_BPU] == bpu)
        & (df[COL_MATCH] == match_status)
        & (df[COL_LOWEST] == lowest_status)
    ]
