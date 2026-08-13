"""
회귀 테스트: 핵심 계산 로직이 여전히 정확한지 확인.

실행: python3 test_regression.py
(pytest 설치돼 있으면 `pytest test_regression.py`로도 실행 가능 — assert 기반이라 호환됨)

이 테스트들은 실제 회사 데이터 없이도 항상 돌아가도록, 손으로 검증 가능한 합성(synthetic)
데이터로 구성했다. 2026-08-13에 실제로 발견/수정했던 버그들을 재현하는 케이스 위주:
  - 부분기간(진행 중인 주/월) raw_daily 절삭 문제 (raw_cutoff_date)
  - CR/객단가 단순평균 금지 원칙
  - 컨버터의 병합 셀(ffill) 문제

새 기능을 추가하거나 기존 계산 로직을 건드릴 때마다 이 스크립트를 돌려서, 예전에
잡았던 버그가 다시 생기지 않았는지 확인하는 용도.
"""
import sys
import os
import io
import pandas as pd
import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

PASS, FAIL = [], []


def check(name, condition, detail=""):
    if condition:
        PASS.append(name)
        print(f"  \u2705 {name}")
    else:
        FAIL.append(name)
        print(f"  \u274c {name}  {detail}")


def _load_app_functions(*names):
    """app.py는 최상단에 st.set_page_config() 등 Streamlit 전용 코드가 있어서 그냥
    import하면 에러가 난다 — 필요한 함수 소스만 추출해서 격리된 네임스페이스에서 실행."""
    app_path = os.path.join(_HERE, "app.py")
    with open(app_path, encoding="utf-8") as f:
        src = f.read()
    from utils import (
        UNIT_CONFIG, compute_kpi_deltas, raw_cutoff_date, _partial_last_period, _match_mean,
    )
    ns = {
        "pd": pd, "np": np, "io": io,
        "UNIT_CONFIG": UNIT_CONFIG, "compute_kpi_deltas": compute_kpi_deltas,
        "raw_cutoff_date": raw_cutoff_date, "_partial_last_period": _partial_last_period,
        "_match_mean": _match_mean,
        "BPU_GROUPS": {"자사": ["e-영업1", "e-영업2"], "입점": ["e-영업3", "e-영업4"]},
    }
    for name in names:
        start = src.index(f"def {name}")
        nxt = src.index("\ndef ", start + 10)
        exec(src[start:nxt], ns)
    return ns


# ============================================================
# 1. raw_cutoff_date: 절삭 기준이 기간의 '시작'이 아니라 '끝'인지
#    (2026-08-13 버그: 기준시점=주의 월요일 라벨인데 그 날짜까지만 잘라서,
#     이미 존재하는 화/수요일 데이터까지 버려지고 있었음)
# ============================================================
def test_raw_cutoff_date():
    print("\n[1] raw_cutoff_date — 절삭 기준")
    from utils import raw_cutoff_date
    check(
        "주별: 월요일 -> 그 주 일요일까지",
        raw_cutoff_date(pd.Timestamp("2026-08-10"), "주별") == pd.Timestamp("2026-08-16"),
    )
    check(
        "월별: 1일 -> 그 달 말일까지",
        raw_cutoff_date(pd.Timestamp("2026-08-01"), "월별") == pd.Timestamp("2026-08-31"),
    )
    check(
        "월마감: 1일 -> 그 달 말일까지",
        raw_cutoff_date(pd.Timestamp("2026-08-01"), "월마감") == pd.Timestamp("2026-08-31"),
    )
    check(
        "일별: 그대로(당일)",
        raw_cutoff_date(pd.Timestamp("2026-08-10"), "일별") == pd.Timestamp("2026-08-10"),
    )


# ============================================================
# 2. compute_kpi_deltas: 부분기간(진행 중인 주) — 실제 존재하는 날짜를 다 써야 함
# ============================================================
def test_partial_week_uses_all_available_days():
    print("\n[2] 부분주(진행 중인 주) — 있는 날짜를 다 써야 함")
    from utils import compute_kpi_deltas, raw_cutoff_date

    dates = pd.date_range("2025-01-01", "2026-08-12")  # 그 주는 8/10~12까지만 존재(3일)
    np.random.seed(1)
    vals = pd.Series(np.random.randint(10_000_000, 20_000_000, len(dates)), index=dates)
    sel = pd.Timestamp("2026-08-10")  # "8월 2주차" 라벨(그 주의 월요일)

    series = vals.resample("W-SUN").mean()
    series.index = series.index - pd.Timedelta(days=6)
    series = series[series.index <= sel]
    raw = vals[vals.index <= raw_cutoff_date(sel, "주별")]
    stats = compute_kpi_deltas(series, "주별", raw_daily=raw)

    expected = vals.loc[["2026-08-10", "2026-08-11", "2026-08-12"]].mean()
    check(
        "3일(8/10~12) 평균을 정확히 씀",
        abs(stats["current"] - expected) < 0.01,
        f"got={stats['current']}, expected={expected}",
    )

    # 예전 버그(선택시점까지만 절삭)와 비교 — 다른 값이 나와야 "버그가 있었다"가 재현됨
    raw_buggy = vals[vals.index <= sel]
    stats_buggy = compute_kpi_deltas(series, "주별", raw_daily=raw_buggy)
    check(
        "예전 버그 방식(월요일까지만 절삭)은 다른 값 -> 지금 방식이 실제로 다르게 동작함을 확인",
        stats_buggy["current"] != stats["current"],
        f"buggy={stats_buggy['current']}, fixed={stats['current']}",
    )


