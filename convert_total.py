"""1_전체실적.xlsx (사내 "전체실적" 리포트: 전사 vs EP 일자별 트래픽/거래액)를
대시보드가 쓰는 ep_total_daily.csv(날짜/채널/트래픽/거래액)로 변환.

원본: 행 = (지표, 회원구분, 신규구분1, 신규구분2, 채널, 채널상세), 열 = 날짜(YYYY-MM-DD 문자열).
지표 라벨은 블록 첫 행에만 채워져 있어 ffill 필요. 쓰는 행:
  - 채널=전체/채널상세=전체  -> 채널 "전체" (전사 합계)
  - 채널=EP/채널상세=전체    -> 채널 "EP"
  - 채널=직접/광고/제휴/PUSH/미디어커머스/브랜드광고 (채널상세 = 채널과 같은 행) -> 같은 이름의 채널
    (원본에 없는 채널은 건너뛰고, 있으면 월별 실적 추이의 '전 채널' 보기에 나온다)
지표는 트래픽/거래액만 (트래픽당 거래액은 거래액/트래픽으로 대시보드에서 재계산).

회원구분/신규구분1 블록(전체·기존·신규·비회원 / 회원)이 있는 원본이면, 전체 블록은 지금처럼
ep_total_daily.csv에, 나머지 세그먼트(신규/기존/비회원/회원)는 ep_total_daily_seg.csv에 회원구분 열과 함께 저장한다
(전체 파일 형식을 그대로 둬서 홈·데이터품질 등 기존 화면에 영향이 없게 하려고 따로 둔다).
세그먼트 블록이 없는 원본(예: 예전 형식의 작년 파일)은 전체만 읽는다.

작년 일자는 1_전체실적_2025.xlsx(같은 형식)가 있으면 같이 읽는다. 두 파일에 같은 날짜가 있으면 1_전체실적.xlsx 값을 쓴다.
원본에 없는 날짜는 기존 파일 행을 보존한다 (convert_coupon.py와 같은 결손 방어).
"""
import os

import pandas as pd
from raw_sanity import abort, guard

SRC = "1_전체실적.xlsx"
SRC_PREV = "1_전체실적_2025.xlsx"  # 있으면 같이 읽는다 (작년 일자 — 올해 파일에는 작년 채널별 트래픽이 없어서)
OUT = "ep_total_daily.csv"
OUT_SEG = "ep_total_daily_seg.csv"

# (회원구분, 신규구분1) 블록 -> 저장할 세그먼트 이름. 회원/기존·회원/신규·비회원/비회원은
# 위 블록과 값이 같은 중복이라 담지 않는다.
SEGMENTS = {("전체", "전체"): "전체", ("전체", "신규"): "신규", ("전체", "기존"): "기존",
            ("전체", "비회원"): "비회원", ("회원", "전체"): "회원"}

# 전체/EP는 필수(없으면 중단), 나머지 채널은 원본에 있을 때만 담는다
REQUIRED = ["전체", "EP"]
OPTIONAL = ["직접", "광고", "제휴", "PUSH", "미디어커머스", "브랜드광고"]


