"""마케팅 실적 현황 대시보드 - 메인 엔트리포인트.

좌측 사이드바: 조회 단위(일/주/월/월마감) + 메뉴(Total + BPU별) + 데이터 업로드
본문: 선택한 메뉴(BPU)에 따라 KPI + 차트 + 표 렌더링
"""
import streamlit as st
import pandas as pd

from data_loader import load_data
from sidebar import render_sidebar, render_combo_filter
from filters import filter_by_combo
from kpi import render_kpi_cards
from charts import main_trend_data, bpu_comparison_data
from comparison_table import render_summary_table_html
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
    load_data.clear()

# --- 데이터 로드 ---
df_raw = load_data()
if side["uploaded_file"] is not None:
    _uf = side["uploaded_file"]
    df_raw = load_data(uploaded_file=_uf, file_name=getattr(_uf, "name", None))
    _min = df_raw[COL_DATE].min().strftime("%Y-%m-%d")
    _max = df_raw[COL_DATE].max().strftime("%Y-%m-%d")
    st.sidebar.success(f"업로드 완료: {_min} ~ {_max}")
    _csv = df_raw.sort_values([COL_BPU, COL_MATCH, COL_LOWEST, COL_DATE]).to_csv(index=False, encoding="utf-8-sig")
    st.sidebar.download_button(
        "⬇️ 전체 데이터 CSV 다운로드", _csv.encode("utf-8-sig"),
        file_name="ep_data_long.csv", mime="text/csv", use_container_width=True,
    )

unit = side["view_unit"]
bpu = side["bpu"]  # 메뉴에서 자동 결정된 BPU

# 데이터 반영 현황
last_date = df_raw[COL_DATE].max()
_weekday_kr = ["월", "화", "수", "목", "금", "토", "일"][last_date.weekday()]
data_status = f"데이터 반영: {last_date.strftime('%Y-%m-%d')}({_weekday_kr})까지"
st.sidebar.info(f"🗓️ {data_status}")

# 기준 라벨
_total = df_raw[(df_raw[COL_BPU] == "Total") & (df_raw[COL_MATCH] == "Total") & (df_raw[COL_LOWEST] == "Total")]
_series = resample_series(_total, "평균 EP 거래액(총결제)", unit).dropna()
period_last = _series.index[-1] if not _series.empty else last_date
period_label = make_period_label(period_last, unit)

# ============================================================
# 공통 페이지 렌더링 (모든 메뉴가 같은 레이아웃, BPU만 다름)
# ============================================================
_page_title = side["page"].split(". ", 1)[-1] if ". " in side["page"] else side["page"]
st.markdown(f"<div class='dash-header-title'>📊 {_page_title}</div>", unsafe_allow_html=True)
st.markdown(
    f"<div class='dash-header-sub'>조회 단위: <b>{unit}</b> · 기준: <b>{period_label}</b> · {data_status}</div>",
    unsafe_allow_html=True,
)

# 원부매칭/최저가 필터 (BPU는 메뉴에서 이미 결정)
flt = render_combo_filter(df_raw, bpu, key_prefix="main")
df_combo = filter_by_combo(df_raw, flt["bpu"], flt["match_status"], flt["lowest_status"])

if df_combo.empty:
    st.warning("선택한 조합에 데이터가 없습니다.")
    st.stop()

st.markdown(
    f"<div class='chart-caption'>아래 KPI는 <b>{flt['bpu']} / {flt['match_status']} / {flt['lowest_status']}</b> 기준, "
    f"<b>{period_label}</b>의 값입니다.</div>",
    unsafe_allow_html=True,
)

# --- KPI 카드 ---
render_kpi_cards(df_combo, unit)
st.markdown("<br/>", unsafe_allow_html=True)

# --- 지표 추이 차트 ---
h1, h2 = st.columns([2, 3])
h1.markdown("**지표 추이**")
metric_main = h2.selectbox("지표 선택", METRIC_COLS,
                           index=METRIC_COLS.index("평균 EP 거래액(총결제)"),
                           key="metric_main", label_visibility="collapsed")

latest_year = int(df_combo[COL_DATE].max().year)
_year_series = resample_series(df_combo, metric_main, unit).dropna()
_this_year = _year_series[_year_series.index.year == latest_year]

import datetime as _dt
_fixed_start = _dt.date(latest_year, 1, 1)
if not _this_year.empty:
    _max_d = _this_year.index.max().date()
    _data_min = _this_year.index.min().date()
else:
    _max_d = df_combo[COL_DATE].max().date()
    _data_min = df_combo[COL_DATE].min().date()
_min_d = max(_fixed_start, _data_min) if _data_min > _fixed_start else _fixed_start

if unit == "일별":
    _default_start = max(_min_d, _max_d - _dt.timedelta(days=30))
    col_date, col_yoy = st.columns([3, 2])
    with col_date:
        date_range = st.date_input(
            "기간 설정", value=(_default_start, _max_d),
            min_value=_min_d, max_value=_max_d, key="trend_range",
        )
    with col_yoy:
        show_yoy = st.checkbox("전년 비교선 표시", value=True, key="show_yoy")
    if isinstance(date_range, tuple) and len(date_range) == 2:
        d_start, d_end = date_range
    else:
        d_start, d_end = _default_start, _max_d
else:
    show_yoy = st.checkbox("전년 비교선 표시", value=True, key="show_yoy")
    d_start, d_end = _min_d, _max_d

_trend_df, _yoy_info = main_trend_data(df_combo, metric_main, unit, show_yoy,
                            current_year=latest_year, date_start=d_start, date_end=d_end)
st.line_chart(_trend_df, height=380)

# --- 캡션 ---
_unit_desc = {"일별": "일별", "주별": "주평균", "월별": "월평균", "월마감": "월평균(마감)"}[unit]
_is_monthly = unit in ("월별", "월마감")

if _is_monthly:
    _last_month_end = last_date + pd.offsets.MonthEnd(0)
    if unit == "월별" and last_date < _last_month_end:
        _end_label = f"{last_date.month}월(~{last_date.day}일)"
    elif unit == "월마감":
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
        _last_month_end = last_date + pd.offsets.MonthEnd(0)
        if last_date < _last_month_end:
            _yoy_last = last_date - pd.Timedelta(days=364)
            _yoy_end_label = f"{_yoy_last.month}월(~{_yoy_last.day}일)"
        else:
            _yoy_end_label = f"{ye.month}월"
        _yoy_range = f"{ys.strftime('%Y')}년 {ys.month}월 ~ {_yoy_end_label}"
        _caption += f"<br/>전년 비교: {_yoy_range} (동요일 기준, 364일 전)"
    elif unit == "월마감":
        _yoy_range = f"{ys.strftime('%Y')}년 {ys.month}월 ~ {ye.month}월"
        _caption += f"<br/>전년 비교: {_yoy_range} (전년 동월)"
    else:
        _yoy_range = f"{ys.strftime('%Y-%m-%d')} ~ {ye.strftime('%Y-%m-%d')}"
        _caption += f"<br/>전년 비교: {_yoy_range} (동요일 기준, 364일 전)"
_caption += "</div>"
st.markdown(_caption, unsafe_allow_html=True)

st.markdown("<br/>", unsafe_allow_html=True)

# --- 하단 실적 요약 표 ---
st.markdown(f"**실적 요약 표**  ·  <span style='color:#6b7280;font-size:0.85rem'>기준: {period_label}</span>", unsafe_allow_html=True)
summary_html = render_summary_table_html(df_combo, unit)
st.markdown(summary_html, unsafe_allow_html=True)
