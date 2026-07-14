"""마케팅 실적 현황 대시보드 - 메인 엔트리포인트.

좌측 사이드바: 조회 단위(일/주/월) + 메뉴(01 실적요약 / 02 BPU별실적) + 데이터 업로드
본문: 선택한 메뉴에 따라 페이지 렌더링
"""
import streamlit as st

from data_loader import load_data
from sidebar import render_sidebar, render_combo_filter
from filters import filter_by_combo
from kpi import render_kpi_cards
from charts import main_trend_data, bpu_comparison_data
from comparison_table import build_comparison_table, build_summary_metrics_table, render_summary_table_html
from bpu_metrics import build_bpu_metrics_table
from utils import (
    COL_DATE, COL_BPU, COL_MATCH, COL_LOWEST, METRIC_COLS,
    resample_series, make_period_label,
)
from styles import CUSTOM_CSS

st.set_page_config(page_title="마케팅 실적 현황 대시보드", layout="wide", page_icon="📊")
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# --- 사이드바 ---
side = render_sidebar()
if side["refresh"]:
    load_data.clear()  # 캐시 비우기

# --- 데이터 로드 ---
df_raw = load_data()
if side["uploaded_file"] is not None:
    _uf = side["uploaded_file"]
    df_raw = load_data(uploaded_file=_uf, file_name=getattr(_uf, "name", None))
    _min = df_raw[COL_DATE].min().strftime("%Y-%m-%d")
    _max = df_raw[COL_DATE].max().strftime("%Y-%m-%d")
    st.sidebar.success(f"업로드 완료: {_min} ~ {_max}")

    # 업로드한 전체 데이터를 CSV로 다운로드 (GitHub의 ep_data_long.csv에 덮어쓰기용)
    _csv = df_raw.sort_values([COL_BPU, COL_MATCH, COL_LOWEST, COL_DATE]).to_csv(index=False, encoding="utf-8-sig")
    st.sidebar.download_button(
        "⬇️ 전체 데이터 CSV 다운로드",
        _csv.encode("utf-8-sig"),
        file_name="ep_data_long.csv",
        mime="text/csv",
        use_container_width=True,
        help="이 파일을 GitHub의 ep_data_long.csv에 덮어쓰면 기본 데이터가 갱신됩니다.",
    )

unit = side["view_unit"]

# 최근 기준일(전체 데이터 마지막 날짜) 및 라벨
last_date = df_raw[COL_DATE].max()
# 선택 단위 기준 최근 라벨은 Total 조합의 리샘플 마지막 인덱스로 계산
_total = df_raw[(df_raw[COL_BPU] == "Total") & (df_raw[COL_MATCH] == "Total") & (df_raw[COL_LOWEST] == "Total")]
_series = resample_series(_total, "평균 EP 거래액(총결제)", unit).dropna()
period_last = _series.index[-1] if not _series.empty else last_date
period_label = make_period_label(period_last, unit)

# 데이터 반영 현황 (실제 마지막 데이터 날짜, 요일 포함)
_weekday_kr = ["월", "화", "수", "목", "금", "토", "일"][last_date.weekday()]
data_status = f"데이터 반영: {last_date.strftime('%Y-%m-%d')}({_weekday_kr})까지"
st.sidebar.info(f"🗓️ {data_status}")


