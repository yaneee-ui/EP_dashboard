"""데이터 품질 점검 — 업로드된 데이터가 최신인지, 서로 맞는지, 빠진 날이 없는지, 갑자기 튄 값은 없는지.

일일 '업뎃' 때마다 사람이 확인하던 항목들(최신성, 데이터 간 합계 일치, 상품 데이터 누락,
채널 트래픽 이상 등)을 대시보드 안에서 자동으로 보여주기 위한 모듈.
계산 함수(compute_*)는 Streamlit과 무관한 순수 함수라 테스트하기 쉽고,
화면 그리기(render_quality_panel)만 streamlit을 쓴다.

각 점검 결과는 {"area": 영역, "level": "ok"|"warn"|"error", "msg": 설명} 한 줄.
"""
import pandas as pd

# --- 기준값 (필요하면 여기서만 조정) ---
SUM_MISMATCH_PCT = 0.5        # EP실적 vs 카테고리/전체일자 합계 차이 허용치(%)
COVERAGE_DROP_PP = 5.0        # 상품/카테고리 비율이 평소보다 이만큼(%p) 낮으면 경고
COVERAGE_BASELINE_DAYS = 14   # '평소' 비율을 구할 직전 일수
GAP_LOOKBACK_DAYS = 60        # 결측일 점검 범위
SPIKE_RATIO_HIGH = 3.0        # 채널 트래픽이 직전 중앙값의 3배 이상이면 이상
SPIKE_RATIO_LOW = 0.33        # 1/3 이하여도 이상
STALE_ERROR_DAYS = 3          # 기준일보다 이만큼 이상 뒤처지면 error (1~2일은 warn)

# 실적이 원래 없는 날(빠진 게 아니라 0이 맞는 날) — 결측일 경고에서 제외. {데이터 이름: [날짜, ...]}
KNOWN_EMPTY_DAYS = {
    "명품(순금+실버)": ["2026-10-25"],
}

# 월초에 트래픽이 크게 느는 게 정상인 채널 — 이 기간(매월 N일까지)의 '급증'은 경고하지 않는다 (급감은 그대로 경고).
# 제휴: 월초 신규 유입이 많은 구조라 정상 (2026-11-05 확인)
EARLY_MONTH_SPIKE_OK = {"제휴": 10}

_WD = ["월", "화", "수", "목", "금", "토", "일"]


def _fmt_d(d):
    d = pd.Timestamp(d)
    return f"{d.month}/{d.day}({_WD[d.weekday()]})"


def _row(area, level, msg):
    return {"area": area, "level": level, "msg": msg}


def _dates(df, col="날짜"):
    if df is None or len(df) == 0 or col not in df.columns:
        return pd.DatetimeIndex([])
    return pd.DatetimeIndex(pd.to_datetime(df[col]).dt.normalize().unique()).sort_values()


def check_freshness(datasets, base_date):
    """datasets: [(이름, 날짜 DatetimeIndex)]. 기준일(보통 EP실적 최신일)보다 뒤처진 데이터를 찾는다."""
    out = []
    base = pd.Timestamp(base_date).normalize()
    for name, ds in datasets:
        if len(ds) == 0:
            out.append(_row("최신성", "warn", f"{name}: 데이터 없음"))
            continue
        last = ds.max()
        lag = (base - last).days
        if lag <= 0:
            out.append(_row("최신성", "ok", f"{name}: {_fmt_d(last)}까지 반영"))
        else:
            lvl = "error" if lag >= STALE_ERROR_DAYS else "warn"
            out.append(_row("최신성", lvl, f"{name}: {_fmt_d(last)}까지만 반영 (EP실적보다 {lag}일 뒤처짐) — 새 파일 업로드 필요"))
    return out


def check_gaps(datasets, lookback=GAP_LOOKBACK_DAYS):
    """최근 lookback일 중 비어 있는 날짜(각 데이터의 최신일 기준)를 찾는다."""
    out = []
    for name, ds in datasets:
        if len(ds) == 0:
            continue
        full = pd.date_range(ds.max() - pd.Timedelta(days=lookback), ds.max())
        # 데이터가 시작되기 전 날짜는 결측이 아니다
        full = full[full >= ds.min()]
        miss = full.difference(ds)
        known = pd.DatetimeIndex(pd.to_datetime(KNOWN_EMPTY_DAYS.get(name, [])))
        miss = miss.difference(known)
        if len(miss) == 0:
            out.append(_row("빠진 날짜", "ok", f"{name}: 최근 {lookback}일 빠진 날 없음"))
        else:
            shown = ", ".join(_fmt_d(d) for d in miss[:6]) + (f" 외 {len(miss) - 6}일" if len(miss) > 6 else "")
            out.append(_row("빠진 날짜", "warn", f"{name}: {len(miss)}일 빠져 있어요 — {shown}"))
    return out


