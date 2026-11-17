"""홈 화면 — 어제 실적 한눈에 + 이번 달 진행 + 주목할 변화 + 데이터 품질 점검.

다른 화면(1번 실적 요약, 10번 마감 예상 등)과 숫자가 어긋나지 않도록 같은 계산 함수를 재사용한다:
  - 어제 실적/사업부별: compute_bpu_comparison_rows (1·3번 화면과 동일)
  - 이번 달/연 목표: build_forecast_table (10번 화면과 동일)
  - 카테고리 변동: summary_compare_ranges + category_gmv_rows (1번 화면 '카테고리 Top 변동'과 동일)
"""
import pandas as pd
import streamlit as st

from dashboard_helpers import (
    compute_bpu_comparison_rows, build_forecast_table, summary_compare_ranges, category_gmv_rows,
)
from data_quality import compute_data_quality, quality_badge_html, render_quality_panel, summarize
from sidebar import goto_page

# 연도별 EP 거래액 목표 (10번 마감 예상 화면과 공용 — 여기서만 관리)
EP_YEARLY_GMV_TARGET = {2026: 46_750_000_000}

# 주목할 변화 기준 (필요하면 여기서 조정)
DROP_PREV_PCT = -20.0     # 전일 대비 이만큼 이상 떨어지면 주목
DROP_YOY_PCT = -10.0      # 전년 동요일 대비 이만큼 이상 떨어지면 주목
SURGE_YOY_PCT = 50.0      # 전년 동요일 대비 이만큼 이상 오르면 주목(좋은 변화)

_WD = ["월", "화", "수", "목", "금", "토", "일"]
_CARD = "background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:14px 16px;height:100%;box-sizing:border-box;"


def _delta(v):
    """증감률(%) -> 색 입힌 문자열. 양수 초록 / 음수 빨강(△)."""
    if v is None or pd.isna(v):
        return "<span style='color:#9ca3af;'>-</span>"
    if v >= 0:
        return f"<span style='color:#16a34a;font-weight:600;'>{v:.1f}%</span>"
    return f"<span style='color:#dc2626;font-weight:600;'>△{abs(v):.1f}%</span>"


def _eok(v):
    return f"{v / 1e8:,.1f}억"


def _section(title, sub=None):
    st.markdown(
        f"<div style='margin:22px 0 8px;'><span style='font-size:1.08rem;font-weight:700;color:#111827;'>{title}</span>"
        + (f"<span style='font-size:0.8rem;color:#6b7280;margin-left:10px;'>{sub}</span>" if sub else "")
        + "</div>",
        unsafe_allow_html=True,
    )


def _kpi_cards(rows, ref):
    by = {(r["metric_label"], r["bpu"]): r for r in rows}
    labels = [("거래액(순결제)", "거래액"), ("EP UV", "UV"), ("구매객수", "구매객수"), ("구매전환율(%)", "전환율"), ("객단가", "객단가")]
    cols = st.columns(len(labels))
    for col, (key, nm) in zip(cols, labels):
        r = by.get((key, "Total"))
        with col:
            if not r or not r["stats"]:
                st.markdown(f"<div style='{_CARD}color:#9ca3af;'>{nm}: -</div>", unsafe_allow_html=True)
                continue
            s = r["stats"]
            v = f"{s['current']:.1f}%" if r["is_pct"] else f"{s['current']:,.0f}"
            st.markdown(
                f"<div style='{_CARD}'>"
                f"<div style='color:#6b7280;font-size:0.8rem;'>{nm}</div>"
                f"<div style='font-size:clamp(1.05rem,1.9vw,1.5rem);font-weight:700;color:#111827;white-space:nowrap;'>{v}</div>"
                f"<div style='font-size:0.78rem;margin-top:6px;line-height:1.6;'>"
                f"전일비 {_delta(s.get('prev_delta'))}<br/>전년동요일비 {_delta(s.get('yoy_delta'))}</div></div>",
                unsafe_allow_html=True,
            )


