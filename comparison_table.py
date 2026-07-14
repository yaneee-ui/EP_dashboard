"""사업부(BPU)별 실적 비교 테이블 생성."""
import pandas as pd

from utils import COL_BPU, COL_MATCH, COL_LOWEST, resample_series, compute_kpi_deltas, format_value


def build_comparison_table(df_all, metric, match_status, lowest_status, unit):
    bpus = sorted(df_all[COL_BPU].unique(), key=lambda x: (x != "Total", x))
    rows = []
    latest_date_label = None

    for bpu in bpus:
        sub = df_all[
            (df_all[COL_BPU] == bpu)
            & (df_all[COL_MATCH] == match_status)
            & (df_all[COL_LOWEST] == lowest_status)
        ]
        if sub.empty:
            continue
        series = resample_series(sub, metric, unit)
        stats = compute_kpi_deltas(series, unit)
        if stats is None:
            continue

        if latest_date_label is None:
            latest_date_label = series.dropna().index[-1]
            _d = pd.Timestamp(latest_date_label).strftime("%Y-%m-%d")
            if unit == "주별":
                value_col = f"{_d} 주 값"
            elif unit in ("월별", "월마감"):
                value_col = f"{pd.Timestamp(latest_date_label).strftime('%Y-%m')} 값"
            else:
                value_col = f"{_d} 값"

        rows.append({
            "사업부": bpu,
            value_col: format_value(stats["current"], metric),
            stats["prev_label"]: _delta_str(stats["prev_delta"]),
            stats["avg_label"]: _delta_str(stats["avg_delta"]),
            stats["yoy_label"]: _delta_str(stats["yoy_delta"]),
        })

    return pd.DataFrame(rows)


def _delta_str(delta):
    if delta is None or pd.isna(delta):
        return "-"
    sign = "+" if delta > 0 else ""
    return f"{sign}{delta:.1f}%"


def build_summary_metrics_table(df_combo, unit):
    """01 실적요약 하단 표: 6개 지표별 [값 / 전기간비 / 전년비].
    비교 기준(전일/전주/전월, 전년동일/동주/동월)은 조회 단위(unit)를 따른다.
    """
    from utils import HEADLINE_METRICS

    rows = []
    prev_label_used = None
    yoy_label_used = None

    for metric in HEADLINE_METRICS:
        series = resample_series(df_combo, metric, unit)
        stats = compute_kpi_deltas(series, unit)
        if stats is None:
            rows.append({"지표": metric, "값": "-", "전기간비": "-", "전년비": "-"})
            continue
        prev_label_used = stats["prev_label"]
        yoy_label_used = stats["yoy_label"]
        rows.append({
            "지표": metric,
            "값": format_value(stats["current"], metric),
            "전기간비": _delta_str(stats["prev_delta"]),
            "전년비": _delta_str(stats["yoy_delta"]),
        })

    out = pd.DataFrame(rows)
    # 컬럼명을 단위에 맞게 (전주비 / 전년동주비 등)
    out = out.rename(columns={
        "전기간비": prev_label_used or "전기간비",
        "전년비": yoy_label_used or "전년비",
    })
    return out


def render_summary_table_html(df_combo, unit):
    """01 실적요약 하단 표: 기본 6개 + 추가 3개(전시상품수, 원부매칭상품수, 회원UV) = 9개 지표."""
    from utils import format_delta_html

    # (실제 컬럼명 또는 특수키, 표시명)
    SUMMARY_ITEMS = [
        ("평균 EP 거래액(총결제)", "EP 거래액(총결제)"),
        ("평균 EP 거래액(순결제)", "EP 거래액(순결제)"),
        ("평균 EP UV", "EP UV"),
        ("_회원UV", "회원UV"),
        ("원부매칭율(%)", "원부매칭율(%)"),
        ("최저가율(%)", "최저가율(%)"),
        ("구매전환율(%)", "구매전환율(%)"),
        ("평균 EP 전시 상품수", "전시상품수"),
        ("평균 원부매칭 상품수", "원부매칭상품수"),
    ]

    prev_label = None
    yoy_label = None
    body_rows = []

    for metric_key, display_name in SUMMARY_ITEMS:
        if metric_key == "_회원UV":
            # 회원UV = 전체UV - 비회원UV
            s_total = resample_series(df_combo, "평균 EP UV", unit)
            s_non = resample_series(df_combo, "평균 EP 비회원UV", unit)
            series = s_total - s_non
            fmt_key = "평균 EP UV"  # 포맷용 (정수 표시)
        else:
            series = resample_series(df_combo, metric_key, unit)
            fmt_key = metric_key

        stats = compute_kpi_deltas(series, unit)
        if stats is None:
            body_rows.append(f"<tr><td>{display_name}</td><td>-</td><td>-</td><td>-</td></tr>")
            continue
        prev_label = stats["prev_label"]
        yoy_label = stats["yoy_label"]
        val = format_value(stats["current"], fmt_key)
        prev = format_delta_html(stats["prev_delta"])
        yoy = format_delta_html(stats["yoy_delta"])
        body_rows.append(
            f"<tr><td class='m'>{display_name}</td><td class='v'>{val}</td>"
            f"<td class='d'>{prev}</td><td class='d'>{yoy}</td></tr>"
        )

    html = (
        "<table class='summary-table'>"
        f"<thead><tr><th>지표</th><th>값</th><th>{prev_label or '전기간비'}</th>"
        f"<th>{yoy_label or '전년비'}</th></tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody></table>"
    )
    return html
