"""1_전체실적.xlsx (사내 "전체실적" 리포트: 전사 vs EP 일자별 트래픽/거래액)를
대시보드가 쓰는 ep_total_daily.csv(날짜/채널/트래픽/거래액)로 변환.

원본: 행 = (지표, 회원구분, 신규구분1, 신규구분2, 채널, 채널상세), 열 = 날짜(YYYY-MM-DD 문자열).
지표 라벨은 블록 첫 행에만 채워져 있어 ffill 필요. 우리가 쓰는 건 두 줄뿐:
  - 채널=전체/채널상세=전체  -> 채널 "전체" (전사 합계)
  - 채널=EP/채널상세=전체    -> 채널 "EP"
지표는 트래픽/거래액만 (트래픽당 거래액은 거래액/트래픽으로 대시보드에서 재계산).

원본에 없는 날짜는 기존 파일 행을 보존한다 (convert_coupon.py와 같은 결손 방어).
"""
import os

import pandas as pd

SRC = "1_전체실적.xlsx"
OUT = "ep_total_daily.csv"

raw = pd.read_excel(SRC, sheet_name=0)
raw = raw.rename(columns={raw.columns[0]: "지표"})
raw["지표"] = raw["지표"].ffill()

date_cols = [c for c in raw.columns[6:] if pd.notna(pd.to_datetime(str(c), errors="coerce"))]

parts = []
for metric in ["트래픽", "거래액"]:
    m = raw[raw["지표"] == metric]
    for channel, mask in [
        ("전체", (m["채널"] == "전체") & (m["채널상세"] == "전체")),
        ("EP", (m["채널"] == "EP") & (m["채널상세"] == "전체")),
    ]:
        row = m[mask]
        if len(row) != 1:
            raise SystemExit(f"{metric}/{channel} 행을 정확히 1개 찾지 못했어요 ({len(row)}개) — 원본 구조가 바뀌었는지 확인하세요.")
        s = row.iloc[0][date_cols]
        parts.append(pd.DataFrame({
            "날짜": pd.to_datetime([str(c) for c in date_cols]),
            "채널": channel, "지표": metric,
            "값": pd.to_numeric(s.values, errors="coerce"),
        }))

long = pd.concat(parts, ignore_index=True)
out_df = long.pivot_table(index=["날짜", "채널"], columns="지표", values="값", aggfunc="first").reset_index()
out_df.columns.name = None
out_df["트래픽"] = out_df["트래픽"].round().astype("int64")
out_df["거래액"] = out_df["거래액"].round().astype("int64")

if os.path.exists(OUT):
    existing = pd.read_csv(OUT, parse_dates=["날짜"])
    _missing = existing[~existing["날짜"].isin(set(out_df["날짜"]))]
    if not _missing.empty:
        print(f"경고: 새 원본에 없는 날짜 {_missing['날짜'].nunique()}일의 기존 행을 보존합니다.")
        out_df = pd.concat([out_df, _missing], ignore_index=True)

out_df = out_df.sort_values(["날짜", "채널"]).reset_index(drop=True)
out_df.to_csv(OUT, index=False, encoding="utf-8-sig")

print(f"저장 완료: {OUT}, shape={out_df.shape}")
print("날짜 범위:", out_df["날짜"].min(), "~", out_df["날짜"].max())
print(out_df.groupby("채널")[["트래픽", "거래액"]].sum())
