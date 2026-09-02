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


def _match_mean(daily: pd.Series, dates):
    """daily(날짜 인덱스 Series)에서 dates 목록에 해당하는 값을 모아 평균낸다.
    정확한 날짜가 없으면 그 이전의 가장 가까운 값으로 근사(build_yoy_series와 동일 규칙)."""
    if daily.empty:
        return None
    idx = daily.index
    vals = []
    for t in dates:
        if t in daily.index:
            v = daily.loc[t]
        else:
            cand = idx[idx <= t]
            v = daily.loc[cand[-1]] if len(cand) else None
        if v is not None and not pd.isna(v):
            vals.append(float(v))
    if not vals:
        return None
    return sum(vals) / len(vals)


def _partial_last_period(daily: pd.Series, unit: str):
    """마지막 기간(주/월)이 아직 진행 중(부분)인지 판정하고, 그 기간에 실제로
    존재하는 일자들과 '한 기간' 오프셋을 반환한다. (is_partial, current_days, step)."""
    if daily.empty:
        return False, None, None
    last = daily.index.max()
    if unit == "월별":
        month_start = last.replace(day=1)
        month_end = (month_start + pd.offsets.MonthBegin(1)) - pd.Timedelta(days=1)
        is_partial = last < month_end
        cur_days = daily.index[(daily.index >= month_start) & (daily.index <= last)]
        step = pd.DateOffset(months=1)
    elif unit == "주별":
        week_mon = last - pd.Timedelta(days=last.weekday())  # 그 주 월요일
        is_partial = last.weekday() < 6  # 일요일(6)이 아니면 미완성 주
        cur_days = daily.index[(daily.index >= week_mon) & (daily.index <= last)]
        step = pd.Timedelta(weeks=1)
    else:
        return False, None, None  # 일별/월마감은 부분기간 보정 대상 아님
    return is_partial, cur_days, step


def compute_kpi_deltas(series: pd.Series, unit: str, raw_daily: pd.Series = None):
    """최신 시점 기준 현재값 + 3종 증감률(전기간/평균/전년) 계산.

    raw_daily(리샘플 전 일별 시리즈)를 주면, 진행 중인(부분) 달/주를 볼 때 비교 대상도
    '같은 일수만큼'으로 맞춰 계산한다. 예) 8월이 1~3일치만 있으면, 전년비를 '작년 8월 전체
    평균'이 아니라 '작년 같은 날들(동요일 364일 전)'과 비교 — 일별 카드와 결과가 일치.
    raw_daily가 없으면 기존 동작 그대로(완성 기간 기준)."""
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

    # --- 진행 중(부분) 기간 보정 ---
    if raw_daily is not None and not raw_daily.empty:
        rd = raw_daily.dropna().sort_index()
        is_partial, cur_days, step = _partial_last_period(rd, unit)
        if is_partial and cur_days is not None and len(cur_days) > 0:
            _cur_raw = rd.loc[cur_days].mean()
            if not pd.isna(_cur_raw):
                current = float(_cur_raw)
            # 전월/전주비: 한 기간 전, 같은 일자들
            _prev2 = _match_mean(rd, [d - step for d in cur_days])
            if _prev2 is not None:
                prev, prev_delta = _prev2, _pct_delta(current, _prev2)
            # 평균비: 이전 avg_window개 기간 각각 같은 일자 평균 → 다시 평균
            _pmeans = []
            for k in range(1, cfg["avg_window"] + 1):
                m = _match_mean(rd, [d - k * step for d in cur_days])
                if m is not None:
                    _pmeans.append(m)
            if _pmeans:
                avg_ref = sum(_pmeans) / len(_pmeans)
                avg_delta = _pct_delta(current, avg_ref)
            # 전년비: 364일(동요일) 기준으로 같은 일자들
            _yoy2 = _match_mean(rd, [d - pd.Timedelta(days=364) for d in cur_days])
            if _yoy2 is not None:
                yoy_ref, yoy_delta = _yoy2, _pct_delta(current, _yoy2)

    return {
        "current": current,
        "prev_label": cfg["prev_label"], "prev_delta": prev_delta, "prev_value": prev,
        "avg_label": cfg["avg_label"], "avg_delta": avg_delta, "avg_value": avg_ref,
        "yoy_label": cfg["yoy_label"], "yoy_delta": yoy_delta, "yoy_value": yoy_ref,
    }


