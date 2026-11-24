"""명품실적(순금+실버).csv / 명품실적(순금제외).csv (유입채널별 명품 일자별 실적 raw)를
대시보드가 쓰는 ep_luxury_channel.csv(날짜/구분/채널/고객구분/거래액/주문고객수)로 변환.

2026년 9월부로 쥬얼리(순금+실버 포함)가 잡화 > 명품 카테고리로 옮겨졌다. 두 파일은 25년 명품 기준으로
집계한 raw라 기존 카테고리 실적과 조금 다를 수 있어서, 별도 화면(13. 명품 채널별 실적)에서만 쓴다.
  - 명품실적(순금제외).csv / 명품실적(순금+실버 외).csv  -> 구분 "순금제외" : 25년 명품 기준과 같은 범위(전년과 바로 비교 가능)
  - 명품실적(순금+실버).csv -> 구분 "순금+실버": 쥬얼리(순금+실버) 분. 둘을 더하면 9월 이후 명품 전체.

원본: UTF-16 탭 구분. 첫 줄은 'AF대분류명(  /  당년신규여부)' 머리글이고, '결제_연도(YYYY)'가 적힌 줄까지가 머리글이다.
  - 2026-11-24부터 (새 형식): 머리글 3단 = 지표(거래액/주문고객수) / 유입채널(EP·직접·광고·제휴·PUSH) / 당년신규여부(Y/N)
      -> 고객구분 Y = "신규", N = "기존". 전체 = 신규 + 기존.
  - 예전 형식: 머리글 1단 = 유입채널, 지표는 거래액만 -> 고객구분 "전체", 주문고객수 없음(빈칸).
일자 행 = 결제_일자(YYYYMMDD), '총계' 행은 검산용으로만 쓴다. 빈칸 = 그 채널 거래 없음(0).
주문고객수는 채널·고객구분별 값이라, 채널끼리 더한 합계는 여러 채널로 산 고객이 중복될 수 있다.
"""
import os

import pandas as pd
from raw_sanity import abort, guard


def _pick(*names):
    # 순금제외 파일은 이름이 '(순금제외)' 또는 '(순금+실버 외)'로 올라와서 둘 다 받고, 둘 다 있으면 더 최근 파일을 쓴다.
    found = [n for n in names if os.path.exists(n)]
    return max(found, key=os.path.getmtime) if found else names[0]


SRCS = {
    "순금+실버": _pick("명품실적(순금+실버).csv"),
    "순금제외": _pick("명품실적(순금+실버 외).csv", "명품실적(순금제외).csv"),
}
OUT = "ep_luxury_channel.csv"
DATE_COL, YEAR_COL, CAT_COL = "결제_일자(YYYYMMDD)", "결제_연도(YYYY)", "영업상품카테고리명"
METRICS = {"거래액", "주문고객수"}
CUST = {"Y": "신규", "N": "기존"}


def _num(s):
    return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False).str.strip(), errors="coerce")