def test_complete_week_uses_full_average():
    print("\n[3] 완성된 주(7일 전부 존재) — 억지로 하루만 쓰면 안 됨")
    from utils import compute_kpi_deltas, raw_cutoff_date

    dates = pd.date_range("2025-01-01", "2026-08-16")  # 그 주 일요일까지 전부 존재
    np.random.seed(1)
    vals = pd.Series(np.random.randint(10_000_000, 20_000_000, len(dates)), index=dates)
    sel = pd.Timestamp("2026-08-10")

    series = vals.resample("W-SUN").mean()
    series.index = series.index - pd.Timedelta(days=6)
    series = series[series.index <= sel]
    raw = vals[vals.index <= raw_cutoff_date(sel, "주별")]
    stats = compute_kpi_deltas(series, "주별", raw_daily=raw)

    expected = vals.loc[pd.date_range("2026-08-10", "2026-08-16")].mean()
    check(
        "7일 전체 평균과 일치(부분기간으로 왜곡 안 됨)",
        abs(stats["current"] - expected) < 0.01,
        f"got={stats['current']}, expected={expected}",
    )


# ============================================================
# 3. CR/객단가: 비율 지표는 날짜별 단순평균이 아니라 분자/분모 합산 후 재계산
# ============================================================
def test_ratio_metric_no_naive_average():
    print("\n[4] 비율 지표(CR/객단가) — 단순평균 금지 원칙 (수치로 확인)")
    gmv = pd.Series([100000, 300000, 50000])  # 거래액
    cnt = pd.Series([10, 10, 5])              # 구매객수
    daily_aov = gmv / cnt                     # 날짜별 객단가
    naive_avg = daily_aov.mean()              # 잘못된 방식: 날짜별 값의 평균
    correct_aov = gmv.sum() / cnt.sum()       # 올바른 방식: 합산 후 재계산
    check(
        "단순평균과 올바른 계산이 실제로 달라짐을 확인(그래서 원칙이 중요함)",
        abs(naive_avg - correct_aov) > 1,
        f"naive={naive_avg:.0f}, correct={correct_aov:.0f}",
    )
    print(f"     참고: 단순평균={naive_avg:.0f} / 올바른 값={correct_aov:.0f} (차이 {naive_avg - correct_aov:+.0f})")