# ============================================================
# 01. 실적 요약
# ============================================================
if side["page"].startswith("01"):
    st.markdown("<div class='dash-header-title'>📊 실적 요약</div>", unsafe_allow_html=True)
    st.markdown(
        f"<div class='dash-header-sub'>조회 단위: <b>{unit}</b> · 기준: <b>{period_label}</b> · {data_status}</div>",
        unsafe_allow_html=True,
    )

    flt = render_combo_filter(df_raw, key_prefix="summary")
    df_combo = filter_by_combo(df_raw, flt["bpu"], flt["match_status"], flt["lowest_status"])

    if df_combo.empty:
        st.warning("선택한 조합에 데이터가 없습니다.")
        st.stop()

    st.markdown(
        f"<div class='chart-caption'>아래 KPI는 <b>{flt['bpu']} / {flt['match_status']} / {flt['lowest_status']}</b> 기준, "
        f"<b>{period_label}</b>의 값입니다.</div>",
        unsafe_allow_html=True,
    )
    render_kpi_cards(df_combo, unit)

    st.markdown("<br/>", unsafe_allow_html=True)

    # 지표 추이 차트 (기간 설정 가능)
    h1, h2 = st.columns([2, 3])
    h1.markdown("**지표 추이**")
    metric_main = h2.selectbox("지표 선택", METRIC_COLS,
                               index=METRIC_COLS.index("평균 EP 거래액(총결제)"),
                               key="metric_main", label_visibility="collapsed")

    latest_year = int(df_combo[COL_DATE].max().year)
    _year_series = resample_series(df_combo, metric_main, unit).dropna()
    _this_year = _year_series[_year_series.index.year == latest_year]

    # 기간: 항상 2026-01-01 ~ 최신 데이터로 고정
    import datetime as _dt
    _fixed_start = _dt.date(latest_year, 1, 1)
    if not _this_year.empty:
        _max_d = _this_year.index.max().date()
        _data_min = _this_year.index.min().date()
    else:
        _max_d = df_combo[COL_DATE].max().date()
        _data_min = df_combo[COL_DATE].min().date()
    # 데이터가 2026-01-01보다 늦게 시작하면 데이터 시작일 사용
    _min_d = max(_fixed_start, _data_min) if _data_min > _fixed_start else _fixed_start

    show_yoy = st.checkbox("전년 비교선 표시", value=True, key="show_yoy")

    d_start, d_end = _min_d, _max_d

    _trend_df, _yoy_info = main_trend_data(df_combo, metric_main, unit, show_yoy,
                                current_year=latest_year, date_start=d_start, date_end=d_end)
    st.line_chart(_trend_df, height=380)
    _unit_desc = {"일별": "일별", "주별": "주평균", "월별": "월평균", "월마감": "월평균(마감)"}[unit]
    _is_monthly = unit in ("월별", "월마감")

    # 월 단위면 "2026년 1월 ~ 7월(~12일)" 식으로, 일별/주별은 날짜 그대로
    if _is_monthly:
        _last_month_end = last_date + pd.offsets.MonthEnd(0)
        if unit == "월별" and last_date < _last_month_end:
            # 월별(진행중): 미완성 달 표시
            _end_label = f"{last_date.month}월(~{last_date.day}일)"
        elif unit == "월마감":
            # 월마감: 마감 완료된 마지막 달 표시
            _series_last = _trend_df.index[-1] if not _trend_df.empty else last_date
            _end_label = f"{pd.Timestamp(_series_last).month}월"
        else:
            _end_label = f"{last_date.month}월"
        _cur_range = f"{d_start.strftime('%Y')}년 {d_start.month}월 ~ {_end_label}"
    else:
        _cur_range = f"{d_start.strftime('%Y-%m-%d')} ~ {d_end.strftime('%Y-%m-%d')}"

    _caption = f"<div class='chart-caption'>올해: {_cur_range} · {_unit_desc} 기준"
    if _yoy_info and show_yoy:
        ys = _yoy_info['yoy_start']
        ye = _yoy_info['yoy_end']
        if unit == "월별":
            # 월별: 동요일(364일) 비교 — 미완성 달 기간까지 표시
            _last_month_end = last_date + pd.offsets.MonthEnd(0)
            if last_date < _last_month_end:
                _yoy_last = last_date - pd.Timedelta(days=364)
                _yoy_end_label = f"{_yoy_last.month}월(~{_yoy_last.day}일)"
            else:
                _yoy_end_label = f"{ye.month}월"
            _yoy_range = f"{ys.strftime('%Y')}년 {ys.month}월 ~ {_yoy_end_label}"
            _caption += f"<br/>전년 비교: {_yoy_range} (동요일 기준, 364일 전)"
        elif unit == "월마감":
            # 월마감: 동월(1년 전) 비교
            _yoy_range = f"{ys.strftime('%Y')}년 {ys.month}월 ~ {ye.month}월"
            _caption += f"<br/>전년 비교: {_yoy_range} (전년 동월)"
        else:
            _yoy_range = f"{ys.strftime('%Y-%m-%d')} ~ {ye.strftime('%Y-%m-%d')}"
            _caption += f"<br/>전년 비교: {_yoy_range} (동요일 기준, 364일 전)"
    _caption += "</div>"
    st.markdown(_caption, unsafe_allow_html=True)

    st.markdown("<br/>", unsafe_allow_html=True)

    # 하단 실적 표 (6개 지표별 값 / 전기간비 / 전년비)
    st.markdown(f"**실적 요약 표**  ·  <span style='color:#6b7280;font-size:0.85rem'>기준: {period_label}</span>", unsafe_allow_html=True)
    summary_html = render_summary_table_html(df_combo, unit)
    st.markdown(summary_html, unsafe_allow_html=True)


