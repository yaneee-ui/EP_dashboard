"""마케팅 실적 현황 대시보드

위: EP 실적 (트래픽/거래액/구매객수/CR/객단가) — EP실적 데이터
아래: EP 채널 지표 (원부매칭율/최저가율 등) — 기존 EP 데이터, 원부매칭/최저가 필터 적용
"""
import streamlit as st
import pandas as pd
import datetime as _dt

from data_loader import load_data, load_traffic_data
from sidebar import render_sidebar
from filters import filter_by_combo
from kpi import render_kpi_cards
from charts import main_trend_data
from comparison_table import render_summary_table_html
from utils import (
    COL_DATE, COL_BPU, COL_MATCH, COL_LOWEST, METRIC_COLS, UNIT_CONFIG,
    resample_series, make_period_label, compute_kpi_deltas,
    format_value, format_delta_html,
)
from styles import CUSTOM_CSS

def _ref_str(val, is_pct=False):
    """비교 대상 실제 값을 괄호로 표시."""
    if val is None or pd.isna(val):
        return ""
    if is_pct:
        return f" <span style='color:#9ca3af'>({val:.1f}%)</span>"
    return f" <span style='color:#9ca3af'>({val:,.0f})</span>"


st.set_page_config(page_title="마케팅 실적 현황 대시보드", layout="wide", page_icon="📊")
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# --- 사이드바 ---
side = render_sidebar()
if side["refresh"]:
    load_data.clear()
    load_traffic_data.clear()

# --- 데이터 로드 ---
df_ep = load_data()           # 기존 EP 데이터 (원부매칭율 등)
df_traffic = load_traffic_data()  # EP실적 데이터 (트래픽/거래액 등)

# EP채널 업로드
if side["ep_channel_file"] is not None:
    _uf = side["ep_channel_file"]
    df_ep = load_data(uploaded_file=_uf, file_name=getattr(_uf, "name", None))
    st.sidebar.success("EP채널 데이터 업로드 완료")

# EP실적 업로드
if side["ep_traffic_file"] is not None:
    _tf = side["ep_traffic_file"]
    df_traffic = pd.read_csv(_tf)
    df_traffic["날짜"] = pd.to_datetime(df_traffic["날짜"])
    _tr_min = df_traffic["날짜"].min().strftime("%Y-%m-%d")
    _tr_max = df_traffic["날짜"].max().strftime("%Y-%m-%d")
    st.sidebar.success(f"EP실적 데이터 업로드 완료: {_tr_min} ~ {_tr_max}")

unit = side["view_unit"]

# 자사/입점 합산용 BPU 그룹 정의
BPU_GROUPS = {
    "자사": ["e-영업1", "e-영업2"],
    "입점": ["e-영업3", "e-영업4"],
}


def aggregate_traffic(df, bpus, member="전체"):
    """여러 BPU의 트래픽 데이터를 합산. CR/객단가는 재계산."""
    sub = df[(df["BPU"].isin(bpus)) & (df["회원구분"] == member)]
    if sub.empty:
        return sub
    agg = sub.groupby("날짜").agg({
        "트래픽": "sum", "거래액": "sum", "구매객수": "sum",
    }).reset_index()
    agg["CR"] = (agg["구매객수"] / agg["트래픽"] * 100).where(agg["트래픽"] > 0, 0)
    agg["객단가"] = (agg["거래액"] / agg["구매객수"]).where(agg["구매객수"] > 0, 0)
    agg["BPU"] = "+".join(bpus)
    agg["회원구분"] = member
    return agg


