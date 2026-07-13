"""Data.xlsx (사내 다운로드 피벗 리포트)를 앱이 쓰는 long-format DataFrame으로 변환.

data_loader.py에서 이 함수를 호출한다.
사용자가 사이드바에 xlsx를 업로드하면 즉시 이 로직으로 변환되어 대시보드에 반영된다.

핵심: 엑셀 2행의 연도 라벨('2025'/'2026')을 그대로 신뢰해서 (연도+월/일)로 날짜를 만든다.
BPU는 Total, e-영업1~4 만 유지.
"""
import datetime
import pandas as pd

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
# 데이터 경량화: 아래 조합만 유지 (매출 데이터가 커서 메모리 절약)
KEEP_MATCH = {"Total", "매칭"}       # 비매칭 제외
KEEP_LOWEST = {"Total", "최저가"}    # 비최저가 제외


def _parse_date(year_val, md_val):
    try:
        y = int(str(year_val).strip())
        m, d = str(md_val).strip().split("/")
        return datetime.date(y, int(m), int(d))
    except (ValueError, AttributeError):
        return None


def convert_excel_to_long(file_or_path) -> pd.DataFrame:
    """사내 Data.xlsx(피벗 형태)를 long-format DataFrame으로 변환한다.

    file_or_path: 파일 경로(str) 또는 Streamlit UploadedFile 객체 둘 다 허용.
    반환: 날짜 / BPU / 원부매칭여부 / 최저가여부 / <18개 지표> 컬럼의 DataFrame
    """
    df = pd.read_excel(file_or_path, sheet_name=0, header=None)

    metric_row = df.iloc[0].ffill(axis=0)
    year_row = df.iloc[1].ffill(axis=0)
    monthday_row = df.iloc[2]
    label_cols = df.iloc[4:, 0:3].ffill(axis=0)

    metric_col_dates = {}
    for metric in METRIC_ORDER:
        cols = [c for c in df.columns if c >= 3 and metric_row[c] == metric]
        col_dates = []
        for c in cols:
            dt = _parse_date(year_row[c], monthday_row[c])
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
        if match_status not in KEEP_MATCH:
            continue
        if lowest_status not in KEEP_LOWEST:
            continue

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

    out_df = pd.DataFrame(rows)
    out_df["날짜"] = pd.to_datetime(out_df["날짜"])
    return out_df.sort_values(["BPU", "원부매칭여부", "최저가여부", "날짜"]).reset_index(drop=True)