def pct_delta_safe(current, ref):
    """증감률(%) 계산. 분모(ref, 비교 대상 기간 값)가 음수일 때(예: 반품/취소로 그 기간
    거래액이 마이너스였던 경우) 그냥 (current-ref)/ref로 나누면 부호가 뒤집혀서, '적자에서
    흑자로 전환'(명백한 개선)인데도 마이너스(하락)로 표시되는 문제가 있었다 — 실제로
    2026-08-14에 이 문제가 발견됨. 분모를 abs(ref)로 써서, '나아졌으면 항상 양수,
    나빠졌으면 항상 음수'가 되도록 한다(분모 부호와 무관하게).
    앱 전체(KPI 카드/표/랭킹 등)에서 증감률을 계산하는 곳은 전부 이 함수로 통일한다."""
    if ref is None or pd.isna(ref) or ref == 0 or current is None or pd.isna(current):
        return None
    return (current - ref) / abs(ref) * 100


def _pct_delta(current, ref):
    return pct_delta_safe(current, ref)


def format_value(value: float, metric: str) -> str:
    if value is None or pd.isna(value):
        return "-"
    if metric in PERCENT_LIKE:
        return f"{value:,.1f}%"
    return f"{value:,.0f}"


def format_delta_html(delta) -> str:
    """증가=초록(기호 없음) / 감소=빨강 △ 로 대시보드 전체에서 통일된 표기를 쓴다."""
    if delta is None or pd.isna(delta):
        return "<span class='delta neutral'>-</span>"
    if delta > 0:
        return f"<span class='delta up'>{delta:.1f}%</span>"
    elif delta < 0:
        return f"<span class='delta down'>△ {abs(delta):.1f}%</span>"
    return "<span class='delta neutral'>- 0.0%</span>"


def format_delta_text(delta) -> str:
    """format_delta_html과 완전히 동일한 표기 규칙(증가=기호 없음/감소=△)의 텍스트 전용
    버전. st.dataframe처럼 HTML이 렌더링 안 되는 곳(색상 없이 텍스트만)에서 쓴다."""
    if delta is None or pd.isna(delta):
        return "-"
    if delta > 0:
        return f"{delta:.1f}%"
    elif delta < 0:
        return f"△ {abs(delta):.1f}%"
    return "- 0.0%"


def raw_cutoff_date(selected_period_date, unit):
    """selected_period_date(주별/월별이면 그 기간의 '시작' 라벨: 주의 월요일, 달의 1일)를
    raw_daily(일별 원본) 절삭용 '그 기간의 끝' 날짜로 바꾼다.

    문제였던 것: KPI 카드/차트 여러 곳에서 raw_daily를 `s.index <= selected_period_date`로
    잘랐는데, selected_period_date가 주의 '월요일 라벨'이다 보니, 실제로는 이미 존재하는
    그 주의 화/수요일 등 데이터까지 통째로 버려지고 있었음(예: 기준시점=8/10인데 원본엔
    8/12까지 있으면, 8/11·8/12가 이미 실제 데이터인데도 무시됨). 그 결과 '아직 하루치만
    있다'고 잘못 판단해서 부분기간 보정이 과도하게 적용되는 문제가 있었음.

    이 함수로 '그 기간의 끝'(주=일요일, 월=말일)까지 잘라야, 그 기간에 실제로 존재하는
    날짜는 다 살리면서도 다음 기간(예: 다음 주) 데이터는 여전히 제외된다 — 원본이 기간
    끝까지 없으면 그냥 있는 데까지만 자동으로 잡히니 안전하다."""
    d = pd.Timestamp(selected_period_date)
    if unit == "주별":
        return d + pd.Timedelta(days=6)
    elif unit in ("월별", "월마감"):
        month_start = d.replace(day=1)
        next_month = month_start + pd.offsets.MonthBegin(1)
        return next_month - pd.Timedelta(days=1)
    return d  # 일별은 그대로


