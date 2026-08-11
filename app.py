"""마케팅 실적 현황 대시보드

위: EP 실적 (트래픽/거래액/구매객수/CR/객단가) — EP실적 데이터
아래: EP 채널 지표 (원부매칭율/최저가율 등) — 기존 EP 데이터, 원부매칭/최저가 필터 적용
"""
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import datetime as _dt
import io

from data_loader import (
    load_data, load_traffic_data, load_category_data, load_brand_names,
    load_coupon_daily, build_coupon_monthly, build_coupon_monthly_detail,
)
from ai_insights import (
    render_metric_insight, generate_ranking_insights, render_ranking_insight_box,
)
from sidebar import render_sidebar, render_sidebar_data_status
from filters import filter_by_combo
from kpi import render_kpi_cards
from charts import main_trend_data
from comparison_table import render_summary_table_html
from utils import (
    COL_DATE, COL_BPU, COL_MATCH, COL_LOWEST, METRIC_COLS, UNIT_CONFIG,
    resample_series, make_period_label, compute_kpi_deltas, week_of_month,
    format_value, format_delta_html,
)
from styles import CUSTOM_CSS
from insight_card import render_insight_card

def _ref_str(val, is_pct=False):
    """비교 대상 실제 값을 괄호로 표시."""
    if val is None or pd.isna(val):
        return ""
    if is_pct:
        return f" <span style='color:#9ca3af'>({val:.1f}%)</span>"
    return f" <span style='color:#9ca3af'>({val:,.0f})</span>"


# ============================================================
# 인사이트 카드: 좌측 자동요약(API 미사용) + 우측 AI·메모(GitHub 저장)
# ============================================================

st.set_page_config(page_title="마케팅 실적 현황 대시보드", layout="wide", page_icon="📊")
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# --- 사이드바 ---
side = render_sidebar()
if side["refresh"]:
    load_data.clear()
    load_traffic_data.clear()
    load_category_data.clear()
    load_coupon_daily.clear()

# --- 데이터 로드 ---
df_ep = load_data()           # 기존 EP 데이터 (원부매칭율 등)
df_traffic = load_traffic_data()  # EP실적 데이터 (트래픽/거래액 등)
df_category = load_category_data()  # 카테고리/브랜드별 실적 데이터
df_coupon_daily = load_coupon_daily()  # 쿠폰명별 일자별 상세 할인 데이터 (BPU: e-영업1~4)
df_coupon = build_coupon_monthly(df_coupon_daily)  # 월별 BPU 집계(Total/자사/입점/e-영업1~4) - daily에서 파생
df_coupon_detail = build_coupon_monthly_detail(df_coupon_daily)  # 월별 쿠폰명별 상세 - daily에서 파생
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

# 쿠폰 데이터 업로드 (일자별 원본 하나로 통합 - 월별 집계/상세는 여기서 자동 파생)
if side["ep_coupon_daily_file"] is not None:
    _cpddf = side["ep_coupon_daily_file"]
    df_coupon_daily = pd.read_csv(_cpddf)
    df_coupon_daily["날짜"] = pd.to_datetime(df_coupon_daily["날짜"])
    df_coupon = build_coupon_monthly(df_coupon_daily)
    df_coupon_detail = build_coupon_monthly_detail(df_coupon_daily)
    st.sidebar.success(f"쿠폰 데이터 업로드 완료 ({df_coupon_daily['날짜'].min().strftime('%Y-%m-%d')} ~ {df_coupon_daily['날짜'].max().strftime('%Y-%m-%d')})")

# --- 사이드바 하단: 데이터셋별 반영 현황(기간/일수) ---
def _status_entry(df, date_col):
    if df is None or df.empty or date_col not in df.columns:
        return None, None, None
    _dmin = df[date_col].min()
    _dmax = df[date_col].max()
    _n = df[date_col].nunique()
    return _dmin.strftime("%Y-%m-%d"), _dmax.strftime("%Y-%m-%d"), _n

_status_items = [
    ("EP채널", *_status_entry(df_ep, COL_DATE)),
    ("EP실적", *_status_entry(df_traffic, "날짜")),
    ("카테고리", *_status_entry(df_category, "날짜")),
    ("쿠폰(일자별)", *_status_entry(df_coupon_daily, "날짜")),
]
render_sidebar_data_status(_status_items)


unit = side["view_unit"]

# 자사/입점 합산용 BPU 그룹 정의
BPU_GROUPS = {
    "자사": ["e-영업1", "e-영업2"],
    "입점": ["e-영업3", "e-영업4"],
}


def _reset_date_range(_state_key, _value):
    """'최근으로' 버튼용 콜백. on_click으로 넘겨서 위젯이 다시 그려지기 전에
    session_state를 먼저 갱신한다 (버튼 클릭 처리 중 위젯이 이미 인스턴스화된
    뒤에 st.session_state[key]=... 를 직접 대입하면 StreamlitAPIException이 남)."""
    st.session_state[_state_key] = _value


def render_week_range_filter(series, key_prefix, col_slider, col_reset, default_weeks=12):
    """'주별' 조회 시 차트 영역에 'N월 N주차' 라벨 기반 주차 범위 슬라이더를 그린다.
    (7/8/9번 페이지에서 쓰던 것과 동일한 라벨 방식을 1/2번 페이지 차트에도 적용)
    '일별'의 날짜 range picker와 같은 자리에, 같은 3분할 레이아웃(슬라이더|최근으로|전년비교선)을
    유지하기 위해 컬럼을 호출부에서 미리 만들어 넘겨받는다(컬럼 안에 컬럼을 또 만들면 레이아웃이
    불균형해지는 문제가 있어서).
    series: 이미 '주별'로 리샘플된(Monday 라벨) 시리즈. 반환값: 선택 범위로 잘라진 시리즈."""
    if series.empty:
        return series
    labels = [f"{d.month}월 {week_of_month(d)}주차" for d in series.index]
    n = len(labels)
    default_start_idx = max(0, n - default_weeks)
    _range_key = f"{key_prefix}_wkrange"
    with col_slider:
        st.markdown("<div style='font-size:0.78rem;color:#6b7280;margin-bottom:1px;'>주차 범위</div>", unsafe_allow_html=True)
        sel_labels = st.select_slider(
            "주차 범위", options=labels, value=(labels[default_start_idx], labels[-1]),
            label_visibility="collapsed", key=_range_key,
        )
    with col_reset:
        st.markdown("<div style='height:1.5rem;'></div>", unsafe_allow_html=True)
        st.button(
            "🔄 최근으로", key=f"{key_prefix}_wkrange_reset", use_container_width=True,
            on_click=_reset_date_range, args=(_range_key, (labels[default_start_idx], labels[-1])),
        )
    start_idx = labels.index(sel_labels[0])
    end_idx = labels.index(sel_labels[1])
    if start_idx > end_idx:
        start_idx, end_idx = end_idx, start_idx
    return series.iloc[start_idx:end_idx + 1]


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


FF_BRAND_CODE = "FF"


def exclude_ff_brand(df):
    """핏플랍(FF, 2025-10월 종료) 브랜드 실적을 카테고리 집계에서 제외한다.

    - '브랜드=전체' 집계행(FF가 속한 카테고리 + '카테고리=전체' 전체 집계행)에서
      FF의 트래픽/거래액/구매객수를 빼고 CR/객단가를 재계산 (비율 지표는 그냥
      빼면 안 되고 항상 분자/분모를 먼저 뺀 뒤 재계산해야 함 - 데이터 정합성 원칙).
    - 개별 브랜드 목록(랭킹 등)에서는 FF 행 자체를 제외.
    - 다른 카테고리/브랜드 행은 전혀 건드리지 않음 (FF는 슈즈에만 있었으므로).
    """
    if df.empty or "브랜드" not in df.columns:
        return df

    ff_rows = df[(df["브랜드"] == FF_BRAND_CODE) & (df["카테고리"] != "전체")]
    df2 = df[df["브랜드"] != FF_BRAND_CODE].copy()  # FF 자체 행(전체/개별 카테고리 다 포함) 제외
    if ff_rows.empty:
        return df2

    group_keys = ["날짜", "BPU"] + (["회원구분"] if "회원구분" in df.columns else [])
    ff_agg = ff_rows.groupby(group_keys, as_index=False)[["트래픽", "거래액", "구매객수"]].sum()
    ff_agg = ff_agg.rename(columns={"트래픽": "_ff_t", "거래액": "_ff_g", "구매객수": "_ff_b"})

    ff_categories = set(ff_rows["카테고리"].unique()) | {"전체"}
    mask = (df2["브랜드"] == "전체") & (df2["카테고리"].isin(ff_categories))
    if not mask.any():
        return df2

    target = df2.loc[mask].merge(ff_agg, on=group_keys, how="left")
    target[["_ff_t", "_ff_g", "_ff_b"]] = target[["_ff_t", "_ff_g", "_ff_b"]].fillna(0)
    target["트래픽"] = target["트래픽"] - target["_ff_t"]
    target["거래액"] = target["거래액"] - target["_ff_g"]
    target["구매객수"] = target["구매객수"] - target["_ff_b"]
    target["CR"] = (target["구매객수"] / target["트래픽"] * 100).where(target["트래픽"] > 0)
    target["객단가"] = (target["거래액"] / target["구매객수"]).where(target["구매객수"] > 0)

    df2.loc[mask, ["트래픽", "거래액", "구매객수", "CR", "객단가"]] = target[
        ["트래픽", "거래액", "구매객수", "CR", "객단가"]
    ].values
    return df2


def exclude_ff_from_traffic(df_traffic, df_category):
    """EP실적 원본(df_traffic)엔 브랜드 정보가 없어서 핏플랍을 직접 제외할 수 없으므로,
    카테고리 원본(df_category)에서 FF의 일자별 트래픽/거래액/구매객수를 가져와 그만큼
    df_traffic에서 빼고 CR/객단가를 재계산한다.

    - 'e-영업1'/'e-영업2' 리터럴 행(FF가 실제로 존재하는 BPU)에서 직접 차감.
    - 'Total' 리터럴 행은 e-영업1~4를 미리 합쳐둔 별도 행이라, e-영업1+e-영업2 합계만큼
      추가로 차감해야 함 (자사/입점 뷰는 앱에서 e-영업1~4를 그때그때 합산하는 구조라
      e-영업1/e-영업2를 고치면 자동으로 반영되지만, Total은 그렇지 않음).
    - 세그먼트는 카테고리 원본에 남아있는 전체/회원/신규만 보정 가능하다(비회원/기존은
      용량 문제로 카테고리 원본에서 뺐던 세그먼트라 원천적으로 보정 불가 — 그대로 둠)."""
    if df_traffic.empty or df_category.empty:
        return df_traffic

    ff = df_category[(df_category["브랜드"] == "FF") & (df_category["카테고리"] != "전체")]
    if ff.empty:
        return df_traffic

    ff_by_bpu = ff.groupby(["날짜", "BPU", "회원구분"], as_index=False)[["트래픽", "거래액", "구매객수"]].sum()
    ff_total = ff_by_bpu.groupby(["날짜", "회원구분"], as_index=False)[["트래픽", "거래액", "구매객수"]].sum()
    ff_total["BPU"] = "Total"
    ff_all = pd.concat([ff_by_bpu, ff_total], ignore_index=True)
    ff_all = ff_all.rename(columns={"트래픽": "_ff_t", "거래액": "_ff_g", "구매객수": "_ff_b"})

    group_keys = ["날짜", "BPU", "회원구분"]
    mask = df_traffic["BPU"].isin(["Total", "e-영업1", "e-영업2"])
    if not mask.any():
        return df_traffic

    target = df_traffic.loc[mask].merge(ff_all, on=group_keys, how="left")
    target[["_ff_t", "_ff_g", "_ff_b"]] = target[["_ff_t", "_ff_g", "_ff_b"]].fillna(0)
    target["트래픽"] = target["트래픽"] - target["_ff_t"]
    target["거래액"] = target["거래액"] - target["_ff_g"]
    target["구매객수"] = target["구매객수"] - target["_ff_b"]
    target["CR"] = (target["구매객수"] / target["트래픽"] * 100).where(target["트래픽"] > 0)
    target["객단가"] = (target["거래액"] / target["구매객수"]).where(target["구매객수"] > 0)

    df2 = df_traffic.copy()
    df2.loc[mask, ["트래픽", "거래액", "구매객수", "CR", "객단가"]] = target[
        ["트래픽", "거래액", "구매객수", "CR", "객단가"]
    ].values
    return df2


def _weekly_of_year(daily_df, metric, year):
    """daily_df(날짜 컬럼 포함)를 해당 연도만 잘라서 월~일 주간 평균으로 리샘플하고,
    그 해 첫 주=1주차로 시작하는 정수 인덱스를 붙인다. (7번 페이지 전용, 스티키 헤더의
    주차 필터와 페이지 본문 둘 다에서 같은 정의를 써야 해서 모듈 레벨에 둠)"""
    d = daily_df[daily_df["날짜"].dt.year == year]
    if d.empty:
        return pd.Series(dtype="float64")
    s = d.set_index("날짜")[metric].sort_index()
    weekly = s.resample("W-SUN").mean()
    weekly.index = weekly.index - pd.Timedelta(days=6)  # 그 주의 월요일로 라벨
    weekly = weekly.reset_index(drop=True)
    weekly.index = weekly.index + 1  # 1주차부터 시작
    return weekly


def _week_labels_for_year(daily_df, metric, year):
    """_weekly_of_year와 정확히 같은 순서로 'N월 N주차' 라벨을 만든다 (1:1 대응 보장).
    그 해 1/1이 월요일이 아니면 첫 주는 실제로 전년도 12월 마지막 주에 걸치는데,
    이건 utils.week_of_month의 '월 경계는 이전 달 마지막 주로 본다' 규칙과 동일하게 처리
    (그래야 예: 1월 1주차가 두 번 나오는 라벨 중복이 안 생김). 그 경우엔 연도를 앞에 붙여
    구분한다(예: '24년 12월 5주차')."""
    d = daily_df[daily_df["날짜"].dt.year == year]
    if d.empty:
        return []
    s = d.set_index("날짜")[metric].sort_index()
    weekly_raw = s.resample("W-SUN").mean()
    labels = []
    for bucket_end in weekly_raw.index:
        mon = bucket_end - pd.Timedelta(days=6)
        if mon.year != year:
            labels.append(f"{mon.year % 100}년 {mon.month}월 {week_of_month(mon)}주차")
        else:
            labels.append(f"{mon.month}월 {week_of_month(mon)}주차")
    return labels


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


def build_weekly_report_excel(unit, selected_period_date, df_traffic, df_category, cat_segment, ff_exclude):
    """주간보고용 엑셀(bytes) 생성.
    - 시트1 'BPU별': compute_bpu_comparison_rows() 그대로 사용 → 1번 페이지 비교표와 100% 동일 로직/숫자
    - 시트2 '카테고리별(거래액)': compute_category_yoy_rows() 그대로 사용(BPU=e-영업1~4 각각)
      → 2번 페이지 '카테고리별 요약'표와 동일한 세그먼트 필터·핏플랍 제외 규칙 적용
    별도로 값을 재계산하지 않고 두 페이지가 쓰는 함수를 그대로 호출하므로, 화면에 보이는 표와
    엑셀 숫자가 어긋날 일이 없다.

    두 시트는 원본이 다르다(ep_traffic.csv vs ep_category.csv). 한쪽 파일이 하루이틀 늦게
    끊겨 있으면 '이번 달 진행 중인 며칠'의 날짜 범위(cur_days)가 시트마다 달라져서 전체
    합계가 안 맞을 수 있다. 없는 날짜를 0으로 채우면 평균이 왜곡되므로(그 날 매출이 없는
    게 아니라 그냥 데이터가 늦게 들어온 것), 대신 두 파일 중 더 짧은 쪽 마지막 날짜로
    기준시점을 맞춰서 둘 다 '실제로 존재하는' 같은 날짜 범위만 보게 한다."""
    cur_year = pd.Timestamp(selected_period_date).year
    prev_year = cur_year - 1
    col_prev, col_cur = f"{prev_year}년", f"{cur_year}년"

    _tr_max = df_traffic["날짜"].max() if not df_traffic.empty else None
    _cat_max = df_category["날짜"].max() if not df_category.empty else None
    _common_cutoff = min([d for d in [_tr_max, _cat_max, pd.Timestamp(selected_period_date)] if d is not None])

    # --- 시트1: BPU별 (1번 페이지와 동일 함수) — 이미지 기준: 전체/e-영업1~4만 ---
    _bpu_rows, cfg, BPU_COLS = compute_bpu_comparison_rows(df_traffic, unit, _common_cutoff)
    _bpu_keep = {"Total", "e-영업1", "e-영업2", "e-영업3", "e-영업4"}
    _bpu_label = {"Total": "전체"}
    left_rows = []
    for r in _bpu_rows:
        if r["bpu"] not in _bpu_keep:
            continue
        stats = r["stats"]
        if stats is None:
            continue
        is_pct = r["is_pct"]
        left_rows.append({
            "지표": r["metric_label"], "구분": _bpu_label.get(r["bpu"], r["bpu"]),
            col_prev: round(stats["yoy_value"], 1) if is_pct else round(stats["yoy_value"]) if stats.get("yoy_value") is not None else None,
            col_cur: round(stats["current"], 1) if is_pct else round(stats["current"]),
            "전년비(%)": round(stats["yoy_delta"], 1) if stats.get("yoy_delta") is not None else None,
        })
    left_df = pd.DataFrame(left_rows)

    # --- 시트2: 카테고리별 (거래액, e-영업1~4 각각) — 2번 페이지와 동일 함수 ---
    right_rows = []
    for bv in ["e-영업1", "e-영업2", "e-영업3", "e-영업4"]:
        for r in compute_category_yoy_rows(df_category, bv, cat_segment, ff_exclude, unit, _common_cutoff):
            right_rows.append({
                "BPU": bv, "카테고리": r["카테고리"],
                col_prev: round(r["yoy_value"]) if r.get("yoy_value") is not None else None,
                col_cur: round(r["current"]),
                "전년비(%)": round(r["yoy_delta"], 1) if r.get("yoy_delta") is not None else None,
            })
    right_df = pd.DataFrame(right_rows)

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        left_df.to_excel(writer, index=False, sheet_name="BPU별")
        right_df.to_excel(writer, index=False, sheet_name="카테고리별(거래액)")
        for _ws in writer.sheets.values():
            for _col in _ws.columns:
                _w = max((len(str(c.value)) for c in _col if c.value is not None), default=8)
                _ws.column_dimensions[_col[0].column_letter].width = min(_w + 3, 40)
    return buf.getvalue(), left_df, right_df


