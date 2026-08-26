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
    _menu_options = [
        "1. 실적 요약", "2. 카테고리 실적 요약", "3. 종합 요약",
        "4. 누적 데이터", "5. 누적 데이터 (카테고리)",
        "6. 전체 실적 (주차별)", "7. 회원 실적 (주차별)", "8. 신규 실적 (주차별)",
        "9. 쿠폰 비용 분석", "10. 마감 예상 실적", "11. 주간보고용",
    ]
    _menu_emoji = {
        "1": "📊", "2": "🗂️", "3": "🧭",
        "4": "📋", "5": "🏷️",
        "6": "📅", "7": "👤", "8": "✨",
        "9": "🎟️", "10": "📈", "11": "📑",
    }

    def _menu_display(opt):
        _num, _label = opt.split(". ", 1)
        return f"{_menu_emoji.get(_num, '•')} {_label}"

    # 그룹(실적요약/종합요약 · 누적데이터 · 주차별 실적 · 쿠폰/마감예상/주간보고) 사이에
    # 구분선을 넣는다 — 4번째·6번째·9번째 옵션 위에 border-top을 그어서 표현.
    st.markdown(
        """
        <style>
        .st-key-main_menu_radio div[role="radiogroup"] > label:nth-of-type(4),
        .st-key-main_menu_radio div[role="radiogroup"] > label:nth-of-type(6),
        .st-key-main_menu_radio div[role="radiogroup"] > label:nth-of-type(9) {
            border-top: 1px solid #e5e7eb;
            margin-top: 6px !important;
            padding-top: 6px !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    page = st.sidebar.radio(
        "메뉴", _menu_options,
        format_func=_menu_display,
        label_visibility="collapsed",
        key="main_menu_radio",
    )

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