# ============================================================
# 02. BPU별 실적
# ============================================================
else:
    st.markdown("<div class='dash-header-title'>🏢 BPU별 실적</div>", unsafe_allow_html=True)
    st.markdown(
        f"<div class='dash-header-sub'>조회 단위: <b>{unit}</b> · 기준: <b>{period_label}</b> · {data_status}</div>",
        unsafe_allow_html=True,
    )

    # 원부매칭/최저가 조건 선택 (BPU는 전체를 열로 펼치므로 선택 안 함)
    c1, c2 = st.columns(2)
    match_options = [v for v in ["Total", "매칭", "비매칭"] if v in df_raw[COL_MATCH].unique()]
    lowest_options = [v for v in ["Total", "최저가", "비최저가"] if v in df_raw[COL_LOWEST].unique()]
    match_status = c1.selectbox("원부매칭여부", match_options, index=0, key="bpu_match")
    lowest_status = c2.selectbox("최저가여부", lowest_options, index=0, key="bpu_lowest")

    st.markdown(
        f"<div class='chart-caption'>아래는 <b>{match_status} / {lowest_status}</b> 기준입니다.</div>",
        unsafe_allow_html=True,
    )

    # --- BPU별 추이 비교 차트 (상단으로 이동, 26년 1월부터 + 전년 비교선) ---
    h1, h2 = st.columns([2, 3])
    h1.markdown("**BPU별 추이 비교**  \n<span style='color:#6b7280;font-size:0.8rem'>2026년 1월부터</span>", unsafe_allow_html=True)
    metric_bpu = h2.selectbox("지표 선택", METRIC_COLS,
                              index=METRIC_COLS.index("평균 EP 거래액(총결제)"),
                              key="metric_bpu", label_visibility="collapsed")
    all_bpus = sorted(df_raw[COL_BPU].unique(), key=lambda x: (x != "Total", x))
    selected_bpus = st.multiselect("비교할 BPU", all_bpus, default=all_bpus, key="bpu_multi", label_visibility="collapsed")
    _bpu_df = bpu_comparison_data(df_raw, metric_bpu, match_status, lowest_status, unit,
                                  selected_bpus, current_year=2026)
    if not _bpu_df.empty:
        st.line_chart(_bpu_df, height=380)
    else:
        st.info("선택한 조건에 해당하는 데이터가 없습니다.")

    st.markdown("<br/>", unsafe_allow_html=True)

    # --- BPU별 전체 지표 표 (하단) ---
    st.markdown(f"**BPU별 전체 지표**  ·  <span style='color:#6b7280;font-size:0.85rem'>기준: {period_label}</span>", unsafe_allow_html=True)
    table = build_bpu_metrics_table(df_raw, match_status, lowest_status, unit)
    st.dataframe(table, use_container_width=True, hide_index=True, height=680)
