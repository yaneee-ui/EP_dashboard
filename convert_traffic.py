"""ep_traffic.csv (사내 "EP실적" 원본, 일자별 트래픽/거래액 raw)를 대시보드가
쓰는 표준 컬럼(날짜/BPU/회원구분/CR/객단가/거래액/구매객수/트래픽)으로 변환.

원본 특징: xlsx, 피벗 형태. 컬럼0=지표(트래픽/거래액/구매객수/CR/객단가, 위에서부터
빈칸이면 이전 값과 동일 - ffill), 컬럼1~5=회원구분/신규구분1/신규구분2/구분/BPU
(마찬가지로 빈칸은 ffill), 컬럼6부터 날짜별 값.

라벨 계층 구조 (지표마다 반복):
  회원구분=전체, 신규구분1=전체           -> 대시보드 회원구분="전체"
    구분=전체, BPU=전체                  -> 대시보드 BPU="Total"
    구분=기본, BPU=전체                  -> (버림, 사업부 소계라 필요없음)
    구분=기본(ffill), BPU=e-영업1~4       -> 대시보드 BPU=e-영업1~4
    구분=기타부서/비상품랜딩              -> (버림, 대시보드가 안 쓰는 구분)
  신규구분1=기존/신규/비회원 (회원구분=전체 유지)  -> 대시보드 회원구분="기존"/"신규"/"비회원"
  회원구분=회원, 신규구분1=전체            -> 대시보드 회원구분="회원"
  (회원 밑의 기존/신규 재귀, 비회원 최상위 재귀는 값이 위와 중복이라 버림)

원본이 2026년(현재분)만 담고 있어서 ep_traffic_2025.csv(마감분, 고정)는 건드리지
않고 ep_traffic.csv(현재분)만 통째로 새로 만든다.
"""
import pandas as pd

SRC = "1_EP실적.xlsx"
OUT = "ep_traffic.csv"

KEEP_BPU = {"e-영업1", "e-영업2", "e-영업3", "e-영업4"}

# (회원구분_ffill, 신규구분1_ffill) -> 대시보드 회원구분. 나머지 조합(회원 밑
# 기존/신규 재귀, 비회원 최상위 재귀 등)은 위 5개 값과 중복이라 버린다.
KEEP_MEMBER = {
    ("전체", "전체"): "전체",
    ("전체", "기존"): "기존",
    ("전체", "신규"): "신규",
    ("전체", "비회원"): "비회원",
    ("회원", "전체"): "회원",
}

df = pd.read_excel(SRC, sheet_name=0, header=None)

label_cols = df.iloc[1:, 0:6].copy()
label_cols.columns = ["지표", "회원구분", "신규구분1", "신규구분2", "구분", "BPU"]
label_cols[["지표", "회원구분", "신규구분1", "구분"]] = label_cols[
    ["지표", "회원구분", "신규구분1", "구분"]
].ffill()

header_row = df.iloc[0, 6:]
parsed_header = pd.to_datetime(header_row, errors="coerce")
date_cols = [c for c in parsed_header.index if pd.notna(parsed_header[c])]
dates = parsed_header[date_cols]

member = label_cols.apply(lambda r: KEEP_MEMBER.get((r["회원구분"], r["신규구분1"])), axis=1)

is_total_row = (label_cols["구분"] == "전체") & (label_cols["BPU"] == "전체")
is_bpu_row = (label_cols["구분"] == "기본") & (label_cols["BPU"].isin(KEEP_BPU))
target_bpu = pd.Series(pd.NA, index=label_cols.index, dtype="object")
target_bpu[is_total_row] = "Total"
target_bpu[is_bpu_row] = label_cols.loc[is_bpu_row, "BPU"]

keep_mask = member.notna() & target_bpu.notna()
kept = label_cols[keep_mask].copy()
kept["회원구분_out"] = member[keep_mask]
kept["BPU_out"] = target_bpu[keep_mask]
kept["지표"] = label_cols.loc[keep_mask, "지표"]

values = df.loc[kept.index, date_cols]
values.columns = dates.values

long_df = kept[["지표", "회원구분_out", "BPU_out"]].join(values)
long_df = long_df.melt(
    id_vars=["지표", "회원구분_out", "BPU_out"], var_name="날짜", value_name="값"
)
long_df = long_df.rename(columns={"회원구분_out": "회원구분", "BPU_out": "BPU"})

wide = long_df.pivot_table(
    index=["날짜", "BPU", "회원구분"], columns="지표", values="값", aggfunc="first"
).reset_index()
wide.columns.name = None

wide["CR"] = wide["CR"] * 100  # 원본은 0~1 비율, 대시보드는 %(0~100) 기준

out_df = wide[["날짜", "BPU", "회원구분", "CR", "객단가", "거래액", "구매객수", "트래픽"]]
out_df = out_df.sort_values(["날짜", "BPU", "회원구분"]).reset_index(drop=True)
out_df.to_csv(OUT, index=False, encoding="utf-8-sig")

print(f"저장 완료: {OUT}, shape={out_df.shape}")
print("BPU 목록:", sorted(out_df["BPU"].unique()))
print("회원구분 목록:", sorted(out_df["회원구분"].unique()))
print("날짜 범위:", out_df["날짜"].min(), "~", out_df["날짜"].max())
