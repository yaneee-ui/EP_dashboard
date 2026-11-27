"""★일자별실적_A_M_P_전채널.xlsx -> ep_ad_app_daily.csv 변환.

2026-11-19부터 EP APP 실적 일부가 쇼핑검색광고(광고) APP로 나뉘어 집계되고 있어서,
대시보드에서 'EP + 쇼핑검색광고 APP 거래액' 합산 보기(사이드바 버튼)를 만들 때 쓰는 원본.

원본 특징: 피벗 형태, 머리글 4줄
  1행: 'AF대분류명 / 앱PC모바일구분'
  2행: 채널(광고 / EP / 총합계)
  3행: 지표(거래액 / 주문고객수)
  4행: 결제_연도 / 결제_연월 / 결제_일자 + 디바이스(A=앱, M=모바일웹, P=PC, 총계)
  데이터: 결제_일자(YYYYMMDD) 한 줄씩, 마지막 줄은 '총계'
컬럼 위치(0부터): 광고 거래액 A/M/P/총계 = 3~6, 광고 주문고객수 = 7~10,
                 EP 거래액 = 11~14, EP 주문고객수 = 15~18

출력 컬럼: 날짜, 채널(광고/EP), 디바이스(A/M/P/총계), 거래액, 주문고객수
원본 위치: 이 폴더에 같은 이름 파일이 있으면 그걸, 없으면 바탕화면 EP+AD_dashboard 폴더.

아래쪽(2)에서 카테고리 x BPU x 신규여부 원본(★일자별실적_A_M_P_전채널_카테고리 추가.xlsx)도
있으면 같이 변환한다 -> ep_ad_app_cat.csv
"""
import os
import sys

import pandas as pd

from raw_sanity import abort, guard

NAMES = ["★일자별실적_A_M_P_전채널.xlsx", "일자별실적_A_M_P_전채널.xlsx"]
DIRS = [".", os.path.join(os.path.expanduser("~"), "Desktop", "EP+AD_dashboard")]
OUT = "ep_ad_app_daily.csv"

args = [a for a in sys.argv[1:] if not a.startswith("--")]
if args:
    SRC = args[0]
else:
    SRC = next((os.path.join(d, n) for n in NAMES for d in DIRS if os.path.exists(os.path.join(d, n))), None)
if not SRC or not os.path.exists(SRC):
    abort("쇼검APP(A/M/P)", [f"원본을 못 찾았어요: {NAMES[0]} (이 폴더 또는 바탕화면 EP+AD_dashboard)"])

with open(SRC, "rb") as f:
    if f.read(2) != b"PK":
        abort("쇼검APP(A/M/P)", ["정상 xlsx가 아니에요(DRM 잠금 가능성). DRM 해제 후 다시 실행해주세요."])

raw = pd.read_excel(SRC, header=None)
hdr_ch, hdr_metric, hdr_dev = raw.iloc[1], raw.iloc[2], raw.iloc[3]
# 머리글 위치가 예상과 같은지 확인 (원본 양식이 바뀌면 조용히 틀린 값을 만들지 않도록)
expect = {3: ("광고", "거래액", "A"), 7: (None, "주문고객수", "A"), 11: ("EP", "거래액", "A"), 15: (None, "주문고객수", "A")}
for c, (ch, met, dev) in expect.items():
    if (ch and hdr_ch[c] != ch) or hdr_metric[c] != met or hdr_dev[c] != dev:
        abort("쇼검APP(A/M/P)", [f"머리글 위치가 예상과 달라요(열 {c}: {hdr_ch[c]}/{hdr_metric[c]}/{hdr_dev[c]}). 원본 양식을 확인해주세요."])

body = raw.iloc[4:]
body = body[body[2].astype(str).str.fullmatch(r"\d{8}")]
dates = pd.to_datetime(body[2].astype(str), format="%Y%m%d")
DEVS = ["A", "M", "P", "총계"]
frames = []
for ch, gmv0, cust0 in (("광고", 3, 7), ("EP", 11, 15)):
    for i, dev in enumerate(DEVS):
        frames.append(pd.DataFrame({
            "날짜": dates.values, "채널": ch, "디바이스": dev,
            "거래액": pd.to_numeric(body[gmv0 + i], errors="coerce").fillna(0).values,
            "주문고객수": pd.to_numeric(body[cust0 + i], errors="coerce").fillna(0).values,
        }))
out = pd.concat(frames, ignore_index=True).sort_values(["날짜", "채널", "디바이스"]).reset_index(drop=True)
out["거래액"] = out["거래액"].round(0)

guard("쇼검APP(A/M/P)", OUT, out, dims=["채널", "디바이스"])
out.to_csv(OUT, index=False, encoding="utf-8-sig")
print(f"원본: {SRC}")
print(f"저장: {OUT}, shape={out.shape}, 날짜 {out['날짜'].min():%Y-%m-%d} ~ {out['날짜'].max():%Y-%m-%d}")
a = out[(out["채널"] == "광고") & (out["디바이스"] == "A")].set_index("날짜")
print("광고 APP 거래액(최근 10일, 백만원):")
print((a["거래액"].tail(10) / 1e6).round(1).to_string())