parts, problems, layouts = [], [], {}
for kind, path in SRCS.items():
    name = f"명품실적({kind})"
    try:
        raw = pd.read_csv(path, sep="\t", encoding="utf-16", header=None, dtype=str)
    except Exception as e:
        abort(name, [f"'{path}'을 읽을 수 없어요 ({type(e).__name__}) — UTF-16 탭 구분 CSV가 맞는지 확인하세요."])

    # '결제_연도(YYYY)'가 적힌 줄 = 마지막 머리글 줄. 그 위(첫 줄 제외)가 상위 머리글.
    _hit = raw.index[raw.apply(lambda r: YEAR_COL in r.values, axis=1)]
    if len(_hit) == 0:
        abort(name, [f"'{path}'에 '{YEAR_COL}' 머리글이 없어요: {raw.iloc[:3, :4].values.tolist()}"])
    h = int(_hit[0])
    hdr_rows = raw.iloc[1:h + 1]
    last = raw.iloc[h]
    key_cols = {v: i for i, v in last.items() if v in (YEAR_COL, DATE_COL, CAT_COL)}
    if YEAR_COL not in key_cols or DATE_COL not in key_cols:
        abort(name, [f"'{path}'의 컬럼이 예상과 달라요: {last.tolist()[:6]}"])
    data_cols = [i for i in raw.columns if i not in key_cols.values()]

    # 데이터 열마다 (지표, 채널, 고객구분)
    col_info = {}
    for i in data_cols:
        levels = [str(v).strip() for v in hdr_rows[i].tolist() if pd.notna(v)]
        if len(levels) == 3 and levels[0] in METRICS and levels[2] in CUST:      # 새 형식
            col_info[i] = (levels[0], levels[1], CUST[levels[2]])
        elif len(levels) == 1:                                                  # 예전 형식
            col_info[i] = ("거래액", levels[0], "전체")
        else:
            abort(name, [f"머리글을 해석할 수 없는 열이 있어요 (열 {i}): {levels}"])
    layouts[kind] = "신규여부 포함" if any(v[2] != "전체" for v in col_info.values()) else "예전 형식(신규여부 없음)"
    if not any(ch == "EP" for _, ch, _ in col_info.values()):
        abort(name, [f"유입채널에 'EP'가 없어요: {sorted({ch for _, ch, _ in col_info.values()})}"])

    body = raw.iloc[h + 1:].copy()
    yr, dt = body[key_cols[YEAR_COL]].ffill(), body[key_cols[DATE_COL]]
    vals = body[data_cols].apply(_num)

    is_day = dt.str.fullmatch(r"\d{8}", na=False)
    days = pd.to_datetime(dt[is_day], format="%Y%m%d")
    if days.empty or days.duplicated().any():
        abort(name, ["일자 행이 없거나 같은 날짜가 중복돼 있어요."])

    # 검산: 연도별 '총계' 행 == 일자 합계 (파일이 중간에 잘렸거나 일부만 내려받았는지 확인)
    for ridx in body.index[(dt == "총계") & yr.str.fullmatch(r"\d{4}", na=False)]:
        y = int(yr[ridx])
        sub = vals.loc[is_day[is_day].index[days.dt.year.values == y]]
        for i in data_cols:
            tot = vals.at[ridx, i] if pd.notna(vals.at[ridx, i]) else 0
            got = sub[i].fillna(0).sum()
            if abs(got - tot) > max(1000 if col_info[i][0] == "거래액" else 0.5, abs(tot) * 1e-6):
                problems.append(f"{kind} {y}년 {'/'.join(col_info[i])}: 일자 합계 {got:,.0f} ≠ 총계 {tot:,.0f}")

    daily = vals[is_day].copy()
    daily.index = days.values
    recs = []
    for i in data_cols:
        metric, ch, cust = col_info[i]
        recs.append(pd.DataFrame({"날짜": daily.index, "채널": ch, "고객구분": cust, "지표": metric, "값": daily[i].values}))
    long = pd.concat(recs, ignore_index=True)
    wide = long.pivot_table(index=["날짜", "채널", "고객구분"], columns="지표", values="값", aggfunc="sum").reset_index()
    wide.columns.name = None
    wide["거래액"] = wide["거래액"].fillna(0).round().astype("int64")
    if "주문고객수" in wide.columns:
        wide["주문고객수"] = wide["주문고객수"].fillna(0).round().astype("int64")
    else:
        wide["주문고객수"] = pd.NA
    # 원본에서 한 날짜의 모든 칸이 빈칸이면 pivot_table에서 빠지니, 일자 x 채널 x 고객구분 전체 격자를 채운다
    grid = pd.MultiIndex.from_product(
        [sorted(daily.index.unique()), sorted({v[1] for v in col_info.values()}), sorted({v[2] for v in col_info.values()})],
        names=["날짜", "채널", "고객구분"],
    )
    wide = wide.set_index(["날짜", "채널", "고객구분"]).reindex(grid).reset_index()
    wide["거래액"] = wide["거래액"].fillna(0).astype("int64")
    if layouts[kind] == "신규여부 포함":
        wide["주문고객수"] = wide["주문고객수"].fillna(0).astype("int64")
    wide.insert(1, "구분", kind)
    parts.append(wide)

    gaps = pd.date_range(daily.index.min(), daily.index.max()).difference(pd.DatetimeIndex(daily.index))
    if len(gaps):
        print(f"참고: {name} 원본에 없는 날짜 {len(gaps)}일 — {[d.strftime('%m/%d') for d in gaps][:5]} (0으로 처리돼요)")

if problems:
    abort("명품실적", problems)
if len(set(layouts.values())) > 1:
    abort("명품실적", [f"두 파일의 형식이 달라요 — 둘 다 같은 형식(신규여부 포함)으로 받아주세요: {layouts}"])

out_df = pd.concat(parts, ignore_index=True)
out_df = out_df[["날짜", "구분", "채널", "고객구분", "거래액", "주문고객수"]].sort_values(["날짜", "구분", "채널", "고객구분"]).reset_index(drop=True)
guard("명품실적", OUT, out_df, dims=["구분", "채널"])
out_df.to_csv(OUT, index=False, encoding="utf-8-sig")

print(f"저장 완료: {OUT}, shape={out_df.shape}  ({', '.join(f'{k}: {v}' for k, v in layouts.items())})")
print("날짜 범위:", out_df["날짜"].min(), "~", out_df["날짜"].max())
for (_k, _c), _g in out_df.groupby(["구분", "고객구분"]):
    print(f"[{_k}/{_c}] 거래액", {c: f"{v:,.0f}" for c, v in _g.groupby("채널")["거래액"].sum().items()})
