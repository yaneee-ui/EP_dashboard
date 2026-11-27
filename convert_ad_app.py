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
