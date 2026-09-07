"""ep_coupon_daily.csv (사내 "EP쿠폰_거래액_플러스/일반_일자별" 원본)를 대시보드가
쓰는 표준 컬럼(날짜/BPU/쿠폰ID/쿠폰명/쿠폰유형/쿠폰할인)으로 변환.

원본 특징: UTF-16(tab-separated), 위 3줄이 메타 헤더(피벗 월별 컬럼 라벨)라서
건너뛰고, 실제 컬럼명은 4번째 줄. "총계" 컬럼이 두 번 나온다(거래액 총계,
쿠폰할인 총계) - pandas가 자동으로 .1 접미사를 붙이므로 위치 기반으로 읽는다.
합계/소계 행(결제_일자가 "총계"인 행)은 버리고, 실제 (쿠폰ID, 날짜) 단위 상세
행만 남긴다 (결제_일자가 8자리 숫자인 행).

플러스/일반 두 파일을 합쳐서 저장. 원본이 2025년부터 전체 이력을 담고 있어서
[[ep_product_raw_pipeline]]과 달리 마감분/현재분 분리 없이 파일 하나로 계속
통째로 갱신한다 (아직 용량이 크지 않아서).
"""
import pandas as pd

OUT = "ep_coupon_daily.csv"
KEEP_BPU = {"e-영업1", "e-영업2", "e-영업3", "e-영업4"}

SOURCES = [
    ("☆EP쿠폰_거래액_플러스_일자별.csv", "플러스", {
        "bpu": 2, "coupon_id": 3, "coupon_name": 4, "date": 5, "discount_total": 7,
    }),
    ("☆EP쿠폰_거래액_일반_일자별.csv", "일반", {
        "bpu": 1, "coupon_id": 2, "coupon_name": 3, "date": 4, "discount_total": 6,
    }),
]


def _to_number(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False), errors="coerce")


parts = []
for src, coupon_type, pos in SOURCES:
    raw = pd.read_csv(src, encoding="utf-16", sep="\t", header=None, skiprows=3)
    date_str = raw.iloc[:, pos["date"]].astype(str).str.strip()
    is_detail = date_str.str.fullmatch(r"\d{8}")
    raw = raw[is_detail].copy()

    out = pd.DataFrame({
        "날짜": pd.to_datetime(date_str[is_detail], format="%Y%m%d"),
        "BPU": raw.iloc[:, pos["bpu"]],
        "쿠폰ID": raw.iloc[:, pos["coupon_id"]],
        "쿠폰명": raw.iloc[:, pos["coupon_name"]],
        "쿠폰유형": coupon_type,
        "쿠폰할인": _to_number(raw.iloc[:, pos["discount_total"]]),
    })
    out = out[out["BPU"].isin(KEEP_BPU)]
    parts.append(out)

out_df = pd.concat(parts, ignore_index=True)
out_df = out_df.sort_values(["날짜", "쿠폰유형", "BPU", "쿠폰ID"]).reset_index(drop=True)
out_df.to_csv(OUT, index=False, encoding="utf-8-sig")

print(f"저장 완료: {OUT}, shape={out_df.shape}")
print("BPU 목록:", sorted(out_df["BPU"].unique()))
print("쿠폰유형 목록:", sorted(out_df["쿠폰유형"].unique()))
print("날짜 범위:", out_df["날짜"].min(), "~", out_df["날짜"].max())
print("쿠폰할인 합계:", f"{out_df['쿠폰할인'].sum():,.0f}")