def effective_month_of_week(date):
    """그 주(월요일 date)가 실제로 속하는 '달'의 1일을 반환한다. 기본은 '월요일이 속한
    달'을 그대로 쓰되, 그 월요일이 그 달의 '마지막 날'인 경우(=화~일 6일이 전부 다음
    달)만 예외로 다음 달로 넘긴다 — week_of_month와 반드시 같은 기준을 써야 '9월
    1주차'인데 '8월'이 붙는 식으로 월과 주차가 어긋나지 않는다."""
    date = pd.Timestamp(date)
    base_month_start = date.replace(day=1)
    base_month_end = (base_month_start + pd.offsets.MonthBegin(1)) - pd.Timedelta(days=1)
    if date == base_month_end:
        return base_month_start + pd.offsets.MonthBegin(1)
    return base_month_start


def week_of_month(date) -> int:
    """해당 날짜(그 주의 월요일)가 같은 달 안에서 몇 번째 주인지.

    기본은 '월요일이 속한 달' 기준 그대로 두되(예전 방식과 동일, 회귀 없음), 딱 하나
    예외가 있다 — 월요일이 그 달의 '마지막 날'이라 화~일 6일이 전부 다음 달에 속하는
    주는, 그 다음 달의 1주차로 본다 (예: 2026-08-31(월)~09-06(일)인 주는 '8월 5주차'가
    아니라 '9월 1주차'). 이 판단은 effective_month_of_week와 반드시 같은 기준을 쓴다.

    예전엔 '(그 달 1일의 요일 오프셋 + 날짜) // 7' 방식으로 계산했는데,
    1일이 월요일이 아닌 달에서는 '그 달의 첫 월요일'이 이미 2주차로 계산되고
    1주차가 통째로 안 나오는 문제가 있었음 (예: 2026년 7월 1일=수요일이라
    7월의 첫 월요일인 7/6이 2주차로 잘못 계산됨).

    같은 달에 속하는 월요일들을 직접 나열해서, 이 날짜가 몇 번째 월요일인지로
    계산하도록 바꿈 — 그 달의 첫 월요일은 항상 1주차가 된다."""
    date = pd.Timestamp(date)
    eff_month_start = effective_month_of_week(date)
    eff_month_end = (eff_month_start + pd.offsets.MonthBegin(1)) - pd.Timedelta(days=1)
    # eff_month_start가 date 자체보다 나중일 수 있다(예: date=8/31인데 eff_month_start=9/1) —
    # 이 경우 date 자신을 목록에 포함시키려면 시작점을 date와 eff_month_start 중 이른
    # 쪽으로 잡아야 한다. 그렇지 않으면 date보다 항상 큰 월요일들만 나열되어 0이 나옴.
    mondays_in_month = pd.date_range(min(eff_month_start, date), eff_month_end, freq="W-MON")
    return int((mondays_in_month <= date).sum())


def make_period_label(last_date, unit: str) -> str:
    """조회 기준 라벨. 예) '26년 7월 2주차' / '26년 7월 11일' / '26년 6월'."""
    d = pd.Timestamp(last_date)
    yy = d.strftime("%y")
    if unit == "일별":
        return f"{yy}년 {d.month}월 {d.day}일"
    elif unit == "주별":
        eff = effective_month_of_week(d)
        wom = week_of_month(d)
        return f"{eff.strftime('%y')}년 {eff.month}월 {wom}주차"
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
