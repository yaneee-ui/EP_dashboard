"""참고 화면과 유사한 라이트 톤의 커스텀 CSS."""

CUSTOM_CSS = """
<style>
.kpi-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
    gap: 14px;
    margin-bottom: 8px;
}
.kpi-card {
    background: #ffffff;
    border: 1px solid #eaecef;
    border-radius: 10px;
    padding: 16px 18px;
    box-shadow: 0 1px 2px rgba(0,0,0,0.04);
}
.kpi-label {
    font-size: 0.82rem;
    color: #6b7280;
    margin-bottom: 6px;
}
.kpi-value {
    font-size: 1.55rem;
    font-weight: 700;
    color: #111827;
    margin-bottom: 10px;
}
.kpi-deltas {
    display: flex;
    flex-direction: column;
    gap: 3px;
}
.delta-row {
    font-size: 0.75rem;
    color: #6b7280;
    display: flex;
    justify-content: space-between;
    gap: 6px;
}
.delta-name {
    white-space: nowrap;
}
.delta.up { color: #16a34a; font-weight: 600; }
.delta.down { color: #dc2626; font-weight: 600; }
.delta.neutral { color: #9ca3af; font-weight: 600; }

.dash-header-title {
    font-size: 1.5rem;
    font-weight: 700;
    color: #111827;
    margin-bottom: 2px;
}
.dash-header-sub {
    font-size: 0.85rem;
    color: #6b7280;
    margin-bottom: 18px;
}
.chart-caption {
    font-size: 0.78rem;
    color: #9ca3af;
    margin-top: 4px;
}

.summary-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.9rem;
    background: #ffffff;
    border: 1px solid #eaecef;
    border-radius: 8px;
    overflow: hidden;
}
.summary-table thead th {
    background: #f7f8fa;
    color: #6b7280;
    font-weight: 600;
    text-align: left;
    padding: 10px 14px;
    border-bottom: 1px solid #eaecef;
    font-size: 0.82rem;
}
.summary-table tbody td {
    padding: 10px 14px;
    border-bottom: 1px solid #f1f2f4;
    color: #111827;
}
.summary-table tbody tr:last-child td { border-bottom: none; }
.summary-table td.m { font-weight: 500; }
.summary-table td.v { font-weight: 600; }
.summary-table td.d { text-align: left; }

/* KPI 카드 높이 통일 */
div[data-testid="stHorizontalBlock"] > div[data-testid="stVerticalBlockBorderWrapper"] {
    height: 100%;
}
div[data-testid="stHorizontalBlock"] > div[data-testid="stVerticalBlockBorderWrapper"] > div {
    height: 100%;
}
</style>
"""