def aggregate_ep(df, bpus, match_status, lowest_status):
    """여러 BPU의 EP채널 데이터를 합산. 비율 지표는 재계산."""
    sub = df[(df[COL_BPU].isin(bpus)) & (df[COL_MATCH] == match_status) & (df[COL_LOWEST] == lowest_status)]
    if sub.empty:
        return sub
    # 합산 가능한 컬럼(수량) vs 재계산이 필요한 컬럼(비율) 분리
    sum_cols = [c for c in sub.columns if c not in [COL_DATE, COL_BPU, COL_MATCH, COL_LOWEST,
                "원부매칭율(%)", "최저가율(%)", "구매전환율(%)", "첫구매거래액(%)", "신규가입율", "첫구매 전환율(%)"]]
    agg = sub.groupby(COL_DATE)[sum_cols].sum().reset_index()
    # 비율 재계산
    if "평균 원부매칭 상품수" in agg.columns and "평균 EP 전시 상품수" in agg.columns:
        agg["원부매칭율(%)"] = (agg["평균 원부매칭 상품수"] / agg["평균 EP 전시 상품수"] * 100).where(agg["평균 EP 전시 상품수"] > 0, 0)
    if "평균 최저가 상품수" in agg.columns and "평균 EP 전시 상품수" in agg.columns:
        agg["최저가율(%)"] = (agg["평균 최저가 상품수"] / agg["평균 EP 전시 상품수"] * 100).where(agg["평균 EP 전시 상품수"] > 0, 0)
    if "평균 EP 고객수(총결제)" in agg.columns and "평균 EP UV" in agg.columns:
        agg["구매전환율(%)"] = (agg["평균 EP 고객수(총결제)"] / agg["평균 EP UV"] * 100).where(agg["평균 EP UV"] > 0, 0)
    if "평균 EP 첫구매 거래액(총결제)" in agg.columns and "평균 EP 거래액(총결제)" in agg.columns:
        agg["첫구매거래액(%)"] = (agg["평균 EP 첫구매 거래액(총결제)"] / agg["평균 EP 거래액(총결제)"] * 100).where(agg["평균 EP 거래액(총결제)"] > 0, 0)
    if "평균 EP 신규가입수" in agg.columns and "평균 EP UV" in agg.columns:
        agg["신규가입율"] = (agg["평균 EP 신규가입수"] / agg["평균 EP UV"] * 100).where(agg["평균 EP UV"] > 0, 0)
    if "평균 EP 첫구매 고객수(총결제)" in agg.columns and "평균 EP UV" in agg.columns:
        agg["첫구매 전환율(%)"] = (agg["평균 EP 첫구매 고객수(총결제)"] / agg["평균 EP UV"] * 100).where(agg["평균 EP UV"] > 0, 0)
    agg[COL_BPU] = "+".join(bpus)
    agg[COL_MATCH] = match_status
    agg[COL_LOWEST] = lowest_status
    return agg

# 데이터 반영 현황
last_date_ep = df_ep[COL_DATE].max()
last_date_tr = df_traffic["날짜"].max()
_weekday_kr = ["월", "화", "수", "목", "금", "토", "일"]
st.sidebar.info(
    f"🗓️ EP실적: ~{last_date_tr.strftime('%m/%d')}({_weekday_kr[last_date_tr.weekday()]})\n\n"
    f"EP채널: ~{last_date_ep.strftime('%m/%d')}({_weekday_kr[last_date_ep.weekday()]})"
)

# --- 페이지 헤더 ---
st.markdown("<div class='dash-header-title'>📊 실적 요약</div>", unsafe_allow_html=True)

# --- 매체 필터 + 기준 시점 ---
BPU_OPTIONS = [
    ("전체", "Total"),
    ("e-영업1", "e-영업1"),
    ("e-영업2", "e-영업2"),
    ("e-영업3", "e-영업3"),
    ("e-영업4", "e-영업4"),
    ("자사 (e1+e2)", "자사"),
    ("입점 (e3+e4)", "입점"),
]

fc1, fc2 = st.columns([2, 2])
with fc1:
    st.markdown("<div style='font-size:0.85rem;color:#6b7280;margin-bottom:2px;'>매체 필터</div>", unsafe_allow_html=True)
    _bpu_label_sel = st.selectbox(
        "매체 필터", [l for l, _ in BPU_OPTIONS],
        label_visibility="collapsed", key="bpu_filter",
    )
    bpu = dict(BPU_OPTIONS)[_bpu_label_sel]

