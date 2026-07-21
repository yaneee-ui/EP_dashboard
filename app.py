"""마케팅 실적 현황 대시보드

위: EP 실적 (트래픽/거래액/구매객수/CR/객단가) — EP실적 데이터
아래: EP 채널 지표 (원부매칭율/최저가율 등) — 기존 EP 데이터, 원부매칭/최저가 필터 적용
"""
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import datetime as _dt

from data_loader import load_data, load_traffic_data, load_category_data, load_brand_names
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
    load_category_data.clear()

# --- 데이터 로드 ---
df_ep = load_data()           # 기존 EP 데이터 (원부매칭율 등)
df_traffic = load_traffic_data()  # EP실적 데이터 (트래픽/거래액 등)
df_category = load_category_data()  # 카테고리/브랜드별 실적 데이터
BRAND_NAMES = load_brand_names()  # 브랜드 코드 -> 한글 브랜드명


def brand_label(code):
    """브랜드 코드를 '코드 (브랜드명)' 형태로 표시. '전체'는 그대로."""
    if code == "전체" or code not in BRAND_NAMES:
        return code
    return f"{code} ({BRAND_NAMES[code]})"


BRAND_LABELS = {code: brand_label(code) for code in BRAND_NAMES}  # 랭킹 차트용 "코드 (이름)" 매핑

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

# 카테고리 업로드
if side["ep_category_file"] is not None:
    _cf = side["ep_category_file"]
    df_category = pd.read_csv(_cf)
    df_category["날짜"] = pd.to_datetime(df_category["날짜"])
    st.sidebar.success(f"카테고리 데이터 업로드 완료 ({df_category['카테고리'].nunique()}개 카테고리)")


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


def render_bpu_comparison_table(df_traffic):
    """사업부별(Total/e-영업1~4/자사/입점) 실적 비교표.
    지표 5개(EP UV/거래액/구매객수/구매전환율/객단가) x 각각 [값/전일비/전주평균비/전년동요일비]."""
    BPU_COLS = ["Total", "e-영업1", "e-영업2", "e-영업3", "e-영업4", "자사", "입점"]
    METRICS = [
        ("트래픽", "EP UV", False),
        ("거래액", "거래액(순결제)", False),
        ("구매객수", "구매객수", False),
        ("CR", "구매전환율(%)", True),
        ("객단가", "객단가", False),
    ]

    def _series_for(bpu_key, metric):
        if bpu_key in BPU_GROUPS:
            sub = aggregate_traffic(df_traffic, BPU_GROUPS[bpu_key], "전체")
        else:
            sub = df_traffic[(df_traffic["BPU"] == bpu_key) & (df_traffic["회원구분"] == "전체")]
        if sub.empty:
            return pd.Series(dtype="float64")
        return sub.set_index("날짜")[metric].sort_index().resample("D").mean()

    for metric_key, metric_label, is_pct in METRICS:
        header_html = "<th>구분</th>" + "".join(f"<th>{b}</th>" for b in BPU_COLS)
        row_val, row_prev, row_avg, row_yoy = [], [], [], []
        for bpu_key in BPU_COLS:
            series = _series_for(bpu_key, metric_key)
            stats = compute_kpi_deltas(series, "일별")
            if stats is None:
                row_val.append("<td>-</td>")
                row_prev.append("<td>-</td>")
                row_avg.append("<td>-</td>")
                row_yoy.append("<td>-</td>")
                continue
            val_str = f"{stats['current']:.1f}%" if is_pct else f"{stats['current']:,.0f}"
            row_val.append(f"<td class='v'>{val_str}</td>")
            row_prev.append(f"<td class='d'>{format_delta_html(stats['prev_delta'])}</td>")
            row_avg.append(f"<td class='d'>{format_delta_html(stats['avg_delta'])}</td>")
            row_yoy.append(f"<td class='d'>{format_delta_html(stats['yoy_delta'])}</td>")

        table_html = (
            "<table class='summary-table' style='margin-bottom:14px;'>"
            f"<thead><tr><th colspan='{len(BPU_COLS)+1}' style='background:#eef2ff;color:#374151;font-weight:700;'>{metric_label}</th></tr>"
            f"<tr>{header_html}</tr></thead>"
            "<tbody>"
            f"<tr><td class='m'>값</td>{''.join(row_val)}</tr>"
            f"<tr><td class='m'>전일비</td>{''.join(row_prev)}</tr>"
            f"<tr><td class='m'>전주평균비</td>{''.join(row_avg)}</tr>"
            f"<tr><td class='m'>전년동요일비</td>{''.join(row_yoy)}</tr>"
            "</tbody></table>"
        )
        st.markdown(table_html, unsafe_allow_html=True)


