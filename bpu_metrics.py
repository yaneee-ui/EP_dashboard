"""BPU별 전체 지표(18개) 실적 테이블 생성.

행 = 지표(18개), 열 = BPU(Total, e-영업1~4).
선택한 단위(일/주/월)의 가장 최근 값을 표시한다.
메모리 절약: 전체 시계열을 만들지 않고, 필요한 마지막 구간 값만 계산한다.
"""
import pandas as pd

from utils import (
    COL_BPU, COL_MATCH, COL_LOWEST, COL_DATE, METRIC_COLS,
    resample_series, format_value,
)


def build_bpu_metrics_table(df_all, match_status, lowest_status, unit):
    """행=지표, 열=BPU 형태의 실적 테이블. 최근 기간 값."""
    bpus = sorted(df_all[COL_BPU].unique(), key=lambda x: (x != "Total", x))

    table = {}
    for bpu in bpus:
        sub = df_all[
            (df_all[COL_BPU] == bpu)
            & (df_all[COL_MATCH] == match_status)
            & (df_all[COL_LOWEST] == lowest_status)
        ]
        if sub.empty:
            continue
        # 지표별로 마지막 구간 값만 필요 -> 리샘플 결과의 마지막 값만 취함
        col_vals = {}
        for metric in METRIC_COLS:
            series = resample_series(sub, metric, unit).dropna()
            col_vals[metric] = format_value(series.iloc[-1], metric) if not series.empty else "-"
        table[bpu] = col_vals
        del sub

    out = pd.DataFrame(table)
    out.index.name = "지표"
    return out.reset_index()
