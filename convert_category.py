"""ep_category.csv.gz (사내 "EP상세실적" 원본, 카테고리/브랜드별 일자 raw)를
대시보드가 쓰는 표준 컬럼(날짜/BPU/카테고리/브랜드/회원구분/CR/객단가/거래액/
구매객수/트래픽)으로 변환.

원본 특징: xlsx, 피벗 형태. 컬럼0=BPU(e-영업1~4, 빈칸이면 ffill), 컬럼1=지표
(트래픽/거래액/구매객수/CR/객단가, 빈칸이면 ffill), 컬럼2~4=회원구분/신규구분1/
신규구분2(빈칸이면 ffill), 컬럼5=카테고리(빈칸이면 ffill), 컬럼6=브랜드(항상
명시값), 컬럼7부터 날짜별 값.

회원구분/신규구분1 라벨 계층은 [[convert_traffic.py]]와 동일한 9블록 구조가
BPU x 지표 조합마다 반복되고, 그 각 블록 안에 카테고리->브랜드 피벗이 다시
중첩되어 있다. 5개만 대시보드가 쓰는 값이라 나머지(회원 밑 기존/신규 재귀,
비회원 최상위 재귀)는 버린다 (자세한 매핑은 convert_traffic.py 주석 참고).

원본이 2026년(현재분)만 담고 있어서 ep_category_2025.csv.gz(마감분, 고정)는
건드리지 않고 ep_category.csv.gz(현재분)만 통째로 새로 만든다.

2026-09-10부터 원본을 xlsx 대신 UTF-16(tab-separated) .csv로 받는 경우가 생겼다
(같은 피벗 레이아웃이지만 숫자가 전부 "2,540"처럼 천단위 콤마 붙은 문자열이고,
CR은 이미 "9.1%"처럼 %가 붙은 사람이 읽기 좋은 형태로 옴 - xlsx는 CR이 0~1
비율의 순수 숫자였음). 둘 다 지원하도록 확장했다: 1_EP상세실적.xlsx가 있으면
그걸 쓰고, 없으면 1_EP상세실적.csv를 이 새 형식으로 읽는다.
"""
import os
import pandas as pd

SRC_XLSX = "1_EP상세실적.xlsx"
SRC_CSV = "1_EP상세실적.csv"
OUT = "ep_category.csv.gz"

KEEP_MEMBER = {
    ("전체", "전체"): "전체",
    ("전체", "기존"): "기존",
    ("전체", "신규"): "신규",
    ("전체", "비회원"): "비회원",
    ("회원", "전체"): "회원",
}

if os.path.exists(SRC_XLSX):
    SRC = SRC_XLSX
    df = pd.read_excel(SRC, sheet_name=0, header=None)
    _cr_is_ratio = True  # xlsx: CR이 0~1 비율 순수 숫자 -> 나중에 *100
else:
    SRC = SRC_CSV
    df = pd.read_csv(SRC, encoding="utf-16", sep="\t", header=None)
    _cr_is_ratio = False  # csv: CR이 이미 "9.1%" 문자열

    def _clean_number(s):
        """콤마 붙은 숫자 문자열("2,540") -> float. CR은 별도로 % 기호까지 제거."""
        return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False).str.replace("%", "", regex=False), errors="coerce")

    # 판다스가 이 파일을 전부 고정 str dtype으로 읽어서, 날짜 값 칸에 .loc로 숫자를
    # 바로 대입하면 dtype 에러가 난다 - 라벨 칸(0~6열)은 그대로 두고 날짜 칸(7열~)만
    # 숫자로 변환한 새 프레임을 만들어 다시 합친다(0행=헤더/날짜 라벨 행은 그대로 유지).
    _date_cols_raw = df.columns[7:]
    _rest_clean = df.loc[1:, _date_cols_raw].apply(_clean_number)
    _rest = pd.concat([df.loc[1:, df.columns[:7]], _rest_clean], axis=1)
    df = pd.concat([df.loc[[0]], _rest], axis=0)

label_cols = df.iloc[1:, 0:7].copy()
label_cols.columns = ["BPU", "지표", "회원구분", "신규구분1", "신규구분2", "카테고리", "브랜드"]
label_cols[["BPU", "지표", "회원구분", "신규구분1", "카테고리"]] = label_cols[
    ["BPU", "지표", "회원구분", "신규구분1", "카테고리"]
].ffill()

header_row = df.iloc[0, 7:]
parsed_header = pd.to_datetime(header_row, errors="coerce")
date_cols = [c for c in parsed_header.index if pd.notna(parsed_header[c])]
dates = parsed_header[date_cols]

member = label_cols.apply(lambda r: KEEP_MEMBER.get((r["회원구분"], r["신규구분1"])), axis=1)
keep_mask = member.notna()

kept = label_cols[keep_mask].copy()
kept["회원구분_out"] = member[keep_mask]

values = df.loc[kept.index, date_cols]
values.columns = dates.values

long_df = kept[["BPU", "지표", "카테고리", "브랜드", "회원구분_out"]].join(values)
long_df = long_df.rename(columns={"회원구분_out": "회원구분"})
long_df = long_df.melt(
    id_vars=["BPU", "지표", "카테고리", "브랜드", "회원구분"], var_name="날짜", value_name="값"
)

wide = long_df.pivot_table(
    index=["날짜", "BPU", "카테고리", "브랜드", "회원구분"],
    columns="지표", values="값", aggfunc="first",
).reset_index()
wide.columns.name = None
if _cr_is_ratio:
    wide["CR"] = wide["CR"] * 100  # xlsx 원본은 0~1 비율, 대시보드는 %(0~100) 기준
# csv 원본은 위 _clean_number에서 이미 "9.1%" -> 9.1로 변환돼 있어서 그대로 씀

out_df = wide[["날짜", "BPU", "카테고리", "브랜드", "회원구분", "CR", "객단가", "거래액", "구매객수", "트래픽"]]
out_df = out_df.sort_values(["날짜", "BPU", "카테고리", "브랜드", "회원구분"]).reset_index(drop=True)
out_df.to_csv(OUT, index=False, encoding="utf-8-sig", compression="gzip")

print(f"저장 완료: {OUT}, shape={out_df.shape}")
print("BPU 목록:", sorted(out_df["BPU"].unique()))
print("회원구분 목록:", sorted(out_df["회원구분"].unique()))
print("카테고리 개수:", out_df["카테고리"].nunique())
print("날짜 범위:", out_df["날짜"].min(), "~", out_df["날짜"].max())