def render_excel_download(df_export, filename, label="⬇️ 엑셀 다운로드"):
    """DataFrame을 엑셀 파일로 변환해 다운로드 버튼으로 제공."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df_export.to_excel(writer, index=False, sheet_name="누적 데이터")
    st.download_button(
        label,
        data=buf.getvalue(),
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=False,
    )


def _truncate_by_range(series, cum_start, cum_end, cum_unit):
    """누적 데이터의 시작일/종료일 필터를 적용.
    월별/월마감은 리샘플 라벨이 '그 달의 말일'이라, 종료일이 월중(예: 7/27)이면
    라벨(7/31)이 종료일보다 커서 그 달 전체가 잘못 걸러지는 문제가 있었음.
    → 월 단위(연-월)로 비교해 종료월이 포함되면 살리도록 수정.
    """
    if series.empty:
        return series
    start_ts = pd.Timestamp(cum_start)
    end_ts = pd.Timestamp(cum_end)
    if cum_unit in ("월별", "월마감"):
        mask = (series.index.to_period("M") >= start_ts.to_period("M")) & \
               (series.index.to_period("M") <= end_ts.to_period("M"))
    else:
        mask = (series.index >= start_ts) & (series.index <= end_ts)
    return series[mask]


def compute_bpu_comparison_rows(df_traffic, unit="일별", selected_period_date=None):
    """render_bpu_comparison_table과 동일한 로직(집계 방식·월마감 규칙·부분기간 보정)으로
    지표×BPU 조합별 compute_kpi_deltas 결과를 계산해 구조화된 리스트로 반환한다.
    HTML 렌더링(render_bpu_comparison_table)과 엑셀 내보내기가 이 함수를 공유해서
    두 군데 숫자가 어긋나지 않게 한다."""
    BPU_COLS = ["Total", "e-영업1", "e-영업2", "e-영업3", "e-영업4", "자사", "입점"]
    METRICS = [
        ("트래픽", "전체", "EP UV", False),
        ("트래픽", "회원", "회원UV", False),
        ("거래액", "전체", "거래액(순결제)", False),
        ("구매객수", "전체", "구매객수", False),
        ("CR", "전체", "구매전환율(%)", True),
        ("객단가", "전체", "객단가", False),
    ]
    SUMMABLE_METRICS = {"트래픽", "거래액", "구매객수"}
    cfg = UNIT_CONFIG[unit]

    def _series_for(bpu_key, metric, member="전체"):
        if bpu_key in BPU_GROUPS:
            sub = aggregate_traffic(df_traffic, BPU_GROUPS[bpu_key], member)
        else:
            sub = df_traffic[(df_traffic["BPU"] == bpu_key) & (df_traffic["회원구분"] == member)]
        if sub.empty:
            return pd.Series(dtype="float64"), pd.Series(dtype="float64")
        s = sub.set_index("날짜")[metric].sort_index()
        _agg = "sum" if (unit == "월마감" and metric in SUMMABLE_METRICS) else "mean"
        series = s.resample(cfg["rule"]).agg(_agg)
        if unit == "주별":
            series.index = series.index - pd.Timedelta(days=6)
        elif unit == "월마감":
            if not series.empty and s.index.max() < series.index[-1]:
                series = series.iloc[:-1]
        _s_raw = s
        if selected_period_date is not None and not series.empty:
            series = series[series.index <= selected_period_date]
            _s_raw = s[s.index <= selected_period_date]
        return series, _s_raw

    rows = []
    for metric_key, member, metric_label, is_pct in METRICS:
        for bpu_key in BPU_COLS:
            series, _s_raw = _series_for(bpu_key, metric_key, member)
            stats = compute_kpi_deltas(series, unit, raw_daily=_s_raw)
            rows.append({"metric_label": metric_label, "is_pct": is_pct, "bpu": bpu_key, "stats": stats})
    return rows, cfg, BPU_COLS


def render_bpu_comparison_table(df_traffic, unit="일별", selected_period_date=None):
    """사업부별(Total/e-영업1~4/자사/입점) 실적 비교표.
    상단의 '조회 단위'(일별/주별/월별/월마감)와 '기준 시점'을 그대로 따른다.
    → 위 KPI 카드/요약표와 동일한 집계 방식이므로 Total 열은 KPI 카드 값과 일치한다."""
    rows, cfg, BPU_COLS = compute_bpu_comparison_rows(df_traffic, unit, selected_period_date)

    by_metric = {}
    for r in rows:
        by_metric.setdefault(r["metric_label"], {"is_pct": r["is_pct"], "cells": {}})
        by_metric[r["metric_label"]]["cells"][r["bpu"]] = r["stats"]

    for metric_label, info in by_metric.items():
        is_pct = info["is_pct"]
        header_html = "<th>구분</th>" + "".join(f"<th>{b}</th>" for b in BPU_COLS)
        row_val, row_prev, row_avg, row_yoy = [], [], [], []
        for bpu_key in BPU_COLS:
            stats = info["cells"].get(bpu_key)
            if stats is None:
                row_val.append("<td>-</td>")
                row_prev.append("<td>-</td>")
                row_avg.append("<td>-</td>")
                row_yoy.append("<td>-</td>")
                continue
            val_str = f"{stats['current']:.1f}%" if is_pct else f"{stats['current']:,.0f}"
            row_val.append(f"<td class='v'>{val_str}</td>")
            row_prev.append(f"<td class='d'>{format_delta_html(stats['prev_delta'])}{_ref_str(stats.get('prev_value'), is_pct)}</td>")
            row_avg.append(f"<td class='d'>{format_delta_html(stats['avg_delta'])}{_ref_str(stats.get('avg_value'), is_pct)}</td>")
            row_yoy.append(f"<td class='d'>{format_delta_html(stats['yoy_delta'])}{_ref_str(stats.get('yoy_value'), is_pct)}</td>")

        cfg = UNIT_CONFIG[unit]
        table_html = (
            "<table class='summary-table' style='margin-bottom:14px;'>"
            f"<thead><tr><th colspan='{len(BPU_COLS)+1}' style='background:#eef2ff;color:#374151;font-weight:700;'>{metric_label}</th></tr>"
            f"<tr>{header_html}</tr></thead>"
            "<tbody>"
            f"<tr><td class='m'>값</td>{''.join(row_val)}</tr>"
            f"<tr><td class='m'>{cfg['prev_label']}</td>{''.join(row_prev)}</tr>"
            f"<tr><td class='m'>{cfg['avg_label']}</td>{''.join(row_avg)}</tr>"
            f"<tr><td class='m'>{cfg['yoy_label']}</td>{''.join(row_yoy)}</tr>"
            "</tbody></table>"
        )
        st.markdown(table_html, unsafe_allow_html=True)


def compute_category_yoy_rows(df_category, bpu_value, cat_segment, ff_exclude, unit, selected_period_date):
    """2번 페이지 '카테고리별 요약'표와 완전히 동일한 규칙(세그먼트 필터·핏플랍 제외·
    compute_kpi_deltas)으로 특정 BPU 하나의 카테고리별 거래액 stats를 계산한다.
    '전체' 카테고리 행도 포함해서 맨 위에 오도록 반환."""
    d = df_category[df_category["BPU"] == bpu_value]
    if d.empty:
        return []
    if "회원구분" in d.columns:
        d = d[d["회원구분"] == cat_segment]
    if ff_exclude:
        d = exclude_ff_brand(d)
    d = d[d["브랜드"] == "전체"][["날짜", "카테고리", "거래액"]]
    if d.empty:
        return []

    cfg = UNIT_CONFIG[unit]
    _agg = "sum" if unit == "월마감" else "mean"
    rows = []
    for cat_name, g in d.groupby("카테고리"):
        s = g.set_index("날짜")["거래액"].sort_index()
        series = s.resample(cfg["rule"]).agg(_agg)
        if unit == "주별":
            series.index = series.index - pd.Timedelta(days=6)
        elif unit == "월마감" and not series.empty and s.index.max() < series.index[-1]:
            series = series.iloc[:-1]
        if not series.empty:
            series = series[series.index <= selected_period_date]
        _s_raw = s[s.index <= selected_period_date] if selected_period_date is not None else s
        stats = compute_kpi_deltas(series, unit, raw_daily=_s_raw)
        if stats is None or not stats["current"]:
            continue
        rows.append({"카테고리": cat_name, **stats})

    _head = [r for r in rows if r["카테고리"] == "전체"]
    _rest = sorted([r for r in rows if r["카테고리"] != "전체"], key=lambda r: r["current"], reverse=True)
    return _head + _rest


# 일자별 그래프에 표시할 이벤트 주석 (날짜, 라벨). 필요하면 여기에 추가/수정하면 됨.
DASHBOARD_EVENTS = [
    (pd.Timestamp("2026-08-04"), "최저가쿠폰 초기화(18시)"),
    (pd.Timestamp("2026-08-05"), "다나와 기준 쿠폰 배치"),
]


def render_line_chart(chart_df, height=350, unit="일별", yoy_actual_dates=None):
    """줌/팬이 비활성화된 라인 차트 (마커 + 호버 툴팁 포함).
    st.line_chart는 마우스 휠 확대/축소가 기본 활성화돼 스크롤 시 화면이 튀므로,
    Altair로 직접 그려 인터랙션을 끈다. (첫 컬럼=금년 진한 파랑, 둘째=전년 하늘색)
    unit이 '월별'/'월마감'이면 x축을 월 단위(연-월)로 표시한다.
    yoy_actual_dates: chart_df.index와 같은 길이의 날짜 배열/시리즈. '전년' 계열은 화면상
    올해 날짜 위치에 겹쳐 그려지지만(비교하기 좋으라고) 실제 값은 작년 것이므로, 이걸 주면
    '(전년)'이 포함된 계열의 툴팁 날짜만 실제 작년 날짜로 보여준다(안 주면 x축 날짜 그대로).
    일별(비월별) 조회일 땐, DASHBOARD_EVENTS 중 화면에 보이는 날짜 범위에 해당하는 이벤트를
    빨간 점선 세로줄 + 라벨로 같이 표시한다."""
    import altair as alt

    if chart_df is None or chart_df.empty:
        st.info("표시할 데이터가 없습니다.")
        return

    cols = list(chart_df.columns)
    colors = ["#2563eb", "#7dd3fc"][: len(cols)]

    _df = chart_df.copy()
    _df.index.name = "날짜"
    long_df = _df.reset_index().melt("날짜", var_name="구분", value_name="값")
    long_df = long_df.dropna(subset=["값"])

    # 전년 비교선의 툴팁 날짜를 실제 작년 날짜로 교체 (x축 위치는 올해 날짜 그대로 유지)
    long_df["_tooltip_date"] = long_df["날짜"]
    if yoy_actual_dates is not None:
        _actual_map = dict(zip(pd.DatetimeIndex(chart_df.index), pd.DatetimeIndex(yoy_actual_dates)))
        _is_yoy_row = long_df["구분"].astype(str).str.contains("(전년)", regex=False)
        long_df.loc[_is_yoy_row, "_tooltip_date"] = long_df.loc[_is_yoy_row, "날짜"].map(_actual_map)

    _is_monthly = unit in ("월별", "월마감")
    _event_rows = []
    if _is_monthly:
        x_enc = alt.X(
            "날짜:T", title=None, timeUnit="yearmonth",
            axis=alt.Axis(format="%Y-%m", labelAngle=0),
        )
        _date_fmt = "%Y-%m"
    else:
        # temporal(T) 타입 x축은 Vega-Lite가 자체적으로 '보기 좋은' 틱 간격을 자동으로 골라서,
        # 며칠 안 되는 좁은 구간에서도 하루에 여러 개의 틱(포맷은 %m/%d라 같은 날짜로 중복 표시)이
        # 찍히는 문제가 있었음. 실제 데이터 포인트 날짜만 문자열 라벨(ordinal)로 써서 방지하고,
        # 점이 많으면(20개 초과) 라벨을 적당히 솎아서 겹치지 않게 한다.
        long_df["_date_label"] = long_df["날짜"].dt.strftime("%m/%d")
        _uniq_dates = sorted(long_df["날짜"].unique())
        _label_order = [pd.Timestamp(d).strftime("%m/%d") for d in _uniq_dates]
        _n = len(_label_order)
        if _n > 20:
            _step = -(-_n // 20)  # ceil(n/20)
            _tick_vals = _label_order[::_step]
            if _label_order[-1] not in _tick_vals:
                _tick_vals.append(_label_order[-1])
        else:
            _tick_vals = _label_order
        x_enc = alt.X(
            "_date_label:O", title=None, sort=_label_order,
            axis=alt.Axis(labelAngle=0, values=_tick_vals),
        )
        _date_fmt = "%Y-%m-%d"

        # 화면에 보이는 날짜 범위 안에 있는 이벤트만 세로 점선+라벨로 표시
        _event_rows = []
        for ev_date, ev_label in DASHBOARD_EVENTS:
            if ev_date.normalize() in set(pd.DatetimeIndex(_uniq_dates).normalize()):
                _event_rows.append({"_date_label": ev_date.strftime("%m/%d"), "이벤트": ev_label})

    chart = (
        alt.Chart(long_df)
        .mark_line(strokeWidth=3, point=alt.OverlayMarkDef(size=45, filled=True, opacity=1))
        .encode(
            x=x_enc,
            y=alt.Y("값:Q", title=None, axis=alt.Axis(format="~s"), scale=alt.Scale(zero=False)),
            color=alt.Color(
                "구분:N",
                scale=alt.Scale(domain=cols, range=colors),
                legend=alt.Legend(orient="bottom", title=None),
            ),
            tooltip=[
                alt.Tooltip("_tooltip_date:T", title="날짜", format=_date_fmt),
                alt.Tooltip("구분:N", title="구분"),
                alt.Tooltip("값:Q", title="값", format=",.0f"),
            ],
        )
        .properties(height=height)
    )

    if _event_rows:
        _ev_df = pd.DataFrame(_event_rows)
        # 세로선 없이, 금년(cols[0]) 라인의 그 날짜 실제 값 위치에만 마커를 찍는다
        _main_vals = long_df[long_df["구분"] == cols[0]][["_date_label", "값"]]
        _ev_df = _ev_df.merge(_main_vals, on="_date_label", how="left").dropna(subset=["값"])
        if not _ev_df.empty:
            _ev_marker = alt.Chart(_ev_df).mark_point(
                shape="triangle-down", size=110, color="#dc2626", filled=True, opacity=0.95,
            ).encode(
                x=alt.X("_date_label:O", sort=_label_order),
                y=alt.Y("값:Q"),
                tooltip=[alt.Tooltip("_date_label:N", title="날짜"), alt.Tooltip("이벤트:N", title="이벤트")],
            )
            chart = alt.layer(chart, _ev_marker).resolve_scale(x="shared", y="shared")

    # .interactive()를 호출하지 않으므로 휠 확대/축소·드래그 팬이 비활성화됨
    st.altair_chart(chart, use_container_width=True)

    if _event_rows:
        _ev_caption = "  ·  ".join(f"📌 {r['_date_label']} {r['이벤트']}" for r in _event_rows)
        st.caption(_ev_caption)


def render_donut_chart(labels, values, colors=None, center_title="", center_value="", size=300,
                       deltas=None, delta_label="", center_sub=""):
    """클릭 가능한 SVG 도넛 차트.
    - 조각이나 범례를 클릭하면 해당 항목이 강조되고 나머지는 흐려진다(다시 클릭하면 해제).
    - deltas가 주어지면 범례에 항목별 전년 거래액/전년비 증감을 함께 표시한다.
    - JS 동작이 필요하므로 components.html(iframe)로 렌더링한다."""
    import math
    import html as _html

    total = sum(v for v in values if v and v > 0)
    if total <= 0:
        st.info("표시할 데이터가 없습니다.")
        return

    palette = colors or [
        "#2563eb", "#3b82f6", "#60a5fa", "#93c5fd", "#7dd3fc",
        "#38bdf8", "#0ea5e9", "#0284c7", "#a5b4fc", "#c7d2fe", "#e2e8f0",
    ]
    NEG_COLOR = "#ef4444"  # 마이너스(반품 등) 항목은 도넛 조각엔 안 넣지만, 범례엔 이 색으로 표시
    cx = cy = size / 2
    r_outer = size / 2 - 6
    r_inner = r_outer * 0.62

    def _pt(r, ang):
        rad = math.radians(ang - 90)
        return cx + r * math.cos(rad), cy + r * math.sin(rad)

    paths = []
    start = 0.0
    visible_idx = []
    for i, (lab, val) in enumerate(zip(labels, values)):
        if not val or val <= 0:
            continue
        visible_idx.append(i)
        frac = val / total
        end = start + frac * 360
        mid = (start + end) / 2
        # 선택 시 바깥으로 살짝 튀어나오는 오프셋
        _mrad = math.radians(mid - 90)
        pop = f"translate({math.cos(_mrad) * 9:.2f}px, {math.sin(_mrad) * 9:.2f}px)"
        tip = _html.escape(f"{lab}: {val:,.0f} ({frac * 100:.1f}%)")
        color = palette[i % len(palette)]

        if frac >= 0.9999:
            paths.append(
                f"<circle class='seg' data-i='{i}' data-pop='{pop}' cx='{cx}' cy='{cy}' "
                f"r='{(r_outer + r_inner) / 2:.2f}' fill='none' stroke='{color}' "
                f"stroke-width='{r_outer - r_inner:.2f}'><title>{tip}</title></circle>"
            )
            start = end
            continue

        large = 1 if (end - start) > 180 else 0
        x1, y1 = _pt(r_outer, start)
        x2, y2 = _pt(r_outer, end)
        x3, y3 = _pt(r_inner, end)
        x4, y4 = _pt(r_inner, start)
        d = (
            f"M {x1:.2f} {y1:.2f} A {r_outer:.2f} {r_outer:.2f} 0 {large} 1 {x2:.2f} {y2:.2f} "
            f"L {x3:.2f} {y3:.2f} A {r_inner:.2f} {r_inner:.2f} 0 {large} 0 {x4:.2f} {y4:.2f} Z"
        )
        paths.append(
            f"<path class='seg' data-i='{i}' data-pop='{pop}' d='{d}' fill='{color}' "
            f"stroke='#fff' stroke-width='1.5'><title>{tip}</title></path>"
        )
        start = end

    center_html = ""
    if center_title or center_value or center_sub:
        _cy_base = cy - 14 if center_sub else cy - 6
        center_html = (
            f"<text x='{cx}' y='{_cy_base}' text-anchor='middle' font-size='11' fill='#6b7280' "
            f"style='pointer-events:none'>{_html.escape(center_title)}</text>"
            f"<text x='{cx}' y='{_cy_base + 20}' text-anchor='middle' font-size='15' font-weight='700' "
            f"fill='#111827' style='pointer-events:none'>{_html.escape(center_value)}</text>"
        )
        if center_sub:
            center_html += (
                f"<text x='{cx}' y='{_cy_base + 38}' text-anchor='middle' font-size='10.5' "
                f"fill='#6b7280' style='pointer-events:none'>{_html.escape(center_sub)}</text>"
            )

    _has_delta = deltas is not None
    header_html = ""
    if _has_delta:
        header_html = (
            "<div class='lg-head'>"
            "<span style='width:17px;flex-shrink:0;'></span>"
            "<span style='flex:1;'>항목</span>"
            "<span style='width:96px;text-align:right;'>올해</span>"
            "<span style='width:44px;text-align:right;'>비중</span>"
            "<span style='width:96px;text-align:right;'>작년</span>"
            f"<span style='width:70px;text-align:right;'>{_html.escape(delta_label or '전년비')}</span>"
            "</div>"
        )

    def _delta_span(v):
        if v is None:
            return "<span style='color:#9ca3af'>-</span>"
        color = "#16a34a" if v >= 0 else "#dc2626"
        arrow = "▲" if v >= 0 else "▼"
        return f"<span style='color:{color};font-weight:600'>{arrow} {abs(v):.1f}%</span>"

    legend_items = []
    for i, (lab, val) in enumerate(zip(labels, values)):
        if not val:
            continue
        is_neg = val < 0
        pct = val / total * 100
        _dot_color = NEG_COLOR if is_neg else palette[i % len(palette)]
        row = (
            f"<div class='lg' data-i='{i}'>"
            f"<span class='dot' style='background:{_dot_color};'></span>"
            f"<span style='flex:1;color:#374151;'>{_html.escape(str(lab))}</span>"
        )
        if _has_delta:
            _d = deltas[i] if i < len(deltas) else None
            _prev_val = _d.get("prev") if isinstance(_d, dict) else None
            _yoy_val = _d.get("yoy") if isinstance(_d, dict) else None
            _prev_str = f"{_prev_val:,.0f}" if _prev_val is not None else "-"
            row += (
                f"<span style='color:#374151;width:96px;text-align:right;'>{val:,.0f}</span>"
                f"<span style='color:#9ca3af;width:44px;text-align:right;'>{pct:.1f}%</span>"
                f"<span style='color:#9ca3af;width:96px;text-align:right;'>{_prev_str}</span>"
                f"<span style='width:70px;text-align:right;'>{_delta_span(_yoy_val)}</span>"
            )
        else:
            row += (
                f"<span style='color:#6b7280;margin-left:10px;'>{val:,.0f}</span>"
                f"<span style='color:#9ca3af;margin-left:8px;width:48px;text-align:right;'>{pct:.1f}%</span>"
            )
        row += "</div>"
        legend_items.append(row)

    n_rows = len(legend_items)
    frame_h = int(max(size + 46, 70 + n_rows * 25 + (24 if _has_delta else 0)))
    legend_min = 440 if _has_delta else 260

    doc = f"""
