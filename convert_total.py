"""1_전체실적.xlsx (사내 "전체실적" 리포트: 전사 vs EP 일자별 트래픽/거래액)를
대시보드가 쓰는 ep_total_daily.csv(날짜/채널/트래픽/거래액)로 변환.

원본: 행 = (지표, 회원구분, 신규구분1, 신규구분2, 채널, 채널상세), 열 = 날짜(YYYY-MM-DD 문자열).
지표 라벨은 블록 첫 행에만 채워져 있어 ffill 필요. 쓰는 행:
  - 채널=전체/채널상세=전체  -> 채널 "전체" (전사 합계)
  - 채널=EP/채널상세=전체    -> 채널 "EP"
  - 채널=직접/광고/제휴/PUSH/미디어커머스/브랜드광고 (채널상세 = 채널과 같은 행) -> 같은 이름의 채널
    (원본에 없는 채널은 건너뛰고, 있으면 월별 실적 추이의 '전 채널' 보기에 나온다)
지표는 트래픽/거래액만 (트래픽당 거래액은 거래액/트래픽으로 대시보드에서 재계산).

원본에 없는 날짜는 기존 파일 행을 보존한다 (convert_coupon.py와 같은 결손 방어).
"""
import os

import pandas as pd
from raw_sanity import abort, guard

SRC = "1_전체실적.xlsx"
OUT = "ep_total_daily.csv"

try:
    raw = pd.read_excel(SRC, sheet_name=0)
except Exception as e:  # DRM(문서보안) 파일 등
    abort("전체실적(1_전체실적.xlsx)", [f"엑셀로 열 수 없어요 — 문서보안(DRM)이 걸린 파일일 수 있어요. ({type(e).__name__})"])
raw = raw.rename(columns={raw.columns[0]: "지표"})
raw["지표"] = raw["지표"].ffill()

date_cols = [c for c in raw.columns[6:] if pd.notna(pd.to_datetime(str(c), errors="coerce"))]
if not date_cols:
    abort("전체실적(1_전체실적.xlsx)", [
        "일자별 열(2026-01-01 ...)이 없어요 — '2026년 01월'처럼 월별 형식으로 내려받은 것 같아요.",
        f"읽힌 열 이름: {list(raw.columns[6:9])} ...",
    ])

# 전체/EP는 필수(없으면 중단), 나머지 채널은 원본에 있을 때만 담는다
REQUIRED = ["전체", "EP"]
OPTIONAL = ["직접", "광고", "제휴", "PUSH", "미디어커머스", "브랜드광고"]

parts = []
for metric in ["트래픽", "거래액"]:
    m = raw[raw["지표"] == metric]
    chan_masks = [
        ("전체", (m["채널"] == "전체") & (m["채널상세"] == "전체")),
        ("EP", (m["채널"] == "EP") & (m["채널상세"] == "전체")),
    ] + [(ch, (m["채널"] == ch) & (m["채널상세"] == ch)) for ch in OPTIONAL]
    for channel, mask in chan_masks:
        row = m[mask]
        if len(row) == 0 and channel not in REQUIRED:
            continue
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
# 빈칸 = 그 채널 거래 없음(0)
out_df["트래픽"] = out_df["트래픽"].fillna(0).round().astype("int64")
out_df["거래액"] = out_df["거래액"].fillna(0).round().astype("int64")

guard("전체실적(1_전체실적.xlsx)", OUT, out_df, dims=["채널"], check_last_date=False)

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
