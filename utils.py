"""공통 유틸리티: 컬럼 상수, 기간단위(일/주/월) 설정, KPI 증감률 계산."""
import pandas as pd

COL_DATE = "날짜"
COL_BPU = "BPU"
COL_MATCH = "원부매칭여부"
COL_LOWEST = "최저가여부"

METRIC_COLS = [
    "평균 EP 전시 상품수", "평균 원부매칭 상품수", "원부매칭율(%)",
    "평균 최저가 상품수", "최저가율(%)", "평균 EP 거래액(순결제)",
    "평균 EP 거래액(총결제)", "평균 EP 고객수(총결제)",
    "평균 EP 첫구매 거래액(총결제)", "평균 EP 첫구매 고객수(총결제)",
    "첫구매거래액(%)", "평균 EP UV", "평균 EP 비회원UV",
    "EP 전시 상품당 유입수", "평균 EP 신규가입수", "신규가입율",
    "구매전환율(%)", "첫구매 전환율(%)",
]

# KPI 요약 카드에 표시할 헤드라인 지표 (실적 요약 탭)
HEADLINE_METRICS = [
    "평균 EP 거래액(총결제)", "평균 EP 거래액(순결제)", "평균 EP UV",
    "원부매칭율(%)", "최저가율(%)", "구매전환율(%)",
]

PERCENT_LIKE = {"원부매칭율(%)", "최저가율(%)", "첫구매거래액(%)", "신규가입율", "구매전환율(%)", "첫구매 전환율(%)"}

# 보기 단위별 설정: 리샘플 규칙 / 이전기간 라벨 / 평균비교 라벨+윈도우 / 전년 라벨
UNIT_CONFIG = {
    "일별": dict(rule="D", prev_label="전일비", avg_label="전주평균비", avg_window=7, yoy_label="전년동요일비"),
    "주별": dict(rule="W-SUN", prev_label="전주비", avg_label="전4주평균비", avg_window=4, yoy_label="전년동주비"),
    "월별": dict(rule="ME", prev_label="전월비", avg_label="전분기평균비", avg_window=3, yoy_label="전년동요일비"),
    "월마감": dict(rule="ME", prev_label="전월비", avg_label="전분기평균비", avg_window=3, yoy_label="전년동월비"),
}


def resample_series(df: pd.DataFrame, metric: str, unit: str) -> pd.Series:
    """단일 조합으로 필터링된 df를 기간단위로 리샘플링한 시계열.

    주별: 월~일요일로 묶고(W-SUN), 라벨은 그 주의 '월요일'로 표시한다.
    월별: 진행 중인 달 포함 (있는 날의 평균으로 표시).
    월마감: 완료된 달만 (미완성 마지막 달 제외).
    """
    s = df.set_index(COL_DATE)[metric].sort_index()
    if s.empty:
        return s
    last_date = s.index.max()
    rule = UNIT_CONFIG[unit]["rule"]
    resampled = s.resample(rule).mean()

    if unit == "주별":
        resampled.index = resampled.index - pd.Timedelta(days=6)
    elif unit == "월마감":
        # 마지막 달이 월말까지 안 찼으면 제외 (마감된 달만)
        last_period_end = resampled.index[-1]
        if last_date < last_period_end:
            resampled = resampled.iloc[:-1]

    return resampled


def build_yoy_series(series: pd.Series, unit: str) -> pd.Series:
    """각 시점의 전년 비교 값을 매칭한 시계열.

    - 일별/주별/월별: 364일(=52주) 전 → 동요일 비교.
    - 월마감: 전년 같은 달(1년 전) → 동월 비교.
    데이터에 해당 날짜가 없으면 가장 가까운 이전 값으로 근사한다.
    """
    if series.empty:
        return series
    idx = series.index

    if unit == "월마감":
        prev_dates = idx - pd.DateOffset(years=1)
    else:
        # 일별/주별/월별: 364일 전 = 52주 전, 요일이 정확히 일치
        prev_dates = idx - pd.Timedelta(days=364)

    yoy_vals = []
    for pd_date in prev_dates:
        if pd_date in series.index:
            yoy_vals.append(series.loc[pd_date])
        else:
            candidates = series.index[series.index <= pd_date]
            yoy_vals.append(series.loc[candidates[-1]] if len(candidates) else None)
    return pd.Series(yoy_vals, index=idx)