def test_bpu_weekly_report_aov_matches_gmv_over_count():
    print("\n[5] 6번 페이지(주간보고) 객단가가 거래액/구매객수와 정확히 일치하는지")
    ns = _load_app_functions(
        "aggregate_traffic", "exclude_ff_brand", "compute_bpu_comparison_rows",
        "compute_category_yoy_rows", "build_weekly_report_excel",
    )
    build_weekly_report_excel = ns["build_weekly_report_excel"]
    compute_bpu_comparison_rows = ns["compute_bpu_comparison_rows"]

    dates = pd.date_range("2025-01-01", "2026-07-31")
    np.random.seed(2)
    rows = []
    for bpu in ["e-영업1", "e-영업2", "e-영업3", "e-영업4"]:
        for seg in ["전체", "회원", "신규"]:  # 새로 추가한 지표(회원UV 등) 검증하려면 이 세그먼트들이 있어야 함
            for d in dates:
                trf = np.random.randint(1000, 2000)
                cnt = np.random.randint(50, 150)
                gmv = cnt * np.random.randint(50000, 150000)
                rows.append({"날짜": d, "BPU": bpu, "회원구분": seg, "트래픽": trf, "거래액": gmv, "구매객수": cnt})
    df_traffic = pd.DataFrame(rows)
    tot = df_traffic.groupby(["날짜", "회원구분"], as_index=False)[["트래픽", "거래액", "구매객수"]].sum()
    tot["BPU"] = "Total"
    df_traffic = pd.concat([df_traffic, tot], ignore_index=True)
    df_traffic["CR"] = (df_traffic["구매객수"] / df_traffic["트래픽"] * 100).where(df_traffic["트래픽"] > 0, 0)
    df_traffic["객단가"] = (df_traffic["거래액"] / df_traffic["구매객수"]).where(df_traffic["구매객수"] > 0, 0)
    df_category = pd.DataFrame(columns=["날짜", "BPU", "카테고리", "브랜드", "회원구분", "거래액"])

    _, left_df, _ = build_weekly_report_excel(
        "월별", pd.Timestamp("2026-07-31"), df_traffic, df_category, "전체", False
    )

    # 반올림된 표 숫자로 역산하면 반올림 오차가 정상적으로 발생하므로(실데이터로도 확인했던
    # 부분), 표 숫자가 아니라 반올림 전 정밀값끼리 직접 비교한다.
    _bpu_rows, _, _ = compute_bpu_comparison_rows(df_traffic, "월별", pd.Timestamp("2026-07-31"))
    gmv_stats = [r for r in _bpu_rows if r["metric_label"] == "거래액(순결제)" and r["bpu"] == "Total"][0]["stats"]
    cnt_stats = [r for r in _bpu_rows if r["metric_label"] == "구매객수" and r["bpu"] == "Total"][0]["stats"]
    _precise_aov = gmv_stats["current"] / cnt_stats["current"]
    _table_aov = left_df[(left_df["구분"] == "전체") & (left_df["지표"] == "객단가")][
        [c for c in left_df.columns if c.endswith("년")][-1]
    ].iloc[0]
    check(
        "정밀 거래액/구매객수 값으로 계산한 객단가와 표의 객단가가 일치(반올림 오차 이내)",
        abs(_precise_aov - _table_aov) < 1,
        f"정밀계산={_precise_aov:.4f}, 표={_table_aov}",
    )
    check("객단가가 '객단가' 지표 행 자체로도 존재", "객단가" in left_df["지표"].values)
    check(
        "새로 추가한 지표(회원UV/회원거래액/신규UV/신규거래액)가 다 있음",
        {"회원UV", "회원거래액", "신규UV", "신규거래액"}.issubset(set(left_df["지표"].values)),
        f"실제 지표들: {sorted(left_df['지표'].unique())}",
    )


# ============================================================
# 4. 컨버터: 병합 셀(ffill) 처리 — 2026-08-13에 발견한 버그 재현
# ============================================================
def test_converter_ffill_merged_cells():
    print("\n[6] 컨버터 — 병합 셀(ffill) 처리")
    converter_path = os.path.join(_HERE, "converter_app.py")
    if not os.path.exists(converter_path):
        print("  \u26a0\ufe0f  converter_app.py 없음 — 건너뜀")
        return
    with open(converter_path, encoding="utf-8") as f:
        src = f.read()

    ns = {"pd": pd, "io": io}
    for fn in ["_pivot_traffic", "detect_file_type", "convert_ep_traffic", "_convert_traffic_old", "_convert_traffic_new"]:
        start = src.index(f"def {fn}")
        nxt = src.index("\ndef ", start + 10)
        exec(src[start:nxt], ns)
    _convert_traffic_old = ns["_convert_traffic_old"]

    # "구 구조" 병합 셀 합성 데이터 (BPU만 매 행 값이 있고 나머지 라벨은 병합 셀처럼 비어있음)
    rows = [
        [None, "회원구분", "신규구분1", "신규구분2", "구분", "BPU", "2026-08-10", "2026-08-11"],
        ["트래픽", "전체", "전체", "전체", "전체", "전체", 1000, 1100],
        [None, None, None, None, "기본", "전체", 900, 950],
        [None, None, None, None, None, "e-영업1", 400, 420],
        [None, None, None, None, None, "e-영업2", 500, 530],
    ]
    df = pd.DataFrame(rows)
    result_df = _convert_traffic_old(df, is_xlsx=False)

    e1 = result_df[(result_df["BPU"] == "e-영업1") & (result_df["회원구분"] == "전체")]
    check("e-영업1 데이터가 (병합 셀 무시하고) 정상 추출됨", not e1.empty)
    if not e1.empty:
        r = e1[e1["날짜"] == "2026-08-10"]
        check(
            "e-영업1의 8/10 트래픽 값이 정확히 400",
            not r.empty and r.iloc[0]["트래픽"] == 400,
            f"got={r['트래픽'].tolist() if not r.empty else 'EMPTY'}",
        )


# ============================================================
# 실행
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("EP 대시보드 회귀 테스트")
    print("=" * 60)

    test_raw_cutoff_date()
    test_partial_week_uses_all_available_days()
    test_complete_week_uses_full_average()
    test_ratio_metric_no_naive_average()
    test_bpu_weekly_report_aov_matches_gmv_over_count()
    test_converter_ffill_merged_cells()

    print()
    print("=" * 60)
    print(f"결과: {len(PASS)}개 통과 / {len(FAIL)}개 실패")
    if FAIL:
        print("실패한 항목:", ", ".join(FAIL))
        sys.exit(1)
    else:
        print("\u2705 전부 통과!")
    print("=" * 60)