# 기준 시점 옵션 (Total 트래픽 데이터 기준으로 생성 — 조회 단위에 맞는 기간 목록)
_tr_total_all = df_traffic[(df_traffic["BPU"] == "Total") & (df_traffic["회원구분"] == "전체")]
_period_s = _tr_total_all.set_index("날짜")["트래픽"].resample(UNIT_CONFIG[unit]["rule"]).mean().dropna()
if unit == "주별":
    _period_s.index = _period_s.index - pd.Timedelta(days=6)
if unit == "월마감":
    _last_tr_all = _tr_total_all["날짜"].max()
    if not _period_s.empty and _last_tr_all < _period_s.index[-1]:
        _period_s = _period_s.iloc[:-1]  # 미완성 달 제외

with fc2:
    _label2 = "기준 일자" if unit == "일별" else "기준 시점"
    st.markdown(f"<div style='font-size:0.85rem;color:#6b7280;margin-bottom:2px;'>{_label2}</div>", unsafe_allow_html=True)
    if unit == "일별":
        _min_d = _period_s.index.min().date()
        _max_d = _period_s.index.max().date()
        _sel_date = st.date_input(
            "기준 일자", value=_max_d, min_value=_min_d, max_value=_max_d,
            label_visibility="collapsed", key="period_filter_date",
        )
        selected_period_date = pd.Timestamp(_sel_date)
        if selected_period_date not in _period_s.index:
            _cand = _period_s.index[_period_s.index <= selected_period_date]
            selected_period_date = _cand[-1] if len(_cand) else _period_s.index[-1]
    else:
        _period_labels = [make_period_label(d, unit) for d in _period_s.index]
        _sel_label = st.selectbox(
            "기준 시점", _period_labels, index=len(_period_labels) - 1,
            label_visibility="collapsed", key="period_filter",
        )
        selected_period_date = _period_s.index[_period_labels.index(_sel_label)]

period_label = make_period_label(selected_period_date, unit)

st.markdown(
    f"<div class='dash-header-sub'>조회 단위: <b>{unit}</b> · 기준: <b>{period_label}</b></div>",
    unsafe_allow_html=True,
)

# ============================================================
# 상단: EP 실적 (트래픽/거래액/구매객수/CR/객단가)
# ============================================================
st.markdown("---")
st.markdown("### 📈 EP 실적")

# 세그먼트 필터 (고객 구분)
_seg_options = [s for s in ["전체", "회원", "비회원", "신규", "기존"] if s in df_traffic["회원구분"].unique()]
segment = st.radio("고객 구분", _seg_options, horizontal=True, key="seg_filter", label_visibility="collapsed")

# 트래픽 데이터 필터 (자사/입점이면 합산)
if bpu in BPU_GROUPS:
    tr_combo = aggregate_traffic(df_traffic, BPU_GROUPS[bpu], segment)
else:
    tr_combo = df_traffic[(df_traffic["BPU"] == bpu) & (df_traffic["회원구분"] == segment)].copy()

if tr_combo.empty:
    st.warning(f"{bpu}의 EP실적 데이터가 없습니다.")