def read_src(path):
    """원본 하나를 (날짜, 채널, 지표, 값) 세로 표로 바꾼다."""
    name = f"전체실적({path})"
    try:
        raw = pd.read_excel(path, sheet_name=0)
    except Exception as e:  # DRM(문서보안) 파일 등
        abort(name, [f"엑셀로 열 수 없어요 — 문서보안(DRM)이 걸린 파일일 수 있어요. ({type(e).__name__})"])
    raw = raw.rename(columns={raw.columns[0]: "지표"})
    raw["지표"] = raw["지표"].ffill()
    # 세그먼트 블록: 블록 첫 행에만 회원구분/신규구분1이 적혀 있어서 위에서 아래로 채운다
    # (지표가 바뀌면 그 지표의 첫 행에 다시 '전체/전체'가 적혀 있으니 지표 경계도 안전)
    for _c in ["회원구분", "신규구분1"]:
        if _c in raw.columns:
            raw[_c] = raw[_c].ffill()
    if "회원구분" in raw.columns and "신규구분1" in raw.columns:
        raw["_세그먼트"] = [SEGMENTS.get((a, b)) for a, b in zip(raw["회원구분"], raw["신규구분1"])]
    else:
        raw["_세그먼트"] = "전체"

    date_cols = [c for c in raw.columns[6:] if pd.notna(pd.to_datetime(str(c), errors="coerce"))]
    if not date_cols:
        abort(name, [
            "일자별 열(2026-01-01 ...)이 없어요 — '2026년 01월'처럼 월별 형식으로 내려받은 것 같아요.",
            f"읽힌 열 이름: {list(raw.columns[6:9])} ...",
        ])

    out = []
    for (seg, metric) in [(sg, mt) for sg in dict.fromkeys(SEGMENTS.values()) for mt in ["트래픽", "거래액"]]:
        m = raw[(raw["지표"] == metric) & (raw["_세그먼트"] == seg)]
        if m.empty and seg != "전체":
            continue  # 이 원본엔 이 세그먼트 블록이 없음 (예: 예전 형식 작년 파일)
        chan_masks = [
            ("전체", (m["채널"] == "전체") & (m["채널상세"] == "전체")),
            ("EP", (m["채널"] == "EP") & (m["채널상세"] == "전체")),
        ] + [(ch, (m["채널"] == ch) & (m["채널상세"] == ch)) for ch in OPTIONAL]
        for channel, mask in chan_masks:
            row = m[mask]
            if len(row) == 0 and channel not in REQUIRED:
                continue
            if len(row) != 1:
                raise SystemExit(f"{path}: {seg}/{metric}/{channel} 행을 정확히 1개 찾지 못했어요 ({len(row)}개) — 원본 구조가 바뀌었는지 확인하세요.")
            s = row.iloc[0][date_cols]
            out.append(pd.DataFrame({
                "날짜": pd.to_datetime([str(c) for c in date_cols]),
                "회원구분": seg, "채널": channel, "지표": metric,
                "값": pd.to_numeric(s.values, errors="coerce"),
            }))
    return out


# 올해 파일을 먼저 두어서 같은 날짜가 겹치면 올해 파일 값이 남는다 (pivot_table aggfunc="first")
parts = read_src(SRC)
if os.path.exists(SRC_PREV):
    parts += read_src(SRC_PREV)

long = pd.concat(parts, ignore_index=True)
all_df = long.pivot_table(index=["날짜", "회원구분", "채널"], columns="지표", values="값", aggfunc="first").reset_index()
all_df.columns.name = None
# 빈칸 = 그 채널 거래 없음(0)
all_df["트래픽"] = all_df["트래픽"].fillna(0).round().astype("int64")
all_df["거래액"] = all_df["거래액"].fillna(0).round().astype("int64")
out_df = all_df[all_df["회원구분"] == "전체"].drop(columns="회원구분").reset_index(drop=True)
seg_df = all_df[all_df["회원구분"] != "전체"].reset_index(drop=True)

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

# 세그먼트(신규/기존/비회원/회원) — 원본에 블록이 있을 때만. 새 원본에 없는 날짜는 기존 행 보존(위와 같은 방어)
if not seg_df.empty:
    if os.path.exists(OUT_SEG):
        _ex = pd.read_csv(OUT_SEG, parse_dates=["날짜"])
        _miss = _ex[~_ex["날짜"].isin(set(seg_df["날짜"]))]
        if not _miss.empty:
            print(f"경고: 세그먼트 — 새 원본에 없는 날짜 {_miss['날짜'].nunique()}일의 기존 행을 보존합니다.")
            seg_df = pd.concat([seg_df, _miss], ignore_index=True)
    seg_df = seg_df.sort_values(["날짜", "회원구분", "채널"]).reset_index(drop=True)
    seg_df.to_csv(OUT_SEG, index=False, encoding="utf-8-sig")
    print()
    print(f"저장 완료: {OUT_SEG}, shape={seg_df.shape}")
    print("세그먼트 날짜 범위:", seg_df["날짜"].min(), "~", seg_df["날짜"].max())
    print(seg_df[seg_df["채널"] == "EP"].groupby("회원구분")[["트래픽", "거래액"]].sum())
else:
    print()
    print("참고: 원본에 회원구분(신규 등) 블록이 없어서 세그먼트 파일은 만들지 않았어요.")
