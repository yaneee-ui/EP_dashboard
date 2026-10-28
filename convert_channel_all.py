"""전체채널별실적.csv (유입채널 x 카테고리 x 정상/이월/입점 구분별 일자별 거래액 raw)를
대시보드가 쓰는 ep_channel_all.csv.gz(날짜/구분/채널/카테고리/거래액)로 변환.

원본: UTF-16 탭 구분. 머리글 3줄 — 1행 'AF대분류명 / 영업상품카테고리명' 라벨, 2행 유입채널(광고/제휴/직접/
EP/PUSH), 3행 카테고리. 데이터 행은 결제_연도 / 정상이월구분명(정상·이월·입점) / 결제_일자(YYYYMMDD) /
채널×카테고리 거래액(빈칸 = 0). 구분 3개는 서로 겹치지 않아서 합치면 전체.
(명품실적(순금+실버/순금제외).csv 와 달리 26년 9월 기준 카테고리 정의 그대로의 raw라 여기 '명품'은
쥬얼리 포함 여부가 날짜에 따라 다를 수 있어요 — 명품만 정확히 보려면 13번 화면의 명품 raw를 쓰세요.)
"""
import pandas as pd
from raw_sanity import abort, guard

SRC = "전체채널별실적.csv"
OUT = "ep_channel_all.csv.gz"
KINDS = {"정상", "이월", "입점"}

try:
    raw = pd.read_csv(SRC, sep="\t", encoding="utf-16", header=None, dtype=str)
except Exception as e:
    abort("전체채널별실적", [f"'{SRC}'을 읽을 수 없어요 ({type(e).__name__}) — UTF-16 탭 구분 CSV가 맞는지 확인하세요."])

problems = []
if raw.shape[0] < 10 or raw.shape[1] < 10 or raw.iloc[2, 1] != "정상이월구분명" or raw.iloc[2, 2] != "결제_일자(YYYYMMDD)":
    abort("전체채널별실적", [
        "머리글이 예상과 달라요 (3번째 줄이 '결제_연도 / 정상이월구분명 / 결제_일자 / 카테고리...'여야 해요).",
        f"읽힌 3번째 줄 앞부분: {raw.iloc[2, :4].tolist() if raw.shape[0] > 2 else '-'}",
    ])

channels = raw.iloc[1, 3:].ffill().tolist()
cats = raw.iloc[2, 3:].tolist()
body = raw.iloc[3:].copy()
body = body[body[2].str.fullmatch(r"\d{8}", na=False)]
unknown = set(body[1].dropna()) - KINDS
if unknown:
    problems.append(f"정상/이월/입점이 아닌 구분이 있어요: {sorted(unknown)}")
if body.empty:
    abort("전체채널별실적", ["일자 행이 없어요."])
body["날짜"] = pd.to_datetime(body[2], format="%Y%m%d")
dup = body.duplicated(["날짜", 1]).sum()
if dup:
    problems.append(f"같은 날짜·구분이 {dup}행 중복돼 있어요.")
per_kind = body.groupby(1)["날짜"].nunique()
if per_kind.nunique() > 1:
    problems.append(f"구분별 일수가 달라요: {per_kind.to_dict()} — 일부 구분이 빠졌을 수 있어요.")
if problems:
    abort("전체채널별실적", problems)

vals = body.iloc[:, 3:3 + len(channels)].apply(lambda s: pd.to_numeric(s.str.replace(",", "", regex=False), errors="coerce"))
vals.columns = pd.MultiIndex.from_arrays([channels, cats], names=["채널", "카테고리"])
vals.index = pd.MultiIndex.from_arrays([body["날짜"], body[1]], names=["날짜", "구분"])
long = vals.stack(["채널", "카테고리"], future_stack=True).dropna().rename("거래액").reset_index()
long = long[long["거래액"] != 0]
long["거래액"] = long["거래액"].round().astype("int64")
out_df = long.sort_values(["날짜", "구분", "채널", "카테고리"]).reset_index(drop=True)

guard("전체채널별실적", OUT, out_df, dims=["구분", "채널", "카테고리"])
out_df.to_csv(OUT, index=False, encoding="utf-8-sig", compression="gzip")

print(f"저장 완료: {OUT}, shape={out_df.shape}")
print("날짜 범위:", out_df["날짜"].min(), "~", out_df["날짜"].max())
print("거래액 합계(채널별):", {c: f"{v:,.0f}" for c, v in out_df.groupby("채널")["거래액"].sum().items()})
print("거래액 합계(구분별):", {c: f"{v:,.0f}" for c, v in out_df.groupby("구분")["거래액"].sum().items()})