# ============================================================
# 2) 카테고리 x BPU x 신규여부 원본 (★일자별실적_A_M_P_전채널_카테고리 추가.xlsx) -> ep_ad_app_cat.csv
#    머리글 5줄: 채널(광고/EP) / 지표(거래액/주문고객수) / 디바이스(A/M/P/총계) / 당년신규여부(N/Y/총계)
#    행: 결제_연도 / 결제_연월 / 영업상품카테고리명 / BPU / 결제_일자 (카테고리·BPU는 첫 행에만 있어서 ffill)
#    광고(쇼핑검색광고) 채널만 저장 — 'EP + 쇼검 APP 합산' 보기에서 카테고리·BPU·신규 실적에 더할 때 쓴다.
# ============================================================
import glob

OUT_CAT = "ep_ad_app_cat.csv"
_cat_src = None
for d in DIRS:
    hits = sorted(glob.glob(os.path.join(d, "*A_M_P*카테고리*.xlsx")))
    hits = [h for h in hits if not os.path.basename(h).startswith("~$")]
    if hits:
        _cat_src = max(hits, key=os.path.getmtime)
        break
if _cat_src is None:
    print("(카테고리 원본 없음 — ep_ad_app_cat.csv는 그대로 둠)")
    sys.exit(0)
with open(_cat_src, "rb") as f:
    if f.read(2) != b"PK":
        abort("쇼검APP 카테고리", ["정상 xlsx가 아니에요(DRM 잠금 가능성). DRM 해제 후 다시 실행해주세요."])

craw = pd.read_excel(_cat_src, header=None)
if list(craw.iloc[4, :5]) != ["결제_연도(YYYY)", "결제_연월(YYYYMM)", "영업상품카테고리명", "BPU", "결제_일자(YYYYMMDD)"]:
    abort("쇼검APP 카테고리", [f"머리글 위치가 예상과 달라요: {list(craw.iloc[4, :5])}"])
ch_row, met_row, dev_row, new_row = craw.iloc[1].ffill(), craw.iloc[2].ffill(), craw.iloc[3].ffill(), craw.iloc[4]
cbody = craw.iloc[5:].copy()
cbody[[2, 3]] = cbody[[2, 3]].ffill()
cbody = cbody[cbody[4].astype(str).str.fullmatch(r"\d{8}")]
cdates = pd.to_datetime(cbody[4].astype(str), format="%Y%m%d")
parts = {}
for c in range(5, craw.shape[1]):
    ch, met, dev, nw = ch_row[c], met_row[c], dev_row[c], new_row[c]
    if ch != "광고" or dev not in ("A", "M", "P") or nw not in ("N", "Y"):
        continue
    key = (dev, nw)
    parts.setdefault(key, {})[met] = pd.to_numeric(cbody[c], errors="coerce").fillna(0).values
cframes = []
for (dev, nw), mets in parts.items():
    if set(mets) != {"거래액", "주문고객수"}:
        abort("쇼검APP 카테고리", [f"{dev}/{nw} 열에 거래액·주문고객수가 다 있지 않아요."])
    cframes.append(pd.DataFrame({
        "날짜": cdates.values, "BPU": cbody[3].values, "카테고리": cbody[2].values,
        "디바이스": dev, "신규": nw, "거래액": mets["거래액"], "주문고객수": mets["주문고객수"],
    }))
if not cframes:
    abort("쇼검APP 카테고리", ["광고 A/M/P x N/Y 열을 못 찾았어요."])
cout = pd.concat(cframes, ignore_index=True)
cout = cout[(cout["거래액"] != 0) | (cout["주문고객수"] != 0)]
cout["거래액"] = cout["거래액"].round(0)
cout = cout.sort_values(["날짜", "BPU", "카테고리", "디바이스", "신규"]).reset_index(drop=True)

# 일자별 파일(광고 A 합계)과 맞는지 확인 — 같은 Tableau 뷰라 합계가 같아야 한다
_chk = cout[cout["디바이스"] == "A"].groupby("날짜")["거래액"].sum()
_ref = out[(out["채널"] == "광고") & (out["디바이스"] == "A")].set_index("날짜")["거래액"].reindex(_chk.index)
_gap = (_chk - _ref).abs()
if (_gap > 1000).any():
    print("⚠️ 카테고리 원본 광고 APP 합계가 일자별 원본과 달라요:", _gap[_gap > 1000].round(0).to_dict())

guard("쇼검APP 카테고리", OUT_CAT, cout, dims=["BPU", "카테고리"])
cout.to_csv(OUT_CAT, index=False, encoding="utf-8-sig")
print(f"카테고리 원본: {_cat_src}")
print(f"저장: {OUT_CAT}, shape={cout.shape}, 날짜 {cout['날짜'].min():%Y-%m-%d} ~ {cout['날짜'].max():%Y-%m-%d}, "
      f"카테고리 {cout['카테고리'].nunique()}개, BPU {sorted(cout['BPU'].unique())}")