<!DOCTYPE html><html><head><meta charset='utf-8'><style>
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font-family:'Source Sans Pro','Apple SD Gothic Neo','Malgun Gothic',sans-serif; }}
  .wrap {{ display:flex; align-items:center; gap:24px; flex-wrap:wrap;
          background:#fff; border:1px solid #e5e7eb; border-radius:10px; padding:16px 20px; }}
  svg {{ flex-shrink:0; }}
  .seg {{ cursor:pointer; transition:opacity .15s ease, transform .15s ease; }}
  .seg.dim {{ opacity:.22; }}
  .legend {{ flex:1; min-width:{legend_min}px; }}
  .lg-head {{ display:flex; align-items:center; font-size:11px; color:#9ca3af;
              border-bottom:1px solid #f1f2f4; padding-bottom:4px; margin-bottom:6px; }}
  .lg {{ display:flex; align-items:center; margin-bottom:4px; font-size:12.5px;
         cursor:pointer; border-radius:5px; padding:2px 5px; transition:opacity .15s, background .15s; }}
  .lg:hover {{ background:#f8fafc; }}
  .lg.sel {{ background:#eef2ff; font-weight:600; }}
  .lg.dim {{ opacity:.4; }}
  .dot {{ display:inline-block; width:10px; height:10px; border-radius:2px;
          margin-right:7px; flex-shrink:0; }}
  .hint {{ font-size:10.5px; color:#9ca3af; margin-top:8px; }}
</style></head><body>
<div class='wrap'>
  <svg width='{size}' height='{size}' viewBox='0 0 {size} {size}'>{''.join(paths)}{center_html}</svg>
  <div class='legend'>{header_html}{''.join(legend_items)}
    <div class='hint'>💡 조각이나 항목을 클릭하면 해당 항목만 강조됩니다 (다시 클릭하면 해제)</div>
  </div>
</div>
<script>
(function() {{
  var sel = null;
  var segs = Array.prototype.slice.call(document.querySelectorAll('.seg'));
  var lgs  = Array.prototype.slice.call(document.querySelectorAll('.lg'));
  function apply() {{
    segs.forEach(function(s) {{
      var i = parseInt(s.getAttribute('data-i'), 10);
      if (sel === null) {{ s.classList.remove('dim'); s.style.transform = ''; }}
      else if (i === sel) {{ s.classList.remove('dim'); s.style.transform = s.getAttribute('data-pop'); }}
      else {{ s.classList.add('dim'); s.style.transform = ''; }}
    }});
    lgs.forEach(function(l) {{
      var i = parseInt(l.getAttribute('data-i'), 10);
      l.classList.toggle('sel', sel === i);
      l.classList.toggle('dim', sel !== null && i !== sel);
    }});
  }}
  function toggle(i) {{ sel = (sel === i) ? null : i; apply(); }}
  segs.forEach(function(s) {{
    s.addEventListener('click', function() {{ toggle(parseInt(s.getAttribute('data-i'), 10)); }});
  }});
  lgs.forEach(function(l) {{
    l.addEventListener('click', function() {{ toggle(parseInt(l.getAttribute('data-i'), 10)); }});
  }});
}})();
</script></body></html>
"""
    components.html(doc, height=frame_h, scrolling=False)


def compute_official_total(df_scope, unit, selected_period_date):
    """df_scope(보통 카테고리='전체'&브랜드='전체' 등으로 필터된 단일 그룹)의
    거래액을 조회단위로 리샘플하여 (현재값, 전년동기값) 튜플로 반환.
    도넛 중앙에 표시할 '진짜 전체값'을 개별 항목 합산과 별개로 정확히 구하기 위함.
    compute_kpi_deltas를 그대로 재사용해서, 진행 중인(부분) 달/주에도 KPI 카드·요약표와
    똑같은 기준(같은 날짜 수만큼 동요일 매칭)으로 전년비가 계산되도록 한다."""
    if df_scope.empty:
        return None, None
    s_full = df_scope.set_index("날짜")["거래액"].sort_index()
    _agg = "sum" if unit == "월마감" else "mean"
    series_full = s_full.resample(UNIT_CONFIG[unit]["rule"]).agg(_agg)
    if unit == "주별":
        series_full.index = series_full.index - pd.Timedelta(days=6)
    elif unit == "월마감" and not series_full.empty and s_full.index.max() < series_full.index[-1]:
        series_full = series_full.iloc[:-1]
    series = series_full[series_full.index <= selected_period_date] if not series_full.empty else series_full
    if series.empty:
        return None, None
    _s_raw = s_full[s_full.index <= selected_period_date] if selected_period_date is not None else s_full
    stats = compute_kpi_deltas(series, unit, raw_daily=_s_raw)
    if stats is None:
        return None, None
    return stats["current"], stats.get("yoy_value")


def render_revenue_ranking(sub_df, group_col, unit, selected_period_date, title, subtitle, label_map=None, hide_zero=False, ai_key=None, ai_context=None, donut=False, official_total=None):
    """
    official_total: (현재값, 작년값) 튜플이 주어지면, 도넛 중앙의 '총 거래액'을
    개별 항목 합산이 아니라 이 값으로 표시한다. (카테고리/브랜드가 여러 개 겹치는 거래는
    개별 항목 합산이 실제 전체보다 커질 수 있어, KPI 카드와 항상 일치시키기 위함)

    group_col(카테고리 또는 브랜드) 기준 거래액 랭킹을 올해/작년 이중 막대로 렌더링.
    label_map이 주어지면 표시 라벨을 매핑해서 보여준다 (예: 브랜드코드 -> 브랜드명).
    hide_zero=True면 올해/작년 거래액이 둘 다 0(또는 0에 가까움)인 항목은 목록에서 제외.
    ai_key가 주어지면 'AI 인사이트' 버튼과 결과 박스를 함께 표시한다.
    """
    rows = []
    for name in sorted(sub_df[group_col].unique()):
        s_full = sub_df[sub_df[group_col] == name].set_index("날짜")["거래액"].sort_index()
        _agg = "sum" if unit == "월마감" else "mean"
        series_full = s_full.resample(UNIT_CONFIG[unit]["rule"]).agg(_agg)
        if unit == "주별":
            series_full.index = series_full.index - pd.Timedelta(days=6)
        elif unit == "월마감" and not series_full.empty and s_full.index.max() < series_full.index[-1]:
            series_full = series_full.iloc[:-1]
        series = series_full[series_full.index <= selected_period_date] if not series_full.empty else series_full
        if series.empty:
            continue
        _s_raw = s_full[s_full.index <= selected_period_date] if selected_period_date is not None else s_full
        # compute_kpi_deltas 재사용 — KPI 카드·요약표와 동일 기준(부분월이면 동요일 매칭)으로 전년비 계산
        _stats = compute_kpi_deltas(series, unit, raw_daily=_s_raw)
        if _stats is None:
            continue
        cur_val = _stats["current"]
        prev_val = _stats.get("yoy_value")

        if hide_zero:
            _cur_zero = pd.isna(cur_val) or abs(cur_val) < 0.5
            _prev_zero = prev_val is None or pd.isna(prev_val) or abs(prev_val) < 0.5
            if _cur_zero and _prev_zero:
                continue

        rows.append({group_col: name, "거래액": cur_val, "전년거래액": prev_val})

    if ai_key:
        _rk_c1, _rk_c2 = st.columns([4, 1])
        with _rk_c1:
            st.markdown(f"**{title}**  ·  <span style='color:#6b7280;font-size:0.85rem'>{subtitle}</span>", unsafe_allow_html=True)
        with _rk_c2:
            _rk_clicked = st.button("🤖 AI 인사이트", key=f"ai_btn_{ai_key}", use_container_width=True)
    else:
        st.markdown(f"**{title}**  ·  <span style='color:#6b7280;font-size:0.85rem'>{subtitle}</span>", unsafe_allow_html=True)
        _rk_clicked = False

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

    # --- AI 인사이트 (요청 시) ---
    if ai_key:
        _ai_rank_result = None
        _rk_ctx_key = f"ai_rank_ctx_{ai_key}"
        _rk_cur_ctx = ai_context or subtitle
        if _rk_clicked:
            _rank_payload = []
            for _, r in share_df.iterrows():
                _nm = r[group_col]
                _nm_disp = label_map.get(_nm, _nm) if label_map else _nm
                _yv = None
                if pd.notna(r["전년거래액"]) and r["전년거래액"] != 0:
                    _yv = ((r["거래액"] / r["전년거래액"]) - 1) * 100
                _rank_payload.append({
                    "name": str(_nm_disp),
                    "current": float(r["거래액"]) if pd.notna(r["거래액"]) else 0.0,
                    "prev": float(r["전년거래액"]) if pd.notna(r["전년거래액"]) else 0.0,
                    "share": float(r["비중"]),
                    "yoy": round(float(_yv), 1) if _yv is not None else None,
                })
            with st.spinner("AI 인사이트 생성 중..."):
                _ai_rank_result = generate_ranking_insights(
                    _rank_payload, ai_context or subtitle, f"rank_{ai_key}"
                )
                st.session_state[f"ai_rank_result_{ai_key}"] = _ai_rank_result
                st.session_state[_rk_ctx_key] = _rk_cur_ctx
        elif (
            f"ai_rank_result_{ai_key}" in st.session_state
            and st.session_state.get(_rk_ctx_key) == _rk_cur_ctx
        ):
            _ai_rank_result = st.session_state[f"ai_rank_result_{ai_key}"]
        else:
            # 매체/세그먼트/조회단위 등 조회 조건이 바뀌어서 이전 인사이트가 더 이상
            # 맞지 않으므로 캐시를 지운다 (버튼을 다시 눌러야 새 조건으로 재생성됨).
            st.session_state.pop(f"ai_rank_result_{ai_key}", None)
            st.session_state.pop(_rk_ctx_key, None)
        render_ranking_insight_box(_ai_rank_result)

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
    # --- 도넛 차트 모드: 구성비를 한눈에 + 전년비 상세는 접이식 ---
    if donut:
        _top_n = 10
        _dn_pos = share_df[share_df["거래액"] > 0].copy()
        _dn_neg = share_df[share_df["거래액"] < 0].copy()
        _labels, _values, _deltas = [], [], []
        for _, r in _dn_pos.head(_top_n).iterrows():
            _nm = r[group_col]
            _labels.append(str(label_map.get(_nm, _nm) if label_map else _nm))
            _values.append(float(r["거래액"]))
            _pv = float(r["전년거래액"]) if pd.notna(r["전년거래액"]) else None
            _yv = ((r["거래액"] / r["전년거래액"]) - 1) * 100 if (_pv is not None and r["전년거래액"] != 0) else None
            _deltas.append({"prev": _pv, "yoy": _yv})

        _rest_df = _dn_pos.iloc[_top_n:] if len(_dn_pos) > _top_n else None
        if _rest_df is not None and len(_rest_df) > 0:
            _rest_cur = float(_rest_df["거래액"].sum())
            if _rest_cur > 0:
                _rest_prev = float(_rest_df["전년거래액"].sum(skipna=True)) if _rest_df["전년거래액"].notna().any() else None
                _rest_yoy = ((_rest_cur / _rest_prev) - 1) * 100 if (_rest_prev and _rest_prev != 0) else None
                _labels.append(f"기타 ({len(_rest_df)}개)")
                _values.append(_rest_cur)
                _deltas.append({"prev": _rest_prev, "yoy": _rest_yoy})

        # 거래액이 마이너스인 항목(반품 등으로 순거래액이 음수)도 도넛에 그대로 포함시킨다.
        # top_n/기타 묶음과는 무관하게 항상 개별 조각으로 넣어서 묻히지 않게 함
        # (render_donut_chart 쪽에서 절대값 크기로 조각을 그리고 빨간 점선으로 구분해서 보여줌).
        for _, r in _dn_neg.sort_values("거래액").iterrows():
            _nm = r[group_col]
            _labels.append(str(label_map.get(_nm, _nm) if label_map else _nm))
            _values.append(float(r["거래액"]))
            _pv = float(r["전년거래액"]) if pd.notna(r["전년거래액"]) else None
            _yv = ((r["거래액"] / r["전년거래액"]) - 1) * 100 if (_pv is not None and r["전년거래액"] != 0) else None
            _deltas.append({"prev": _pv, "yoy": _yv})

        # 전체 합계 기준 전년비 — official_total(카테고리=전체 등 진짜 전체값)이 있으면 그걸 우선 사용.
        # (개별 항목을 단순 합산하면, 여러 카테고리에 걸친 거래가 중복 집계되어
        #  KPI 카드의 진짜 전체값보다 커질 수 있음 — 그래서 중앙 표시는 항상 official_total과 일치시킴)
        if official_total is not None:
            _tot_cur, _tot_prev = official_total
            _tot_cur = float(_tot_cur) if _tot_cur is not None else float(share_df["거래액"].sum())
        else:
            _tot_cur = float(share_df["거래액"].sum())
            _tot_prev = float(share_df["전년거래액"].sum(skipna=True)) if share_df["전년거래액"].notna().any() else None
        if _tot_prev and _tot_prev != 0:
            _tot_yoy = ((_tot_cur / _tot_prev) - 1) * 100
            _center_sub = f"{_yoy_label_share} {_tot_yoy:+.1f}%"
        else:
            _center_sub = ""

        render_donut_chart(
            _labels, _values,
            center_title="총 거래액",
            center_value=f"{_tot_cur:,.0f}",
            center_sub=_center_sub,
            deltas=_deltas,
            delta_label=_yoy_label_share,
        )
        if official_total is not None:
            st.caption(
                "ℹ️ 중앙 '총 거래액'은 KPI카드와 동일한 전체 집계값이에요. "
                "여러 카테고리/브랜드에 걸친 거래가 있으면, 아래 항목별 값을 다 더한 합계는 "
                "이 값과 정확히 일치하지 않을 수 있어요(항목 간 중복 집계 가능)."
            )
        if len(_dn_neg) > 0:
            st.caption(
                "🔴 빨간 점 항목은 거래액이 마이너스예요(반품 등으로 환불이 매출보다 많은 경우). "
                "도넛 조각으로는 표시되지 않고, 오른쪽 목록에 실제 마이너스 값 그대로 표시돼요."
            )

        with st.expander(f"📊 전체 항목 · 전년 대비 막대로 보기 ({_yoy_label_share})", expanded=False):
            st.markdown(
                "<div style='display:flex;gap:14px;margin-bottom:10px;font-size:0.76rem;color:#6b7280;'>"
                "<span><span style='display:inline-block;width:10px;height:10px;background:#2563eb;border-radius:2px;margin-right:4px;'></span>올해</span>"
                "<span><span style='display:inline-block;width:10px;height:10px;background:#7dd3fc;border-radius:2px;margin-right:4px;'></span>작년(동시점)</span>"
                "</div>" + "".join(bar_rows_html),
                unsafe_allow_html=True,
            )
        return

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
        "5": "🎟️ 쿠폰 비용 분석", "6": "📑 주간보고용",
        "7": "📅 전체 실적 (주차별)", "8": "📅 회원 실적 (주차별)", "9": "📅 신규 실적 (주차별)",
    }

    # ========================================================
    # 페이지 5: 쿠폰 비용 분석 — 매체/쿠폰유형/기준일자(또는 기준시점)를
    # 1·2번 페이지와 동일하게 상단 고정 필터로 올림
    # ========================================================
    if _page_num == "5":
        _cp_bpu_options_top = (
            [b for b in ["Total", "자사", "입점", "e-영업1", "e-영업2", "e-영업3", "e-영업4"] if b in df_coupon["BPU"].unique()]
            if not df_coupon.empty else []
        )
        coupon_unit = "월별" if unit in ("월별", "월마감") else unit

        if not _cp_bpu_options_top:
            st.markdown(
                f"<span style='font-size:1.15rem;font-weight:700;'>{_page_titles[_page_num]}</span>",
                unsafe_allow_html=True,
            )
        else:
            # 기준 시점 옵션: 매체/쿠폰유형 선택과 무관하게, 존재하는 날짜 전체를 기준으로 산출
            # (페이지1/2도 매체 선택 전에 Total 기준으로 기간 옵션부터 만드는 것과 동일한 방식)
            if coupon_unit == "월별":
                _cp_period_s = df_coupon.groupby("연월")["쿠폰할인"].sum().sort_index()
            else:
                _cp_rule_preview = "D" if coupon_unit == "일별" else "W-SUN"
                _cp_period_s = df_coupon_daily.groupby("날짜")["쿠폰할인"].sum().resample(_cp_rule_preview).sum()
                if coupon_unit == "주별":
                    _cp_period_s.index = _cp_period_s.index - pd.Timedelta(days=6)

            if coupon_unit == "일별":
                _cp_min_d = _cp_period_s.index.min().date()
                _cp_max_d = _cp_period_s.index.max().date()
                _cp_prev_date = st.session_state.get("coupon_ref_date", _cp_max_d)
                try:
                    _cp_ref_preview = pd.Timestamp(_cp_prev_date).strftime("%Y-%m-%d")
                except Exception:
                    _cp_ref_preview = _cp_max_d.strftime("%Y-%m-%d")
            else:
                _cp_period_labels = [
                    (d.strftime("%Y년 %m월") if coupon_unit == "월별" else f"{d.strftime('%Y-%m-%d')} 주")
                    for d in _cp_period_s.index
                ]
                _cp_default_label = _cp_period_labels[-1] if _cp_period_labels else ""
                _cp_prev_label_sel = st.session_state.get("coupon_ref_period", _cp_default_label)
                _cp_ref_preview = _cp_prev_label_sel if _cp_prev_label_sel in _cp_period_labels else _cp_default_label

            st.markdown(
                f"<div style='display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin-bottom:6px;'>"
                f"<span style='font-size:1.15rem;font-weight:700;'>{_page_titles[_page_num]}</span>"
                f"<span style='font-size:0.8rem;color:#6b7280;'>조회 단위: <b>{coupon_unit}</b> · 기준: <b>{_cp_ref_preview}</b></span>"
                f"</div>",
                unsafe_allow_html=True,
            )

            fc1, fc2, fc3, _fc_spacer = st.columns([1, 1, 1, 5])
            with fc1:
                st.markdown("<div style='font-size:0.78rem;color:#6b7280;margin-bottom:1px;'>매체</div>", unsafe_allow_html=True)
                coupon_bpu = st.selectbox("매체", _cp_bpu_options_top, index=0, key="coupon_bpu", label_visibility="collapsed")
            with fc2:
                st.markdown("<div style='font-size:0.78rem;color:#6b7280;margin-bottom:1px;'>쿠폰 유형</div>", unsafe_allow_html=True)
                coupon_type_sel = st.radio(
                    "쿠폰유형", ["합산", "플러스", "일반"], horizontal=True, key="coupon_type_sel", label_visibility="collapsed",
                )
            with fc3:
                _cp_label3 = "기준 일자" if coupon_unit == "일별" else "기준 시점"
                st.markdown(f"<div style='font-size:0.78rem;color:#6b7280;margin-bottom:1px;'>{_cp_label3}</div>", unsafe_allow_html=True)
                if coupon_unit == "일별":
                    _cp_sel_date = st.date_input(
                        "기준 일자", value=_cp_max_d, min_value=_cp_min_d, max_value=_cp_max_d,
                        label_visibility="collapsed", key="coupon_ref_date",
                    )
                    coupon_ref_ts = pd.Timestamp(_cp_sel_date)
                    if coupon_ref_ts not in _cp_period_s.index:
                        _cand = _cp_period_s.index[_cp_period_s.index <= coupon_ref_ts]
                        coupon_ref_ts = _cand[-1] if len(_cand) else _cp_period_s.index[-1]
                else:
                    _cp_sel_label = st.selectbox(
                        "기준 시점", _cp_period_labels, index=len(_cp_period_labels) - 1,
                        label_visibility="collapsed", key="coupon_ref_period",
                    )
                    coupon_ref_ts = _cp_period_s.index[_cp_period_labels.index(_cp_sel_label)]

    # ========================================================
    # 페이지 1 / 2: 매체필터 + 기준시점 (+카테고리/브랜드)
    # ========================================================
    elif _page_num in ("1", "2"):
        # 기준 시점 옵션: 페이지1은 트래픽(EP실적) 데이터, 페이지2는 카테고리 데이터 기준으로 생성
        # (두 데이터의 최신 날짜가 다를 수 있어, 실제 존재하는 기간만 선택지로 제공)
        if _page_num == "2" and not df_category.empty:
            _period_base_df = df_category[(df_category["카테고리"] == "전체") & (df_category["브랜드"] == "전체")]
            if "회원구분" in _period_base_df.columns:
                _period_base_df = _period_base_df[_period_base_df["회원구분"] == "전체"]
            _period_metric_col = "트래픽"
        else:
            _period_base_df = df_traffic[(df_traffic["BPU"] == "Total") & (df_traffic["회원구분"] == "전체")]
            _period_metric_col = "트래픽"

        _period_s = _period_base_df.set_index("날짜")[_period_metric_col].resample(UNIT_CONFIG[unit]["rule"]).mean().dropna()
        if unit == "주별":
            _period_s.index = _period_s.index - pd.Timedelta(days=6)
        if unit == "월마감":
            _last_base_date = _period_base_df["날짜"].max()
            if not _period_s.empty and _last_base_date < _period_s.index[-1]:
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
        _ff_exclude = False  # 기본값 (아래에서 조건에 맞으면 덮어씀)
        if _is_cat_page:
            fc1, fc2, fc3, fc4, fc5, _fc_spacer = st.columns([1, 1, 1, 1, 1, 5])
        else:
            fc1, fc2, fc3, _fc_spacer = st.columns([1, 1, 1, 7])

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

        # 1번 페이지(카테고리 필터가 없는 페이지)는 매체필터/기준시점과 같은 줄 fc3에 핏플랍 제외 배치
        # (2번 페이지는 카테고리/브랜드 뒤 fc5에 배치 — 두 페이지 다 '마지막 필터 바로 옆' 위치로 통일)
        if not _is_cat_page:
            if (not df_category.empty) and (df_category["브랜드"] == "FF").any():
                with fc3:
                    st.markdown("<div style='font-size:0.78rem;color:#6b7280;margin-bottom:1px;'>&nbsp;</div>", unsafe_allow_html=True)
                    _ff_exclude = st.checkbox(
                        "핏플랍 제외",
                        value=st.session_state.get("cat_ff_exclude", False), key="cat_ff_exclude",
                        help="핏플랍은 2025년 10월에 종료된 브랜드예요. 켜면 카테고리 원본(ep_category.csv)에서 "
                             "FF 실적을 찾아 EP실적(트래픽/거래액/구매객수)에서도 빼고 CR/객단가를 다시 계산해요. "
                             "2번 페이지의 체크박스와 같은 설정을 공유해요.",
                    )
            else:
                _ff_exclude = False

        # 카테고리 페이지일 때만 매체필터 옆에 카테고리/브랜드 필터 노출
        selected_cat, selected_brand = "전체", "전체"
        cat_segment = "전체"
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

            # 핏플랍(FF) 제외 — 브랜드 필터 옆에 배치, FF 브랜드 데이터가 실제로 있을 때만 노출
            with fc5:
                if (df_category["브랜드"] == "FF").any():
                    st.markdown("<div style='font-size:0.78rem;color:#6b7280;margin-bottom:1px;'>&nbsp;</div>", unsafe_allow_html=True)
                    _ff_exclude = st.checkbox(
                        "핏플랍 제외",
                        value=False, key="cat_ff_exclude",
                        help="핏플랍은 2025년 10월에 종료된 브랜드예요. 켜면 슈즈 카테고리·전체 집계에서 "
                             "FF 실적을 빼고 CR/객단가까지 다시 계산해서 보여줘요 (트래픽/구매객수도 같이 빠짐).",
                    )
                else:
                    _ff_exclude = False

            # 세그먼트(고객 구분) — 카테고리 레벨(브랜드=전체)에서만 제공
            _has_segment = "회원구분" in df_category.columns
            if _has_segment and selected_brand == "전체":
                _cat_seg_options = [s for s in ["전체", "회원", "비회원", "신규", "기존"] if s in df_category["회원구분"].unique()]
            else:
                _cat_seg_options = ["전체"]
            if len(_cat_seg_options) > 1:
                st.markdown("<div style='margin-top:6px;'></div>", unsafe_allow_html=True)
                cat_segment = st.radio(
                    "고객 구분", _cat_seg_options, horizontal=True,
                    key="cat_seg_filter", label_visibility="collapsed",
                )
            else:
                cat_segment = "전체"
                if _has_segment and selected_brand != "전체":
                    st.caption("ℹ️ 브랜드별 데이터는 전체 세그먼트만 제공됩니다.")

        # 페이지1(실적요약)일 때는 EP실적용 세그먼트(고객 구분) 필터만 노출 (핏플랍 제외는 위 fc3에서 처리됨)
        if _page_num == "1":
            _seg_options = [s for s in ["전체", "회원", "비회원", "신규", "기존"] if s in df_traffic["회원구분"].unique()]
            st.markdown("<div style='margin-top:6px;'></div>", unsafe_allow_html=True)
            segment = st.radio(
                "고객 구분", _seg_options, horizontal=True,
                key="seg_filter", label_visibility="collapsed",
            )

        period_label = make_period_label(selected_period_date, unit)

    # ========================================================
    # 페이지 6: 주간보고용은 자체 필터(기준 시점)를 페이지 본문에서 처리하므로,
    # 여기서는 간단한 제목만 표시
    # ========================================================
    elif _page_num == "6":
        st.markdown(
            f"<span style='font-size:1.15rem;font-weight:700;'>{_page_titles[_page_num]}</span>",
            unsafe_allow_html=True,
        )

    # ========================================================
    # 페이지 7/8/9: 전체·회원·신규 실적(주차별) — 주차 범위 필터를 상단 고정 영역에 배치
    # (세 페이지가 세그먼트만 다르고 주차 필터 UI는 동일해서 하나로 묶음)
    # ========================================================
    elif _page_num in ("7", "8", "9"):
        st.markdown(
            f"<span style='font-size:1.15rem;font-weight:700;'>{_page_titles[_page_num]}</span>",
            unsafe_allow_html=True,
        )
        if df_traffic.empty:
            wk_range = (1, 1)
        else:
            # 25년/26년 각각의 실제 데이터로 라벨을 만들고(두 해가 다르게 밀릴 수 있어서),
            # 더 긴 쪽(보통 25년, 최대 53주)을 기준으로 슬라이더를 그린다.
            # _week_labels_for_year가 _weekly_of_year와 정확히 같은 순서로 라벨을 만들어서
            # 인덱스가 어긋나지 않는다.
            _wk7_total = df_traffic[df_traffic["BPU"] == "Total"]
            _wk7_labels_25 = _week_labels_for_year(_wk7_total, "트래픽", 2025)
            _wk7_labels_26 = _week_labels_for_year(_wk7_total, "트래픽", 2026)
            _wk7_labels = _wk7_labels_25 if len(_wk7_labels_25) >= len(_wk7_labels_26) else _wk7_labels_26
            if not _wk7_labels:
                _wk7_labels = ["1주차"]

            # 기본값 = 최근 10주. '최근'은 26년(진행 중인 올해) 기준 마지막 주차로 잡고,
            # 26년 데이터가 없으면 라벨 목록 전체의 마지막 10주로 대체한다.
            _wk7_latest_wk = len(_wk7_labels_26) if _wk7_labels_26 else len(_wk7_labels)
            _wk7_default_end = max(1, min(_wk7_latest_wk, len(_wk7_labels)))
            _wk7_default_start = max(1, _wk7_default_end - 9)

            _wk7_c1, _wk7_spacer = st.columns([2, 3])
            with _wk7_c1:
                st.markdown("<div style='font-size:0.78rem;color:#6b7280;margin-bottom:1px;'>주차 범위</div>", unsafe_allow_html=True)
                _wk7_sel_labels = st.select_slider(
                    "주차 범위", options=_wk7_labels,
                    value=(_wk7_labels[_wk7_default_start - 1], _wk7_labels[_wk7_default_end - 1]),
                    label_visibility="collapsed", key="wk_traffic_range",
                )
            wk_range = (_wk7_labels.index(_wk7_sel_labels[0]) + 1, _wk7_labels.index(_wk7_sel_labels[1]) + 1)

    # ========================================================
    # 페이지 3 / 4: 매체필터 + 기간유형 + 시작일/종료일 (+카테고리/브랜드)
    # ========================================================
    else:
        CUM_UNIT_OPTIONS = [("일자별", "일별"), ("주차별", "주별"), ("월별", "월별"), ("월마감", "월마감")]

        _cum_bpu_prev = st.session_state.get("cum_bpu_filter", "전체")
        _cum_unit_prev = st.session_state.get("cum_unit_filter", "일자별")
        _cum_agg_prev = st.session_state.get("cum_agg_mode", "일평균")
        st.markdown(
            f"<div style='display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin-bottom:6px;'>"
            f"<span style='font-size:1.15rem;font-weight:700;'>{_page_titles[_page_num]}</span>"
            f"<span style='font-size:0.8rem;color:#6b7280;'>매체: <b>{_cum_bpu_prev}</b> · 기간유형: <b>{_cum_unit_prev}</b> · 집계: <b>{_cum_agg_prev}</b></span>"
            f"</div>",
            unsafe_allow_html=True,
        )

        _is_cum_cat_page = _page_num == "4"
        gc1, gc2, gc3, gc4, gc5, _gc_spacer = st.columns([1, 1, 1, 1, 1, 3])

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

        with gc3:
            st.markdown("<div style='font-size:0.78rem;color:#6b7280;margin-bottom:1px;'>집계 방식</div>", unsafe_allow_html=True)
            if cum_unit == "월마감":
                # 월마감은 '완료된 달의 총 실적'을 보는 기준이라 일평균은 의미가 없어서 누적으로 고정.
                # (일별/주별/월별에서는 그대로 일평균/누적 토글 가능)
                cum_agg_mode = "누적"
                st.markdown(
                    "<div style='padding:0.4rem 0.6rem;background:#f3f4f6;border-radius:6px;"
                    "font-size:0.85rem;color:#374151;'>누적 <span style='color:#9ca3af;font-size:0.72rem;'>"
                    "(월마감은 항상 누적)</span></div>",
                    unsafe_allow_html=True,
                )
            else:
                cum_agg_mode = st.selectbox(
                    "집계 방식", ["일평균", "누적"],
                    label_visibility="collapsed", key="cum_agg_mode",
                )

        # 데이터 있는 전체 날짜 범위 (트래픽 데이터 기준)
        _cum_min_d = df_traffic["날짜"].min().date()
        _cum_max_d = df_traffic["날짜"].max().date()

        with gc4:
            st.markdown("<div style='font-size:0.78rem;color:#6b7280;margin-bottom:1px;'>시작일</div>", unsafe_allow_html=True)
            cum_start = st.date_input(
                "시작일", value=_cum_min_d, min_value=_cum_min_d, max_value=_cum_max_d,
                label_visibility="collapsed", key="cum_start_date",
            )
        with gc5:
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


        # 페이지3(누적 데이터)/4(카테고리)는 둘째 줄에 세그먼트(고객 구분) 필터 추가
        cum_segment = "전체"
        if _page_num == "3":
            _cum_seg_options = [s for s in ["전체", "회원", "비회원", "신규", "기존"] if s in df_traffic["회원구분"].unique()]
            if len(_cum_seg_options) > 1:
                st.markdown("<div style='margin-top:8px;'></div>", unsafe_allow_html=True)
                cum_segment = st.radio(
                    "고객 구분", _cum_seg_options, horizontal=True,
                    key="cum_seg_filter", label_visibility="collapsed",
                )
        elif _page_num == "4":
            _has_cum_cat_segment = "회원구분" in df_category.columns
            if _has_cum_cat_segment and selected_brand == "전체":
                _cum_cat_seg_options = [s for s in ["전체", "회원", "비회원", "신규", "기존"] if s in df_category["회원구분"].unique()]
            else:
                _cum_cat_seg_options = ["전체"]
            if len(_cum_cat_seg_options) > 1:
                st.markdown("<div style='margin-top:8px;'></div>", unsafe_allow_html=True)
                cum_segment = st.radio(
                    "고객 구분", _cum_cat_seg_options, horizontal=True,
                    key="cum_cat_seg_filter", label_visibility="collapsed",
                )
            elif _has_cum_cat_segment and selected_brand != "전체":
                st.caption("ℹ️ 브랜드별 데이터는 전체 세그먼트만 제공됩니다.")

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
    /* '전년 비교선 표시' 체크박스를 각자 컬럼의 오른쪽 끝에 붙임 (기본은 왼쪽 정렬이라
       [3,1,1] 비율의 마지막 칸에서 체크박스와 라벨 뒤로 빈 공간이 남는 문제 해결).
       내부 label이 컨테이너 폭 전체로 늘어나면 justify-content가 무효화되므로
       label 자체도 콘텐츠 크기로 고정한다. */
    .st-key-tr_yoy, .st-key-ep_yoy_cb, .st-key-cat_yoy {
        width: 100% !important;
        display: flex !important;
        justify-content: flex-end !important;
    }
    .st-key-tr_yoy label, .st-key-ep_yoy_cb label, .st-key-cat_yoy label,
    .st-key-tr_yoy div[data-testid="stCheckbox"], .st-key-ep_yoy_cb div[data-testid="stCheckbox"],
    .st-key-cat_yoy div[data-testid="stCheckbox"] {
        flex: 0 0 auto !important;
        width: auto !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# 고정된 필터 영역이 차지하던 자리만큼, 아래 콘텐츠가 가려지지 않도록 여백 확보
if _page_num == "4":
    _spacer_height = 155
elif _page_num in ("1", "2", "3"):
    _spacer_height = 100
else:
    _spacer_height = 65
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
    # 핏플랍(FF) 제외 — 2번 페이지와 체크박스를 공유. df_traffic엔 브랜드 정보가 없어서
    # 카테고리 원본(df_category)에서 FF 기여분을 가져와 빼는 방식 (exclude_ff_from_traffic 참고)
    if _ff_exclude:
        df_traffic = exclude_ff_from_traffic(df_traffic, df_category)

    # ============================================================
    # 상단: EP 실적 (트래픽/거래액/구매객수/CR/객단가)
    # ============================================================
    st.markdown("---")
    st.markdown("### 📈 EP 실적")

    # 세그먼트 필터는 상단 고정 영역에서 이미 선택됨 (segment 변수 재사용)

    # 트래픽 데이터 필터 (자사/입점이면 합산)
    if bpu in BPU_GROUPS:
        tr_combo = aggregate_traffic(df_traffic, BPU_GROUPS[bpu], segment)
        tr_member = aggregate_traffic(df_traffic, BPU_GROUPS[bpu], "회원")
    else:
        tr_combo = df_traffic[(df_traffic["BPU"] == bpu) & (df_traffic["회원구분"] == segment)].copy()
        tr_member = df_traffic[(df_traffic["BPU"] == bpu) & (df_traffic["회원구분"] == "회원")].copy()

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
        all_items = TRAFFIC_METRICS

        # 핏플랍(FF) 제외 중일 때, KPI 카드에 참고로 보여줄 FF 기여분 계산용 데이터 준비.
        # df_category에서 FF만 뽑아 지금 선택된 매체(bpu)+세그먼트 범위로 맞춘다.
        # (세그먼트가 카테고리 원본에 없는 비회원/기존이면 FF 기여분을 못 구해서 표기 생략)
        _ff_note_df = None
        if _ff_exclude and not df_category.empty and segment in ("전체", "회원", "신규"):
            _ff_raw = df_category[
                (df_category["브랜드"] == "FF") & (df_category["카테고리"] != "전체") & (df_category["회원구분"] == segment)
            ]
            if bpu in BPU_GROUPS:
                _ff_raw = _ff_raw[_ff_raw["BPU"].isin(BPU_GROUPS[bpu])]
            elif bpu != "Total":
                _ff_raw = _ff_raw[_ff_raw["BPU"] == bpu]
            if not _ff_raw.empty:
                _ff_note_df = _ff_raw.groupby("날짜", as_index=False)[["트래픽", "거래액", "구매객수"]].sum()

        # 1단계: 값/증감 먼저 계산 (AI 인사이트용 payload 구성)
        _kpi_computed = {}
        _ff_computed = {}
        for col_name, display_name in all_items:
            s = tr_combo.set_index("날짜")[col_name].sort_index()
            # 절대값 지표(트래픽/거래액/구매객수)는 월마감이면 합계, 비율 지표(CR/객단가)는 항상 평균
            _agg = "sum" if (unit == "월마감" and col_name in {"트래픽", "거래액", "구매객수"}) else "mean"
            series = s.resample(UNIT_CONFIG[unit]["rule"]).agg(_agg)
            if unit == "주별":
                series.index = series.index - pd.Timedelta(days=6)
            elif unit == "월마감":
                if not series.empty and s.index.max() < series.index[-1]:
                    series = series.iloc[:-1]
            if not series.empty:
                series = series[series.index <= selected_period_date]
            _s_raw = s[s.index <= selected_period_date] if selected_period_date is not None else s
            stats = compute_kpi_deltas(series, unit, raw_daily=_s_raw)
            _kpi_computed[display_name] = (col_name, stats)

            # CR/객단가는 계산되는 값이라 FF 기여분을 따로 표기할 필요 없음 — 여기서 건너뜀
            _ff_stats = None
            if _ff_note_df is not None and col_name in ("트래픽", "거래액", "구매객수"):
                ff_s = _ff_note_df.set_index("날짜")[col_name].sort_index()
                # 메인 시리즈(s)와 날짜 범위를 맞춘다 (FF 매출 0인 날엔 원본에 행 자체가 없어서,
                # 안 맞추면 FF 시리즈만 마지막 날짜가 짧아져 '진행 중인 기간' 판정이 어긋나던 버그 있었음)
                ff_s = ff_s.reindex(s.index, fill_value=0)
                ff_series = ff_s.resample(UNIT_CONFIG[unit]["rule"]).agg(_agg)
                if unit == "주별":
                    ff_series.index = ff_series.index - pd.Timedelta(days=6)
                elif unit == "월마감" and not ff_series.empty and ff_s.index.max() < ff_series.index[-1]:
                    ff_series = ff_series.iloc[:-1]
                ff_series = ff_series[ff_series.index <= selected_period_date] if not ff_series.empty else ff_series
                _ff_s_raw = ff_s[ff_s.index <= selected_period_date] if selected_period_date is not None else ff_s
                _ff_stats = compute_kpi_deltas(ff_series, unit, raw_daily=_ff_s_raw)
            _ff_computed[display_name] = _ff_stats

        # 2단계: 인사이트 카드 (좌: 자동요약 / 우: AI·메모)
        _ai_context_ep = f"실적요약 · {bpu} · {segment} · {unit} · 기준 {period_label}"
        _ai_payload_ep = []
        cfg = UNIT_CONFIG[unit]
        for display_name, (col_name, stats) in _kpi_computed.items():
            if stats:
                _is_pct_tmp = col_name == "CR"
                _val_str_tmp = f"{stats['current']:.1f}%" if _is_pct_tmp else f"{stats['current']:,.0f}"
                _ai_payload_ep.append({
                    "name": display_name, "value": _val_str_tmp,
                    "prev_label": cfg["prev_label"], "prev_delta": float(stats["prev_delta"] or 0),
                    "yoy_label": cfg["yoy_label"], "yoy_delta": float(stats["yoy_delta"] or 0),
                })

        # KPI 카드뿐 아니라 하단 '사업부별 실적 비교'표 내용도 요약에 반영 —
        # 거래액 기준으로 e-영업1~4 중 가장 많이 오르고/내린 사업부를 뽑는다.
        # (render_bpu_comparison_table과 완전히 같은 함수를 재사용해서 숫자가 어긋나지 않음)
        _extra_sections_ep = []
        try:
            _bpu_rows_all, _, _ = compute_bpu_comparison_rows(df_traffic, unit, selected_period_date)
            _bpu_gmv_rows = [
                r for r in _bpu_rows_all
                if r["metric_label"] == "거래액(순결제)" and r["bpu"] in ("e-영업1", "e-영업2", "e-영업3", "e-영업4") and r["stats"]
            ]
            if len(_bpu_gmv_rows) >= 2:
                _key_delta = lambda r: r["stats"].get("yoy_delta") if r["stats"].get("yoy_delta") is not None else r["stats"].get("prev_delta")
                _ranked = sorted([r for r in _bpu_gmv_rows if _key_delta(r) is not None], key=_key_delta, reverse=True)
                if _ranked:
                    _bpu_items = []
                    _top, _bottom = _ranked[0], _ranked[-1]
                    for _r, _tag in ((_top, "최대 상승"), (_bottom, "최대 하락")):
                        if _r is _top and _r is _bottom:
                            continue  # 사업부가 1개뿐이면 하나만
                        _bpu_items.append({
                            "name": f"{_r['bpu']} ({_tag})", "value": f"{_r['stats']['current']:,.0f}",
                            "yoy_label": cfg["yoy_label"], "yoy_delta": _r["stats"].get("yoy_delta"),
                            "prev_label": cfg["prev_label"], "prev_delta": _r["stats"].get("prev_delta"),
                        })
                    if _bpu_items:
                        _extra_sections_ep.append({"header": "사업부(BPU)별 거래액 비교", "items": _bpu_items})
        except Exception:
            pass  # 요약은 보조 기능이라, 계산 중 문제가 있어도 KPI 요약은 그대로 보여준다

        _memo_key_ep = f"ep_summary::{bpu}::{segment}::{unit}::{period_label}"
        _ai_result_ep = render_insight_card(
            _ai_payload_ep, _ai_context_ep, "ep_summary", _memo_key_ep, period_label,
            extra_sections=_extra_sections_ep,
        )


        # 3단계: KPI 카드 렌더링 (+ 지표별 AI 한줄 인사이트)
        kpi_cols = st.columns(5)
        for i, (col_name, display_name) in enumerate(all_items):
            with kpi_cols[i]:
                _, stats = _kpi_computed[display_name]
                if stats:
                    _is_pct = col_name == "CR"
                    if _is_pct:
                        val_str = f"{stats['current']:.1f}%"
                    elif col_name == "객단가":
                        val_str = f"{stats['current']:,.0f}"
                    else:
                        val_str = f"{stats['current']:,.0f}"

                    cfg = UNIT_CONFIG[unit]

                    def _ff_note(v, _is_pct=_is_pct):
                        if v is None or pd.isna(v) or abs(v) < 0.5:
                            return ""
                        _s = f"{v:.1f}%" if _is_pct else f"{v:,.0f}"
                        return f" <span style='color:#ef4444;font-weight:600;'>[FF {_s}]</span>"

                    _ff_stats = _ff_computed.get(display_name)
                    _ff_cur_note = _ff_note(_ff_stats["current"]) if _ff_stats else ""
                    _ff_prev_note = _ff_note(_ff_stats.get("prev_value")) if _ff_stats else ""
                    _ff_avg_note = _ff_note(_ff_stats.get("avg_value")) if _ff_stats else ""
                    _ff_yoy_note = _ff_note(_ff_stats.get("yoy_value")) if _ff_stats else ""

                    st.markdown(
                        f"<div style='background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:14px 16px;min-height:180px;'>"
                        f"<div style='color:#6b7280;font-size:0.8rem;margin-bottom:4px;'>{display_name}</div>"
                        f"<div style='font-size:1.5rem;font-weight:700;color:#111827;'>{val_str}</div>{_ff_cur_note}"
                        f"<div style='font-size:0.78rem;margin-top:6px;'>"
                        f"{cfg['prev_label']} {format_delta_html(stats['prev_delta'])}{_ref_str(stats.get('prev_value'), _is_pct)}{_ff_prev_note}<br/>"
                        f"{cfg['avg_label']} {format_delta_html(stats['avg_delta'])}{_ref_str(stats.get('avg_value'), _is_pct)}{_ff_avg_note}<br/>"
                        f"{cfg['yoy_label']} {format_delta_html(stats['yoy_delta'])}{_ref_str(stats.get('yoy_value'), _is_pct)}{_ff_yoy_note}"
                        f"</div></div>",
                        unsafe_allow_html=True,
                    )
                    render_metric_insight(_ai_result_ep, display_name)

        st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

        # 지표 추이 차트 (트래픽 지표)
        st.markdown("**EP 실적 추이**")
        tr_metric_options = ["트래픽", "거래액", "구매객수", "CR", "객단가"]
        tr_metric = st.radio(
            "지표 선택", tr_metric_options, index=0, key="tr_metric",
            horizontal=True, label_visibility="collapsed",
        )

        # 리샘플 (전체 기간 — 전년 비교선용)
        s_raw = tr_combo.set_index("날짜")[tr_metric].sort_index()
        _agg = "sum" if (unit == "월마감" and tr_metric in {"트래픽", "거래액", "구매객수"}) else "mean"
        tr_full = s_raw.resample(UNIT_CONFIG[unit]["rule"]).agg(_agg)
        if unit == "주별":
            tr_full.index = tr_full.index - pd.Timedelta(days=6)
        elif unit == "월마감" and not tr_full.empty and s_raw.index.max() < tr_full.index[-1]:
            tr_full = tr_full.iloc[:-1]

        # 올해만 추출
        latest_year = int(tr_full.index.max().year)
        tr_series = tr_full[tr_full.index.year == latest_year]
        # 표/KPI 카드는 selected_period_date까지만 자르는데 이 차트는 최신 연도 데이터를
        # 끝까지 다 보여주고 있어서 표랑 차트 마지막 지점이 다른 값을 가리키는 버그가
        # 있었음(2번 페이지에서 먼저 발견됨) — 여기도 동일하게 자른다.
        if selected_period_date is not None and not tr_series.empty:
            tr_series = tr_series[tr_series.index <= selected_period_date]

        # 일별이면 최근 30일 + 기간 조정
        if unit == "일별":
            _default_start = max(tr_series.index.min().date(), tr_series.index.max().date() - _dt.timedelta(days=30))
            _tr_range_key = f"tr_range_{bpu}_{segment}"
            col_d, col_reset, col_y = st.columns([3, 1, 1])
            with col_d:
                dr = st.date_input("기간", value=(_default_start, tr_series.index.max().date()),
                                   min_value=tr_series.index.min().date(), max_value=tr_series.index.max().date(),
                                   key=_tr_range_key)
            with col_reset:
                st.markdown("<div style='height:1.5rem;'></div>", unsafe_allow_html=True)
                st.button(
                    "🔄 최근으로", key=f"tr_range_reset_{bpu}_{segment}", use_container_width=True,
                    on_click=_reset_date_range, args=(_tr_range_key, (_default_start, tr_series.index.max().date())),
                )
            with col_y:
                show_tr_yoy = st.checkbox("전년 비교선 표시", value=True, key="tr_yoy")
            if isinstance(dr, tuple) and len(dr) == 2:
                tr_series = tr_series[(tr_series.index >= pd.Timestamp(dr[0])) & (tr_series.index <= pd.Timestamp(dr[1]))]
        else:
            if unit == "주별":
                col_wk, col_reset, col_y = st.columns([3, 1, 1])
                tr_series = render_week_range_filter(tr_series, f"tr_{bpu}_{segment}", col_wk, col_reset)
                with col_y:
                    st.markdown("<div style='height:1.5rem;'></div>", unsafe_allow_html=True)
                    show_tr_yoy = st.checkbox("전년 비교선 표시", value=True, key="tr_yoy")
            else:
                _sp1, _sp2, col_y = st.columns([3, 1, 1])
                with col_y:
                    show_tr_yoy = st.checkbox("전년 비교선 표시", value=True, key="tr_yoy")

        chart_df = pd.DataFrame({tr_metric: tr_series})

        # 전년 비교선 (동요일 364일 / 월마감은 1년)
        yoy_col_name = None
        _tr_yoy_actual_dates = None
        if show_tr_yoy and not tr_series.empty:
            if unit == "월마감":
                prev_dates = tr_series.index - pd.DateOffset(years=1)
            else:
                prev_dates = tr_series.index - pd.Timedelta(days=364)
            yoy_vals = []
            yoy_actual = []
            for pd_date in prev_dates:
                if pd_date in tr_full.index:
                    yoy_vals.append(tr_full.loc[pd_date])
                    yoy_actual.append(pd_date)
                else:
                    cand = tr_full.index[tr_full.index <= pd_date]
                    yoy_vals.append(tr_full.loc[cand[-1]] if len(cand) else None)
                    yoy_actual.append(cand[-1] if len(cand) else pd_date)
            yoy_label = UNIT_CONFIG[unit]["yoy_label"]
            yoy_col_name = f"{yoy_label}(전년)"
            chart_df[yoy_col_name] = yoy_vals
            _tr_yoy_actual_dates = yoy_actual

        # 금년=진한 파랑, 전년=하늘색
        render_line_chart(chart_df, height=350, unit=unit, yoy_actual_dates=_tr_yoy_actual_dates)

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
            _agg = "sum" if (unit == "월마감" and col_name in {"트래픽", "거래액", "구매객수"}) else "mean"
            series = s.resample(UNIT_CONFIG[unit]["rule"]).agg(_agg)
            if unit == "주별":
                series.index = series.index - pd.Timedelta(days=6)
            elif unit == "월마감" and not series.empty and s.index.max() < series.index[-1]:
                series = series.iloc[:-1]
            if not series.empty:
                series = series[series.index <= selected_period_date]
            _s_raw = s[s.index <= selected_period_date] if selected_period_date is not None else s
            stats = compute_kpi_deltas(series, unit, raw_daily=_s_raw)
            if stats is None:
                body_rows.append(f"<tr><td>{display_name}</td><td>-</td><td>-</td><td>-</td></tr>")
                continue
            prev_label = stats["prev_label"]
            yoy_label = stats["yoy_label"]
            is_pct = col_name == "CR"
            val = f"{stats['current']:.1f}%" if is_pct else f"{stats['current']:,.0f}"
            body_rows.append(
                f"<tr><td class='m'>{display_name}</td><td class='v'>{val}</td>"
                f"<td class='d'>{format_delta_html(stats['prev_delta'])}{_ref_str(stats.get('prev_value'), is_pct)}</td>"
                f"<td class='d'>{format_delta_html(stats['yoy_delta'])}{_ref_str(stats.get('yoy_value'), is_pct)}</td></tr>"
            )

        # 회원UV 행 추가 (선택된 세그먼트와 무관하게 항상 표시)
        if not tr_member.empty:
            s_mem = tr_member.set_index("날짜")["트래픽"].sort_index()
            _agg_mem = "sum" if unit == "월마감" else "mean"
            series_mem = s_mem.resample(UNIT_CONFIG[unit]["rule"]).agg(_agg_mem)
            if unit == "주별":
                series_mem.index = series_mem.index - pd.Timedelta(days=6)
            elif unit == "월마감" and not series_mem.empty and s_mem.index.max() < series_mem.index[-1]:
                series_mem = series_mem.iloc[:-1]
            if not series_mem.empty:
                series_mem = series_mem[series_mem.index <= selected_period_date]
            _s_mem_raw = s_mem[s_mem.index <= selected_period_date] if selected_period_date is not None else s_mem
            stats_mem = compute_kpi_deltas(series_mem, unit, raw_daily=_s_mem_raw)
            if stats_mem is None:
                body_rows.append("<tr><td>회원UV</td><td>-</td><td>-</td><td>-</td></tr>")
            else:
                body_rows.append(
                    f"<tr><td class='m'>회원UV</td><td class='v'>{stats_mem['current']:,.0f}</td>"
                    f"<td class='d'>{format_delta_html(stats_mem['prev_delta'])}{_ref_str(stats_mem.get('prev_value'))}</td>"
                    f"<td class='d'>{format_delta_html(stats_mem['yoy_delta'])}{_ref_str(stats_mem.get('yoy_value'))}</td></tr>"
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



    # --- 쿠폰 비용 요약 (최신월 기준, 상세는 5.쿠폰 비용 분석 페이지) ---
    if not df_coupon.empty:
        st.markdown("---")
        st.markdown("### 🎟️ 쿠폰 비용 요약", unsafe_allow_html=True)
        _cs_sub = df_coupon[df_coupon["BPU"] == "Total"]
        _cs_by_month = _cs_sub.groupby("연월")["쿠폰할인"].sum().sort_index()
        if not _cs_by_month.empty:
            _cs_latest = _cs_by_month.index.max()
            _cs_gmv = df_traffic[(df_traffic["BPU"] == "Total") & (df_traffic["회원구분"] == "전체")].set_index("날짜")["거래액"].resample("MS").sum()
            _cs_gmv_val = _cs_gmv.get(_cs_latest, None)
            _cs_coupon_val = _cs_by_month.get(_cs_latest, 0)
            _cs_rate = (_cs_coupon_val / _cs_gmv_val * 100) if _cs_gmv_val else None
            _cs_c1, _cs_c2, _cs_c3 = st.columns(3)
            with _cs_c1:
                st.markdown(
                    f"<div style='background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:14px 16px;'>"
                    f"<div style='color:#6b7280;font-size:0.8rem;margin-bottom:4px;'>{_cs_latest.strftime('%Y년 %m월')} 쿠폰할인</div>"
                    f"<div style='font-size:1.4rem;font-weight:700;color:#111827;'>{_cs_coupon_val:,.0f}</div></div>",
                    unsafe_allow_html=True,
                )
            with _cs_c2:
                st.markdown(
                    f"<div style='background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:14px 16px;'>"
                    f"<div style='color:#6b7280;font-size:0.8rem;margin-bottom:4px;'>거래액(Total)</div>"
                    f"<div style='font-size:1.4rem;font-weight:700;color:#111827;'>{_cs_gmv_val:,.0f}</div></div>"
                    if _cs_gmv_val else "<div></div>",
                    unsafe_allow_html=True,
                )
            with _cs_c3:
                st.markdown(
                    f"<div style='background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:14px 16px;'>"
                    f"<div style='color:#6b7280;font-size:0.8rem;margin-bottom:4px;'>비용률</div>"
                    f"<div style='font-size:1.4rem;font-weight:700;color:#7c3aed;'>{_cs_rate:.2f}%</div></div>"
                    if _cs_rate is not None else "<div></div>",
                    unsafe_allow_html=True,
                )
            st.caption("👉 매체별·쿠폰유형별 상세, 쿠폰명 랭킹은 사이드바 '5. 쿠폰 비용 분석' 페이지에서 볼 수 있어요.")

    st.markdown("---")
    st.markdown("### 🏢 사업부별 실적 비교", unsafe_allow_html=True)
    _bpu_cfg = UNIT_CONFIG[unit]
    st.markdown(
        f"<div class='chart-caption'>Total / e-영업1~4 / 자사 / 입점 · "
        f"<b>{unit}</b> 기준 · 기준시점: <b>{period_label}</b> · "
        f"값·{_bpu_cfg['prev_label']}·{_bpu_cfg['avg_label']}·{_bpu_cfg['yoy_label']}</div>",
        unsafe_allow_html=True,
    )
    render_bpu_comparison_table(df_traffic, unit=unit, selected_period_date=selected_period_date)

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
                _ep_raw = df_ep_combo.set_index(COL_DATE)[metric_key].sort_index()
                _ep_raw = _ep_raw[_ep_raw.index <= selected_period_date]
                stats = compute_kpi_deltas(series, unit, raw_daily=_ep_raw)
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
        st.markdown("**EP 채널 추이**")
        ep_metrics_list = [m for m, _ in EP_CHANNEL_METRICS]
        ep_metric = st.radio(
            "지표", ep_metrics_list, index=0, key="ep_metric",
            horizontal=True, label_visibility="collapsed",
        )

        _ep_latest_year = int(last_date_ep.year)
        if unit == "일별":
            _ep_max_d = last_date_ep.date()
            _ep_min_d = _dt.date(_ep_latest_year, 1, 1)
            _ep_default_start = max(_ep_min_d, _ep_max_d - _dt.timedelta(days=30))
            _ep_range_key = f"ep_range_{bpu}_{match_status}_{lowest_status}"
            col_ed, col_ereset, col_ey = st.columns([3, 1, 1])
            with col_ed:
                ep_dr = st.date_input(
                    "기간", value=(_ep_default_start, _ep_max_d),
                    min_value=_ep_min_d, max_value=_ep_max_d, key=_ep_range_key,
                )
            with col_ereset:
                st.markdown("<div style='height:1.5rem;'></div>", unsafe_allow_html=True)
                st.button(
                    "🔄 최근으로", key=f"ep_range_reset_{bpu}_{match_status}_{lowest_status}", use_container_width=True,
                    on_click=_reset_date_range, args=(_ep_range_key, (_ep_default_start, _ep_max_d)),
                )
            with col_ey:
                show_ep_yoy = st.checkbox("전년 비교선 표시", value=True, key="ep_yoy_cb")
            if isinstance(ep_dr, tuple) and len(ep_dr) == 2:
                _ep_date_start, _ep_date_end = ep_dr
            else:
                _ep_date_start, _ep_date_end = _ep_default_start, _ep_max_d
        else:
            _esp1, _esp2, col_ey = st.columns([3, 1, 1])
            with col_ey:
                show_ep_yoy = st.checkbox("전년 비교선 표시", value=True, key="ep_yoy_cb")
            _ep_date_start = _dt.date(_ep_latest_year, 1, 1)
            # 절대 최신 날짜(last_date_ep)가 아니라 선택된 기준시점까지만 —
            # 안 그러면 표/KPI 카드는 기준시점까지만 보여주는데 이 차트만 그 뒤 데이터까지
            # 더 보여줘서 마지막 지점 값이 서로 달라지는 버그가 있었음(다른 차트 2곳에서
            # 먼저 발견돼서 여기도 같은 패턴인지 점검함).
            _ep_date_end = selected_period_date.date() if selected_period_date is not None else last_date_ep.date()

        ep_trend, ep_yoy = main_trend_data(df_ep_combo, ep_metric, unit, show_yoy=show_ep_yoy,
                                           current_year=_ep_latest_year,
                                           date_start=_ep_date_start,
                                           date_end=_ep_date_end)

        ep_cols = list(ep_trend.columns)
        if len(ep_cols) > 1:
            render_line_chart(ep_trend, height=350, unit=unit)
        else:
            render_line_chart(ep_trend, height=350, unit=unit)

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
            _ep_raw2 = df_ep_combo.set_index(COL_DATE)[metric_key].sort_index()
            _ep_raw2 = _ep_raw2[_ep_raw2.index <= selected_period_date]
            stats = compute_kpi_deltas(series, unit, raw_daily=_ep_raw2)
            if stats is None:
                ep_body_rows.append(f"<tr><td>{display_name}</td><td>-</td><td>-</td><td>-</td></tr>")
                continue
            ep_prev_label = stats["prev_label"]
            ep_yoy_label = stats["yoy_label"]
            _is_pct = "%" in metric_key or metric_key == "신규가입율"
            val = f"{stats['current']:.1f}%" if _is_pct else f"{stats['current']:,.0f}"
            ep_body_rows.append(
                f"<tr><td class='m'>{display_name}</td><td class='v'>{val}</td>"
                f"<td class='d'>{format_delta_html(stats['prev_delta'])}{_ref_str(stats.get('prev_value'), _is_pct)}</td>"
                f"<td class='d'>{format_delta_html(stats['yoy_delta'])}{_ref_str(stats.get('yoy_value'), _is_pct)}</td></tr>"
            )
        ep_summary_html = (
            "<table class='summary-table'>"
            f"<thead><tr><th>지표</th><th>값</th><th>{ep_prev_label or '-'}</th><th>{ep_yoy_label or '-'}</th></tr></thead>"
            f"<tbody>{''.join(ep_body_rows)}</tbody></table>"
        )
        st.markdown(ep_summary_html, unsafe_allow_html=True)


if side["page"].startswith("2"):
    # ============================================================
    # 카테고리별 실적 (카테고리 → 브랜드 드릴다운, 전년비교 가능)
    # ============================================================
    st.markdown("---")
    st.markdown("### 🗂️ 카테고리별 실적")

    if df_category.empty:
        st.info("카테고리 데이터가 없습니다. 사이드바에서 ep_category.csv를 업로드해주세요.")
    else:
        # 핏플랍(FF) 제외 여부(_ff_exclude)는 상단 고정 필터에서 이미 정해져서 넘어온다.

        # 매체필터(bpu)에 맞춰 카테고리 데이터 필터링 (자사/입점은 합산)
        if bpu in BPU_GROUPS:
            cat_bpu_df = df_category[df_category["BPU"].isin(BPU_GROUPS[bpu])]
        elif bpu == "Total":
            cat_bpu_df = df_category  # 전체 BPU 합산은 아래에서 groupby로 처리
        else:
            cat_bpu_df = df_category[df_category["BPU"] == bpu]

        # 세그먼트 필터는 상단 고정 영역에서 이미 선택됨 (cat_segment 변수 재사용)
        _has_segment = "회원구분" in df_category.columns

        # 세그먼트 필터 적용 전 원본 보관 (브랜드 랭킹은 세그먼트=전체 데이터만 있으므로 이걸 사용)
        cat_bpu_df_all_seg = cat_bpu_df

        if _has_segment:
            cat_bpu_df = cat_bpu_df[cat_bpu_df["회원구분"] == cat_segment]

        _ff_only_df = None
        if _ff_exclude:
            _ff_only_df = cat_bpu_df[(cat_bpu_df["브랜드"] == "FF") & (cat_bpu_df["카테고리"] != "전체")]
            cat_bpu_df = exclude_ff_brand(cat_bpu_df)
            cat_bpu_df_all_seg = exclude_ff_brand(cat_bpu_df_all_seg)

        # 카테고리별 거래액 요약(전기간비/평균비/전년비) — 아래쪽 '카테고리별 요약'표랑
        # 인사이트 카드(자동요약) 둘 다에서 쓸 거라 여기서 한 번만 계산해둔다.
        # 카테고리 선택 필터와 무관하게 전체 카테고리를 대상으로 함 (개요용이라서).
        _cat_summary_rows = []
        _cat_daily_df_early = cat_bpu_df[(cat_bpu_df["브랜드"] == "전체") & (cat_bpu_df["카테고리"] != "전체")]
        if bpu == "Total" or bpu in BPU_GROUPS:
            _cat_daily_df_early = _cat_daily_df_early.groupby(["날짜", "카테고리"], as_index=False)["거래액"].sum()
        else:
            _cat_daily_df_early = _cat_daily_df_early[["날짜", "카테고리", "거래액"]]
        if not _cat_daily_df_early.empty:
            _cat_cfg_early = UNIT_CONFIG[unit]
            _cat_agg_early = "sum" if unit == "월마감" else "mean"
            for cat_name, g in _cat_daily_df_early.groupby("카테고리"):
                s = g.set_index("날짜")["거래액"].sort_index()
                series = s.resample(_cat_cfg_early["rule"]).agg(_cat_agg_early)
                if unit == "주별":
                    series.index = series.index - pd.Timedelta(days=6)
                elif unit == "월마감" and not series.empty and s.index.max() < series.index[-1]:
                    series = series.iloc[:-1]
                if not series.empty:
                    series = series[series.index <= selected_period_date]
                _s_raw = s[s.index <= selected_period_date] if selected_period_date is not None else s
                stats = compute_kpi_deltas(series, unit, raw_daily=_s_raw)
                if stats is None or not stats["current"]:
                    continue
                _cat_summary_rows.append({
                    "카테고리": cat_name, "거래액": stats["current"],
                    "prev": stats["prev_delta"], "avg": stats["avg_delta"], "yoy": stats["yoy_delta"],
                    "prev_v": stats.get("prev_value"), "avg_v": stats.get("avg_value"), "yoy_v": stats.get("yoy_value"),
                })
        _cat_summary_rows.sort(key=lambda r: r["거래액"], reverse=True)

        cat_combo = cat_bpu_df[(cat_bpu_df["카테고리"] == selected_cat) & (cat_bpu_df["브랜드"] == selected_brand)]
        if (bpu == "Total" or bpu in BPU_GROUPS) and not cat_combo.empty:
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

            # 핏플랍 제외 중이고, 지금 보는 화면이 실제로 FF의 영향을 받는 범위(카테고리=전체/슈즈,
            # 브랜드=전체)일 때만 'FF 기여분'을 계산해서 KPI 카드에 참고용으로 같이 보여준다.
            _ff_note_df = None
            if _ff_exclude and _ff_only_df is not None and not _ff_only_df.empty and selected_brand == "전체":
                if selected_cat == "전체":
                    _ff_scope = _ff_only_df
                else:
                    _ff_scope = _ff_only_df[_ff_only_df["카테고리"] == selected_cat]
                if not _ff_scope.empty:
                    _ff_note_df = _ff_scope.groupby("날짜", as_index=False).agg(
                        {"트래픽": "sum", "거래액": "sum", "구매객수": "sum"}
                    )
                    _ff_note_df["CR"] = (_ff_note_df["구매객수"] / _ff_note_df["트래픽"] * 100).where(_ff_note_df["트래픽"] > 0)
                    _ff_note_df["객단가"] = (_ff_note_df["거래액"] / _ff_note_df["구매객수"]).where(_ff_note_df["구매객수"] > 0)

            # 1단계: 값/증감 먼저 계산 (AI payload 구성용)
            _cat_computed = {}
            _ff_computed = {}
            for col_name, display_name in CAT_METRICS:
                s = cat_combo.set_index("날짜")[col_name].sort_index()
                _agg = "sum" if (unit == "월마감" and col_name in {"트래픽", "거래액", "구매객수"}) else "mean"
                series = s.resample(UNIT_CONFIG[unit]["rule"]).agg(_agg)
                if unit == "주별":
                    series.index = series.index - pd.Timedelta(days=6)
                elif unit == "월마감" and not series.empty and s.index.max() < series.index[-1]:
                    series = series.iloc[:-1]
                series = series[series.index <= selected_period_date] if not series.empty else series
                _s_raw = s[s.index <= selected_period_date] if selected_period_date is not None else s
                _cat_computed[display_name] = (col_name, compute_kpi_deltas(series, unit, raw_daily=_s_raw))

                _ff_stats = None
                # CR/객단가는 트래픽·구매객수·거래액에서 계산되는 값이라, FF 기여분을 따로
                # 표기할 필요 없음(원본 3개 지표만 보면 충분) — 여기서 계산 자체를 건너뜀.
                if _ff_note_df is not None and col_name in ("트래픽", "거래액", "구매객수"):
                    ff_s = _ff_note_df.set_index("날짜")[col_name].sort_index()
                    # 메인 시리즈(s)와 날짜 범위를 맞춘다. FF는 매출 0인 날엔 원본에 행 자체가
                    # 없을 수 있어서, 그대로 두면 FF 시리즈의 마지막 날짜가 메인보다 짧아져
                    # '진행 중인 달' 판정(cur_days)이 메인과 어긋나는 문제가 있었음.
                    ff_s = ff_s.reindex(s.index, fill_value=0)
                    ff_series = ff_s.resample(UNIT_CONFIG[unit]["rule"]).agg(_agg)
                    if unit == "주별":
                        ff_series.index = ff_series.index - pd.Timedelta(days=6)
                    elif unit == "월마감" and not ff_series.empty and ff_s.index.max() < ff_series.index[-1]:
                        ff_series = ff_series.iloc[:-1]
                    ff_series = ff_series[ff_series.index <= selected_period_date] if not ff_series.empty else ff_series
                    _ff_s_raw = ff_s[ff_s.index <= selected_period_date] if selected_period_date is not None else ff_s
                    # compute_kpi_deltas를 그대로 재사용해서, 메인 지표와 정확히 같은 기준 시점
                    # (전기간/전년동기)의 FF 값을 뽑는다. 전년비교 기준연도(2025)에 FF가 활발했으므로,
                    # 지금(2026) 시점만 보면 0에 가깝지만 전년동기 쪽엔 값이 커질 수 있음.
                    _ff_stats = compute_kpi_deltas(ff_series, unit, raw_daily=_ff_s_raw)
                _ff_computed[display_name] = _ff_stats

            # 2단계: 인사이트 카드 (좌: 자동요약 / 우: AI·메모)
            _cfg_cat = UNIT_CONFIG[unit]
            _ai_payload_cat = []
            for display_name, (col_name, stats) in _cat_computed.items():
                if stats:
                    _is_pct_c = col_name == "CR"
                    _ai_payload_cat.append({
                        "name": display_name,
                        "value": f"{stats['current']:.1f}%" if _is_pct_c else f"{stats['current']:,.0f}",
                        "prev_label": _cfg_cat["prev_label"], "prev_delta": float(stats["prev_delta"] or 0),
                        "yoy_label": _cfg_cat["yoy_label"], "yoy_delta": float(stats["yoy_delta"] or 0),
                    })
            _ai_context_cat = (
                f"카테고리 실적 · {bpu} · {selected_cat}/{brand_label(selected_brand)} · {cat_segment} · "
                f"{unit} · 기준 {period_label}" + (" · 핏플랍제외" if _ff_exclude else "")
            )
            _memo_key_cat = (
                f"cat_summary::{bpu}::{selected_cat}::{selected_brand}::{cat_segment}::{unit}::{period_label}"
                + ("::ff제외" if _ff_exclude else "")
            )

            # KPI 카드뿐 아니라 하단 '카테고리별 요약'표 내용도 요약에 반영 —
            # 거래액 전년비 기준으로 가장 많이 오르고/내린 카테고리를 뽑는다.
            # (_cat_summary_rows는 위에서 이미 계산해둔 걸 그대로 씀 — 표와 숫자가 어긋나지 않음)
            _extra_sections_cat = []
            try:
                _cat_movers = [r for r in _cat_summary_rows if r.get("yoy") is not None]
                if len(_cat_movers) >= 2:
                    _ranked_cat = sorted(_cat_movers, key=lambda r: r["yoy"], reverse=True)
                    _top_c, _bottom_c = _ranked_cat[0], _ranked_cat[-1]
                    _cat_items = []
                    for _r, _tag in ((_top_c, "최대 상승"), (_bottom_c, "최대 하락")):
                        _cat_items.append({
                            "name": f"{_r['카테고리']} ({_tag})", "value": f"{_r['거래액']:,.0f}",
                            "yoy_label": _cfg_cat["yoy_label"], "yoy_delta": _r["yoy"],
                        })
                    if _cat_items:
                        _extra_sections_cat.append({"header": "카테고리별 거래액 톱무버", "items": _cat_items})
            except Exception:
                pass  # 요약은 보조 기능이라, 계산 중 문제가 있어도 KPI 요약은 그대로 보여준다

            _ai_result_cat = render_insight_card(
                _ai_payload_cat, _ai_context_cat, "cat_summary", _memo_key_cat, period_label,
                extra_sections=_extra_sections_cat,
            )

            # 3단계: KPI 카드 렌더링 (+ 지표별 AI 한줄 인사이트)
            cat_cols = st.columns(5)
            for i, (col_name, display_name) in enumerate(CAT_METRICS):
                with cat_cols[i]:
                    _, stats = _cat_computed[display_name]
                    if stats:
                        _is_pct = col_name == "CR"
                        val_str = f"{stats['current']:.1f}%" if _is_pct else f"{stats['current']:,.0f}"
                        cfg = UNIT_CONFIG[unit]

                        def _ff_note(v, _is_pct=_is_pct):
                            # 값이 거의 0이면(그 시점엔 FF 영향이 없으면) 표시 안 함 —
                            # 지금이 2026년이면 '현재'/전기간 쪽은 대부분 0, 전년비교 쪽(2025)에
                            # 큰 값이 나오는 게 정상 (FF는 2025-10월에 종료됐으므로)
                            if v is None or pd.isna(v) or abs(v) < 0.5:
                                return ""
                            _s = f"{v:.1f}%" if _is_pct else f"{v:,.0f}"
                            return f" <span style='color:#ef4444;font-weight:600;'>[FF {_s}]</span>"

                        _ff_stats = _ff_computed.get(display_name)
                        _ff_cur_note = _ff_note(_ff_stats["current"]) if _ff_stats else ""
                        _ff_prev_note = _ff_note(_ff_stats.get("prev_value")) if _ff_stats else ""
                        _ff_yoy_note = _ff_note(_ff_stats.get("yoy_value")) if _ff_stats else ""

                        st.markdown(
                            f"<div style='background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:14px 16px;min-height:180px;'>"
                            f"<div style='color:#6b7280;font-size:0.8rem;margin-bottom:4px;'>{display_name}</div>"
                            f"<div style='font-size:1.4rem;font-weight:700;color:#111827;'>{val_str}</div>{_ff_cur_note}"
                            f"<div style='font-size:0.76rem;margin-top:6px;'>"
                            f"{cfg['prev_label']} {format_delta_html(stats['prev_delta'])}{_ref_str(stats.get('prev_value'), _is_pct)}{_ff_prev_note}<br/>"
                            f"{cfg['yoy_label']} {format_delta_html(stats['yoy_delta'])}{_ref_str(stats.get('yoy_value'), _is_pct)}{_ff_yoy_note}"
                            f"</div></div>",
                            unsafe_allow_html=True,
                        )
                        render_metric_insight(_ai_result_cat, display_name)
                    else:
                        st.markdown(
                            f"<div style='background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:14px 16px;min-height:160px;'>"
                            f"<div style='color:#6b7280;font-size:0.8rem;'>{display_name}</div>"
                            f"<div style='font-size:1.2rem;color:#9ca3af;'>-</div></div>",
                            unsafe_allow_html=True,
                        )

            st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

            # --- 추이 차트 (전년 비교선 포함) ---
            st.markdown("**카테고리 실적 추이**")
            cat_metric = st.radio(
                "지표", ["트래픽", "거래액", "구매객수", "CR", "객단가"],
                index=1, key="cat_metric", horizontal=True, label_visibility="collapsed",
            )

            s_raw = cat_combo.set_index("날짜")[cat_metric].sort_index()
            _agg = "sum" if (unit == "월마감" and cat_metric in {"트래픽", "거래액", "구매객수"}) else "mean"
            cat_full = s_raw.resample(UNIT_CONFIG[unit]["rule"]).agg(_agg)
            if unit == "주별":
                cat_full.index = cat_full.index - pd.Timedelta(days=6)
            elif unit == "월마감" and not cat_full.empty and s_raw.index.max() < cat_full.index[-1]:
                cat_full = cat_full.iloc[:-1]

            latest_year_cat = int(cat_full.index.max().year) if not cat_full.empty else None
            cat_series = cat_full[cat_full.index.year == latest_year_cat] if latest_year_cat else cat_full
            # 표(카테고리 실적 요약 표)/KPI 카드는 selected_period_date까지만 자르는데,
            # 이 차트는 그걸 안 하고 최신 연도 데이터를 끝까지 다 보여주고 있어서 표랑 차트
            # 마지막 지점이 다른 값을 가리키는 버그가 있었음 — 여기서도 동일하게 자른다.
            if selected_period_date is not None and not cat_series.empty:
                cat_series = cat_series[cat_series.index <= selected_period_date]

            if unit == "일별" and not cat_series.empty:
                _cat_max_d = cat_series.index.max().date()
                _cat_min_d = cat_series.index.min().date()
                _cat_default_start = max(_cat_min_d, _cat_max_d - _dt.timedelta(days=30))
                # 카테고리/브랜드/매체 조합마다 별도 키를 써서, 다른 조합에서 수동으로 바꾼
                # 기간이 이어서 남지 않도록 함(예전엔 키가 고정돼 있어 다른 카테고리 선택시에도
                # 이전에 봤던 기간이 그대로 남아있는 문제가 있었음)
                _cat_range_key = f"cat_range_{bpu}_{selected_cat}_{selected_brand}"
                col_cd, col_reset, col_cy = st.columns([3, 1, 1])
                with col_cd:
                    cat_dr = st.date_input(
                        "기간", value=(_cat_default_start, _cat_max_d),
                        min_value=_cat_min_d, max_value=_cat_max_d, key=_cat_range_key,
                    )
                with col_reset:
                    st.markdown("<div style='height:1.5rem;'></div>", unsafe_allow_html=True)
                    st.button(
                        "🔄 최근으로", key=f"cat_range_reset_{bpu}_{selected_cat}_{selected_brand}", use_container_width=True,
                        on_click=_reset_date_range, args=(_cat_range_key, (_cat_default_start, _cat_max_d)),
                    )
                with col_cy:
                    show_cat_yoy = st.checkbox("전년 비교선 표시", value=True, key="cat_yoy")
                if isinstance(cat_dr, tuple) and len(cat_dr) == 2:
                    cat_series = cat_series[(cat_series.index >= pd.Timestamp(cat_dr[0])) & (cat_series.index <= pd.Timestamp(cat_dr[1]))]
            else:
                if unit == "주별":
                    col_wk, col_reset, col_cy = st.columns([3, 1, 1])
                    cat_series = render_week_range_filter(
                        cat_series, f"cat_{bpu}_{selected_cat}_{selected_brand}", col_wk, col_reset
                    )
                    with col_cy:
                        st.markdown("<div style='height:1.5rem;'></div>", unsafe_allow_html=True)
                        show_cat_yoy = st.checkbox("전년 비교선 표시", value=True, key="cat_yoy")
                else:
                    _csp1, _csp2, col_cy = st.columns([3, 1, 1])
                    with col_cy:
                        show_cat_yoy = st.checkbox("전년 비교선 표시", value=True, key="cat_yoy")

            cat_chart_df = pd.DataFrame({cat_metric: cat_series})

            _cat_yoy_actual_dates = None
            if show_cat_yoy and not cat_series.empty:
                if unit == "월마감":
                    prev_dates = cat_series.index - pd.DateOffset(years=1)
                else:
                    prev_dates = cat_series.index - pd.Timedelta(days=364)
                yoy_vals = []
                yoy_actual = []
                for pd_date in prev_dates:
                    if pd_date in cat_full.index:
                        yoy_vals.append(cat_full.loc[pd_date])
                        yoy_actual.append(pd_date)
                    else:
                        cand = cat_full.index[cat_full.index <= pd_date]
                        yoy_vals.append(cat_full.loc[cand[-1]] if len(cand) else None)
                        yoy_actual.append(cand[-1] if len(cand) else pd_date)
                yoy_label_cat = UNIT_CONFIG[unit]["yoy_label"]
                cat_chart_df[f"{yoy_label_cat}(전년)"] = yoy_vals
                _cat_yoy_actual_dates = yoy_actual
            render_line_chart(cat_chart_df, height=350, unit=unit, yoy_actual_dates=_cat_yoy_actual_dates)

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
                _agg2 = "sum" if (unit == "월마감" and col_name in {"트래픽", "거래액", "구매객수"}) else "mean"
                series2 = s2.resample(UNIT_CONFIG[unit]["rule"]).agg(_agg2)
                if unit == "주별":
                    series2.index = series2.index - pd.Timedelta(days=6)
                elif unit == "월마감" and not series2.empty and s2.index.max() < series2.index[-1]:
                    series2 = series2.iloc[:-1]
                series2 = series2[series2.index <= selected_period_date] if not series2.empty else series2
                _s2_raw = s2[s2.index <= selected_period_date] if selected_period_date is not None else s2
                stats2 = compute_kpi_deltas(series2, unit, raw_daily=_s2_raw)
                if stats2 is None:
                    cat_summary_rows.append(f"<tr><td>{display_name}</td><td>-</td><td>-</td><td>-</td></tr>")
                    continue
                cat_prev_label = stats2["prev_label"]
                cat_yoy_label = stats2["yoy_label"]
                _is_pct2 = col_name == "CR"
                val2 = f"{stats2['current']:.1f}%" if _is_pct2 else f"{stats2['current']:,.0f}"
                cat_summary_rows.append(
                    f"<tr><td class='m'>{display_name}</td><td class='v'>{val2}</td>"
                    f"<td class='d'>{format_delta_html(stats2['prev_delta'])}{_ref_str(stats2.get('prev_value'), _is_pct2)}</td>"
                    f"<td class='d'>{format_delta_html(stats2['yoy_delta'])}{_ref_str(stats2.get('yoy_value'), _is_pct2)}</td></tr>"
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
        if bpu == "Total" or bpu in BPU_GROUPS:
            _share_df = _share_df.groupby(["날짜", "카테고리"], as_index=False)["거래액"].sum()

        # 진짜 전체값(카테고리=전체&브랜드=전체) — 개별 카테고리 합산이 아니라 이걸로 중앙에 표시
        _official_all_df = cat_bpu_df[(cat_bpu_df["카테고리"] == "전체") & (cat_bpu_df["브랜드"] == "전체")]
        if bpu == "Total" or bpu in BPU_GROUPS:
            _official_all_df = _official_all_df.groupby("날짜", as_index=False)["거래액"].sum()
        _official_cat_total = compute_official_total(_official_all_df, unit, selected_period_date)

        render_revenue_ranking(_share_df, "카테고리", unit, selected_period_date, "카테고리별 거래액 비중", f"{bpu} 기준",
                               donut=True, official_total=_official_cat_total,
                               ai_key="cat_share", ai_context=f"카테고리별 거래액 비중 · {bpu} · {cat_segment} · {unit} · 기준 {period_label}" + (" · 핏플랍제외" if _ff_exclude else ""))

        st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

        # --- 브랜드별 거래액 랭킹 ---
        # 카테고리='전체'면 전체 브랜드 랭킹, 특정 카테고리 선택시 그 카테고리 안의 브랜드만
        # (브랜드 레벨 데이터는 세그먼트=전체만 존재하므로 cat_bpu_df_all_seg 사용)
        if selected_cat == "전체":
            _brand_share_df = cat_bpu_df_all_seg[(cat_bpu_df_all_seg["카테고리"] == "전체") & (cat_bpu_df_all_seg["브랜드"] != "전체")]
            _brand_subtitle = f"{bpu} · 전체 카테고리 기준"
        else:
            _brand_share_df = cat_bpu_df_all_seg[(cat_bpu_df_all_seg["카테고리"] == selected_cat) & (cat_bpu_df_all_seg["브랜드"] != "전체")]
            _brand_subtitle = f"{bpu} · {selected_cat} 카테고리 기준"
        if _has_segment:
            _brand_share_df = _brand_share_df[_brand_share_df["회원구분"] == "전체"]
        if bpu == "Total" or bpu in BPU_GROUPS:
            _brand_share_df = _brand_share_df.groupby(["날짜", "브랜드"], as_index=False)["거래액"].sum()

        # 진짜 전체값(선택한 카테고리 범위 기준, 브랜드=전체) — 브랜드 합산이 아니라 이걸로 중앙에 표시
        _official_brand_scope_df = cat_bpu_df_all_seg[(cat_bpu_df_all_seg["카테고리"] == selected_cat) & (cat_bpu_df_all_seg["브랜드"] == "전체")]
        if _has_segment:
            _official_brand_scope_df = _official_brand_scope_df[_official_brand_scope_df["회원구분"] == "전체"]
        if bpu == "Total" or bpu in BPU_GROUPS:
            _official_brand_scope_df = _official_brand_scope_df.groupby("날짜", as_index=False)["거래액"].sum()
        _official_brand_total = compute_official_total(_official_brand_scope_df, unit, selected_period_date)

        render_revenue_ranking(_brand_share_df, "브랜드", unit, selected_period_date, "브랜드별 거래액 랭킹", _brand_subtitle,
                               label_map=BRAND_LABELS, hide_zero=True,
                               donut=True, official_total=_official_brand_total,
                               ai_key="brand_rank", ai_context=f"브랜드별 거래액 랭킹 · {_brand_subtitle} · {unit} · 기준 {period_label}" + (" · 핏플랍제외" if _ff_exclude else ""))

        st.markdown("<div style='height:16px;'></div>", unsafe_allow_html=True)

        # --- 카테고리별 요약표 (조회 단위에 맞춰 전기간비/평균비/전년비) ---
        # 사이드바 조회단위(일별/주별/월별/월마감)를 그대로 따라간다 — KPI 카드와 같은
        # compute_kpi_deltas를 재사용해서 라벨(전일비/전주비/전월비 등)도 자동으로 맞춰짐.
        # 카테고리 선택 필터와 무관하게 전체 카테고리를 대상으로 함 (개요용 표라서).
        # _cat_summary_rows는 위(cat_bpu_df 확정 직후)에서 이미 계산해둔 걸 그대로 씀
        # (인사이트 카드 자동요약에서도 같은 값을 써서 숫자가 어긋나지 않게 하기 위함).
        st.markdown(f"**카테고리별 요약**  ·  <span style='color:#6b7280;font-size:0.85rem'>{bpu} · 거래액 기준 · {unit}</span>", unsafe_allow_html=True)

        if not _cat_summary_rows:
            st.info("거래액이 있는 카테고리가 없습니다.")
        else:
            if True:
                _cat_cfg = UNIT_CONFIG[unit]
                _cat_summary_body = "".join(
                    f"<tr><td class='m'>{r['카테고리']}</td>"
                    f"<td class='v' style='text-align:right;'>{r['거래액']:,.0f}</td>"
                    f"<td style='text-align:right;'>{format_delta_html(r['prev'])}{_ref_str(r['prev_v'])}</td>"
                    f"<td style='text-align:right;'>{format_delta_html(r['avg'])}{_ref_str(r['avg_v'])}</td>"
                    f"<td style='text-align:right;'>{format_delta_html(r['yoy'])}{_ref_str(r['yoy_v'])}</td></tr>"
                    for r in _cat_summary_rows
                )
                st.markdown(
                    "<div style='overflow-x:auto;'><table class='summary-table'><thead><tr>"
                    "<th>카테고리</th><th style='text-align:right;'>거래액</th>"
                    f"<th style='text-align:right;'>{_cat_cfg['prev_label']}</th>"
                    f"<th style='text-align:right;'>{_cat_cfg['avg_label']}</th>"
                    f"<th style='text-align:right;'>{_cat_cfg['yoy_label']}</th>"
                    "</tr></thead><tbody>" + _cat_summary_body + "</tbody></table></div>",
                    unsafe_allow_html=True,
                )
                st.caption(f"ℹ️ 기준: {period_label} · 거래액이 있는 카테고리만 표시돼요.")

        st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)



# ============================================================
# 페이지 3: 누적 데이터 (EP실적 + EP채널 합쳐서 기간별 표)
# ============================================================
if side["page"].startswith("3"):
    st.markdown("---")
    st.markdown(
        f"<div class='chart-caption'>매체: <b>{bpu}</b> · 기간유형: <b>{cum_unit}</b> · 집계: <b>{cum_agg_mode}</b> · "
        f"고객구분: <b>{cum_segment}</b> · {cum_start} ~ {cum_end}"
        f"{' (EP채널 지표는 고객구분 구분 없이 전체 기준)' if cum_segment != '전체' else ''}</div>",
        unsafe_allow_html=True,
    )
    _agg_func = "sum" if cum_agg_mode == "누적" else "mean"

    # --- EP실적 부분 (트래픽/거래액/구매객수는 합계 가능, CR/객단가는 합계 기반 재계산) ---
    if bpu in BPU_GROUPS:
        _cum_tr = aggregate_traffic(df_traffic, BPU_GROUPS[bpu], cum_segment)
    else:
        _cum_tr = df_traffic[(df_traffic["BPU"] == bpu) & (df_traffic["회원구분"] == cum_segment)]

    tr_table_rows = {}
    if not _cum_tr.empty:
        base_series = {}
        for base_metric in ["트래픽", "거래액", "구매객수"]:
            s = _cum_tr.set_index("날짜")[base_metric].sort_index()
            series = s.resample(UNIT_CONFIG[cum_unit]["rule"]).agg(_agg_func)
            if cum_unit == "주별":
                series.index = series.index - pd.Timedelta(days=6)
            elif cum_unit == "월마감" and not series.empty and s.index.max() < series.index[-1]:
                series = series.iloc[:-1]
            series = _truncate_by_range(series, cum_start, cum_end, cum_unit)
            base_series[base_metric] = series
            tr_table_rows[base_metric] = series

        # 비율 지표(CR/객단가)는 일평균/누적 모드와 무관하게 항상 기간 합계 기반으로 재계산
        # (일별 비율값을 단순 평균하면 부정확 — 분자·분모를 각각 합산한 뒤 비율을 구해야 정확함)
        _sum_series = {}
        for base_metric in ["트래픽", "거래액", "구매객수"]:
            s = _cum_tr.set_index("날짜")[base_metric].sort_index()
            series_sum = s.resample(UNIT_CONFIG[cum_unit]["rule"]).sum()
            if cum_unit == "주별":
                series_sum.index = series_sum.index - pd.Timedelta(days=6)
            elif cum_unit == "월마감" and not series_sum.empty and s.index.max() < series_sum.index[-1]:
                series_sum = series_sum.iloc[:-1]
            series_sum = _truncate_by_range(series_sum, cum_start, cum_end, cum_unit)
            _sum_series[base_metric] = series_sum
        tr_table_rows["CR"] = (_sum_series["구매객수"] / _sum_series["트래픽"] * 100).replace([float("inf")], None)
        tr_table_rows["객단가"] = (_sum_series["거래액"] / _sum_series["구매객수"]).replace([float("inf")], None)

    # --- EP채널 부분 (전시상품수 등은 모드에 따라 평균/합계, 원부매칭율/최저가율은 항상 합계기반 재계산) ---
    if bpu in BPU_GROUPS:
        _cum_ep = aggregate_ep(df_ep, BPU_GROUPS[bpu], "Total", "Total")
    elif bpu == "Total":
        _cum_ep = df_ep[(df_ep[COL_BPU] == "Total") & (df_ep[COL_MATCH] == "Total") & (df_ep[COL_LOWEST] == "Total")]
    else:
        _cum_ep = df_ep[(df_ep[COL_BPU] == bpu) & (df_ep[COL_MATCH] == "Total") & (df_ep[COL_LOWEST] == "Total")]

    ep_table_rows = {}
    if not _cum_ep.empty:
        # 전시상품수/원부매칭상품수/최저가상품수는 집계 모드(일평균/누적)에 따라 평균 또는 합계
        for base_metric in ["평균 EP 전시 상품수", "평균 원부매칭 상품수", "평균 최저가 상품수"]:
            s = _cum_ep.set_index(COL_DATE)[base_metric].sort_index()
            series = s.resample(UNIT_CONFIG[cum_unit]["rule"]).agg(_agg_func)
            if cum_unit == "주별":
                series.index = series.index - pd.Timedelta(days=6)
            elif cum_unit == "월마감" and not series.empty and s.index.max() < series.index[-1]:
                series = series.iloc[:-1]
            series = _truncate_by_range(series, cum_start, cum_end, cum_unit)
            ep_table_rows[base_metric] = series

        # 원부매칭율/최저가율은 일평균/누적 모드와 무관하게 항상 기간 합계 기반으로 재계산
        ep_base_sum = {}
        for base_metric in ["평균 EP 전시 상품수", "평균 원부매칭 상품수", "평균 최저가 상품수"]:
            s = _cum_ep.set_index(COL_DATE)[base_metric].sort_index()
            series_sum = s.resample(UNIT_CONFIG[cum_unit]["rule"]).sum()
            if cum_unit == "주별":
                series_sum.index = series_sum.index - pd.Timedelta(days=6)
            elif cum_unit == "월마감" and not series_sum.empty and s.index.max() < series_sum.index[-1]:
                series_sum = series_sum.iloc[:-1]
            series_sum = _truncate_by_range(series_sum, cum_start, cum_end, cum_unit)
            ep_base_sum[base_metric] = series_sum
        ep_table_rows["원부매칭율(%)"] = (ep_base_sum["평균 원부매칭 상품수"] / ep_base_sum["평균 EP 전시 상품수"] * 100).replace([float("inf")], None)
        ep_table_rows["최저가율(%)"] = (ep_base_sum["평균 최저가 상품수"] / ep_base_sum["평균 EP 전시 상품수"] * 100).replace([float("inf")], None)

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
        export_rows = []
        for d in all_dates:
            row_label = make_period_label(d, cum_unit)
            cells = []
            export_row = {"구분": row_label}
            for key, label, is_pct in COLS:
                src = tr_table_rows.get(key, ep_table_rows.get(key))
                val = src.get(d) if src is not None and d in src.index else None
                if val is None or pd.isna(val):
                    cells.append("<td>-</td>")
                    export_row[label] = None
                elif is_pct:
                    cells.append(f"<td>{val:.1f}%</td>")
                    export_row[label] = float(val)  # 엑셀에는 반올림 없이 원본 값 그대로
                else:
                    cells.append(f"<td>{val:,.0f}</td>")
                    export_row[label] = float(val)  # 엑셀에는 반올림 없이 원본 값 그대로
            body_rows.append(f"<tr><td class='m'>{row_label}</td>{''.join(cells)}</tr>")
            export_rows.append(export_row)

        _tc1, _tc2 = st.columns([4, 1])
        with _tc1:
            st.markdown(f"**누적 데이터**  ·  <span style='color:#6b7280;font-size:0.85rem'>{len(all_dates)}개 기간</span>", unsafe_allow_html=True)
        with _tc2:
            _fname = f"누적데이터_{bpu}_{cum_unit}_{cum_start}_{cum_end}.xlsx".replace(" ", "")
            render_excel_download(pd.DataFrame(export_rows), _fname)
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
        f"<div class='chart-caption'>매체: <b>{bpu}</b> · 기간유형: <b>{cum_unit}</b> · 집계: <b>{cum_agg_mode}</b> · "
        f"고객구분: <b>{cum_segment}</b> · {cum_start} ~ {cum_end} · <b>{selected_cat}</b> / <b>{brand_label(selected_brand)}</b></div>",
        unsafe_allow_html=True,
    )
    _agg_func = "sum" if cum_agg_mode == "누적" else "mean"

    if df_category.empty:
        st.info("카테고리 데이터가 없습니다.")
    else:
        if bpu in BPU_GROUPS:
            _cum_cat_df = df_category[df_category["BPU"].isin(BPU_GROUPS[bpu])]
        elif bpu == "Total":
            _cum_cat_df = df_category
        else:
            _cum_cat_df = df_category[df_category["BPU"] == bpu]

        if "회원구분" in _cum_cat_df.columns:
            _cum_cat_df = _cum_cat_df[_cum_cat_df["회원구분"] == cum_segment]

        _cum_cat_combo = _cum_cat_df[(_cum_cat_df["카테고리"] == selected_cat) & (_cum_cat_df["브랜드"] == selected_brand)]
        if (bpu == "Total" or bpu in BPU_GROUPS) and not _cum_cat_combo.empty:
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
            # UV/거래액/구매객수는 집계 모드(일평균/누적)에 따라 평균 또는 합계
            for base_metric in ["트래픽", "거래액", "구매객수"]:
                s = _cum_cat_combo.set_index("날짜")[base_metric].sort_index()
                series = s.resample(UNIT_CONFIG[cum_unit]["rule"]).agg(_agg_func)
                if cum_unit == "주별":
                    series.index = series.index - pd.Timedelta(days=6)
                elif cum_unit == "월마감" and not series.empty and s.index.max() < series.index[-1]:
                    series = series.iloc[:-1]
                series = _truncate_by_range(series, cum_start, cum_end, cum_unit)
                cat_table_rows[base_metric] = series

            # CR/객단가는 일평균/누적 모드와 무관하게 항상 기간 합계 기반으로 재계산
            cat_base_sum = {}
            for base_metric in ["트래픽", "거래액", "구매객수"]:
                s = _cum_cat_combo.set_index("날짜")[base_metric].sort_index()
                series_sum = s.resample(UNIT_CONFIG[cum_unit]["rule"]).sum()
                if cum_unit == "주별":
                    series_sum.index = series_sum.index - pd.Timedelta(days=6)
                elif cum_unit == "월마감" and not series_sum.empty and s.index.max() < series_sum.index[-1]:
                    series_sum = series_sum.iloc[:-1]
                series_sum = _truncate_by_range(series_sum, cum_start, cum_end, cum_unit)
                cat_base_sum[base_metric] = series_sum
            cat_table_rows["CR"] = (cat_base_sum["구매객수"] / cat_base_sum["트래픽"] * 100).replace([float("inf")], None)
            cat_table_rows["객단가"] = (cat_base_sum["거래액"] / cat_base_sum["구매객수"]).replace([float("inf")], None)

            all_cat_dates = sorted(set().union(*[s.index for s in cat_table_rows.values()]), reverse=True)
            if not all_cat_dates:
                st.info("선택한 조건에 데이터가 없습니다.")
            else:
                header_html2 = "<th>구분</th>" + "".join(f"<th>{label}</th>" for _, label, _ in CAT_CUM_COLS)
                body_rows2 = []
                export_rows2 = []
                for d in all_cat_dates:
                    row_label = make_period_label(d, cum_unit)
                    cells = []
                    export_row2 = {"구분": row_label}
                    for key, label, _is_pct in CAT_CUM_COLS:
                        val = cat_table_rows[key].get(d)
                        if val is None or pd.isna(val):
                            cells.append("<td>-</td>")
                            export_row2[label] = None
                        elif _is_pct:
                            cells.append(f"<td>{val:.1f}%</td>")
                            export_row2[label] = float(val)  # 엑셀에는 반올림 없이 원본 값 그대로
                        else:
                            cells.append(f"<td>{val:,.0f}</td>")
                            export_row2[label] = float(val)  # 엑셀에는 반올림 없이 원본 값 그대로
                    body_rows2.append(f"<tr><td class='m'>{row_label}</td>{''.join(cells)}</tr>")
                    export_rows2.append(export_row2)

                _tc3, _tc4 = st.columns([4, 1])
                with _tc3:
                    st.markdown(f"**카테고리 누적 데이터**  ·  <span style='color:#6b7280;font-size:0.85rem'>{len(all_cat_dates)}개 기간</span>", unsafe_allow_html=True)
                with _tc4:
                    _fname2 = f"카테고리누적데이터_{bpu}_{selected_cat}_{brand_label(selected_brand)}_{cum_unit}.xlsx".replace(" ", "")
                    render_excel_download(pd.DataFrame(export_rows2), _fname2)
                table_html2 = (
                    "<div style='overflow-x:auto;'><table class='summary-table'>"
                    f"<thead><tr>{header_html2}</tr></thead>"
                    f"<tbody>{''.join(body_rows2)}</tbody></table></div>"
                )
                st.markdown(table_html2, unsafe_allow_html=True)


# ============================================================
# 페이지 5: 쿠폰 비용 분석
# ============================================================
if side["page"].startswith("5"):
    st.markdown("---")

    _has_daily = not df_coupon_daily.empty

    if df_coupon.empty:
        st.info("쿠폰 데이터가 없습니다. 사이드바에서 ep_coupon_daily.csv를 업로드해주세요.")
    else:
        # 매체(coupon_bpu)·쿠폰유형(coupon_type_sel)·조회단위(coupon_unit)·기준시점(coupon_ref_ts)은
        # 모두 상단 고정 필터(사이드바 바로 아래)에서 이미 정해져서 넘어온다.

        def _bpu_gmv_source(bpu_val):
            if bpu_val in BPU_GROUPS:
                return df_traffic[(df_traffic["BPU"].isin(BPU_GROUPS[bpu_val])) & (df_traffic["회원구분"] == "전체")]
            elif bpu_val == "Total":
                return df_traffic[(df_traffic["BPU"] == "Total") & (df_traffic["회원구분"] == "전체")]
            else:
                return df_traffic[(df_traffic["BPU"] == bpu_val) & (df_traffic["회원구분"] == "전체")]

        # ============================================================
        # 전체 시계열(_combined_full) 생성 — 아래 상단 기간필터 적용 전 원본.
        # 전기간비/전년비 조회는 항상 이 전체 시계열 기준으로 해서, 선택 구간을
        # 좁혀도 비교값을 못 찾는 일이 없게 한다.
        # ============================================================
        if coupon_unit == "월별":
            _cp_sub = df_coupon[df_coupon["BPU"] == coupon_bpu].copy()
            if coupon_type_sel != "합산":
                _cp_sub = _cp_sub[_cp_sub["쿠폰유형"] == coupon_type_sel]

            _coupon_by_month = _cp_sub.groupby("연월", as_index=False)["쿠폰할인"].sum().set_index("연월")["쿠폰할인"].sort_index()
            _gmv_by_month = _bpu_gmv_source(coupon_bpu).set_index("날짜")["거래액"].resample("MS").sum()
            _coupon_by_month.index = _coupon_by_month.index.to_period("M").to_timestamp()

            _combined_full = pd.DataFrame({"쿠폰할인": _coupon_by_month, "거래액": _gmv_by_month}).dropna(how="all")
            _combined_full["거래액"] = _combined_full["거래액"].fillna(0)
            _combined_full["쿠폰할인"] = _combined_full["쿠폰할인"].fillna(0)
            _combined_full["비용률"] = (_combined_full["쿠폰할인"] / _combined_full["거래액"] * 100).where(_combined_full["거래액"] > 0)
            _combined_full = _combined_full.sort_index()
            _period_fmt = lambda d: d.strftime("%Y년 %m월")
            _prev_label, _has_yoy = "전월비", True
            _step = pd.DateOffset(months=1)

        # ============================================================
        # 일별/주별 조회: 일자별 상세(ep_coupon_daily.csv) 사용
        # 참고: 이제 원본에 25년치도 있지만, 일/주별 전년비교 로직은 아직 미구현 상태(항상 _has_yoy=False)
        # ============================================================
        else:
            if coupon_bpu in BPU_GROUPS:
                _cpd_sub = df_coupon_daily[df_coupon_daily["BPU"].isin(BPU_GROUPS[coupon_bpu])].copy()
            elif coupon_bpu == "Total":
                _cpd_sub = df_coupon_daily.copy()
            else:
                _cpd_sub = df_coupon_daily[df_coupon_daily["BPU"] == coupon_bpu].copy()
            if coupon_type_sel != "합산":
                _cpd_sub = _cpd_sub[_cpd_sub["쿠폰유형"] == coupon_type_sel]

            _rule = "D" if coupon_unit == "일별" else "W-SUN"
            _coupon_series = _cpd_sub.groupby("날짜")["쿠폰할인"].sum().resample(_rule).sum()
            _gmv_series = _bpu_gmv_source(coupon_bpu).set_index("날짜")["거래액"].resample(_rule).sum()
            if coupon_unit == "주별":
                _coupon_series.index = _coupon_series.index - pd.Timedelta(days=6)
                _gmv_series.index = _gmv_series.index - pd.Timedelta(days=6)

            _combined_full = pd.DataFrame({"쿠폰할인": _coupon_series, "거래액": _gmv_series}).dropna(how="all")
            _combined_full["거래액"] = _combined_full["거래액"].fillna(0)
            _combined_full["쿠폰할인"] = _combined_full["쿠폰할인"].fillna(0)
            _combined_full["비용률"] = (_combined_full["쿠폰할인"] / _combined_full["거래액"] * 100).where(_combined_full["거래액"] > 0)
            _combined_full = _combined_full.sort_index()
            _prev_label_txt = "전일비" if coupon_unit == "일별" else "전주비"
            _period_fmt = (lambda d: d.strftime("%Y-%m-%d")) if coupon_unit == "일별" else (lambda d: f"{d.strftime('%Y-%m-%d')} 주")
            _prev_label, _has_yoy = _prev_label_txt, False
            _step = {"일별": pd.DateOffset(days=1), "주별": pd.DateOffset(weeks=1)}[coupon_unit]

        if _combined_full.empty:
            st.warning("해당 조건에 데이터가 없습니다.")
        else:
            # ============================================================
            # 상단 고정 필터의 기준일자/기준시점(coupon_ref_ts)까지만 사용.
            # KPI 카드·쿠폰명 랭킹·전년비 비교표가 모두 "그 시점 기준"으로 표시됨.
            # 전기간비/전년비는 그 이전 데이터를 찾아야 하므로 _combined_full을 그대로 쓴다.
            # ============================================================
            _latest = coupon_ref_ts
            if _latest not in _combined_full.index:
                _cp_cand = _combined_full.index[_combined_full.index <= _latest]
                _latest = _cp_cand[-1] if len(_cp_cand) else _combined_full.index[-1]
            _combined = _combined_full[_combined_full.index <= _latest]

            if _combined.empty:
                st.warning("선택한 기준일자에 데이터가 없습니다.")
            else:
                _prev_period = _latest - _step
                _prev_year = _latest - pd.DateOffset(years=1)

                _cur_coupon = _combined.loc[_latest, "쿠폰할인"]
                _cur_gmv = _combined.loc[_latest, "거래액"]
                _cur_rate = _combined.loc[_latest, "비용률"]

                def _delta_pct(cur, ref):
                    if ref is None or pd.isna(ref) or ref == 0:
                        return None
                    return (cur / ref - 1) * 100

                # 전기간비/전년비는 선택 구간 밖 값도 찾을 수 있도록 _combined_full 기준으로 조회
                _prev_coupon = _combined_full.loc[_prev_period, "쿠폰할인"] if _prev_period in _combined_full.index else None
                _prev_gmv = _combined_full.loc[_prev_period, "거래액"] if _prev_period in _combined_full.index else None
                _prev_rate = _combined_full.loc[_prev_period, "비용률"] if _prev_period in _combined_full.index else None
                if _has_yoy:
                    _yoy_coupon = _combined_full.loc[_prev_year, "쿠폰할인"] if _prev_year in _combined_full.index else None
                    _yoy_gmv = _combined_full.loc[_prev_year, "거래액"] if _prev_year in _combined_full.index else None
                    _yoy_rate = _combined_full.loc[_prev_year, "비용률"] if _prev_year in _combined_full.index else None
                else:
                    _yoy_coupon = _yoy_gmv = _yoy_rate = None

                _yoy_note = "" if _has_yoy else " · <span style='color:#9ca3af'>일별/주별 전년비교는 아직 지원 예정 기능이에요</span>"
                st.markdown(
                    f"<div class='chart-caption'>{coupon_bpu} · {coupon_type_sel} · {coupon_unit} · 기준: {_period_fmt(_latest)}{_yoy_note}</div>",
                    unsafe_allow_html=True,
                )
                kc1, kc2, kc3 = st.columns(3)
                with kc1:
                    _yoy_line = (
                        f"전년동기비 {format_delta_html(_delta_pct(_cur_coupon, _yoy_coupon))}{_ref_str(_yoy_coupon)}<br/>"
                        if _has_yoy else ""
                    )
                    st.markdown(
                        f"<div style='background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:14px 16px;min-height:150px;'>"
                        f"<div style='color:#6b7280;font-size:0.8rem;margin-bottom:4px;'>쿠폰할인</div>"
                        f"<div style='font-size:1.4rem;font-weight:700;color:#111827;'>{_cur_coupon:,.0f}</div>"
                        f"<div style='font-size:0.76rem;margin-top:6px;'>"
                        f"{_prev_label} {format_delta_html(_delta_pct(_cur_coupon, _prev_coupon))}{_ref_str(_prev_coupon)}<br/>"
                        f"{_yoy_line}"
                        f"</div></div>", unsafe_allow_html=True,
                    )
                with kc2:
                    _yoy_line2 = (
                        f"전년동기비 {format_delta_html(_delta_pct(_cur_gmv, _yoy_gmv))}{_ref_str(_yoy_gmv)}<br/>"
                        if _has_yoy else ""
                    )
                    st.markdown(
                        f"<div style='background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:14px 16px;min-height:150px;'>"
                        f"<div style='color:#6b7280;font-size:0.8rem;margin-bottom:4px;'>거래액(기존 대시보드 기준)</div>"
                        f"<div style='font-size:1.4rem;font-weight:700;color:#111827;'>{_cur_gmv:,.0f}</div>"
                        f"<div style='font-size:0.76rem;margin-top:6px;'>"
                        f"{_prev_label} {format_delta_html(_delta_pct(_cur_gmv, _prev_gmv))}{_ref_str(_prev_gmv)}<br/>"
                        f"{_yoy_line2}"
                        f"</div></div>", unsafe_allow_html=True,
                    )
                with kc3:
                    _rate_prev_delta = (_cur_rate - _prev_rate) if (_prev_rate is not None and pd.notna(_prev_rate) and pd.notna(_cur_rate)) else None
                    _rate_yoy_delta = (_cur_rate - _yoy_rate) if (_has_yoy and _yoy_rate is not None and pd.notna(_yoy_rate) and pd.notna(_cur_rate)) else None
                    _yoy_line3 = (
                        f"전년동기비 {format_delta_html(_rate_yoy_delta) if _rate_yoy_delta is not None else '-'}%p{_ref_str(_yoy_rate, True)}<br/>"
                        if _has_yoy else ""
                    )
                    st.markdown(
                        f"<div style='background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:14px 16px;min-height:150px;'>"
                        f"<div style='color:#6b7280;font-size:0.8rem;margin-bottom:4px;'>비용률 (쿠폰할인/거래액)</div>"
                        f"<div style='font-size:1.4rem;font-weight:700;color:#111827;'>{_cur_rate:.2f}%</div>"
                        f"<div style='font-size:0.76rem;margin-top:6px;'>"
                        f"{_prev_label} {format_delta_html(_rate_prev_delta) if _rate_prev_delta is not None else '-'}%p{_ref_str(_prev_rate, True)}<br/>"
                        f"{_yoy_line3}"
                        f"</div></div>", unsafe_allow_html=True,
                    )

                st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)

                # 쿠폰 유형별 비용률 (합산 선택시)
                if coupon_type_sel == "합산":
                    st.markdown("**쿠폰 유형별 비용률 (같은 매체·기간 기준)**")
                    _type_rows = []
                    for _t in ["플러스", "일반"]:
                        if coupon_unit == "월별":
                            _t_src = df_coupon[(df_coupon["BPU"] == coupon_bpu) & (df_coupon["쿠폰유형"] == _t)]
                            if _t_src.empty:
                                continue
                            _t_by_period = _t_src.groupby("연월")["쿠폰할인"].sum()
                            _t_by_period.index = _t_by_period.index.to_period("M").to_timestamp()
                        else:
                            if coupon_bpu in BPU_GROUPS:
                                _t_src = df_coupon_daily[(df_coupon_daily["BPU"].isin(BPU_GROUPS[coupon_bpu])) & (df_coupon_daily["쿠폰유형"] == _t)]
                            elif coupon_bpu == "Total":
                                _t_src = df_coupon_daily[df_coupon_daily["쿠폰유형"] == _t]
                            else:
                                _t_src = df_coupon_daily[(df_coupon_daily["BPU"] == coupon_bpu) & (df_coupon_daily["쿠폰유형"] == _t)]
                            if _t_src.empty:
                                continue
                            _t_by_period = _t_src.groupby("날짜")["쿠폰할인"].sum().resample(_rule).sum()
                            if coupon_unit == "주별":
                                _t_by_period.index = _t_by_period.index - pd.Timedelta(days=6)
                        _t_cur = _t_by_period.get(_latest, 0)
                        _t_rate = (_t_cur / _cur_gmv * 100) if _cur_gmv > 0 else None
                        _type_rows.append({"쿠폰유형": _t, "쿠폰할인": _t_cur, "비용률": _t_rate})
                    _type_df = pd.DataFrame(_type_rows)
                    _tcols = st.columns(len(_type_df)) if len(_type_df) else []
                    for _i, _r in enumerate(_type_df.itertuples()):
                        with _tcols[_i]:
                            _rate_html = f"비용률 {_r.비용률:.2f}%" if _r.비용률 is not None else "비용률 -"
                            st.markdown(
                                f"<div style='background:#f8fafc;border:1px solid #e5e7eb;border-radius:8px;padding:10px 14px;'>"
                                f"<div style='font-size:0.78rem;color:#6b7280;'>{_r.쿠폰유형}</div>"
                                f"<div style='font-size:1.1rem;font-weight:700;'>{_r.쿠폰할인:,.0f}</div>"
                                f"<div style='font-size:0.85rem;color:#7c3aed;'>{_rate_html}</div>"
                                f"</div>", unsafe_allow_html=True,
                            )
                    st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)

                # ============================================================
                # 추이 차트: 상단 기간필터가 적용된 _combined을 기본으로 사용.
                # 일별 조회일 땐 점이 너무 많아지므로, 그래프 전용 기간(줌) 컨트롤을
                # 추가로 둔다 (기본 최근 30일 + "최근으로" 리셋 버튼).
                # ============================================================
                st.markdown(f"**{coupon_unit} 쿠폰할인 · 비용률 추이**")

                _chart_series = _combined
                if coupon_unit == "일별" and len(_combined) > 1:
                    _cp_chart_default_start = max(
                        _combined.index.min().date(), _combined.index.max().date() - _dt.timedelta(days=30)
                    )
                    _cp_chart_key = f"coupon_chart_range_{coupon_bpu}_{coupon_type_sel}"
                    _cc1, _cc2 = st.columns([2, 1])
                    with _cc1:
                        st.markdown("<div style='font-size:0.78rem;color:#6b7280;margin-bottom:1px;'>그래프 기간</div>", unsafe_allow_html=True)
                        _cp_chart_dr = st.date_input(
                            "그래프 기간",
                            value=(_cp_chart_default_start, _combined.index.max().date()),
                            min_value=_combined.index.min().date(), max_value=_combined.index.max().date(),
                            label_visibility="collapsed", key=_cp_chart_key,
                        )
                    with _cc2:
                        st.markdown("<div style='height:1.5rem;'></div>", unsafe_allow_html=True)
                        st.button(
                            "🔄 최근으로", key=f"{_cp_chart_key}_reset", use_container_width=True,
                            on_click=_reset_date_range, args=(_cp_chart_key, (_cp_chart_default_start, _combined.index.max().date())),
                        )
                    if isinstance(_cp_chart_dr, tuple) and len(_cp_chart_dr) == 2:
                        _chart_series = _combined[
                            (_combined.index >= pd.Timestamp(_cp_chart_dr[0])) & (_combined.index <= pd.Timestamp(_cp_chart_dr[1]))
                        ]

                import altair as alt
                _trend_df = _chart_series.copy()
                _trend_df.index.name = "연월"
                _trend_df = _trend_df.reset_index()
                _trend_df["연월_label"] = _trend_df["연월"].apply(_period_fmt)
                _month_order = _trend_df["연월_label"].tolist()
                _base = alt.Chart(_trend_df).encode(
                    x=alt.X("연월_label:O", title=None, sort=_month_order, axis=alt.Axis(labelAngle=-40))
                )
                _bar = _base.mark_bar(color="#93c5fd", size=18).encode(
                    y=alt.Y("쿠폰할인:Q", title="쿠폰할인", axis=alt.Axis(format="~s")),
                    tooltip=[alt.Tooltip("연월_label:N", title="기간"), alt.Tooltip("쿠폰할인:Q", title="쿠폰할인", format=",.0f")],
                )
                _line = _base.mark_line(color="#dc2626", strokeWidth=2, point=alt.OverlayMarkDef(size=45, filled=True)).encode(
                    y=alt.Y("비용률:Q", title="비용률(%)", axis=alt.Axis(format=".1f")),
                    tooltip=[alt.Tooltip("연월_label:N", title="기간"), alt.Tooltip("비용률:Q", title="비용률", format=".2f")],
                )
                _chart = alt.layer(_bar, _line).resolve_scale(y="independent").properties(height=350)
                st.altair_chart(_chart, use_container_width=True)

                _export_df = _trend_df.copy()
                _export_df["연월"] = _export_df["연월_label"]
                _export_df = _export_df.drop(columns=["연월_label"])
                render_excel_download(_export_df, f"쿠폰비용_{coupon_bpu}_{coupon_type_sel}_{coupon_unit}.xlsx")

                st.markdown("<div style='height:16px;'></div>", unsafe_allow_html=True)

                # 쿠폰명별 랭킹 (최신 기간 기준)
                st.markdown(f"**쿠폰명별 할인액 랭킹 · {_period_fmt(_latest)} 기준**")
                if coupon_unit == "월별":
                    if df_coupon_detail.empty:
                        st.info("쿠폰 상세 데이터가 없습니다. 사이드바에서 ep_coupon_daily.csv를 업로드해주세요.")
                        _detail_sub = None
                    else:
                        _detail_sub = df_coupon_detail[df_coupon_detail["연월"] == _latest]
                else:
                    if not _has_daily:
                        _detail_sub = None
                    else:
                        if coupon_unit == "일별":
                            _detail_sub = df_coupon_daily[df_coupon_daily["날짜"] == _latest]
                        else:  # 주별: 해당 주(월~일) 범위 합산
                            _week_start, _week_end = _latest, _latest + pd.Timedelta(days=6)
                            _detail_sub = df_coupon_daily[(df_coupon_daily["날짜"] >= _week_start) & (df_coupon_daily["날짜"] <= _week_end)]

                if _detail_sub is None:
                    pass
                else:
                    if coupon_bpu in BPU_GROUPS:
                        _detail_sub = _detail_sub[_detail_sub["BPU"].isin(BPU_GROUPS[coupon_bpu])]
                    elif coupon_bpu != "Total":
                        _detail_sub = _detail_sub[_detail_sub["BPU"] == coupon_bpu]
                    if coupon_type_sel != "합산":
                        _detail_sub = _detail_sub[_detail_sub["쿠폰유형"] == coupon_type_sel]

                    if _detail_sub.empty:
                        st.info("해당 조건의 쿠폰 상세 데이터가 없습니다.")
                    else:
                        _rank = _detail_sub.groupby(["쿠폰ID", "쿠폰명", "쿠폰유형"], as_index=False)["쿠폰할인"].sum()
                        _rank = _rank.sort_values("쿠폰할인", ascending=False).head(15).reset_index(drop=True)
                        _rank_html = "".join(
                            f"<tr><td>{i+1}</td><td>{r['쿠폰ID']}</td><td>{r['쿠폰명']}</td><td>{r['쿠폰유형']}</td>"
                            f"<td style='text-align:right;'>{r['쿠폰할인']:,.0f}</td></tr>"
                            for i, r in _rank.iterrows()
                        )
                        st.markdown(
                            "<table class='summary-table'><thead><tr>"
                            "<th>#</th><th>쿠폰번호</th><th>쿠폰명</th><th>유형</th><th style='text-align:right;'>할인액</th>"
                            "</tr></thead><tbody>" + _rank_html + "</tbody></table>",
                            unsafe_allow_html=True,
                        )

                st.markdown("<div style='height:16px;'></div>", unsafe_allow_html=True)

                # 전년비 비교표는 월별 조회에서만 (일/주별 전년비교는 아직 미구현)
                # 선택한 기간(_combined) 범위만 표에 나오되, 전년 값 조회는 _combined_full에서 한다.
                if _has_yoy:
                    st.markdown("**월별 전년비 비교**")
                    _yoy_rows = []
                    for _m in sorted(_combined.index, reverse=True):
                        _py = _m - pd.DateOffset(years=1)
                        _cur_gmv_m = _combined.loc[_m, "거래액"]
                        _cur_coupon_m = _combined.loc[_m, "쿠폰할인"]
                        _cur_rate_m = _combined.loc[_m, "비용률"]
                        if _py in _combined_full.index:
                            _py_gmv = _combined_full.loc[_py, "거래액"]
                            _py_coupon = _combined_full.loc[_py, "쿠폰할인"]
                            _py_rate = _combined_full.loc[_py, "비용률"]
                        else:
                            _py_gmv = _py_coupon = _py_rate = None
                        _gmv_yoy = ((_cur_gmv_m / _py_gmv) - 1) * 100 if _py_gmv else None
                        _coupon_yoy = ((_cur_coupon_m / _py_coupon) - 1) * 100 if _py_coupon else None
                        _rate_yoy_pt = (_cur_rate_m - _py_rate) if (_py_rate is not None and pd.notna(_py_rate) and pd.notna(_cur_rate_m)) else None
                        _yoy_rows.append({
                            "연월": _m, "거래액": _cur_gmv_m, "작년거래액": _py_gmv, "거래액증감": _gmv_yoy,
                            "쿠폰할인": _cur_coupon_m, "작년쿠폰할인": _py_coupon, "쿠폰할인증감": _coupon_yoy,
                            "비용률": _cur_rate_m, "작년비용률": _py_rate, "비용률증감": _rate_yoy_pt,
                        })

                    def _fmt_num(v):
                        return f"{v:,.0f}" if v is not None and pd.notna(v) else "-"

                    def _fmt_pct(v):
                        return f"{v:.2f}%" if v is not None and pd.notna(v) else "-"

                    _yoy_body = ""
                    for r in _yoy_rows:
                        _yoy_body += (
                            f"<tr><td class='m'>{r['연월'].strftime('%Y년 %m월')}</td>"
                            f"<td style='text-align:right;'>{_fmt_num(r['거래액'])}</td>"
                            f"<td style='text-align:right;color:#9ca3af;'>{_fmt_num(r['작년거래액'])}</td>"
                            f"<td style='text-align:right;'>{format_delta_html(r['거래액증감'])}</td>"
                            f"<td style='text-align:right;'>{_fmt_num(r['쿠폰할인'])}</td>"
                            f"<td style='text-align:right;color:#9ca3af;'>{_fmt_num(r['작년쿠폰할인'])}</td>"
                            f"<td style='text-align:right;'>{format_delta_html(r['쿠폰할인증감'])}</td>"
                            f"<td style='text-align:right;'>{_fmt_pct(r['비용률'])}</td>"
                            f"<td style='text-align:right;color:#9ca3af;'>{_fmt_pct(r['작년비용률'])}</td>"
                            f"<td style='text-align:right;'>{format_delta_html(r['비용률증감'])}</td></tr>"
                        )
                    st.markdown(
                        "<div style='overflow-x:auto;'><table class='summary-table'>"
                        "<thead><tr><th>연월</th>"
                        "<th colspan='3' style='text-align:center;background:#eef2ff;'>거래액</th>"
                        "<th colspan='3' style='text-align:center;background:#fef3c7;'>쿠폰할인</th>"
                        "<th colspan='3' style='text-align:center;background:#fce7f3;'>비용률</th>"
                        "</tr><tr><th></th>"
                        "<th style='text-align:right;'>올해</th><th style='text-align:right;'>작년</th><th style='text-align:right;'>증감</th>"
                        "<th style='text-align:right;'>올해</th><th style='text-align:right;'>작년</th><th style='text-align:right;'>증감</th>"
                        "<th style='text-align:right;'>올해</th><th style='text-align:right;'>작년</th><th style='text-align:right;'>증감</th>"
                        "</tr></thead>"
                        f"<tbody>{_yoy_body}</tbody></table></div>",
                        unsafe_allow_html=True,
                    )

                    _yoy_export = pd.DataFrame(_yoy_rows)
                    _yoy_export["연월"] = _yoy_export["연월"].dt.strftime("%Y-%m")
                    render_excel_download(_yoy_export, f"쿠폰비용_전년비교_{coupon_bpu}_{coupon_type_sel}.xlsx")
                else:
                    st.caption("ℹ️ 전년비 비교표는 월별 조회에서만 제공돼요 (일별/주별 전년비교는 아직 지원 예정 기능이에요).")


# ============================================================
# 페이지 6: 주간보고용 (전년동요일 요약 엑셀 다운로드)
# ============================================================
if side["page"].startswith("6"):
    st.markdown("---")
    st.markdown("### 📑 주간보고용 · 전년동요일 요약")

    if df_traffic.empty and df_category.empty:
        st.info("데이터가 없습니다. 사이드바에서 EP실적/카테고리 CSV를 업로드해주세요.")
    else:
        # 이 페이지는 항상 '월별' 기준으로 만든다 (사이드바 조회단위와 무관 — 예전 스크린샷과
        # 동일하게 "진행 중인 달 1~N일" vs "작년 같은 날짜들"을 비교하는 게 목적이라서).
        _wk_unit = "월별"

        if not df_traffic.empty:
            _wk_base = df_traffic[(df_traffic["BPU"] == "Total") & (df_traffic["회원구분"] == "전체")] \
                if "회원구분" in df_traffic.columns else df_traffic[df_traffic["BPU"] == "Total"]
            _all_dates = pd.DatetimeIndex(sorted(_wk_base["날짜"].unique()))
        else:
            _all_dates = pd.DatetimeIndex(sorted(df_category["날짜"].unique()))

        # 카테고리 세그먼트/핏플랍 제외는 2번 페이지에서 지금 설정해둔 값을 그대로 가져온다
        # (2번 페이지를 안 들렀으면 기본값: 전체 세그먼트, 핏플랍 포함)
        _wk_cat_segment = st.session_state.get("cat_seg_filter", "전체")
        _wk_ff_exclude = st.session_state.get("cat_ff_exclude", False)

        _rule = UNIT_CONFIG[_wk_unit]["rule"]
        _wk_s = pd.Series(1, index=_all_dates).resample(_rule).sum()
        _wk_periods = list(_wk_s.index)
        _wk_labels = [make_period_label(d, _wk_unit) for d in _wk_periods]
        _wk_c1, _wk_c2 = st.columns([1, 3])
        with _wk_c1:
            st.markdown("<div style='font-size:0.78rem;color:#6b7280;margin-bottom:1px;'>기준 시점(월)</div>", unsafe_allow_html=True)
            _wk_sel_label = st.selectbox(
                "기준 시점", _wk_labels, index=len(_wk_labels) - 1,
                label_visibility="collapsed", key="wk_ref_period",
            )
        _wk_ref = _wk_periods[_wk_labels.index(_wk_sel_label)]
        st.caption(
            f"BPU별 상세는 **1. 실적 요약**과 동일한 로직, 카테고리별 거래액은 **2. 카테고리 실적 요약**과 "
            f"동일한 로직(세그먼트: {_wk_cat_segment}"
            + (", 핏플랍 제외 적용" if _wk_ff_exclude else "")
            + ")을 그대로 재사용해서 만들어요."
        )
        if _wk_ff_exclude:
            st.caption(
                "ℹ️ 핏플랍 제외는 **카테고리별 시트에만** 반영돼요 — EP실적 원본(ep_traffic.csv)엔 "
                "브랜드 정보가 없어서 BPU별 시트에서는 애초에 제외할 수가 없어요. 그래서 이 상태로는 "
                "두 시트의 '전체' 합계가 핏플랍 매출만큼 차이 날 수 있어요."
            )

        try:
            _wk_xlsx, _pv_left, _pv_right = build_weekly_report_excel(
                _wk_unit, _wk_ref, df_traffic, df_category, _wk_cat_segment, _wk_ff_exclude
            )

            # 실제 계산에 쓰인 공통 cutoff 기준으로 날짜 범위를 표시 (진행 중인 달이면 예: 8/1~3 vs 작년 8/2~4)
            _wk_tr_max = df_traffic["날짜"].max() if not df_traffic.empty else None
            _wk_cat_max = df_category["날짜"].max() if not df_category.empty else None
            _wk_cutoff = min([d for d in [_wk_tr_max, _wk_cat_max, pd.Timestamp(_wk_ref)] if d is not None])
            _wk_month_start = pd.Timestamp(_wk_ref).replace(day=1)
            _wk_cur_days = _all_dates[(_all_dates >= _wk_month_start) & (_all_dates <= _wk_cutoff)]
            _wk_prev_days = pd.DatetimeIndex([d - pd.Timedelta(days=364) for d in _wk_cur_days])
            _wk_cur_rng = f"{_wk_cur_days.min().strftime('%y.%m.%d')} ~ {_wk_cur_days.max().strftime('%m.%d')}" if len(_wk_cur_days) else "-"
            _wk_prev_rng = f"{_wk_prev_days.min().strftime('%y.%m.%d')} ~ {_wk_prev_days.max().strftime('%m.%d')}" if len(_wk_prev_days) else "-"

            if _wk_tr_max is not None and _wk_cat_max is not None and _wk_tr_max.normalize() != _wk_cat_max.normalize():
                st.caption(
                    f"⚠️ EP실적 원본은 {_wk_tr_max.strftime('%Y-%m-%d')}까지, 카테고리 원본은 "
                    f"{_wk_cat_max.strftime('%Y-%m-%d')}까지 있어서, 더 짧은 쪽({_wk_cutoff.strftime('%Y-%m-%d')})에 "
                    "맞춰서 두 표를 계산했어요 (그래야 BPU별/카테고리별 '전체' 합계가 일치해요)."
                )

            st.markdown(
                f"<div style='background:#f8fafc;border:1px solid #e5e7eb;border-radius:8px;padding:10px 14px;margin:8px 0;'>"
                f"<div style='font-size:0.85rem;color:#374151;'>📅 <b>올해</b> {_wk_cur_rng}"
                f" &nbsp;vs&nbsp; <b>전년 동요일</b> {_wk_prev_rng}</div>"
                f"<div style='font-size:0.76rem;color:#6b7280;margin-top:3px;'>"
                f"트래픽·거래액·구매객수는 기간 합계, CR·객단가는 합계에서 재계산 · 거래액 없는 카테고리 제외</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

            st.download_button(
                "⬇️ 전년동요일 요약 엑셀 다운로드",
                data=_wk_xlsx,
                file_name=f"EP_주간보고_전년동요일_{pd.Timestamp(_wk_ref).strftime('%Y%m')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=False,
            )

            st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)
            _pc1, _pc2 = st.columns(2)
            with _pc1:
                st.markdown("**BPU별**")
                st.dataframe(_pv_left, use_container_width=True, hide_index=True, height=360)
            with _pc2:
                st.markdown("**카테고리별 (거래액)**")
                st.dataframe(_pv_right, use_container_width=True, hide_index=True, height=360)
        except Exception as _e:
            st.error(f"요약 엑셀 생성 중 문제가 발생했어요: {_e}")


# ============================================================
# 페이지 7/8/9: 전체/회원/신규 실적 (주차별) — 25년 vs 26년 vs 25년(FF제외)
# 세 페이지가 트래픽 세그먼트만 다르고 나머지 구조는 완전히 동일해서 공유 함수로 처리.
# ============================================================
def _render_weekly_segment_page(page_title, traffic_segment):
    """page_title: 화면에 보일 이름(예: '전체 실적'). traffic_segment: 트래픽 섹션에 쓸
    회원구분('전체'/'회원'/'신규'). 거래액 섹션은 기존에 정한 대로 항상 '전체' 세그먼트를 쓴다
    (거래액은 세그먼트 구분보다 전체 기준으로 보는 게 맞다고 판단했던 부분 그대로 유지)."""
    st.markdown("---")
    st.markdown(f"### 📅 {page_title} · 주차별 25년 vs 26년")
    st.caption(
        "각 연도 1월 1일부터 월~일 단위로 주차를 매겨서(그 해의 1주차부터), "
        "올해/작년 같은 주차끼리 나란히 비교해요. 자사 정상=e-영업1, 자사 이월=e-영업2, "
        f"입점=e-영업3+e-영업4. 트래픽·거래액 둘 다 '{traffic_segment}' 세그먼트 기준이에요."
    )

    if df_traffic.empty:
        st.info("데이터가 없습니다. 사이드바에서 ep_traffic.csv를 업로드해주세요.")
        return

    def _render_weekly_yearly_chart(title, s_by_label, wk_range, color_scheme=None, y_domain=None, week_labels=None):
        """s_by_label: {라벨: Series(주차 정수 인덱스)} — 라벨 순서대로 그린다.
        wk_range: (시작주차, 끝주차) — 이 범위만 잘라서 표시.
        color_scheme: {"25년":색, "26년":색, "25년(FF제외)":색} — 차트마다 다른 색 팔레트.
        y_domain: (최소,최대) 주어지면 y축을 이 값으로 고정한다(같은 섹션의 4개 차트가
        같은 y축 범위를 공유해서 서로 높이를 비교할 수 있게 하기 위함). 없으면 차트별로
        자동 확대(zero=False).
        week_labels: 주차 정수(1-based) -> 'N월 N주차' 라벨 리스트. 주면 x축에 숫자 대신
        이 라벨을 쓴다(상단 주차 범위 슬라이더와 동일한 라벨 체계)."""
        import altair as alt
        _colors = color_scheme or {"25년": "#2563eb", "26년": "#f97316", "25년(FF제외)": "#9ca3af"}
        frames = []
        for label, s in s_by_label.items():
            if s is not None and not s.empty:
                s = s[(s.index >= wk_range[0]) & (s.index <= wk_range[1])]
                if not s.empty:
                    frames.append(pd.DataFrame({"주차": s.index, "값": s.values, "구분": label}))
        if not frames:
            st.info("선택한 주차 범위에 데이터가 없습니다.")
            return
        long_df = pd.concat(frames, ignore_index=True)

        # "26년" 라인 위에 마우스 올렸을 때 전년비(%)도 같이 보이게 — 같은 주차의 "25년"
        # 값과 비교해서 계산한다. 26년이 아닌 행(25년/25년(FF제외))에는 안 채운다.
        long_df["전년비"] = pd.NA
        if "25년" in s_by_label and "26년" in s_by_label:
            _s25 = s_by_label["25년"]
            _s26_mask = long_df["구분"] == "26년"
            for idx in long_df[_s26_mask].index:
                _wk = long_df.at[idx, "주차"]
                if _s25 is not None and _wk in _s25.index and pd.notna(_s25.loc[_wk]) and _s25.loc[_wk] != 0:
                    long_df.at[idx, "전년비"] = (long_df.at[idx, "값"] / _s25.loc[_wk] - 1) * 100
        long_df["전년비_표시"] = long_df["전년비"].apply(
            lambda v: f"{'▲' if v >= 0 else '▼'}{abs(v):.1f}%" if pd.notna(v) else "-"
        )

        _domain = [d for d in s_by_label.keys() if d in long_df["구분"].unique()]
        _range = [_colors.get(d, "#000000") for d in _domain]
        # "25년(FF제외)"만 점선으로 그려서 실제값(25/26년)과 구분되게 함
        _dash_range = [[1, 0] if d != "25년(FF제외)" else [5, 3] for d in _domain]
        _y_scale = alt.Scale(domain=list(y_domain)) if y_domain is not None else alt.Scale(zero=False)

        if week_labels:
            long_df["주차_라벨"] = long_df["주차"].apply(
                lambda w: week_labels[w - 1] if 0 <= w - 1 < len(week_labels) else str(w)
            )
            _wk_uniq = sorted(long_df["주차"].unique())
            _wk_sort = [week_labels[w - 1] if 0 <= w - 1 < len(week_labels) else str(w) for w in _wk_uniq]
            _x_field, _x_sort = "주차_라벨:O", _wk_sort
            _x_tooltip_field, _x_tooltip_title = "주차_라벨:N", "주차"
        else:
            _x_field, _x_sort = "주차:O", None
            _x_tooltip_field, _x_tooltip_title = "주차:O", "주차"

        chart = (
            alt.Chart(long_df)
            .mark_line(strokeWidth=3, point=alt.OverlayMarkDef(size=32, filled=True))
            .encode(
                x=alt.X(_x_field, title=None, sort=_x_sort, axis=alt.Axis(labelAngle=-90, labelFontSize=8, labelPadding=2)),
                y=alt.Y("값:Q", title=None, axis=alt.Axis(format="~s"), scale=_y_scale),
                color=alt.Color(
                    "구분:N", scale=alt.Scale(domain=_domain, range=_range),
                    legend=alt.Legend(orient="bottom", title=None),
                ),
                strokeDash=alt.StrokeDash(
                    "구분:N", scale=alt.Scale(domain=_domain, range=_dash_range), legend=None,
                ),
                tooltip=[
                    alt.Tooltip(_x_tooltip_field, title=_x_tooltip_title),
                    alt.Tooltip("구분:N", title="구분"),
                    alt.Tooltip("값:Q", title="값", format=",.0f"),
                    alt.Tooltip("전년비_표시:N", title="전년비"),
                ],
            )
            .properties(height=280)
            .interactive()  # 확대(fullscreen) 보기에서 휠 줌/드래그 팬 가능하게
        )
        st.markdown(f"**{title}**")
        st.altair_chart(chart, use_container_width=True)

    _has_ff_data = not df_category.empty and (df_category["브랜드"] == "FF").any()
    _tr_ff_adj = exclude_ff_from_traffic(df_traffic, df_category) if _has_ff_data else None

    # 차트(BPU)별로 다른 색 계열 — 25년=연한색, 26년=진한색, FF제외=같은 계열의 중간톤
    _charts_def = [
        ("전체", "single", "Total", {"25년": "#c7c7c7", "26년": "#7f7f7f", "25년(FF제외)": "#ffbb78"}),
        ("자사 정상", "single", "e-영업1", {"25년": "#aec7e8", "26년": "#1f77b4", "25년(FF제외)": "#ffbb78"}),
        ("자사 이월", "single", "e-영업2", {"25년": "#98df8a", "26년": "#2ca02c", "25년(FF제외)": "#ffbb78"}),
        ("입점", "multi", ["e-영업3", "e-영업4"], {"25년": "#c5b0d5", "26년": "#9467bd", "25년(FF제외)": "#ffbb78"}),
    ]

    # 주차 범위(wk_range)와 라벨(_wk7_labels)은 상단 고정 영역에서 이미 만들어져서 넘어온다.

    def _render_section(section_title, metric, segment_value, show_ff):
        """metric(트래픽/거래액), segment_value(세그먼트) 기준으로 4개 BPU 차트를 그린다.
        '전체'는 규모가 훨씬 커서 같이 묶으면 나머지가 다 눌려 보이므로 독자적인 y축을 쓰고,
        '자사 정상/자사 이월/입점' 3개는 서로 규모가 비슷해서 공통 y축을 공유해 흐름을
        비교할 수 있게 한다."""
        st.markdown(f"#### {section_title}")
        _base = df_traffic[df_traffic["회원구분"] == segment_value]
        _base_ff = None
        if show_ff and _tr_ff_adj is not None:
            _base_ff = _tr_ff_adj[_tr_ff_adj["회원구분"] == segment_value]

        # 1단계: 4개 차트 데이터를 먼저 만들면서, 화면에 실제로 표시될(주차 범위로 자른)
        # 값들의 최소/최대를 '전체' 따로, '정상/이월/입점' 따로 모은다.
        _chart_series = []
        _total_vals, _shared_vals = [], []
        for label, kind, bpu_sel, color_scheme in _charts_def:
            if kind == "single":
                _d = _base[_base["BPU"] == bpu_sel][["날짜", metric]]
            else:
                _d = _base[_base["BPU"].isin(bpu_sel)].groupby("날짜", as_index=False)[metric].sum()

            s2025 = _weekly_of_year(_d, metric, 2025)
            s2026 = _weekly_of_year(_d, metric, 2026)

            s2025_ff = None
            if show_ff and kind == "single" and _base_ff is not None:
                _d_ff = _base_ff[_base_ff["BPU"] == bpu_sel][["날짜", metric]]
                s2025_ff = _weekly_of_year(_d_ff, metric, 2025)

            _series_map = {"25년": s2025, "26년": s2026}
            if s2025_ff is not None and not s2025_ff.empty:
                _series_map["25년(FF제외)"] = s2025_ff

            _chart_series.append((label, color_scheme, _series_map))
            _vals_bucket = _total_vals if label == "전체" else _shared_vals
            for s in _series_map.values():
                if s is not None and not s.empty:
                    _s_clip = s[(s.index >= wk_range[0]) & (s.index <= wk_range[1])]
                    if not _s_clip.empty:
                        _vals_bucket.append(float(_s_clip.min()))
                        _vals_bucket.append(float(_s_clip.max()))

        def _domain_from(vals):
            if not vals:
                return None
            _min, _max = min(vals), max(vals)
            _pad = (_max - _min) * 0.05 if _max > _min else (abs(_max) * 0.05 or 1)
            return (_min - _pad, _max + _pad)

        _total_domain = _domain_from(_total_vals)
        _shared_domain = _domain_from(_shared_vals)

        # '전체' 대비 비중(%) — 26년, 선택된 주차 범위의 합계 기준으로 계산해서 타이틀에 붙인다
        _total_26_sum = None
        for _label0, _cs0, _sm0 in _chart_series:
            if _label0 == "전체":
                _s26_total = _sm0.get("26년")
                if _s26_total is not None and not _s26_total.empty:
                    _s26_total_clip = _s26_total[(_s26_total.index >= wk_range[0]) & (_s26_total.index <= wk_range[1])]
                    if not _s26_total_clip.empty:
                        _total_26_sum = float(_s26_total_clip.sum())
                break

        # 2단계: '전체'는 자기 domain, 나머지 3개는 공유 domain으로 그린다
        _cols = st.columns(4)
        for i, (label, color_scheme, _series_map) in enumerate(_chart_series):
            with _cols[i]:
                _y_domain = _total_domain if label == "전체" else _shared_domain
                # "전체 실적" 페이지의 "전체"(Total) 차트처럼, label과 section_title이
                # 겹쳐서 "전체 전체 트래픽"같이 중복되는 경우 label을 또 붙이지 않는다.
                _title = section_title if section_title.startswith(label) else f"{label} {section_title}"
                if label != "전체" and _total_26_sum:
                    _s26 = _series_map.get("26년")
                    if _s26 is not None and not _s26.empty:
                        _s26_clip = _s26[(_s26.index >= wk_range[0]) & (_s26.index <= wk_range[1])]
                        if not _s26_clip.empty:
                            _share = float(_s26_clip.sum()) / _total_26_sum * 100
                            _title += f" (전체 중 {_share:.0f}%)"
                _render_weekly_yearly_chart(
                    _title, _series_map, wk_range, color_scheme,
                    y_domain=_y_domain, week_labels=_wk7_labels,
                )

    _render_section(f"{traffic_segment} 트래픽", "트래픽", traffic_segment, show_ff=True)

    st.markdown("<div style='height:16px;'></div>", unsafe_allow_html=True)
    st.markdown("---")
    _render_section(f"{traffic_segment} 거래액", "거래액", traffic_segment, show_ff=True)


if side["page"].startswith("7"):
    _render_weekly_segment_page("전체 실적", "전체")

if side["page"].startswith("8"):
    _render_weekly_segment_page("회원 실적", "회원")

if side["page"].startswith("9"):
    _render_weekly_segment_page("신규 실적", "신규")
