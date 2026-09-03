"""ep_product.csv (사내 원본, 상품코드별 거래액 raw)를 대시보드가 쓰는
표준 컬럼(날짜/BPU/카테고리/브랜드/상품코드/상품명/거래액)으로 변환.

원본 특징: UTF-16(tab-separated), 컬럼명이 결제_일자(YYYYMMDD)/BPU/영업상품카테고리명/
SAP대표브랜드코드/상품코드/상품명/거래액/주문수량. BPU에 e-영업1~4 외에 PROJECT-C,
e-Corner 등 다른 사업부 데이터도 섞여 있어서 카테고리 데이터(ep_category.csv.gz)와
동일하게 e-영업1~4만 남긴다.

결과는 ep_product.csv.gz(gzip, utf-8-sig)로 저장 — data_loader.load_product_data()가
.gz를 우선으로 읽는다(상품 단위는 행이 많아서 압축 권장).
"""
import pandas as pd

SRC = "ep_product_raw.csv"
OUT = "ep_product.csv.gz"

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
out_df.to_csv(OUT, index=False, encoding="utf-8-sig", compression="gzip")

print(f"저장 완료: {OUT}, shape={out_df.shape}")
print("BPU 목록:", sorted(out_df["BPU"].unique()))
print("카테고리 목록:", sorted(out_df["카테고리"].unique()))
print("날짜 범위:", out_df["날짜"].min(), "~", out_df["날짜"].max())
print("거래액 합계:", f"{out_df['거래액'].sum():,.0f}")