def check_sum_consistency(df_traffic, df_category, df_total_daily, days=7):
    """같은 날 같은 지표(거래액)가 데이터마다 일치하는지 — EP실적 Total vs 카테고리(전체) vs 전체일자(EP)."""
    out = []
    if df_traffic is None or df_traffic.empty:
        return out
    t = df_traffic[(df_traffic["BPU"] == "Total") & (df_traffic["회원구분"] == "전체")].groupby("날짜")["거래액"].sum()
    t = t.sort_index().tail(days)
    if t.empty:
        return out

    def _cmp(name, other):
        other = other.reindex(t.index)
        bad = []
        for d, v in t.items():
            o = other.get(d)
            if o is None or pd.isna(o) or v == 0:
                continue
            diff_pct = (o - v) / v * 100
            if abs(diff_pct) > SUM_MISMATCH_PCT:
                bad.append(f"{_fmt_d(d)} {diff_pct:+.1f}%")
        if bad:
            out.append(_row("합계 일치", "warn", f"EP실적 vs {name} 거래액이 안 맞는 날: " + ", ".join(bad[:5])))
        else:
            out.append(_row("합계 일치", "ok", f"EP실적 = {name} 거래액 일치 (최근 {len(t)}일)"))

    if df_category is not None and not df_category.empty:
        c = df_category[(df_category["카테고리"] == "전체") & (df_category["브랜드"] == "전체")]
        if "회원구분" in c.columns:
            c = c[c["회원구분"] == "전체"]
        _cmp("카테고리", c.groupby("날짜")["거래액"].sum())
    if df_total_daily is not None and not df_total_daily.empty:
        e = df_total_daily[df_total_daily["채널"] == "EP"].groupby("날짜")["거래액"].sum()
        _cmp("전체일자(EP)", e)
    return out


def check_product_coverage(df_product, df_category, recent=3):
    """상품 데이터 합계 ÷ 카테고리 데이터 합계 비율이 평소보다 갑자기 떨어졌는지.
    (상품 원본은 일부 상품이 빠져 보통 96~98% 수준 — 최신일에 raw가 덜 들어오면 이 비율이 급락)"""
    if df_product is None or df_product.empty or df_category is None or df_category.empty:
        return []
    c = df_category[(df_category["카테고리"] == "전체") & (df_category["브랜드"] == "전체")]
    if "회원구분" in c.columns:
        c = c[c["회원구분"] == "전체"]
    c = c.groupby("날짜")["거래액"].sum()
    p = df_product.groupby("날짜")["거래액"].sum()
    ratio = (p / c).dropna()
    ratio = ratio[c.reindex(ratio.index) > 0]
    if len(ratio) < recent + 5:
        return []
    ratio = ratio.sort_index()
    latest = ratio.tail(recent)
    base = ratio.iloc[:-recent].tail(COVERAGE_BASELINE_DAYS)
    base_med = float(base.median())
    bad = [(d, r) for d, r in latest.items() if (base_med - r) * 100 > COVERAGE_DROP_PP]
    if bad:
        txt = ", ".join(f"{_fmt_d(d)} {r * 100:.1f}%" for d, r in bad)
        return [_row(
            "상품 데이터", "warn",
            f"상품 거래액이 카테고리 대비 평소({base_med * 100:.1f}%)보다 낮아요 — {txt}. "
            "상품 raw가 덜 들어왔을 수 있어 최신일 상품 랭킹은 참고만 하세요",
        )]
    return [_row("상품 데이터", "ok", f"상품 ÷ 카테고리 거래액 {latest.iloc[-1] * 100:.1f}% (평소 {base_med * 100:.1f}%)")]


def check_channel_traffic(df_total_daily, recent=3):
    """채널별(직접/광고/제휴/PUSH/EP) 트래픽이 직전 2주 중앙값 대비 갑자기 튀거나 꺼졌는지."""
    if df_total_daily is None or df_total_daily.empty or "트래픽" not in df_total_daily.columns:
        return []
    out = []
    bad_any = False
    for ch in ["EP", "직접", "광고", "제휴", "PUSH"]:
        s = df_total_daily[df_total_daily["채널"] == ch].groupby("날짜")["트래픽"].sum().sort_index()
        s = s[s > 0]
        if len(s) < recent + 7:
            continue
        base = s.iloc[:-recent].tail(14)
        med = float(base.median())
        if med <= 0:
            continue
        flagged = []
        for d, v in s.tail(recent).items():
            r = v / med
            if r >= SPIKE_RATIO_HIGH and d.day <= EARLY_MONTH_SPIKE_OK.get(ch, 0):
                continue
            if r >= SPIKE_RATIO_HIGH or r <= SPIKE_RATIO_LOW:
                flagged.append(f"{_fmt_d(d)} {v:,.0f} (평소의 {r:.1f}배)")
        if flagged:
            bad_any = True
            out.append(_row("채널 트래픽", "warn", f"{ch} 트래픽이 평소와 크게 달라요 — " + ", ".join(flagged) + " · 원본 확인 필요"))
    if not bad_any:
        out.append(_row("채널 트래픽", "ok", "채널별 트래픽이 평소 범위 안"))
    return out


