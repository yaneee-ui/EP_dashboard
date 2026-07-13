"""Data.xlsx -> long-format CSV 변환 (v2, 올바른 날짜 파싱).

핵심 수정: 엑셀 2행의 연도 라벨('2025'/'2026')을 그대로 신뢰해서
          (연도 + 월/일)로 실제 날짜를 만든다. (이전엔 7/9부터 하루씩 더해서 틀렸음)

결과: 2025년 1/1~12/31 + 2026년 1/1~7/8 데이터가 모두 살아있음.
      -> 대시보드에서 2026 메인선 + 2025 전년비교선 둘 다 그릴 수 있음.

BPU 필터: Total, e-영업1~4 만 유지 (e-Corner, PROJECT-C, 47996, 미매칭, SPACE-R 제외).
"""
import datetime
import pandas as pd

SRC = "Data.xlsx"
OUT = "ep_data_long.csv"

METRIC_ORDER = [
    "평균 EP 전시 상품수", "평균 원부매칭 상품수", "원부매칭율(%)",
    "평균 최저가 상품수", "최저가율(%)", "평균 EP 거래액(순결제)",
    "평균 EP 거래액(총결제)", "평균 EP 고객수(총결제)",
    "평균 EP 첫구매 거래액(총결제)", "평균 EP 첫구매 고객수(총결제)",
    "첫구매거래액(%)", "평균 EP UV", "평균 EP 비회원UV",
    "EP 전시 상품당 유입수", "평균 EP 신규가입수", "신규가입율",
    "구매전환율(%)", "첫구매 전환율(%)",
]
PERCENT_COLS = [
    "원부매칭율(%)", "최저가율(%)", "첫구매거래액(%)",
    "신규가입율", "구매전환율(%)", "첫구매 전환율(%)",
]
KEEP_BPU = {"Total", "e-영업1", "e-영업2", "e-영업3", "e-영업4"}

df = pd.read_excel(SRC, sheet_name="Sheet 1", header=None)

metric_row = df.iloc[0].ffill(axis=0)
year_row = df.iloc[1].ffill(axis=0)
monthday_row = df.iloc[2]
label_cols = df.iloc[4:, 0:3].ffill(axis=0)


def parse_date(year_val, md_val):
    """('2025', '7/9') -> date(2025,7,9). 파싱 실패 시 None."""
    try:
        y = int(str(year_val).strip())
        m, d = str(md_val).strip().split("/")
        return datetime.date(y, int(m), int(d))
    except (ValueError, AttributeError):
        return None


# 지표별 (컬럼, 날짜) 목록 구성 - 연도 라벨을 신뢰
metric_col_dates = {}
for metric in METRIC_ORDER:
    cols = [c for c in df.columns if c >= 3 and metric_row[c] == metric]
    col_dates = []
    for c in cols:
        dt = parse_date(year_row[c], monthday_row[c])
        if dt is not None:
            col_dates.append((c, dt))
    metric_col_dates[metric] = col_dates

rows = []
for r in range(4, len(df)):
    bpu = label_cols.loc[r, 0]
    match_status = label_cols.loc[r, 1]
    lowest_status = label_cols.loc[r, 2]
    if pd.isna(bpu) or pd.isna(match_status) or pd.isna(lowest_status):
        continue
    if bpu not in KEEP_BPU:
        continue

    # 날짜별로 행을 모음 (지표들을 합침)
    by_date = {}
    for metric in METRIC_ORDER:
        for c, dt in metric_col_dates[metric]:
            raw = df.iloc[r, c]
            if isinstance(raw, str):
                raw = raw.replace(",", "").replace("%", "")
            val = float(raw) if pd.notna(raw) and raw != "" else None
            if val is not None and metric in PERCENT_COLS:
                val = val * 100
            by_date.setdefault(dt, {})[metric] = val

    for dt, metrics in by_date.items():
        row = {"날짜": dt, "BPU": bpu, "원부매칭여부": match_status, "최저가여부": lowest_status}
        for metric in METRIC_ORDER:
            row[metric] = metrics.get(metric)
        rows.append(row)

out_df = pd.DataFrame(rows).sort_values(["BPU", "원부매칭여부", "최저가여부", "날짜"]).reset_index(drop=True)
out_df.to_csv(OUT, index=False, encoding="utf-8-sig")

print(f"저장 완료: {OUT}, shape={out_df.shape}")
print("조합 개수:", out_df[["BPU", "원부매칭여부", "최저가여부"]].drop_duplicates().shape[0])
print("BPU 목록:", sorted(out_df["BPU"].unique()))
print("날짜 범위:", out_df["날짜"].min(), "~", out_df["날짜"].max())
print("연도별 일수:")
tmp = out_df[(out_df.BPU == "Total") & (out_df.원부매칭여부 == "Total") & (out_df.최저가여부 == "Total")].copy()
tmp["연"] = pd.to_datetime(tmp["날짜"]).dt.year
print(tmp.groupby("연").size())
