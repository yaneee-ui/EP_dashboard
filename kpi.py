"""KPI 요약 카드 렌더링 (커스텀 HTML/CSS 카드, 3종 증감률 동시 표시)."""
import streamlit as st

from utils import HEADLINE_METRICS, resample_series, compute_kpi_deltas, format_value, format_delta_html


def _delta_row(name, delta_html):
    return f"<div class='delta-row'><span class='delta-name'>{name}</span>{delta_html}</div>"


def render_kpi_cards(df_combo, unit):
    cards = []
    for metric in HEADLINE_METRICS:
        series = resample_series(df_combo, metric, unit)
        stats = compute_kpi_deltas(series, unit)

        if stats is None:
            cards.append(
                f"<div class='kpi-card'><div class='kpi-label'>{metric}</div>"
                f"<div class='kpi-value'>-</div></div>"
            )
            continue

        value_str = format_value(stats["current"], metric)
        deltas = (
            _delta_row(stats["prev_label"], format_delta_html(stats["prev_delta"]))
            + _delta_row(stats["avg_label"], format_delta_html(stats["avg_delta"]))
            + _delta_row(stats["yoy_label"], format_delta_html(stats["yoy_delta"]))
        )
        card = (
            f"<div class='kpi-card'>"
            f"<div class='kpi-label'>{metric}</div>"
            f"<div class='kpi-value'>{value_str}</div>"
            f"<div class='kpi-deltas'>{deltas}</div>"
            f"</div>"
        )
        cards.append(card)

    grid_html = "<div class='kpi-grid'>" + "".join(cards) + "</div>"
    st.markdown(grid_html, unsafe_allow_html=True)