def _month_progress(df_traffic, ref):
    """이번 달 누적 · 전년 동기간 비교 · 마감예상 · 연 목표 달성률."""
    base = df_traffic[(df_traffic["BPU"] == "Total") & (df_traffic["회원구분"] == "전체")]
    cur, prev, _ = summary_compare_ranges("월별", ref, ref)
    gm = lambda rng: float(base[(base["날짜"] >= rng[0]) & (base["날짜"] <= rng[1])]["거래액"].sum())
    mtd, mtd_prev = gm(cur), gm(prev)
    mtd_yoy = (mtd / mtd_prev - 1) * 100 if mtd_prev > 0 else None
    days = (cur[1] - cur[0]).days + 1

    fc_month = fc_year = None
    year = ref.year
    try:
        tbl = build_forecast_table(df_traffic, "거래액", "거래액", None, year, is_ratio=False, ratio_scale=1.0)
        if "Total" in tbl.index:
            tot = tbl.loc["Total"]
            fc_month = float(tot.get(f"{ref.month}월", 0)) or None
            fc_year = float(tot["합계"])
    except Exception:
        pass
    ytd = float(base[base["날짜"].dt.year == year]["거래액"].sum())
    target = EP_YEARLY_GMV_TARGET.get(year)

    cards = [
        (f"{ref.month}월 누적 거래액 ({cur[0].month}/{cur[0].day}~{cur[1].month}/{cur[1].day}, {days}일)", _eok(mtd),
         f"전년 동기간 {_delta(mtd_yoy)} · {_eok(mtd_prev)}"),
    ]
    if fc_month:
        cards.append((f"{ref.month}월 마감예상", _eok(fc_month), "일할계산 · 10번 '마감 예상 실적'과 동일"))
    if target:
        rate = ytd / target * 100
        sub = f"{_eok(ytd)} / 목표 {_eok(target)}"
        if fc_year:
            sub += f" · 마감예상 반영 {fc_year / target * 100:.1f}%"
        cards.append((f"{year}년 목표 달성률 (누적)", f"{rate:.1f}%", sub))
    cols = st.columns(len(cards))
    for col, (t, v, sub) in zip(cols, cards):
        with col:
            st.markdown(
                f"<div style='{_CARD}'><div style='color:#6b7280;font-size:0.78rem;'>{t}</div>"
                f"<div style='font-size:clamp(1.05rem,1.9vw,1.5rem);font-weight:700;color:#111827;white-space:nowrap;'>{v}</div>"
                f"<div style='font-size:0.76rem;color:#6b7280;margin-top:6px;line-height:1.5;'>{sub}</div></div>",
                unsafe_allow_html=True,
            )
    if target:
        pct = max(0.0, min(ytd / target * 100, 100.0))
        fpct = max(pct, min((fc_year or ytd) / target * 100, 100.0))
        st.markdown(
            "<div style='position:relative;height:12px;background:#e5e7eb;border-radius:6px;overflow:hidden;margin-top:10px;'>"
            f"<div style='position:absolute;left:0;top:0;height:100%;width:{fpct:.1f}%;background:#93c5fd;'></div>"
            f"<div style='position:absolute;left:0;top:0;height:100%;width:{pct:.1f}%;background:#2563eb;'></div></div>",
            unsafe_allow_html=True,
        )