def check_sign(df_traffic):
    """최신일 거래액이 0 이하이거나 BPU 거래액이 음수인 경우."""
    if df_traffic is None or df_traffic.empty:
        return []
    last = df_traffic["날짜"].max()
    d = df_traffic[(df_traffic["날짜"] == last) & (df_traffic["회원구분"] == "전체")]
    neg = d[d["거래액"] < 0]["BPU"].astype(str).tolist()
    tot = d[d["BPU"] == "Total"]["거래액"].sum()
    if tot <= 0:
        return [_row("값 이상", "error", f"{_fmt_d(last)} 전체 거래액이 {tot:,.0f} — 원본 확인 필요")]
    if neg:
        return [_row("값 이상", "warn", f"{_fmt_d(last)} 거래액이 마이너스인 매체: {', '.join(neg)} (순취소일 수 있어요)")]
    return [_row("값 이상", "ok", f"{_fmt_d(last)} 거래액 값 정상")]


def compute_data_quality(df_ep, df_traffic, df_category, df_product, df_total_daily,
                         df_coupon_daily, df_lux, df_chall, ep_date_col="일자"):
    """모든 점검을 돌려서 [{"area","level","msg"}, ...] (심각한 것부터)로 반환."""
    if df_traffic is None or df_traffic.empty:
        return [_row("최신성", "error", "EP실적 데이터가 없어요")]
    base = df_traffic["날짜"].max()

    lux_sets = []
    if df_lux is not None and not df_lux.empty and "구분" in df_lux.columns:
        for k, g in df_lux.groupby("구분"):
            lux_sets.append((f"명품({k})", _dates(g)))
    elif df_lux is not None and not df_lux.empty:
        lux_sets.append(("명품", _dates(df_lux)))

    sets = [
        ("EP실적", _dates(df_traffic)),
        ("카테고리", _dates(df_category)),
        ("상품", _dates(df_product)),
        ("쿠폰", _dates(df_coupon_daily)),
        ("전체일자(채널별)", _dates(df_total_daily)),
        ("전체 채널별 전년비", _dates(df_chall)),
        ("EP채널(원부매칭)", _dates(df_ep, ep_date_col)),
    ] + lux_sets

    items = []
    items += check_freshness(sets, base)
    items += check_sum_consistency(df_traffic, df_category, df_total_daily)
    items += check_product_coverage(df_product, df_category)
    items += check_channel_traffic(df_total_daily)
    items += check_sign(df_traffic)
    items += check_gaps([s for s in sets if s[0] != "EP채널(원부매칭)"])

    order = {"error": 0, "warn": 1, "ok": 2}
    items.sort(key=lambda r: order[r["level"]])
    return items


def summarize(items):
    """(error 수, warn 수, ok 수)"""
    e = sum(1 for r in items if r["level"] == "error")
    w = sum(1 for r in items if r["level"] == "warn")
    o = sum(1 for r in items if r["level"] == "ok")
    return e, w, o


def quality_badge_html(items):
    e, w, _ = summarize(items)
    if e:
        return f"<span style='background:#fee2e2;color:#b91c1c;border-radius:12px;padding:3px 12px;font-weight:700;font-size:0.82rem;'>❌ 확인 필요 {e + w}건</span>"
    if w:
        return f"<span style='background:#fef3c7;color:#b45309;border-radius:12px;padding:3px 12px;font-weight:700;font-size:0.82rem;'>⚠️ 확인 필요 {w}건</span>"
    return "<span style='background:#dcfce7;color:#15803d;border-radius:12px;padding:3px 12px;font-weight:700;font-size:0.82rem;'>✅ 데이터 정상</span>"


def render_quality_panel(items):
    """홈 화면용: 문제 항목은 항상 보이고, 정상 항목은 접어서 보여준다."""
    import streamlit as st

    icons = {"error": "❌", "warn": "⚠️", "ok": "✅"}
    colors = {"error": "#b91c1c", "warn": "#b45309", "ok": "#15803d"}
    bgs = {"error": "#fef2f2", "warn": "#fffbeb", "ok": "#f0fdf4"}

    def _line(r):
        return (
            f"<div style='background:{bgs[r['level']]};border-left:4px solid {colors[r['level']]};"
            "border-radius:6px;padding:7px 12px;margin-bottom:6px;font-size:0.84rem;color:#374151;'>"
            f"{icons[r['level']]} <b style='color:{colors[r['level']]};'>{r['area']}</b> · {r['msg']}</div>"
        )

    problems = [r for r in items if r["level"] != "ok"]
    oks = [r for r in items if r["level"] == "ok"]
    if problems:
        st.markdown("".join(_line(r) for r in problems), unsafe_allow_html=True)
    else:
        st.markdown(
            "<div style='background:#f0fdf4;border-left:4px solid #15803d;border-radius:6px;padding:8px 12px;"
            "font-size:0.86rem;color:#15803d;font-weight:600;'>✅ 모든 점검 항목이 정상이에요</div>",
            unsafe_allow_html=True,
        )
    if oks:
        with st.expander(f"정상 항목 {len(oks)}개 보기", expanded=False):
            st.markdown("".join(_line(r) for r in oks), unsafe_allow_html=True)