def compute_kpi_deltas(series: pd.Series, unit: str):
    """최신 시점 기준 현재값 + 3종 증감률(전기간/평균/전년) 계산."""
    cfg = UNIT_CONFIG[unit]
    series = series.dropna()
    if series.empty:
        return None

    current = series.iloc[-1]

    prev = series.shift(1).iloc[-1] if len(series) > 1 else None
    prev_delta = _pct_delta(current, prev)

    avg_ref = series.shift(1).rolling(cfg["avg_window"]).mean().iloc[-1]
    avg_delta = _pct_delta(current, avg_ref)

    # 전년: 최신 시점의 '작년 같은 날짜' 값
    yoy_series = build_yoy_series(series, unit)
    yoy_ref = yoy_series.iloc[-1] if not yoy_series.empty else None
    yoy_delta = _pct_delta(current, yoy_ref)

    return {
        "current": current,
        "prev_label": cfg["prev_label"], "prev_delta": prev_delta, "prev_value": prev,
        "avg_label": cfg["avg_label"], "avg_delta": avg_delta, "avg_value": avg_ref,
        "yoy_label": cfg["yoy_label"], "yoy_delta": yoy_delta, "yoy_value": yoy_ref,
    }


def _pct_delta(current, ref):
    if ref is None or pd.isna(ref) or ref == 0 or pd.isna(current):
        return None
    return (current - ref) / ref * 100


def format_value(value: float, metric: str) -> str:
    if value is None or pd.isna(value):
        return "-"
    if metric in PERCENT_LIKE:
        return f"{value:,.1f}%"
    return f"{value:,.0f}"


def format_delta_html(delta) -> str:
    if delta is None or pd.isna(delta):
        return "<span class='delta neutral'>-</span>"
    if delta > 0:
        return f"<span class='delta up'>▲ {delta:.1f}%</span>"
    elif delta < 0:
        return f"<span class='delta down'>▼ {abs(delta):.1f}%</span>"
    return "<span class='delta neutral'>- 0.0%</span>"


def week_of_month(date) -> int:
    """해당 날짜가 그 달의 몇 번째 주인지 (1일이 속한 주=1주차, 월요일 시작 기준)."""
    date = pd.Timestamp(date)
    first_day = date.replace(day=1)
    # 그 달 1일의 요일(월=0) 만큼 오프셋
    dom = date.day + first_day.weekday()
    return (dom - 1) // 7 + 1


def make_period_label(last_date, unit: str) -> str:
    """조회 기준 라벨. 예) '26년 7월 2주차' / '26년 7월 11일' / '26년 6월'."""
    d = pd.Timestamp(last_date)
    yy = d.strftime("%y")
    if unit == "일별":
        return f"{yy}년 {d.month}월 {d.day}일"
    elif unit == "주별":
        wom = week_of_month(d)
        return f"{yy}년 {d.month}월 {wom}주차"
    elif unit == "월마감":
        return f"{yy}년 {d.month}월 (마감)"
    else:  # 월별
        return f"{yy}년 {d.month}월"


def is_last_period_partial(df, unit) -> bool:
    """선택 단위의 마지막 구간(주/월)이 아직 진행 중(미완성)인지 판단.
    일별은 항상 완성으로 본다."""
    s = df.set_index(COL_DATE).sort_index()
    if s.empty:
        return False
    last_date = s.index.max()
    if unit == "주별":
        # 그 주 일요일까지 데이터가 있는지
        days_since_monday = last_date.weekday()  # 월=0 ... 일=6
        return days_since_monday < 6  # 일요일(6)이 아니면 미완성
    elif unit == "월별":
        # 그 달 말일까지 데이터가 있는지
        next_month = (last_date + pd.offsets.MonthBegin(1))
        month_end = next_month - pd.Timedelta(days=1)
        return last_date < month_end
    return False
