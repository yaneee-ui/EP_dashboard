"""ep_product.csv (사내 원본, 상품코드별 거래액 raw)를 대시보드가 쓰는
표준 컬럼(날짜/BPU/카테고리/브랜드/상품코드/상품명/거래액/구매건수)으로 변환.

원본은 두 형식을 다 지원한다 (ep_product_raw.xlsx가 있으면 그걸 우선 쓰고, 없으면
ep_product_raw.csv를 예전 형식으로 읽는다):
  - .csv (예전 형식): UTF-16(tab-separated), 모든 행에 결제_일자/BPU/카테고리/브랜드
    값이 그대로 반복돼 있음.
  - .xlsx (2026-09-11부터 이 형식으로도 옴): 같은 컬럼이지만 엑셀 병합 셀처럼
    결제_일자/BPU/영업상품카테고리명/SAP대표브랜드코드가 그 블록 첫 행에만 채워져
    있고 나머지 행은 빈칸(NaN) - convert_traffic.py/convert_category.py의 병합 셀
    ffill과 동일한 처리가 필요하다. 거래액도 정수 문자열이 아니라 소수가 섞인 순수
    숫자로 온다(반올림해서 저장).

컬럼명: 결제_일자(YYYYMMDD)/BPU/영업상품카테고리명/SAP대표브랜드코드/상품코드/
상품명/거래액/주문수량. BPU에 e-영업1~4 외에 PROJECT-C, e-Corner 등 다른 사업부
데이터도 섞여 있어서 카테고리 데이터(ep_category.csv.gz)와 동일하게 e-영업1~4만
남긴다.

카테고리 데이터와 동일하게 마감분/현재분 두 파일로 나눠서 저장한다 (data_loader.
load_product_data()가 두 파일을 합쳐서 읽음):
  - ep_product_archive.csv.gz : ARCHIVE_CUTOFF까지 마감된 데이터. 더 이상 바뀌지
    않으므로 이미 파일이 있으면 다시 만들지 않는다(매번 8MB+ 파일을 다시 올릴 필요
    없게). 마감 기준일을 늦추고 싶으면(예: 다음 마감 때) 파일을 지우고 재실행.
  - ep_product.csv.gz : ARCHIVE_CUTOFF 다음날부터의 데이터. 계속 갱신되므로 매번
    새로 만든다.
"""
import os

import pandas as pd

SRC_XLSX = "ep_product_raw.xlsx"
SRC_CSV = "ep_product_raw.csv"
OUT_CURRENT = "ep_product.csv.gz"
OUT_ARCHIVE = "ep_product_archive.csv.gz"

# 이 날짜까지는 마감(더 이상 변동 없음) — 26년 8월까지 마감, 9월부터 현재분으로 관리.
ARCHIVE_CUTOFF = "2026-08-31"

KEEP_BPU = {"e-영업1", "e-영업2", "e-영업3", "e-영업4"}

_FFILL_COLS = ["결제_일자(YYYYMMDD)", "BPU", "영업상품카테고리명", "SAP대표브랜드코드"]

if os.path.exists(SRC_XLSX):
    SRC = SRC_XLSX
    df = pd.read_excel(SRC, sheet_name=0)
    df[_FFILL_COLS] = df[_FFILL_COLS].ffill()
else:
    SRC = SRC_CSV
    df = pd.read_csv(SRC, sep="\t", encoding="utf-16")

df = df.rename(columns={
    "결제_일자(YYYYMMDD)": "날짜",
    "영업상품카테고리명": "카테고리",
    "SAP대표브랜드코드": "브랜드",
    "주문수량": "구매건수",
})

df = df[df["BPU"].isin(KEEP_BPU)].copy()

df["날짜"] = pd.to_datetime(df["날짜"].astype("int64").astype(str), format="%Y%m%d")
# xlsx는 이미 숫자(소수 섞임), csv는 콤마 붙은 문자열 - 둘 다 안전하게 통과하도록
# 문자열화 후 콤마 제거 -> 숫자 변환 -> 반올림(예전엔 정수 문자열이라 astype(int64)로
# 충분했는데, xlsx 쪽은 진짜 소수라 그냥 자르면 계속 절삭 방향으로 오차가 쌓인다).
df["거래액"] = pd.to_numeric(
    df["거래액"].astype(str).str.replace(",", "", regex=False), errors="coerce"
).round().astype("int64")
df["구매건수"] = pd.to_numeric(
    df["구매건수"].astype(str).str.replace(",", "", regex=False), errors="coerce"
).round().astype("int64")

out_df = df[["날짜", "BPU", "카테고리", "브랜드", "상품코드", "상품명", "거래액", "구매건수"]]
out_df = out_df.sort_values("날짜").reset_index(drop=True)

cutoff = pd.Timestamp(ARCHIVE_CUTOFF)
archive_df = out_df[out_df["날짜"] <= cutoff]
current_df = out_df[out_df["날짜"] > cutoff]

if os.path.exists(OUT_ARCHIVE):
    print(f"'{OUT_ARCHIVE}' 이미 있어서 다시 만들지 않았어요 (마감 데이터는 안 바뀌니까). "
          "마감 기준일을 바꾸려면 이 파일을 지우고 다시 실행하세요.")
else:
    archive_df.to_csv(OUT_ARCHIVE, index=False, encoding="utf-8-sig", compression="gzip")
    print(f"마감분 저장: {OUT_ARCHIVE}, shape={archive_df.shape}, ~{ARCHIVE_CUTOFF}까지")

current_df.to_csv(OUT_CURRENT, index=False, encoding="utf-8-sig", compression="gzip")
print(f"현재분 저장: {OUT_CURRENT}, shape={current_df.shape}")

print("BPU 목록:", sorted(out_df["BPU"].unique()))
print("카테고리 목록:", sorted(out_df["카테고리"].unique()))
print("날짜 범위:", out_df["날짜"].min(), "~", out_df["날짜"].max())
print("거래액 합계:", f"{out_df['거래액'].sum():,.0f}")