def compute_watch_items(rows):
    """거래액·핵심 지표에서 주목할 변화를 규칙으로 뽑는다.

    같은 대상·지표는 한 줄로 합친다(전일비·전년동요일비를 한 줄에 같이 보여주려고).
    반환: [{"sev","kind"(drop/surge),"name","metric","cur","prev","yoy","prev_flag","yoy_flag"}] — 심각도 큰 순.
    *_flag 는 해당 칸이 기준을 넘었는지("drop"/"surge"/None)."""
    items = []
    by = {(r["metric_label"], r["bpu"]): r["stats"] for r in rows}
    nm = {"Total": "전체"}

    def _add(name, metric, cur, s, check_prev):
        prev, yoy = s.get("prev_delta"), s.get("yoy_delta")
        pf = "drop" if (check_prev and prev is not None and prev <= DROP_PREV_PCT) else None
        yf = None
        if yoy is not None and yoy <= DROP_YOY_PCT:
            yf = "drop"
        elif yoy is not None and yoy >= SURGE_YOY_PCT:
            yf = "surge"
        if not pf and not yf:
            return
        kind = "drop" if "drop" in (pf, yf) else "surge"
        sev = max(
            abs(prev) if pf else 0,
            (abs(yoy) + 5) if yf == "drop" else 0,
            (yoy / 2) if yf == "surge" else 0,
        )
        items.append({"sev": sev, "kind": kind, "name": name, "metric": metric, "cur": cur,
                      "prev": prev, "yoy": yoy, "prev_flag": pf, "yoy_flag": yf})

    for bpu in ["Total", "e-영업1", "e-영업2", "e-영업3", "e-영업4", "자사", "입점"]:
        s = by.get(("거래액(순결제)", bpu))
        if s:
            _add(nm.get(bpu, bpu), "거래액", f"{s['current'] / 1e6:,.0f}백만", s, True)
    # 비율·UV·객단가는 전일 변동이 원래 크므로 전년 동요일 하락만 본다(기존 규칙 그대로)
    for label, fmt in [("구매전환율(%)", "{:.1f}%"), ("EP UV", "{:,.0f}"), ("객단가", "{:,.0f}")]:
        s = by.get((label, "Total"))
        if s and s.get("yoy_delta") is not None and s["yoy_delta"] <= DROP_YOY_PCT:
            _add("전체", label.replace("(%)", ""), fmt.format(s["current"]), s, False)
    items.sort(key=lambda x: -x["sev"])
    return items


def _watch_cell(v, flag):
    """증감률 한 칸. 기준을 넘은 칸만 색 배지로 강조하고, 나머지는 옅게."""
    if v is None or pd.isna(v):
        return "<td class='w-n'><span style='color:#cbd5e1;'>-</span></td>"
    txt = f"△{abs(v):.1f}%" if v < 0 else f"+{v:.1f}%"
    if flag == "drop":
        return f"<td class='w-n'><span style='background:#fee2e2;color:#b91c1c;font-weight:700;border-radius:6px;padding:2px 8px;'>{txt}</span></td>"
    if flag == "surge":
        return f"<td class='w-n'><span style='background:#dcfce7;color:#15803d;font-weight:700;border-radius:6px;padding:2px 8px;'>{txt}</span></td>"
    return f"<td class='w-n'><span style='color:#9ca3af;'>{txt}</span></td>"


def _watch_table(items):
    rows = ""
    for it in items:
        bar = "#ef4444" if it["kind"] == "drop" else "#22c55e"
        rows += (
            f"<tr><td style='border-left:4px solid {bar};padding-left:10px;white-space:nowrap;'><b>{it['name']}</b></td>"
            f"<td style='white-space:nowrap;color:#374151;'>{it['metric']}</td>"
            f"<td class='w-n' style='color:#6b7280;'>{it['cur']}</td>"
            f"{_watch_cell(it['prev'], it['prev_flag'])}{_watch_cell(it['yoy'], it['yoy_flag'])}</tr>"
        )
    return (
        "<style>.watch-t{width:100%;border-collapse:collapse;font-size:0.88rem;}"
        ".watch-t th{font-size:0.76rem;color:#6b7280;font-weight:600;text-align:right;padding:4px 10px;border-bottom:1px solid #e5e7eb;}"
        ".watch-t th:first-child,.watch-t th:nth-child(2){text-align:left;}"
        ".watch-t td{padding:7px 10px;border-bottom:1px solid #f1f2f4;}"
        ".watch-t td.w-n{text-align:right;white-space:nowrap;}</style>"
        "<div style='background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:6px 8px;overflow-x:auto;'>"
        "<table class='watch-t'><thead><tr><th>대상</th><th>지표</th><th>어제 값</th><th>전일비</th><th>전년 동요일비</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
    )