else:
    # KPI 카드 (트래픽 지표 5개)
    TRAFFIC_METRICS = [
        ("트래픽", "EP UV"),
        ("거래액", "거래액(순결제)"),
        ("구매객수", "구매객수"),
        ("CR", "구매전환율(%)"),
        ("객단가", "객단가"),
    ]

    kpi_cols = st.columns(5)
    all_items = TRAFFIC_METRICS

    for i, (col_name, display_name) in enumerate(all_items):
        with kpi_cols[i]:
            s = tr_combo.set_index("날짜")[col_name].sort_index()
            series = s.resample(UNIT_CONFIG[unit]["rule"]).mean()
            if unit == "주별":
                series.index = series.index - pd.Timedelta(days=6)
            elif unit == "월마감":
                if not series.empty and s.index.max() < series.index[-1]:
                    series = series.iloc[:-1]
            # 월마감에서 특정 월 선택 시, 그 월까지로 자르기
            if not series.empty:
                series = series[series.index <= selected_period_date]

            stats = compute_kpi_deltas(series, unit)
            if stats:
                _is_pct = col_name == "CR"
                if _is_pct:
                    val_str = f"{stats['current']:.1f}%"
                elif col_name == "객단가":
                    val_str = f"{stats['current']:,.0f}"
                else:
                    val_str = f"{stats['current']:,.0f}"

                cfg = UNIT_CONFIG[unit]
                st.markdown(
                    f"<div style='background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:14px 16px;min-height:180px;'>"
                    f"<div style='color:#6b7280;font-size:0.8rem;margin-bottom:4px;'>{display_name}</div>"
                    f"<div style='font-size:1.5rem;font-weight:700;color:#111827;'>{val_str}</div>"
                    f"<div style='font-size:0.78rem;margin-top:6px;'>"
                    f"{cfg['prev_label']} {format_delta_html(stats['prev_delta'])}{_ref_str(stats.get('prev_value'), _is_pct)}<br/>"
                    f"{cfg['avg_label']} {format_delta_html(stats['avg_delta'])}{_ref_str(stats.get('avg_value'), _is_pct)}<br/>"
                    f"{cfg['yoy_label']} {format_delta_html(stats['yoy_delta'])}{_ref_str(stats.get('yoy_value'), _is_pct)}"
                    f"</div></div>",
                    unsafe_allow_html=True,
                )

    st.markdown("<br/>", unsafe_allow_html=True)

    # 지표 추이 차트 (트래픽 지표)
    h1, h2 = st.columns([2, 3])
    h1.markdown("**EP 실적 추이**")
    tr_metric_options = ["트래픽", "거래액", "구매객수", "CR", "객단가"]
    tr_metric = h2.selectbox("지표 선택", tr_metric_options, index=0, key="tr_metric", label_visibility="collapsed")

    # 리샘플 (전체 기간 — 전년 비교선용)
    s_raw = tr_combo.set_index("날짜")[tr_metric].sort_index()
    tr_full = s_raw.resample(UNIT_CONFIG[unit]["rule"]).mean()
    if unit == "주별":
        tr_full.index = tr_full.index - pd.Timedelta(days=6)
    elif unit == "월마감" and not tr_full.empty and s_raw.index.max() < tr_full.index[-1]:
        tr_full = tr_full.iloc[:-1]

    # 올해만 추출
    latest_year = int(tr_full.index.max().year)
    tr_series = tr_full[tr_full.index.year == latest_year]

    # 일별이면 최근 30일 + 기간 조정
    if unit == "일별":
        _default_start = max(tr_series.index.min().date(), tr_series.index.max().date() - _dt.timedelta(days=30))
        col_d, col_y = st.columns([4, 1])
        with col_d:
            dr = st.date_input("기간", value=(_default_start, tr_series.index.max().date()),
                               min_value=tr_series.index.min().date(), max_value=tr_series.index.max().date(),
                               key="tr_range")
        with col_y:
            show_tr_yoy = st.checkbox("전년 비교선 표시", value=True, key="tr_yoy")
        if isinstance(dr, tuple) and len(dr) == 2:
            tr_series = tr_series[(tr_series.index >= pd.Timestamp(dr[0])) & (tr_series.index <= pd.Timestamp(dr[1]))]
    else:
        col_sp, col_y = st.columns([5, 1])
        with col_y:
            show_tr_yoy = st.checkbox("전년 비교선 표시", value=True, key="tr_yoy")

    chart_df = pd.DataFrame({tr_metric: tr_series})

    # 전년 비교선 (동요일 364일 / 월마감은 1년)
    yoy_col_name = None
    if show_tr_yoy and not tr_series.empty:
        if unit == "월마감":
            prev_dates = tr_series.index - pd.DateOffset(years=1)
        else:
            prev_dates = tr_series.index - pd.Timedelta(days=364)
        yoy_vals = []
        for pd_date in prev_dates:
            if pd_date in tr_full.index:
                yoy_vals.append(tr_full.loc[pd_date])
            else:
                cand = tr_full.index[tr_full.index <= pd_date]
                yoy_vals.append(tr_full.loc[cand[-1]] if len(cand) else None)
        yoy_label = UNIT_CONFIG[unit]["yoy_label"]
        yoy_col_name = f"{yoy_label}(전년)"
        chart_df[yoy_col_name] = yoy_vals

    # 금년=진한 파랑, 전년=하늘색
    if yoy_col_name and show_tr_yoy:
        st.line_chart(chart_df, height=350, color=["#2563eb", "#7dd3fc"])
    else:
        st.line_chart(chart_df, height=350, color=["#2563eb"])

    _tr_start = tr_series.index.min().strftime('%Y-%m-%d')
    _tr_end = tr_series.index.max().strftime('%Y-%m-%d')
    _yoy_note = ""
    if show_tr_yoy and not tr_series.empty:
        _yoy_s = prev_dates[0].strftime('%Y-%m-%d')
        _yoy_e = prev_dates[-1].strftime('%Y-%m-%d')
        _yoy_note = f"<br/>전년 비교: {_yoy_s} ~ {_yoy_e} (동요일 기준)"
    st.markdown(
        f"<div class='chart-caption'>올해: {_tr_start} ~ {_tr_end}{_yoy_note}</div>",
        unsafe_allow_html=True,
    )

    st.markdown("<br/>", unsafe_allow_html=True)

    # 실적 요약 표 (트래픽 지표)
    st.markdown(f"**EP 실적 요약 표**  ·  <span style='color:#6b7280;font-size:0.85rem'>{bpu}</span>", unsafe_allow_html=True)
    body_rows = []
    prev_label = yoy_label = None
    for col_name, display_name in all_items:
        s = tr_combo.set_index("날짜")[col_name].sort_index()
        series = s.resample(UNIT_CONFIG[unit]["rule"]).mean()
        if unit == "주별":
            series.index = series.index - pd.Timedelta(days=6)
        elif unit == "월마감" and not series.empty and s.index.max() < series.index[-1]:
            series = series.iloc[:-1]
        if not series.empty:
            series = series[series.index <= selected_period_date]
        stats = compute_kpi_deltas(series, unit)
        if stats is None:
            body_rows.append(f"<tr><td>{display_name}</td><td>-</td><td>-</td><td>-</td></tr>")
            continue
        prev_label = stats["prev_label"]
        yoy_label = stats["yoy_label"]
        is_pct = col_name == "CR"
        val = f"{stats['current']:.1f}%" if is_pct else f"{stats['current']:,.0f}"
        body_rows.append(
            f"<tr><td class='m'>{display_name}</td><td class='v'>{val}</td>"
            f"<td class='d'>{format_delta_html(stats['prev_delta'])}</td>"
            f"<td class='d'>{format_delta_html(stats['yoy_delta'])}</td></tr>"
        )
    html = (
        "<table class='summary-table'>"
        f"<thead><tr><th>지표</th><th>값</th><th>{prev_label or '-'}</th><th>{yoy_label or '-'}</th></tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody></table>"
    )
    st.markdown(html, unsafe_allow_html=True)

    # --- 월마감일 때 누계 표시 ---
    if unit == "월마감" and not tr_combo.empty:
        latest_year = int(tr_combo["날짜"].max().year)
        # 선택 월이 있으면 그 월을 cutoff로, 없으면 마감 완료된 마지막 달
        _cutoff = selected_period_date
        _cutoff_month = _cutoff.month

        # 올해 누계 (1월 ~ 마감 월)
        ytd_cur = tr_combo[
            (tr_combo["날짜"] >= f"{latest_year}-01-01") &
            (tr_combo["날짜"] <= _cutoff)
        ]
        # 전년 동기간
        ytd_prev = tr_combo[
            (tr_combo["날짜"] >= f"{latest_year-1}-01-01") &
            (tr_combo["날짜"] <= f"{latest_year-1}-{_cutoff_month:02d}-{_cutoff.day:02d}")
        ]
        # 회원UV용

        st.markdown(f"<br/>", unsafe_allow_html=True)
        st.markdown(f"**📊 1~{_cutoff_month}월 누계**  ·  <span style='color:#6b7280;font-size:0.85rem'>전년 동기간 비교</span>", unsafe_allow_html=True)

        ytd_items = [
            ("트래픽", "EP UV", False),
            ("거래액", "거래액(순결제)", False),
            ("구매객수", "구매객수", False),
            ("_CR", "구매전환율(%)", True),
            ("_객단가", "객단가", False),
        ]

        ytd_rows = []
        for key, label, is_pct_ytd in ytd_items:
            if key == "_CR":
                c_val = ytd_cur["구매객수"].sum() / ytd_cur["트래픽"].sum() * 100 if ytd_cur["트래픽"].sum() > 0 else 0
                p_val = ytd_prev["구매객수"].sum() / ytd_prev["트래픽"].sum() * 100 if not ytd_prev.empty and ytd_prev["트래픽"].sum() > 0 else None
                c_str = f"{c_val:.1f}%"
                p_str = f"{p_val:.1f}%" if p_val else "-"
            elif key == "_객단가":
                c_val = ytd_cur["거래액"].sum() / ytd_cur["구매객수"].sum() if ytd_cur["구매객수"].sum() > 0 else 0
                p_val = ytd_prev["거래액"].sum() / ytd_prev["구매객수"].sum() if not ytd_prev.empty and ytd_prev["구매객수"].sum() > 0 else None
                c_str = f"{c_val:,.0f}"
                p_str = f"{p_val:,.0f}" if p_val else "-"

            else:
                c_val = ytd_cur[key].sum()
                p_val = ytd_prev[key].sum() if not ytd_prev.empty else None
                c_str = f"{c_val:,.0f}"
                p_str = f"{p_val:,.0f}" if p_val else "-"

            yoy_d = ((c_val / p_val) - 1) * 100 if p_val and p_val != 0 else None
            ytd_rows.append(
                f"<tr><td class='m'>{label}</td><td class='v'>{c_str}</td>"
                f"<td class='v'>{p_str}</td>"
                f"<td class='d'>{format_delta_html(yoy_d)}</td></tr>"
            )

        ytd_html = (
            "<table class='summary-table'>"
            f"<thead><tr><th>지표</th><th>{latest_year}년 누계</th>"
            f"<th>{latest_year-1}년 동기간</th><th>YoY</th></tr></thead>"
            f"<tbody>{''.join(ytd_rows)}</tbody></table>"
        )
        st.markdown(ytd_html, unsafe_allow_html=True)


