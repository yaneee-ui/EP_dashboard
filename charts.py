"""차트용 데이터 생성 (plotly 없이 Streamlit 내장 차트 사용).

각 함수는 st.line_chart()에 넘길 DataFrame을 반환한다.
인덱스=날짜, 컬럼=계열(실적/전년 등).
"""
import pandas as pd

from utils import (
    COL_BPU, COL_MATCH, COL_LOWEST, UNIT_CONFIG,
    resample_series, is_last_period_partial,
)


def main_trend_data(df_combo, metric, unit, show_yoy=True, current_year=None,
                    date_start=None, date_end=None):
    """지표 추이용 DataFrame + 전년 비교 기간 정보.

    Returns: (DataFrame, dict or None)
        dict keys: yoy_start, yoy_end (전년 비교 기간의 시작/끝 실제 날짜)
    """
    full = resample_series(df_combo, metric, unit)
    if current_year is not None:
        series = full[full.index.year == current_year]
    else:
        series = full
    if date_start is not None:
        series = series[series.index >= pd.Timestamp(date_start)]
    if date_end is not None:
        series = series[series.index <= pd.Timestamp(date_end)]

    data = pd.DataFrame({metric: series})
    yoy_info = None

    if show_yoy and not series.empty:
        if unit == "월마감":
            prev_dates = series.index - pd.DateOffset(years=1)
        else:
            prev_dates = series.index - pd.Timedelta(days=364)
        yoy_vals = []
        for pd_date in prev_dates:
            if pd_date in full.index:
                yoy_vals.append(full.loc[pd_date])
            else:
                cand = full.index[full.index <= pd_date]
                yoy_vals.append(full.loc[cand[-1]] if len(cand) else None)
        cfg = UNIT_CONFIG[unit]
        data[f"{cfg['yoy_label']}(전년)"] = yoy_vals

        # 전년 비교 기간 정보
        yoy_info = {
            "yoy_start": prev_dates[0],
            "yoy_end": prev_dates[-1],
        }

    return data, yoy_info


def bpu_comparison_data(df_all, metric, match_status, lowest_status, unit,
                        selected_bpus, current_year=None):
    """사업부별 비교용 DataFrame. 컬럼=각 BPU."""
    cols = {}
    for bpu in selected_bpus:
        sub = df_all[
            (df_all[COL_BPU] == bpu)
            & (df_all[COL_MATCH] == match_status)
            & (df_all[COL_LOWEST] == lowest_status)
        ]
        if sub.empty:
            continue
        full = resample_series(sub, metric, unit)
        if current_year is not None:
            series = full[full.index.year >= current_year]
        else:
            series = full
        cols[bpu] = series
        del sub

    if not cols:
        return pd.DataFrame()
    return pd.DataFrame(cols)