def render_revenue_ranking(sub_df, group_col, unit, selected_period_date, title, subtitle, label_map=None):
    """group_col(카테고리 또는 브랜드) 기준 거래액 랭킹을 올해/작년 이중 막대로 렌더링.
    label_map이 주어지면 표시 라벨을 매핑해서 보여준다 (예: 브랜드코드 -> 브랜드명)."""
    rows = []
    for name in sorted(sub_df[group_col].unique()):
        s_full = sub_df[sub_df[group_col] == name].set_index("날짜")["거래액"].sort_index()
        series_full = s_full.resample(UNIT_CONFIG[unit]["rule"]).mean()
        if unit == "주별":
            series_full.index = series_full.index - pd.Timedelta(days=6)
        elif unit == "월마감" and not series_full.empty and s_full.index.max() < series_full.index[-1]:
            series_full = series_full.iloc[:-1]
        series = series_full[series_full.index <= selected_period_date] if not series_full.empty else series_full
        if series.empty:
            continue
        cur_val = series.iloc[-1]
        cur_date = series.index[-1]

        if unit == "월마감":
            prev_date = cur_date - pd.DateOffset(years=1)
        else:
            prev_date = cur_date - pd.Timedelta(days=364)
        if prev_date in series_full.index:
            prev_val = series_full.loc[prev_date]
        else:
            cand = series_full.index[series_full.index <= prev_date]
            prev_val = series_full.loc[cand[-1]] if len(cand) else None

        rows.append({group_col: name, "거래액": cur_val, "전년거래액": prev_val})

    st.markdown(f"**{title}**  ·  <span style='color:#6b7280;font-size:0.85rem'>{subtitle}</span>", unsafe_allow_html=True)

    if not rows:
        st.info("해당 조건에 데이터가 없습니다.")
        return

    share_df = pd.DataFrame(rows).sort_values("거래액", ascending=False).reset_index(drop=True)
    _total_gmv = share_df["거래액"].sum()
    share_df["비중"] = (share_df["거래액"] / _total_gmv * 100) if _total_gmv > 0 else 0
    _max_gmv = max(
        share_df["거래액"].max() if not share_df.empty else 1,
        share_df["전년거래액"].max(skipna=True) if share_df["전년거래액"].notna().any() else 0,
        1,
    )
    _yoy_label_share = UNIT_CONFIG[unit]["yoy_label"]

    bar_rows_html = []
    for _, r in share_df.iterrows():
        _pct_width = max(0, (r["거래액"] / _max_gmv * 100)) if _max_gmv > 0 else 0
        _has_prev = pd.notna(r["전년거래액"])
        _prev_pct_width = max(0, (r["전년거래액"] / _max_gmv * 100)) if _has_prev and _max_gmv > 0 else 0
        _yoy_delta = ((r["거래액"] / r["전년거래액"]) - 1) * 100 if _has_prev and r["전년거래액"] != 0 else None
        _prev_val_str = f"{r['전년거래액']:,.0f}" if _has_prev else "-"

        _raw_label = r[group_col]
        _display_label = label_map.get(_raw_label, _raw_label) if label_map else _raw_label
        _label_width = 190 if label_map else 80

        bar_rows_html.append(
            "<div style='margin-bottom:12px;'>"
            "<div style='display:flex;align-items:center;margin-bottom:3px;'>"
            f"<div style='width:{_label_width}px;flex-shrink:0;font-size:0.8rem;color:#374151;font-weight:600;'>{_display_label}</div>"
            "<div style='flex:1;background:#f1f2f4;border-radius:4px;height:20px;margin:0 10px;position:relative;'>"
            f"<div style='width:{_pct_width:.1f}%;background:#2563eb;height:100%;border-radius:4px;'></div>"
            "</div>"
            f"<div style='width:190px;flex-shrink:0;text-align:right;font-size:0.82rem;color:#374151;'>"
            f"{r['거래액']:,.0f} <span style='color:#9ca3af'>({r['비중']:.1f}%)</span></div>"
            "</div>"
            "<div style='display:flex;align-items:center;'>"
            f"<div style='width:{_label_width}px;flex-shrink:0;'></div>"
            "<div style='flex:1;background:#f1f2f4;border-radius:4px;height:14px;margin:0 10px;position:relative;'>"
            f"<div style='width:{_prev_pct_width:.1f}%;background:#7dd3fc;height:100%;border-radius:4px;'></div>"
            "</div>"
            f"<div style='width:190px;flex-shrink:0;text-align:right;font-size:0.76rem;color:#9ca3af;'>"
            f"{_prev_val_str}{f' · {_yoy_label_share} ' + format_delta_html(_yoy_delta) if _yoy_delta is not None else ''}</div>"
            "</div>"
            "</div>"
        )
    st.markdown(
        "<div style='background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:16px 20px;'>"
        "<div style='display:flex;gap:14px;margin-bottom:10px;font-size:0.76rem;color:#6b7280;'>"
        "<span><span style='display:inline-block;width:10px;height:10px;background:#2563eb;border-radius:2px;margin-right:4px;'></span>올해</span>"
        "<span><span style='display:inline-block;width:10px;height:10px;background:#7dd3fc;border-radius:2px;margin-right:4px;'></span>작년(동시점)</span>"
        "</div>"
        + "".join(bar_rows_html) +
        "</div>",
        unsafe_allow_html=True,
    )

# 데이터 반영 현황
last_date_ep = df_ep[COL_DATE].max()
last_date_tr = df_traffic["날짜"].max()
_weekday_kr = ["월", "화", "수", "목", "금", "토", "일"]
st.sidebar.info(
    f"🗓️ EP실적: ~{last_date_tr.strftime('%m/%d')}({_weekday_kr[last_date_tr.weekday()]})\n\n"
    f"EP채널: ~{last_date_ep.strftime('%m/%d')}({_weekday_kr[last_date_ep.weekday()]})"
)

# --- 페이지 헤더 + 매체 필터 + 기준 시점 (스크롤 시 상단 고정) ---
_sticky = st.container(key="sticky_header")
_page_num = side["page"].split(".")[0]

