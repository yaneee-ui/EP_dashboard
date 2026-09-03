"""ep_product.csv (사내 원본, 상품코드별 거래액 raw)를 대시보드가 쓰는
표준 컬럼(날짜/BPU/카테고리/브랜드/상품코드/상품명/거래액)으로 변환.

원본 특징: UTF-16(tab-separated), 컬럼명이 결제_일자(YYYYMMDD)/BPU/영업상품카테고리명/
SAP대표브랜드코드/상품코드/상품명/거래액/주문수량. BPU에 e-영업1~4 외에 PROJECT-C,
e-Corner 등 다른 사업부 데이터도 섞여 있어서 카테고리 데이터(ep_category.csv.gz)와
동일하게 e-영업1~4만 남긴다.

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

SRC = "ep_product_raw.csv"
OUT_CURRENT = "ep_product.csv.gz"
OUT_ARCHIVE = "ep_product_archive.csv.gz"

# 이 날짜까지는 마감(더 이상 변동 없음) — 26년 8월까지 마감, 9월부터 현재분으로 관리.
ARCHIVE_CUTOFF = "2026-08-31"

KEEP_BPU = {"e-영업1", "e-영업2", "e-영업3", "e-영업4"}

df = pd.read_csv(SRC, sep="\t", encoding="utf-16")

df = df.rename(columns={
    "결제_일자(YYYYMMDD)": "날짜",
    "영업상품카테고리명": "카테고리",
    "SAP대표브랜드코드": "브랜드",
})

df = df[df["BPU"].isin(KEEP_BPU)].copy()

df["날짜"] = pd.to_datetime(df["날짜"], format="%Y%m%d")
df["거래액"] = (
    df["거래액"].astype(str).str.replace(",", "", regex=False).astype("int64")
)

out_df = df[["날짜", "BPU", "카테고리", "브랜드", "상품코드", "상품명", "거래액"]]
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