def _category_top(df_category, ref, last):
    """전체 BPU 합산 카테고리 거래액의 전년 동요일 대비 증감 Top3 / Bottom3 (백만원)."""
    cur, prev, _ = summary_compare_ranges("일별", ref, last)
    rows = category_gmv_rows(df_category, prev, cur, "sum", "전체", False)
    agg = {}
    for r in rows:
        e = agg.setdefault(r["카테고리"], [0.0, 0.0])
        e[0] += r["A"]
        e[1] += r["B"]
    ups = sorted([(c, b - a, a, b) for c, (a, b) in agg.items() if b - a > 0], key=lambda x: -x[1])[:3]
    downs = sorted([(c, b - a, a, b) for c, (a, b) in agg.items() if b - a < 0], key=lambda x: x[1])[:3]
    return ups, downs


def _cat_list(items, up):
    color = "#16a34a" if up else "#dc2626"
    title = "▲ 전년 동요일보다 늘어난 카테고리" if up else "▼ 전년 동요일보다 줄어든 카테고리"
    if not items:
        body = "<div style='color:#9ca3af;font-size:0.84rem;padding:6px 0;'>해당 없음</div>"
    else:
        body = ""
        for c, diff, a, b in items:
            pct = f"{(b / a - 1) * 100:+.0f}%" if a > 0 else ""
            sign = "+" if up else "△"
            body += (
                "<div style='display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid #f1f2f4;font-size:0.88rem;'>"
                f"<span>{c}</span><span style='color:{color};font-weight:700;white-space:nowrap;'>{sign}{abs(diff) / 1e6:,.1f}백만원"
                f"<span style='font-weight:400;font-size:0.78rem;margin-left:6px;'>{pct}</span></span></div>"
            )
    st.markdown(
        f"<div style='{_CARD}'><div style='font-weight:700;color:{color};font-size:0.84rem;margin-bottom:4px;'>{title}</div>{body}</div>",
        unsafe_allow_html=True,
    )