# ============================================================
# 하단: EP 채널 지표 (원부매칭율/최저가율 등)
# ============================================================
st.markdown("---")
st.markdown("### 🏷️ EP 채널 지표")

# 원부매칭/최저가 필터
from utils import COL_MATCH, COL_LOWEST
c1, c2 = st.columns(2)
match_options = [v for v in ["Total", "매칭"] if v in df_ep[COL_MATCH].unique()]
lowest_options = [v for v in ["Total", "최저가"] if v in df_ep[COL_LOWEST].unique()]
match_status = c1.selectbox("원부매칭여부", match_options, index=0, key="ep_match")
lowest_status = c2.selectbox("최저가여부", lowest_options, index=0, key="ep_lowest")

if bpu in BPU_GROUPS:
    df_ep_combo = aggregate_ep(df_ep, BPU_GROUPS[bpu], match_status, lowest_status)
else:
    df_ep_combo = filter_by_combo(df_ep, bpu, match_status, lowest_status)

if df_ep_combo.empty:
    st.warning("선택한 조합에 데이터가 없습니다.")
else:
    # EP 채널 지표 KPI
    EP_CHANNEL_METRICS = [
        ("원부매칭율(%)", "원부매칭율(%)"),
        ("최저가율(%)", "최저가율(%)"),
        ("평균 EP 전시 상품수", "전시상품수"),
        ("평균 원부매칭 상품수", "원부매칭상품수"),
        ("평균 최저가 상품수", "최저가상품수"),
    ]

    ep_cols = st.columns(len(EP_CHANNEL_METRICS))
    for i, (metric_key, display_name) in enumerate(EP_CHANNEL_METRICS):
        with ep_cols[i]:
            series = resample_series(df_ep_combo, metric_key, unit).dropna()
            series = series[series.index <= selected_period_date]
            stats = compute_kpi_deltas(series, unit)
            if stats:
                _is_pct = "%" in metric_key or metric_key == "신규가입율"
                val_str = f"{stats['current']:.1f}%" if _is_pct else f"{stats['current']:,.0f}"
                cfg = UNIT_CONFIG[unit]
                st.markdown(
                    f"<div style='background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:14px 16px;min-height:180px;'>"
                    f"<div style='color:#6b7280;font-size:0.8rem;margin-bottom:4px;'>{display_name}</div>"
                    f"<div style='font-size:1.5rem;font-weight:700;color:#111827;'>{val_str}</div>"
                    f"<div style='font-size:0.78rem;margin-top:6px;'>"
                    f"{cfg['prev_label']} {format_delta_html(stats['prev_delta'])}{_ref_str(stats.get('prev_value'), _is_pct)}<br/>"
                    f"{cfg['avg_label']} {format_delta_html(stats['avg_delta'])}{_ref_str(stats.get('avg_value'), _is_pct)}<br/>"
                    f"{cfg['yoy_label']} {format_delta_html(stats['yoy_delta'])}{_ref_str(stats.get('yoy_value'), _is_pct)}"
                    f"</div></div>",
                    unsafe_allow_html=True,
                )

    st.markdown("<br/>", unsafe_allow_html=True)

    # EP 채널 지표 추이
    h1, h2 = st.columns([2, 3])
    h1.markdown("**EP 채널 추이**")
    ep_metrics_list = [m for m, _ in EP_CHANNEL_METRICS]
    ep_metric = h2.selectbox("지표", ep_metrics_list, index=0, key="ep_metric", label_visibility="collapsed")

    ep_trend, ep_yoy = main_trend_data(df_ep_combo, ep_metric, unit, show_yoy=True,
                                       current_year=int(last_date_ep.year),
                                       date_start=_dt.date(int(last_date_ep.year), 1, 1),
                                       date_end=last_date_ep.date())

    ep_cols = list(ep_trend.columns)
    if len(ep_cols) > 1:
        st.line_chart(ep_trend, height=350, color=["#2563eb", "#7dd3fc"])
    else:
        st.line_chart(ep_trend, height=350, color=["#2563eb"])

    st.markdown(
        f"<div class='chart-caption'>EP채널 데이터 · {bpu} / {match_status} / {lowest_status} 기준 · 전년 비교선(동요일) 포함</div>",
        unsafe_allow_html=True,
    )

    st.markdown("<br/>", unsafe_allow_html=True)

    # --- EP 채널 요약 표 (EP실적 요약표와 동일 스타일 · 동일 비교 기준) ---
    st.markdown(f"**EP 채널 요약 표**  ·  <span style='color:#6b7280;font-size:0.85rem'>{bpu} / {match_status} / {lowest_status}</span>", unsafe_allow_html=True)

    ep_body_rows = []
    ep_prev_label = ep_yoy_label = None
    for metric_key, display_name in EP_CHANNEL_METRICS:
        series = resample_series(df_ep_combo, metric_key, unit)
        series = series[series.index <= selected_period_date] if not series.empty else series
        stats = compute_kpi_deltas(series, unit)
        if stats is None:
            ep_body_rows.append(f"<tr><td>{display_name}</td><td>-</td><td>-</td><td>-</td></tr>")
            continue
        ep_prev_label = stats["prev_label"]
        ep_yoy_label = stats["yoy_label"]
        _is_pct = "%" in metric_key or metric_key == "신규가입율"
        val = f"{stats['current']:.1f}%" if _is_pct else f"{stats['current']:,.0f}"
        ep_body_rows.append(
            f"<tr><td class='m'>{display_name}</td><td class='v'>{val}</td>"
            f"<td class='d'>{format_delta_html(stats['prev_delta'])}</td>"
            f"<td class='d'>{format_delta_html(stats['yoy_delta'])}</td></tr>"
        )
    ep_summary_html = (
        "<table class='summary-table'>"
        f"<thead><tr><th>지표</th><th>값</th><th>{ep_prev_label or '-'}</th><th>{ep_yoy_label or '-'}</th></tr></thead>"
        f"<tbody>{''.join(ep_body_rows)}</tbody></table>"
    )
    st.markdown(ep_summary_html, unsafe_allow_html=True)