with _sticky:
    # 고정 대상 식별용 마커 (반드시 이 컨테이너의 첫 요소여야 함)
    st.markdown("<div id='sticky-marker-anchor'></div>", unsafe_allow_html=True)

    BPU_OPTIONS = [
        ("전체", "Total"),
        ("e-영업1", "e-영업1"),
        ("e-영업2", "e-영업2"),
        ("e-영업3", "e-영업3"),
        ("e-영업4", "e-영업4"),
        ("자사 (e1+e2)", "자사"),
        ("입점 (e3+e4)", "입점"),
    ]

    _page_titles = {
        "1": "📊 실적 요약", "2": "🗂️ 카테고리 실적 요약",
        "3": "📋 누적 데이터", "4": "📋 누적 데이터 (카테고리)",
    }

    # ========================================================
    # 페이지 1 / 2: 매체필터 + 기준시점 (+카테고리/브랜드)
    # ========================================================
    if _page_num in ("1", "2"):
        # 기준 시점 옵션 (Total 트래픽 데이터 기준으로 생성 — 조회 단위에 맞는 기간 목록)
        _tr_total_all = df_traffic[(df_traffic["BPU"] == "Total") & (df_traffic["회원구분"] == "전체")]
        _period_s = _tr_total_all.set_index("날짜")["트래픽"].resample(UNIT_CONFIG[unit]["rule"]).mean().dropna()
        if unit == "주별":
            _period_s.index = _period_s.index - pd.Timedelta(days=6)
        if unit == "월마감":
            _last_tr_all = _tr_total_all["날짜"].max()
            if not _period_s.empty and _last_tr_all < _period_s.index[-1]:
                _period_s = _period_s.iloc[:-1]  # 미완성 달 제외

        if unit == "일별":
            _min_d = _period_s.index.min().date()
            _max_d = _period_s.index.max().date()
        else:
            _period_labels = [make_period_label(d, unit) for d in _period_s.index]

        # 위젯 렌더 전, 세션 상태로 현재 선택값을 미리 파악해 제목 옆에 표시
        if unit == "일별":
            _prev_date = st.session_state.get("period_filter_date", _max_d)
            try:
                _period_label_preview = make_period_label(pd.Timestamp(_prev_date), unit)
            except Exception:
                _period_label_preview = make_period_label(pd.Timestamp(_max_d), unit)
        else:
            _default_label = _period_labels[-1] if _period_labels else ""
            _prev_label_sel = st.session_state.get("period_filter", _default_label)
            _period_label_preview = _prev_label_sel if _prev_label_sel in _period_labels else _default_label

        st.markdown(
            f"<div style='display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin-bottom:6px;'>"
            f"<span style='font-size:1.15rem;font-weight:700;'>{_page_titles[_page_num]}</span>"
            f"<span style='font-size:0.8rem;color:#6b7280;'>조회 단위: <b>{unit}</b> · 기준: <b>{_period_label_preview}</b></span>"
            f"</div>",
            unsafe_allow_html=True,
        )

        _is_cat_page = _page_num == "2"
        if _is_cat_page:
            fc1, fc2, fc3, fc4, _fc_spacer = st.columns([1, 1, 1, 1, 6])
        else:
            fc1, fc2, _fc_spacer = st.columns([1, 1, 8])

        with fc1:
            st.markdown("<div style='font-size:0.78rem;color:#6b7280;margin-bottom:1px;'>매체 필터</div>", unsafe_allow_html=True)
            _bpu_label_sel = st.selectbox(
                "매체 필터", [l for l, _ in BPU_OPTIONS],
                label_visibility="collapsed", key="bpu_filter",
            )
            bpu = dict(BPU_OPTIONS)[_bpu_label_sel]

        with fc2:
            _label2 = "기준 일자" if unit == "일별" else "기준 시점"
            st.markdown(f"<div style='font-size:0.78rem;color:#6b7280;margin-bottom:1px;'>{_label2}</div>", unsafe_allow_html=True)
            if unit == "일별":
                _sel_date = st.date_input(
                    "기준 일자", value=_max_d, min_value=_min_d, max_value=_max_d,
                    label_visibility="collapsed", key="period_filter_date",
                )
                selected_period_date = pd.Timestamp(_sel_date)
                if selected_period_date not in _period_s.index:
                    _cand = _period_s.index[_period_s.index <= selected_period_date]
                    selected_period_date = _cand[-1] if len(_cand) else _period_s.index[-1]
            else:
                _sel_label = st.selectbox(
                    "기준 시점", _period_labels, index=len(_period_labels) - 1,
                    label_visibility="collapsed", key="period_filter",
                )
                selected_period_date = _period_s.index[_period_labels.index(_sel_label)]

        # 카테고리 페이지일 때만 매체필터 옆에 카테고리/브랜드 필터 노출
        selected_cat, selected_brand = "전체", "전체"
        if _is_cat_page and not df_category.empty:
            # 매체필터(bpu) 기준으로 데이터 범위 결정 (자사/입점은 합산)
            if bpu in BPU_GROUPS:
                _cat_bpu_df_preview = df_category[df_category["BPU"].isin(BPU_GROUPS[bpu])]
            elif bpu == "Total":
                _cat_bpu_df_preview = df_category
            else:
                _cat_bpu_df_preview = df_category[df_category["BPU"] == bpu]

            with fc3:
                st.markdown("<div style='font-size:0.78rem;color:#6b7280;margin-bottom:1px;'>카테고리</div>", unsafe_allow_html=True)
                _valid_cats_top = (
                    _cat_bpu_df_preview.dropna(subset=["트래픽", "거래액", "구매객수"], how="all")
                    .loc[lambda d: (d["트래픽"] > 0) | (d["거래액"] > 0) | (d["구매객수"] > 0), "카테고리"]
                    .unique()
                )
                _cat_options_top = ["전체"] + sorted([c for c in _valid_cats_top if c != "전체"])
                selected_cat = st.selectbox("카테고리", _cat_options_top, index=0, label_visibility="collapsed", key="cat_select")

            with fc4:
                st.markdown("<div style='font-size:0.78rem;color:#6b7280;margin-bottom:1px;'>브랜드</div>", unsafe_allow_html=True)
                _cat_filtered_top = _cat_bpu_df_preview[_cat_bpu_df_preview["카테고리"] == selected_cat]
                _valid_brands_top = (
                    _cat_filtered_top.dropna(subset=["트래픽", "거래액", "구매객수"], how="all")
                    .loc[lambda d: (d["트래픽"] > 0) | (d["거래액"] > 0) | (d["구매객수"] > 0), "브랜드"]
                    .unique()
                )
                _brand_options_top = ["전체"] + sorted([b for b in _valid_brands_top if b != "전체"])
                selected_brand = st.selectbox("브랜드", _brand_options_top, index=0, format_func=brand_label, label_visibility="collapsed", key="brand_select")

        period_label = make_period_label(selected_period_date, unit)

    # ========================================================
    # 페이지 3 / 4: 매체필터 + 기간유형 + 시작일/종료일 (+카테고리/브랜드)
    # ========================================================
    else:
        CUM_UNIT_OPTIONS = [("일자별", "일별"), ("주차별", "주별"), ("월별", "월별"), ("월마감", "월마감")]

        _cum_bpu_prev = st.session_state.get("cum_bpu_filter", "전체")
        _cum_unit_prev = st.session_state.get("cum_unit_filter", "일자별")
        st.markdown(
            f"<div style='display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin-bottom:6px;'>"
            f"<span style='font-size:1.15rem;font-weight:700;'>{_page_titles[_page_num]}</span>"
            f"<span style='font-size:0.8rem;color:#6b7280;'>매체: <b>{_cum_bpu_prev}</b> · 기간유형: <b>{_cum_unit_prev}</b></span>"
            f"</div>",
            unsafe_allow_html=True,
        )

        _is_cum_cat_page = _page_num == "4"
        gc1, gc2, gc3, gc4, _gc_spacer = st.columns([1, 1, 1, 1, 4])

        with gc1:
            st.markdown("<div style='font-size:0.78rem;color:#6b7280;margin-bottom:1px;'>매체</div>", unsafe_allow_html=True)
            _cum_bpu_label = st.selectbox(
                "매체", [l for l, _ in BPU_OPTIONS],
                label_visibility="collapsed", key="cum_bpu_filter",
            )
            bpu = dict(BPU_OPTIONS)[_cum_bpu_label]

        with gc2:
            st.markdown("<div style='font-size:0.78rem;color:#6b7280;margin-bottom:1px;'>기간 유형</div>", unsafe_allow_html=True)
            _cum_unit_label = st.selectbox(
                "기간 유형", [l for l, _ in CUM_UNIT_OPTIONS],
                label_visibility="collapsed", key="cum_unit_filter",
            )
            cum_unit = dict(CUM_UNIT_OPTIONS)[_cum_unit_label]

        # 데이터 있는 전체 날짜 범위 (트래픽 데이터 기준)
        _cum_min_d = df_traffic["날짜"].min().date()
        _cum_max_d = df_traffic["날짜"].max().date()

        with gc3:
            st.markdown("<div style='font-size:0.78rem;color:#6b7280;margin-bottom:1px;'>시작일</div>", unsafe_allow_html=True)
            cum_start = st.date_input(
                "시작일", value=_cum_min_d, min_value=_cum_min_d, max_value=_cum_max_d,
                label_visibility="collapsed", key="cum_start_date",
            )
        with gc4:
            st.markdown("<div style='font-size:0.78rem;color:#6b7280;margin-bottom:1px;'>종료일</div>", unsafe_allow_html=True)
            cum_end = st.date_input(
                "종료일", value=_cum_max_d, min_value=_cum_min_d, max_value=_cum_max_d,
                label_visibility="collapsed", key="cum_end_date",
            )

        # 카테고리 페이지(4번)는 둘째 줄에 카테고리/브랜드 필터 추가
        selected_cat, selected_brand = "전체", "전체"
        if _is_cum_cat_page and not df_category.empty:
            if bpu in BPU_GROUPS:
                _cat_bpu_df_preview = df_category[df_category["BPU"].isin(BPU_GROUPS[bpu])]
            elif bpu == "Total":
                _cat_bpu_df_preview = df_category
            else:
                _cat_bpu_df_preview = df_category[df_category["BPU"] == bpu]

            st.markdown("<div style='margin-top:8px;'></div>", unsafe_allow_html=True)
            gc5, gc6, _gc_spacer2 = st.columns([1, 1, 8])

            with gc5:
                st.markdown("<div style='font-size:0.78rem;color:#6b7280;margin-bottom:1px;'>카테고리</div>", unsafe_allow_html=True)
                _valid_cats_top = (
                    _cat_bpu_df_preview.dropna(subset=["트래픽", "거래액", "구매객수"], how="all")
                    .loc[lambda d: (d["트래픽"] > 0) | (d["거래액"] > 0) | (d["구매객수"] > 0), "카테고리"]
                    .unique()
                )
                _cat_options_top = ["전체"] + sorted([c for c in _valid_cats_top if c != "전체"])
                selected_cat = st.selectbox("카테고리", _cat_options_top, index=0, label_visibility="collapsed", key="cat_select")

            with gc6:
                st.markdown("<div style='font-size:0.78rem;color:#6b7280;margin-bottom:1px;'>브랜드</div>", unsafe_allow_html=True)
                _cat_filtered_top = _cat_bpu_df_preview[_cat_bpu_df_preview["카테고리"] == selected_cat]
                _valid_brands_top = (
                    _cat_filtered_top.dropna(subset=["트래픽", "거래액", "구매객수"], how="all")
                    .loc[lambda d: (d["트래픽"] > 0) | (d["거래액"] > 0) | (d["구매객수"] > 0), "브랜드"]
                    .unique()
                )
                _brand_options_top = ["전체"] + sorted([b for b in _valid_brands_top if b != "전체"])
                selected_brand = st.selectbox("브랜드", _brand_options_top, index=0, format_func=brand_label, label_visibility="collapsed", key="brand_select")

