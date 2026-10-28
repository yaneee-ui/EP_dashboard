"""명품실적(순금+실버).csv / 명품실적(순금제외).csv (유입채널별 명품 일자별 거래액 raw)를
대시보드가 쓰는 ep_luxury_channel.csv(날짜/구분/채널/거래액)로 변환.

2026년 9월부로 쥬얼리(순금+실버 포함)가 잡화 > 명품 카테고리로 옮겨졌다. 두 파일은 25년 명품 기준으로
집계한 raw라 기존 카테고리 실적과 조금 다를 수 있어서, 별도 화면(13. 명품 채널별 실적)에서만 쓴다.
  - 명품실적(순금제외).csv  -> 구분 "순금제외" : 25년 명품 기준과 같은 범위(전년과 바로 비교 가능)
  - 명품실적(순금+실버).csv -> 구분 "순금+실버": 쥬얼리(순금+실버) 분. 둘을 더하면 9월 이후 명품 전체.
원본: UTF-16 탭 구분, 첫 줄은 'AF대분류명' 머리글, 둘째 줄이 실제 컬럼명. 컬럼 = 영업상품카테고리명/
결제_연도/결제_일자(YYYYMMDD)/유입채널(EP·직접·광고·제휴·PUSH...). '총계' 행은 검산용으로만 쓴다.
빈칸 = 그 채널 거래 없음(0).
"""
import pandas as pd
from raw_sanity import abort, guard

SRCS = {"순금+실버": "명품실적(순금+실버).csv", "순금제외": "명품실적(순금제외).csv"}
OUT = "ep_luxury_channel.csv"
DATE_COL, YEAR_COL, CAT_COL = "결제_일자(YYYYMMDD)", "결제_연도(YYYY)", "영업상품카테고리명"

parts, problems = [], []
for kind, path in SRCS.items():
    try:
        raw = pd.read_csv(path, sep="\t", encoding="utf-16", header=1, thousands=",", dtype=str)
    except Exception as e:
        abort(f"명품실적({kind})", [f"'{path}'을 읽을 수 없어요 ({type(e).__name__}) — UTF-16 탭 구분 CSV가 맞는지 확인하세요."])
    if DATE_COL not in raw.columns or CAT_COL not in raw.columns:
        abort(f"명품실적({kind})", [f"'{path}'의 컬럼이 예상과 달라요: {list(raw.columns)[:6]}"])
    channels = [c for c in raw.columns if c not in (CAT_COL, YEAR_COL, DATE_COL)]
    if "EP" not in channels:
        abort(f"명품실적({kind})", [f"유입채널 컬럼에 'EP'가 없어요: {channels}"])
    for c in channels:
        raw[c] = pd.to_numeric(raw[c].str.replace(",", "", regex=False), errors="coerce")

    daily = raw[raw[DATE_COL].str.fullmatch(r"\d{8}", na=False)].copy()
    daily["날짜"] = pd.to_datetime(daily[DATE_COL], format="%Y%m%d")
    if daily.empty or daily["날짜"].duplicated().any():
        abort(f"명품실적({kind})", ["일자 행이 없거나 같은 날짜가 중복돼 있어요."])

    # 검산: 연도별 '총계' 행 == 일자 합계 (파일이 중간에 잘렸거나 일부만 내려받았는지 확인)
    year_rows = raw[(raw[YEAR_COL].str.fullmatch(r"\d{4}", na=False)) & (raw[DATE_COL] == "총계")]
    for _, yr in year_rows.iterrows():
        sub = daily[daily["날짜"].dt.year == int(yr[YEAR_COL])]
        for c in channels:
            tot = yr[c] if pd.notna(yr[c]) else 0
            if abs(sub[c].fillna(0).sum() - tot) > max(1000, abs(tot) * 1e-6):
                problems.append(f"{kind} {yr[YEAR_COL]}년 {c}: 일자 합계 {sub[c].fillna(0).sum():,.0f} ≠ 총계 {tot:,.0f}")

    long = daily.melt(id_vars="날짜", value_vars=channels, var_name="채널", value_name="거래액")
    long["거래액"] = long["거래액"].fillna(0).round().astype("int64")
    long.insert(1, "구분", kind)
    parts.append(long)
    gaps = pd.date_range(daily["날짜"].min(), daily["날짜"].max()).difference(daily["날짜"])
    if len(gaps):
        print(f"참고: 명품실적({kind}) 원본에 없는 날짜 {len(gaps)}일 — {[d.strftime('%m/%d') for d in gaps][:5]} (0으로 처리돼요)")

if problems:
    abort("명품실적", problems)

out_df = pd.concat(parts, ignore_index=True).sort_values(["날짜", "구분", "채널"]).reset_index(drop=True)
guard("명품실적", OUT, out_df, dims=["구분", "채널"])
out_df.to_csv(OUT, index=False, encoding="utf-8-sig")

print(f"저장 완료: {OUT}, shape={out_df.shape}")
print("날짜 범위:", out_df["날짜"].min(), "~", out_df["날짜"].max())
for _k, _g in out_df.groupby("구분"):
    print(f"[{_k}]", {c: f"{v:,.0f}" for c, v in _g.groupby("채널")["거래액"].sum().items()})