def render_home(df_ep, df_traffic, df_category, df_product, df_total_daily, df_coupon_daily, df_lux, df_chall, ep_date_col):
    if df_traffic is None or df_traffic.empty:
        st.info("데이터가 없습니다. 사이드바에서 데이터를 업로드해주세요.")
        return
    ref = df_traffic["날짜"].max().normalize()

    quality = compute_data_quality(
        df_ep, df_traffic, df_category, df_product, df_total_daily, df_coupon_daily, df_lux, df_chall, ep_date_col=ep_date_col,
    )

    # --- 머리말: 기준일 + 데이터 상태 배지 ---
    st.markdown(
        "<div style='display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-top:4px;'>"
        f"<span style='font-size:1.5rem;font-weight:800;color:#111827;'>🏠 {ref.month}월 {ref.day}일({_WD[ref.weekday()]}) 실적</span>"
        f"{quality_badge_html(quality)}"
        "<span style='font-size:0.8rem;color:#6b7280;'>EP실적 최신일 기준 · 전체 매체 · 전체 고객</span></div>",
        unsafe_allow_html=True,
    )

    # --- 1) 어제 실적 ---
    rows, _cfg, _ = compute_bpu_comparison_rows(df_traffic, "일별", ref)
    _section("📌 핵심 지표", "전일비 · 전년 동요일비(364일 전)")
    _kpi_cards(rows, ref)

    # --- 2) 이번 달 진행 ---
    _section("📅 이번 달 진행", "누적 · 마감예상 · 연 목표")
    _month_progress(df_traffic, ref)

    # --- 3) 사업부별 거래액 ---
    _section("🏢 사업부별 거래액", "전체 · e-영업1~4 · 자사/입점")
    by = {(r["metric_label"], r["bpu"]): r["stats"] for r in rows}
    head = "<th>매체</th><th>거래액</th><th>전일비</th><th>전주평균비</th><th>전년동요일비</th>"
    body = ""
    for bpu in ["Total", "e-영업1", "e-영업2", "e-영업3", "e-영업4", "자사", "입점"]:
        s = by.get(("거래액(순결제)", bpu))
        if not s:
            continue
        nm = "전체" if bpu == "Total" else bpu
        bold = "font-weight:700;background:#f3f4f6;" if bpu == "Total" else ""
        body += (
            f"<tr style='{bold}'><td class='m' style='white-space:nowrap;'>{nm}</td><td class='v'>{s['current']:,.0f}</td>"
            f"<td>{_delta(s.get('prev_delta'))}</td><td>{_delta(s.get('avg_delta'))}</td><td>{_delta(s.get('yoy_delta'))}</td></tr>"
        )
    st.markdown(
        f"<div style='overflow-x:auto;'><table class='summary-table'><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>",
        unsafe_allow_html=True,
    )

    # --- 4) 주목할 변화 ---
    _section("🔔 주목할 변화", f"전일 {DROP_PREV_PCT:.0f}% · 전년 동요일 {DROP_YOY_PCT:.0f}% 이하 하락 / +{SURGE_YOY_PCT:.0f}% 이상 상승")
    watch = compute_watch_items(rows)
    if watch:
        drops = [w for w in watch if w["kind"] == "drop"]
        surges = [w for w in watch if w["kind"] == "surge"]
        st.markdown(
            "<div style='font-size:0.86rem;color:#374151;margin:0 0 6px;'>"
            f"<span style='color:#b91c1c;font-weight:700;'>📉 하락 {len(drops)}건</span>"
            f" &nbsp;·&nbsp; <span style='color:#15803d;font-weight:700;'>📈 상승 {len(surges)}건</span>"
            " <span style='color:#9ca3af;'>· 색 칠한 칸이 기준을 넘은 값이에요</span></div>",
            unsafe_allow_html=True,
        )
        TOP_N = 5
        st.markdown(_watch_table(watch[:TOP_N]), unsafe_allow_html=True)
        if len(watch) > TOP_N:
            with st.expander(f"나머지 {len(watch) - TOP_N}건 더 보기"):
                st.markdown(_watch_table(watch[TOP_N:]), unsafe_allow_html=True)
    else:
        st.markdown(
            "<div style='background:#f0fdf4;border-radius:8px;padding:9px 14px;font-size:0.88rem;color:#15803d;'>"
            "✅ 기준을 넘는 급락/급등은 없어요</div>",
            unsafe_allow_html=True,
        )
    if df_category is not None and not df_category.empty:
        try:
            ups, downs = _category_top(df_category, ref, df_category["날짜"].max())
            st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
            c1, c2 = st.columns(2)
            with c1:
                _cat_list(ups, True)
            with c2:
                _cat_list(downs, False)
        except Exception:
            pass

    # --- 5) 데이터 품질 점검 ---
    e, w, o = summarize(quality)
    _section("🩺 데이터 품질 점검", f"점검 {e + w + o}개 · 문제 {e + w}개")
    render_quality_panel(quality)

    # --- 6) 바로가기 ---
    _section("🔗 자세히 보기")
    links = [
        ("📊 실적 요약", "1. 실적 요약"), ("🗂️ 카테고리 실적", "2. 카테고리 실적 요약"),
        ("📈 마감 예상", "10. 마감 예상 실적"), ("📑 주간보고용", "11. 주간보고용"), ("🎉 행사 기간 비교", "12. 행사 기간 비교"),
    ]
    cols = st.columns(len(links))
    for col, (label, page) in zip(cols, links):
        with col:
            st.button(label, key=f"home_go_{page}", on_click=goto_page, args=(page,), use_container_width=True)