# 필터 영역 상단 고정(fixed) CSS — position:fixed는 스크롤 컨테이너 구조와 무관하게 항상 화면에 고정됨
st.markdown(
    """
    <style>
    /* 방법 1: container key 클래스 직접 타겟팅 */
    .st-key-sticky_header {
        position: fixed !important;
        top: 3.7rem !important;
        left: 22rem !important;
        right: 2rem !important;
        z-index: 999 !important;
        background: #f7f8fa !important;
        padding: 6px 16px 8px 16px !important;
        border-bottom: 1px solid #e5e7eb !important;
        box-shadow: 0 2px 6px rgba(0,0,0,0.06) !important;
    }
    /* 방법 2: 마커 기반 :has() 셀렉터 (백업) */
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="element-container"] > div#sticky-marker-anchor) {
        position: fixed !important;
        top: 3.7rem !important;
        left: 22rem !important;
        right: 2rem !important;
        z-index: 999 !important;
        background: #f7f8fa !important;
        padding: 6px 16px 8px 16px !important;
        border-bottom: 1px solid #e5e7eb !important;
        box-shadow: 0 2px 6px rgba(0,0,0,0.06) !important;
    }
    /* Streamlit 자체 상단 툴바(Share/GitHub 등)는 항상 최상단에 보이도록 z-index 우선 */
    header[data-testid="stHeader"] {
        z-index: 1000 !important;
    }
    /* 고정 영역 내부 위젯(selectbox/date_input) 상하 여백 축소 + 폭 제한(잘림 방지) */
    .st-key-sticky_header div[data-testid="stSelectbox"],
    .st-key-sticky_header div[data-testid="stDateInput"] {
        margin-bottom: -6px !important;
        max-width: 260px !important;
    }
    .st-key-sticky_header div[data-testid="stSelectbox"] > div,
    .st-key-sticky_header div[data-testid="stDateInput"] > div {
        max-width: 260px !important;
    }
    .st-key-sticky_header div[data-testid="element-container"] {
        margin-bottom: 0 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# 고정된 필터 영역이 차지하던 자리만큼, 아래 콘텐츠가 가려지지 않도록 여백 확보
_spacer_height = 120 if _page_num == "4" else 65
st.markdown(
    f"<div style='height:{_spacer_height}px;'></div>"
    "<div id='content-align-marker' style='height:0;'></div>",
    unsafe_allow_html=True,
)

# 사이드바 접힘/펼침/크기조정에 맞춰 고정 영역의 좌우 위치를 아래 콘텐츠와 정확히 일치시킴
components.html(
    """
    <script>
    function adjustStickyPosition() {
        try {
            const doc = window.parent.document;
            const marker = doc.querySelector('#content-align-marker');
            const stickyEls = doc.querySelectorAll('.st-key-sticky_header');
            if (marker && stickyEls.length) {
                const rect = marker.getBoundingClientRect();
                const rightPx = window.parent.innerWidth - rect.right;
                const PAD = 16; // 고정 영역 자체의 좌우 padding(px)과 동일한 값
                stickyEls.forEach(function(el) {
                    el.style.setProperty('left', (rect.left - PAD) + 'px', 'important');
                    el.style.setProperty('right', (rightPx - PAD) + 'px', 'important');
                });
            }
        } catch (e) {}
    }
    adjustStickyPosition();
    try {
        const obs = new MutationObserver(adjustStickyPosition);
        obs.observe(window.parent.document.body, {attributes: true, subtree: true, attributeFilter: ['style', 'class']});
        window.parent.addEventListener('resize', adjustStickyPosition);
    } catch (e) {}
    setInterval(adjustStickyPosition, 400); // 안전망: 주기적 재계산
    </script>
    """,
    height=0,
)



if side["page"].startswith("1"):
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

        st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

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

        st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

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

        st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

        # EP 채널 지표 추이
        h1, h2 = st.columns([2, 3])
        h1.markdown("**EP 채널 추이**")
        ep_metrics_list = [m for m, _ in EP_CHANNEL_METRICS]
        ep_metric = h2.selectbox("지표", ep_metrics_list, index=0, key="ep_metric", label_visibility="collapsed")

        _ep_latest_year = int(last_date_ep.year)
        if unit == "일별":
            _ep_max_d = last_date_ep.date()
            _ep_min_d = _dt.date(_ep_latest_year, 1, 1)
            _ep_default_start = max(_ep_min_d, _ep_max_d - _dt.timedelta(days=30))
            col_ed, col_ey = st.columns([4, 1])
            with col_ed:
                ep_dr = st.date_input(
                    "기간", value=(_ep_default_start, _ep_max_d),
                    min_value=_ep_min_d, max_value=_ep_max_d, key="ep_range",
                )
            with col_ey:
                show_ep_yoy = st.checkbox("전년 비교선 표시", value=True, key="ep_yoy_cb")
            if isinstance(ep_dr, tuple) and len(ep_dr) == 2:
                _ep_date_start, _ep_date_end = ep_dr
            else:
                _ep_date_start, _ep_date_end = _ep_default_start, _ep_max_d
        else:
            col_esp, col_ey = st.columns([5, 1])
            with col_ey:
                show_ep_yoy = st.checkbox("전년 비교선 표시", value=True, key="ep_yoy_cb")
            _ep_date_start = _dt.date(_ep_latest_year, 1, 1)
            _ep_date_end = last_date_ep.date()

        ep_trend, ep_yoy = main_trend_data(df_ep_combo, ep_metric, unit, show_yoy=show_ep_yoy,
                                           current_year=_ep_latest_year,
                                           date_start=_ep_date_start,
                                           date_end=_ep_date_end)

        ep_cols = list(ep_trend.columns)
        if len(ep_cols) > 1:
            st.line_chart(ep_trend, height=350, color=["#2563eb", "#7dd3fc"])
        else:
            st.line_chart(ep_trend, height=350, color=["#2563eb"])

        st.markdown(
            f"<div class='chart-caption'>EP채널 데이터 · {bpu} / {match_status} / {lowest_status} 기준"
            f"{' · 전년 비교선(동요일) 포함' if show_ep_yoy else ''}</div>",
            unsafe_allow_html=True,
        )

        st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

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

    st.markdown("---")
    st.markdown("### 🏢 사업부별 실적 비교", unsafe_allow_html=True)
    st.markdown(
        "<div class='chart-caption'>Total / e-영업1~4 / 자사 / 입점 · 일별 기준 · 값·전일비·전주평균비·전년동요일비</div>",
        unsafe_allow_html=True,
    )
    render_bpu_comparison_table(df_traffic)


if side["page"].startswith("2"):
    # ============================================================
    # 카테고리별 실적 (카테고리 → 브랜드 드릴다운, 전년비교 가능)
    # ============================================================
    st.markdown("---")
    st.markdown("### 🗂️ 카테고리별 실적")

    if df_category.empty:
        st.info("카테고리 데이터가 없습니다. 사이드바에서 ep_category.csv를 업로드해주세요.")
    else:
        # 매체필터(bpu)에 맞춰 카테고리 데이터 필터링 (자사/입점은 합산)
        if bpu in BPU_GROUPS:
            cat_bpu_df = df_category[df_category["BPU"].isin(BPU_GROUPS[bpu])]
        elif bpu == "Total":
            cat_bpu_df = df_category  # 전체 BPU 합산은 아래에서 groupby로 처리
        else:
            cat_bpu_df = df_category[df_category["BPU"] == bpu]

        cat_combo = cat_bpu_df[(cat_bpu_df["카테고리"] == selected_cat) & (cat_bpu_df["브랜드"] == selected_brand)]
        if bpu == "Total" and not cat_combo.empty:
            cat_combo = cat_combo.groupby("날짜", as_index=False).agg({"트래픽": "sum", "거래액": "sum", "구매객수": "sum"})
            cat_combo["CR"] = (cat_combo["구매객수"] / cat_combo["트래픽"] * 100).where(cat_combo["트래픽"] > 0, 0)
            cat_combo["객단가"] = (cat_combo["거래액"] / cat_combo["구매객수"]).where(cat_combo["구매객수"] > 0, 0)

        if cat_combo.empty:
            st.warning(f"{selected_cat} / {brand_label(selected_brand)} 조합에 데이터가 없습니다.")
        else:
            st.markdown(
                f"<div class='chart-caption'>{bpu} · <b>{selected_cat}</b> / <b>{brand_label(selected_brand)}</b> 기준</div>",
                unsafe_allow_html=True,
            )

            # --- KPI 카드 ---
            CAT_METRICS = [
                ("트래픽", "UV"),
                ("거래액", "거래액"),
                ("구매객수", "구매객수"),
                ("CR", "구매전환율(%)"),
                ("객단가", "객단가"),
            ]
            cat_cols = st.columns(5)
            for i, (col_name, display_name) in enumerate(CAT_METRICS):
                with cat_cols[i]:
                    s = cat_combo.set_index("날짜")[col_name].sort_index()
                    series = s.resample(UNIT_CONFIG[unit]["rule"]).mean()
                    if unit == "주별":
                        series.index = series.index - pd.Timedelta(days=6)
                    elif unit == "월마감" and not series.empty and s.index.max() < series.index[-1]:
                        series = series.iloc[:-1]
                    series = series[series.index <= selected_period_date] if not series.empty else series
                    stats = compute_kpi_deltas(series, unit)
                    if stats:
                        _is_pct = col_name == "CR"
                        val_str = f"{stats['current']:.1f}%" if _is_pct else f"{stats['current']:,.0f}"
                        cfg = UNIT_CONFIG[unit]
                        st.markdown(
                            f"<div style='background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:14px 16px;min-height:160px;'>"
                            f"<div style='color:#6b7280;font-size:0.8rem;margin-bottom:4px;'>{display_name}</div>"
                            f"<div style='font-size:1.4rem;font-weight:700;color:#111827;'>{val_str}</div>"
                            f"<div style='font-size:0.76rem;margin-top:6px;'>"
                            f"{cfg['prev_label']} {format_delta_html(stats['prev_delta'])}<br/>"
                            f"{cfg['yoy_label']} {format_delta_html(stats['yoy_delta'])}"
                            f"</div></div>",
                            unsafe_allow_html=True,
                        )
                    else:
                        st.markdown(
                            f"<div style='background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:14px 16px;min-height:160px;'>"
                            f"<div style='color:#6b7280;font-size:0.8rem;'>{display_name}</div>"
                            f"<div style='font-size:1.2rem;color:#9ca3af;'>-</div></div>",
                            unsafe_allow_html=True,
                        )

            st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

            # --- 추이 차트 (전년 비교선 포함) ---
            h1, h2 = st.columns([2, 3])
            h1.markdown("**카테고리 실적 추이**")
            cat_metric = h2.selectbox(
                "지표", ["트래픽", "거래액", "구매객수", "CR", "객단가"],
                index=1, key="cat_metric", label_visibility="collapsed",
            )

            s_raw = cat_combo.set_index("날짜")[cat_metric].sort_index()
            cat_full = s_raw.resample(UNIT_CONFIG[unit]["rule"]).mean()
            if unit == "주별":
                cat_full.index = cat_full.index - pd.Timedelta(days=6)
            elif unit == "월마감" and not cat_full.empty and s_raw.index.max() < cat_full.index[-1]:
                cat_full = cat_full.iloc[:-1]

            latest_year_cat = int(cat_full.index.max().year) if not cat_full.empty else None
            cat_series = cat_full[cat_full.index.year == latest_year_cat] if latest_year_cat else cat_full

            if unit == "일별" and not cat_series.empty:
                _cat_max_d = cat_series.index.max().date()
                _cat_min_d = cat_series.index.min().date()
                _cat_default_start = max(_cat_min_d, _cat_max_d - _dt.timedelta(days=30))
                col_cd, col_cy = st.columns([4, 1])
                with col_cd:
                    cat_dr = st.date_input(
                        "기간", value=(_cat_default_start, _cat_max_d),
                        min_value=_cat_min_d, max_value=_cat_max_d, key="cat_range",
                    )
                with col_cy:
                    show_cat_yoy = st.checkbox("전년 비교선 표시", value=True, key="cat_yoy")
                if isinstance(cat_dr, tuple) and len(cat_dr) == 2:
                    cat_series = cat_series[(cat_series.index >= pd.Timestamp(cat_dr[0])) & (cat_series.index <= pd.Timestamp(cat_dr[1]))]
            else:
                col_csp, col_cy = st.columns([5, 1])
                with col_cy:
                    show_cat_yoy = st.checkbox("전년 비교선 표시", value=True, key="cat_yoy")

            cat_chart_df = pd.DataFrame({cat_metric: cat_series})

            if show_cat_yoy and not cat_series.empty:
                if unit == "월마감":
                    prev_dates = cat_series.index - pd.DateOffset(years=1)
                else:
                    prev_dates = cat_series.index - pd.Timedelta(days=364)
                yoy_vals = []
                for pd_date in prev_dates:
                    if pd_date in cat_full.index:
                        yoy_vals.append(cat_full.loc[pd_date])
                    else:
                        cand = cat_full.index[cat_full.index <= pd_date]
                        yoy_vals.append(cat_full.loc[cand[-1]] if len(cand) else None)
                yoy_label_cat = UNIT_CONFIG[unit]["yoy_label"]
                cat_chart_df[f"{yoy_label_cat}(전년)"] = yoy_vals
                st.line_chart(cat_chart_df, height=350, color=["#2563eb", "#7dd3fc"])
            else:
                st.line_chart(cat_chart_df, height=350, color=["#2563eb"])

            st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

            # --- 카테고리 실적 요약 표 (EP실적/EP채널과 동일 스타일·기준) ---
            st.markdown(
                f"**카테고리 실적 요약 표**  ·  <span style='color:#6b7280;font-size:0.85rem'>{bpu} · {selected_cat} / {brand_label(selected_brand)}</span>",
                unsafe_allow_html=True,
            )
            cat_summary_rows = []
            cat_prev_label = cat_yoy_label = None
            for col_name, display_name in CAT_METRICS:
                s2 = cat_combo.set_index("날짜")[col_name].sort_index()
                series2 = s2.resample(UNIT_CONFIG[unit]["rule"]).mean()
                if unit == "주별":
                    series2.index = series2.index - pd.Timedelta(days=6)
                elif unit == "월마감" and not series2.empty and s2.index.max() < series2.index[-1]:
                    series2 = series2.iloc[:-1]
                series2 = series2[series2.index <= selected_period_date] if not series2.empty else series2
                stats2 = compute_kpi_deltas(series2, unit)
                if stats2 is None:
                    cat_summary_rows.append(f"<tr><td>{display_name}</td><td>-</td><td>-</td><td>-</td></tr>")
                    continue
                cat_prev_label = stats2["prev_label"]
                cat_yoy_label = stats2["yoy_label"]
                _is_pct2 = col_name == "CR"
                val2 = f"{stats2['current']:.1f}%" if _is_pct2 else f"{stats2['current']:,.0f}"
                cat_summary_rows.append(
                    f"<tr><td class='m'>{display_name}</td><td class='v'>{val2}</td>"
                    f"<td class='d'>{format_delta_html(stats2['prev_delta'])}</td>"
                    f"<td class='d'>{format_delta_html(stats2['yoy_delta'])}</td></tr>"
                )
            cat_summary_html = (
                "<table class='summary-table'>"
                f"<thead><tr><th>지표</th><th>값</th><th>{cat_prev_label or '-'}</th><th>{cat_yoy_label or '-'}</th></tr></thead>"
                f"<tbody>{''.join(cat_summary_rows)}</tbody></table>"
            )
            st.markdown(cat_summary_html, unsafe_allow_html=True)

        st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

        # --- 카테고리별 거래액 비중 (브랜드=전체 기준, 선택 시점까지) ---
        _share_df = cat_bpu_df[(cat_bpu_df["브랜드"] == "전체") & (cat_bpu_df["카테고리"] != "전체")]
        if bpu == "Total":
            _share_df = _share_df.groupby(["날짜", "카테고리"], as_index=False)["거래액"].sum()
        render_revenue_ranking(_share_df, "카테고리", unit, selected_period_date, "카테고리별 거래액 비중", f"{bpu} 기준")

        st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

        # --- 브랜드별 거래액 랭킹 ---
        # 카테고리='전체'면 전체 브랜드 랭킹, 특정 카테고리 선택시 그 카테고리 안의 브랜드만
        if selected_cat == "전체":
            _brand_share_df = cat_bpu_df[(cat_bpu_df["카테고리"] == "전체") & (cat_bpu_df["브랜드"] != "전체")]
            _brand_subtitle = f"{bpu} · 전체 카테고리 기준"
        else:
            _brand_share_df = cat_bpu_df[(cat_bpu_df["카테고리"] == selected_cat) & (cat_bpu_df["브랜드"] != "전체")]
            _brand_subtitle = f"{bpu} · {selected_cat} 카테고리 기준"
        if bpu == "Total":
            _brand_share_df = _brand_share_df.groupby(["날짜", "브랜드"], as_index=False)["거래액"].sum()
        render_revenue_ranking(_brand_share_df, "브랜드", unit, selected_period_date, "브랜드별 거래액 랭킹", _brand_subtitle, label_map=BRAND_LABELS)

        st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)



# ============================================================
# 페이지 3: 누적 데이터 (EP실적 + EP채널 합쳐서 기간별 표)
# ============================================================
if side["page"].startswith("3"):
    st.markdown("---")
    st.markdown(
        f"<div class='chart-caption'>매체: <b>{bpu}</b> · 기간유형: <b>{cum_unit}</b> · "
        f"{cum_start} ~ {cum_end}</div>",
        unsafe_allow_html=True,
    )

    # --- EP실적 부분 (트래픽/거래액/구매객수/CR/객단가) ---
    if bpu in BPU_GROUPS:
        _cum_tr = aggregate_traffic(df_traffic, BPU_GROUPS[bpu], "전체")
    else:
        _cum_tr = df_traffic[(df_traffic["BPU"] == bpu) & (df_traffic["회원구분"] == "전체")]

    tr_table_rows = {}
    if not _cum_tr.empty:
        for metric in ["트래픽", "거래액", "구매객수", "CR", "객단가"]:
            s = _cum_tr.set_index("날짜")[metric].sort_index()
            series = s.resample(UNIT_CONFIG[cum_unit]["rule"]).mean()
            if cum_unit == "주별":
                series.index = series.index - pd.Timedelta(days=6)
            elif cum_unit == "월마감" and not series.empty and s.index.max() < series.index[-1]:
                series = series.iloc[:-1]
            series = series[(series.index >= pd.Timestamp(cum_start)) & (series.index <= pd.Timestamp(cum_end))]
            tr_table_rows[metric] = series

    # --- EP채널 부분 (원부매칭율 등, Total/Total 기준) ---
    if bpu in BPU_GROUPS:
        _cum_ep = aggregate_ep(df_ep, BPU_GROUPS[bpu], "Total", "Total")
    elif bpu == "Total":
        _cum_ep = df_ep[(df_ep[COL_BPU] == "Total") & (df_ep[COL_MATCH] == "Total") & (df_ep[COL_LOWEST] == "Total")]
    else:
        _cum_ep = df_ep[(df_ep[COL_BPU] == bpu) & (df_ep[COL_MATCH] == "Total") & (df_ep[COL_LOWEST] == "Total")]

    EP_CUM_METRICS = ["원부매칭율(%)", "최저가율(%)", "평균 EP 전시 상품수", "평균 원부매칭 상품수", "평균 최저가 상품수"]
    ep_table_rows = {}
    if not _cum_ep.empty:
        for metric in EP_CUM_METRICS:
            series = resample_series(_cum_ep, metric, cum_unit)
            series = series[(series.index >= pd.Timestamp(cum_start)) & (series.index <= pd.Timestamp(cum_end))]
            ep_table_rows[metric] = series

    # --- 병합해서 표 만들기 (최신 기간이 위로 오도록 내림차순) ---
    all_dates = sorted(set().union(
        *[s.index for s in tr_table_rows.values()],
        *[s.index for s in ep_table_rows.values()],
    ), reverse=True)

    if not all_dates:
        st.info("선택한 조건에 데이터가 없습니다.")
    else:
        COLS = [
            ("트래픽", "UV", False), ("거래액", "거래액(순결제)", False), ("구매객수", "구매객수", False),
            ("CR", "구매전환율(%)", True), ("객단가", "객단가", False),
            ("원부매칭율(%)", "원부매칭율(%)", True), ("최저가율(%)", "최저가율(%)", True),
            ("평균 EP 전시 상품수", "전시상품수", False), ("평균 원부매칭 상품수", "원부매칭상품수", False),
            ("평균 최저가 상품수", "최저가상품수", False),
        ]
        header_html = "<th>구분</th>" + "".join(f"<th>{label}</th>" for _, label, _ in COLS)
        body_rows = []
        for d in all_dates:
            row_label = make_period_label(d, cum_unit)
            cells = []
            for key, _, is_pct in COLS:
                src = tr_table_rows.get(key, ep_table_rows.get(key))
                val = src.get(d) if src is not None and d in src.index else None
                if val is None or pd.isna(val):
                    cells.append("<td>-</td>")
                elif is_pct:
                    cells.append(f"<td>{val:.1f}%</td>")
                else:
                    cells.append(f"<td>{val:,.0f}</td>")
            body_rows.append(f"<tr><td class='m'>{row_label}</td>{''.join(cells)}</tr>")

        st.markdown(f"**누적 데이터**  ·  <span style='color:#6b7280;font-size:0.85rem'>{len(all_dates)}개 기간</span>", unsafe_allow_html=True)
        table_html = (
            "<div style='overflow-x:auto;'><table class='summary-table'>"
            f"<thead><tr>{header_html}</tr></thead>"
            f"<tbody>{''.join(body_rows)}</tbody></table></div>"
        )
        st.markdown(table_html, unsafe_allow_html=True)


# ============================================================
# 페이지 4: 누적 데이터 (카테고리)
# ============================================================
if side["page"].startswith("4"):
    st.markdown("---")
    st.markdown(
        f"<div class='chart-caption'>매체: <b>{bpu}</b> · 기간유형: <b>{cum_unit}</b> · "
        f"{cum_start} ~ {cum_end} · <b>{selected_cat}</b> / <b>{brand_label(selected_brand)}</b></div>",
        unsafe_allow_html=True,
    )

    if df_category.empty:
        st.info("카테고리 데이터가 없습니다.")
    else:
        if bpu in BPU_GROUPS:
            _cum_cat_df = df_category[df_category["BPU"].isin(BPU_GROUPS[bpu])]
        elif bpu == "Total":
            _cum_cat_df = df_category
        else:
            _cum_cat_df = df_category[df_category["BPU"] == bpu]

        _cum_cat_combo = _cum_cat_df[(_cum_cat_df["카테고리"] == selected_cat) & (_cum_cat_df["브랜드"] == selected_brand)]
        if bpu == "Total" and not _cum_cat_combo.empty:
            _cum_cat_combo = _cum_cat_combo.groupby("날짜", as_index=False).agg({"트래픽": "sum", "거래액": "sum", "구매객수": "sum"})
            _cum_cat_combo["CR"] = (_cum_cat_combo["구매객수"] / _cum_cat_combo["트래픽"] * 100).where(_cum_cat_combo["트래픽"] > 0, 0)
            _cum_cat_combo["객단가"] = (_cum_cat_combo["거래액"] / _cum_cat_combo["구매객수"]).where(_cum_cat_combo["구매객수"] > 0, 0)

        if _cum_cat_combo.empty:
            st.warning(f"{selected_cat} / {brand_label(selected_brand)} 조합에 데이터가 없습니다.")
        else:
            CAT_CUM_COLS = [
                ("트래픽", "UV", False), ("거래액", "거래액", False), ("구매객수", "구매객수", False),
                ("CR", "구매전환율(%)", True), ("객단가", "객단가", False),
            ]
            cat_table_rows = {}
            for key, _, _is_pct in CAT_CUM_COLS:
                s = _cum_cat_combo.set_index("날짜")[key].sort_index()
                series = s.resample(UNIT_CONFIG[cum_unit]["rule"]).mean()
                if cum_unit == "주별":
                    series.index = series.index - pd.Timedelta(days=6)
                elif cum_unit == "월마감" and not series.empty and s.index.max() < series.index[-1]:
                    series = series.iloc[:-1]
                series = series[(series.index >= pd.Timestamp(cum_start)) & (series.index <= pd.Timestamp(cum_end))]
                cat_table_rows[key] = series

            all_cat_dates = sorted(set().union(*[s.index for s in cat_table_rows.values()]), reverse=True)
            if not all_cat_dates:
                st.info("선택한 조건에 데이터가 없습니다.")
            else:
                header_html2 = "<th>구분</th>" + "".join(f"<th>{label}</th>" for _, label, _ in CAT_CUM_COLS)
                body_rows2 = []
                for d in all_cat_dates:
                    row_label = make_period_label(d, cum_unit)
                    cells = []
                    for key, _, _is_pct in CAT_CUM_COLS:
                        val = cat_table_rows[key].get(d)
                        if val is None or pd.isna(val):
                            cells.append("<td>-</td>")
                        elif _is_pct:
                            cells.append(f"<td>{val:.1f}%</td>")
                        else:
                            cells.append(f"<td>{val:,.0f}</td>")
                    body_rows2.append(f"<tr><td class='m'>{row_label}</td>{''.join(cells)}</tr>")

                st.markdown(f"**카테고리 누적 데이터**  ·  <span style='color:#6b7280;font-size:0.85rem'>{len(all_cat_dates)}개 기간</span>", unsafe_allow_html=True)
                table_html2 = (
                    "<div style='overflow-x:auto;'><table class='summary-table'>"
                    f"<thead><tr>{header_html2}</tr></thead>"
                    f"<tbody>{''.join(body_rows2)}</tbody></table></div>"
                )
                st.markdown(table_html2, unsafe_allow_html=True)
