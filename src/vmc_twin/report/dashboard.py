from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import plotly.graph_objects as go

from vmc_twin.domain.events import Event
from vmc_twin.optimize.pareto import PolicyBenchmarkResult
from vmc_twin.predict.tool_wear import ToolPrognosticAssessment, WearRiskLevel
from vmc_twin.report.kpis import FleetKPIs
from vmc_twin.report.plots import PlotlyVisualizer
from vmc_twin.rules.engine import ExplanationTrace, RuleSeverity


class UnifiedDashboardGenerator:
    """Constructs a comprehensive, standalone offline HTML report combining all twin sub-engines."""

    @staticmethod
    def create_pareto_scatter(benchmarks: Sequence[PolicyBenchmarkResult]) -> go.Figure:
        """Constructs a 2D scatter chart of makespan vs. weighted tardiness for all benchmarked policies."""
        fig = go.Figure()
        if not benchmarks:
            fig.update_layout(title="No Tournament Benchmark Data Available", template="plotly_dark")
            return fig

        policies = sorted({b.policy_name for b in benchmarks})
        palette = ["#00E676", "#FFD600", "#00B0FF", "#E040FB", "#FF9100", "#FF5252", "#7C4DFF"]

        for idx, pol in enumerate(policies):
            records = [b for b in benchmarks if b.policy_name == pol]
            x_val = [r.makespan_minutes for r in records]
            y_val = [r.total_weighted_tardiness for r in records]
            color = palette[idx % len(palette)]

            fig.add_trace(
                go.Scatter(
                    x=x_val,
                    y=y_val,
                    mode="markers+text",
                    name=pol,
                    text=[pol] * len(records),
                    textposition="top center",
                    marker={"size": 12, "color": color, "line": {"width": 1, "color": "#FFFFFF"}},
                    hovertemplate=(
                        f"<b>{pol}</b><br>"
                        "Makespan: %{x:.1f} min<br>"
                        "Weighted Tardiness: %{y:.1f}<br>"
                        "<extra></extra>"
                    ),
                )
            )

        fig.update_layout(
            title="Multi-Scheduler Multi-Objective Pareto Trade-Off Analysis",
            xaxis={"title": "Makespan (minutes)", "showgrid": True, "gridcolor": "rgba(255,255,255,0.1)"},
            yaxis={"title": "Total Weighted Tardiness", "showgrid": True, "gridcolor": "rgba(255,255,255,0.1)"},
            template="plotly_dark",
            height=450,
            margin={"l": 60, "r": 40, "t": 60, "b": 40},
        )
        return fig

    @staticmethod
    def create_tool_wear_chart(assessments: Sequence[ToolPrognosticAssessment]) -> go.Figure:
        """Constructs a bar chart showing tool wear (VB mm) and conditional failure risk."""
        fig = go.Figure()
        if not assessments:
            fig.update_layout(title="No Tool Wear Assessment Data", template="plotly_dark")
            return fig

        tool_ids = [f"{a.tool_id} ({a.tool_type[:10]})" for a in assessments]
        vb_vals = [a.flank_wear_vb_mm for a in assessments]
        p_fails = [a.p_fail_next_operation * 100.0 for a in assessments]

        fig.add_trace(
            go.Bar(
                name="Flank Wear (VB mm)",
                x=tool_ids,
                y=vb_vals,
                marker_color="#FF9100",
                yaxis="y",
            )
        )
        fig.add_trace(
            go.Scatter(
                name="Failure Risk Next Op (%)",
                x=tool_ids,
                y=p_fails,
                mode="lines+markers",
                marker={"size": 10, "color": "#FF5252"},
                yaxis="y2",
            )
        )

        fig.update_layout(
            title="Tool Flank Wear (VB mm) & Next Operation Failure Risk (%)",
            xaxis={"title": "Tool ID & Type", "tickangle": -30},
            yaxis={"title": "Flank Wear VB (mm)", "range": [0, 0.40]},
            yaxis2={
                "title": "Failure Risk (%)",
                "overlaying": "y",
                "side": "right",
                "range": [0, 100],
            },
            template="plotly_dark",
            legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
            height=450,
            margin={"l": 60, "r": 60, "t": 60, "b": 80},
        )
        return fig

    @classmethod
    def generate_report(
        cls,
        kpis: FleetKPIs,
        events: Sequence[Event],
        diagnostic_trace: ExplanationTrace | None = None,
        benchmarks: Sequence[PolicyBenchmarkResult] | None = None,
        tool_assessments: Sequence[ToolPrognosticAssessment] | None = None,
        output_path: Path | str = "outputs/report.html",
    ) -> Path:
        """Assembles and writes the full-spectrum standalone digital twin HTML report."""
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        gantt_fig = PlotlyVisualizer.create_gantt_chart(events)
        util_fig = PlotlyVisualizer.create_utilization_chart(kpis)
        idle_fig = PlotlyVisualizer.create_idle_pareto_chart(kpis)
        pareto_fig = cls.create_pareto_scatter(benchmarks or [])
        tool_fig = cls.create_tool_wear_chart(tool_assessments or [])

        # Diagnostic Table Rows
        diag_rows_html = ""
        if diagnostic_trace and diagnostic_trace.findings:
            for d in diagnostic_trace.findings:
                if d.severity == RuleSeverity.CRITICAL:
                    badge_style = "background: #D50000; color: white;"
                elif d.severity == RuleSeverity.WARNING:
                    badge_style = "background: #FF9100; color: black;"
                else:
                    badge_style = "background: #00B0FF; color: black;"

                evidence_str = "<br>".join(f"• <strong>{k}</strong>: {v}" for k, v in d.matched_facts.items())
                diag_rows_html += f"""
                <tr>
                    <td><span class="badge" style="{badge_style}">{d.severity.value}</span></td>
                    <td><strong>{d.rule_id}</strong></td>
                    <td><code>{d.target_entity or 'FLEET'}</code></td>
                    <td>{d.root_cause_narrative}</td>
                    <td>{evidence_str}</td>
                    <td style="color: #00E676;">{d.actionable_remediation}</td>
                </tr>
                """
        else:
            diag_rows_html = "<tr><td colspan='6' style='text-align:center; color:#888;'>No diagnostic anomalies detected. System operating nominally.</td></tr>"

        # Tool Wear Rows
        tool_rows_html = ""
        if tool_assessments:
            for t in tool_assessments:
                if t.risk_level == WearRiskLevel.CRITICAL:
                    risk_badge = "background: #D50000; color: white;"
                elif t.risk_level == WearRiskLevel.MAINTENANCE_REQUIRED:
                    risk_badge = "background: #FF9100; color: black;"
                elif t.risk_level == WearRiskLevel.MONITOR:
                    risk_badge = "background: #FFD600; color: black;"
                else:
                    risk_badge = "background: #00E676; color: black;"

                tool_rows_html += f"""
                <tr>
                    <td><strong>{t.tool_id}</strong></td>
                    <td>{t.tool_type}</td>
                    <td>{t.accumulated_cut_minutes:.1f} m</td>
                    <td>{t.flank_wear_vb_mm:.3f} mm</td>
                    <td>{t.expected_rul_minutes:.1f} m</td>
                    <td>{t.p_fail_next_operation * 100:.1f}%</td>
                    <td><span class="badge" style="{risk_badge}">{t.risk_level.value}</span></td>
                    <td>{t.recommendation}</td>
                </tr>
                """
        else:
            tool_rows_html = "<tr><td colspan='8' style='text-align:center; color:#888;'>No tool instances currently active in shop inventory.</td></tr>"

        html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CNC VMC Digital Twin Comprehensive Report - {kpis.scenario_name}</title>
    <script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
    <style>
        :root {{
            --bg-primary: #121212;
            --bg-card: #1E1E1E;
            --bg-hover: #2A2A2A;
            --text-primary: #ECEFF1;
            --text-secondary: #90A4AE;
            --accent-green: #00E676;
            --accent-blue: #00B0FF;
            --accent-amber: #FFD600;
            --accent-orange: #FF9100;
            --accent-red: #D50000;
            --border-color: #333333;
        }}
        body {{
            background-color: var(--bg-primary);
            color: var(--text-primary);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            margin: 0;
            padding: 24px;
            line-height: 1.5;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 2px solid var(--border-color);
            padding-bottom: 16px;
            margin-bottom: 24px;
        }}
        .header h1 {{
            margin: 0;
            font-size: 28px;
            color: #FFFFFF;
            letter-spacing: -0.5px;
        }}
        .header-meta {{
            color: var(--text-secondary);
            font-size: 14px;
        }}
        .kpi-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 28px;
        }}
        .kpi-card {{
            background: var(--bg-card);
            border-radius: 8px;
            padding: 16px 20px;
            border-left: 4px solid var(--accent-green);
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        }}
        .kpi-val {{
            font-size: 26px;
            font-weight: 700;
            color: #FFFFFF;
            margin-top: 4px;
        }}
        .kpi-lbl {{
            font-size: 12px;
            font-weight: 600;
            text-transform: uppercase;
            color: var(--text-secondary);
            letter-spacing: 0.5px;
        }}
        .section-title {{
            font-size: 20px;
            font-weight: 700;
            margin: 32px 0 16px 0;
            color: #FFFFFF;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .chart-box {{
            background: var(--bg-card);
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 24px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        }}
        .grid-2 {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
        }}
        @media (max-width: 900px) {{
            .grid-2 {{ grid-template-columns: 1fr; }}
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            background: var(--bg-card);
            border-radius: 8px;
            overflow: hidden;
            margin-bottom: 24px;
        }}
        th, td {{
            padding: 12px 16px;
            text-align: left;
            border-bottom: 1px solid var(--border-color);
            font-size: 14px;
        }}
        th {{
            background: #252525;
            color: var(--text-secondary);
            font-weight: 600;
            text-transform: uppercase;
            font-size: 12px;
        }}
        tr:hover {{
            background: var(--bg-hover);
        }}
        .badge {{
            display: inline-block;
            padding: 3px 8px;
            border-radius: 4px;
            font-weight: 700;
            font-size: 11px;
            text-transform: uppercase;
        }}
        .footer {{
            text-align: center;
            margin-top: 48px;
            padding-top: 24px;
            border-top: 1px solid var(--border-color);
            color: var(--text-secondary);
            font-size: 13px;
        }}
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <div>
            <h1>CNC VMC Digital Twin - Production Report</h1>
            <div class="header-meta">
                Scenario: <strong>{kpis.scenario_name}</strong> | Simulated Horizon: <strong>{kpis.horizon_hours:.1f} hours ({kpis.horizon_hours/24.0:.1f} days)</strong> | Fleet: <strong>{kpis.fleet_size} CNC VMCs</strong>
            </div>
        </div>
        <div>
            <span class="badge" style="background: var(--accent-green); color: black;">100% OFFLINE TWIN</span>
        </div>
    </div>

    <!-- Executive KPI Grid -->
    <div class="kpi-grid">
        <div class="kpi-card" style="border-left-color: var(--accent-green);">
            <div class="kpi-lbl">Spindle Utilization</div>
            <div class="kpi-val">{kpis.mean_spindle_utilization_pct:.1f}%</div>
        </div>
        <div class="kpi-card" style="border-left-color: var(--accent-amber);">
            <div class="kpi-lbl">Changeover Setup %</div>
            <div class="kpi-val">{kpis.mean_setup_pct:.1f}%</div>
        </div>
        <div class="kpi-card" style="border-left-color: var(--accent-orange);">
            <div class="kpi-lbl">Lost Idle %</div>
            <div class="kpi-val">{kpis.mean_idle_pct:.1f}%</div>
        </div>
        <div class="kpi-card" style="border-left-color: var(--accent-blue);">
            <div class="kpi-lbl">On-Time Delivery (OTD)</div>
            <div class="kpi-val">{kpis.on_time_delivery_pct:.1f}%</div>
        </div>
        <div class="kpi-card" style="border-left-color: #E040FB;">
            <div class="kpi-lbl">Completed / Total Jobs</div>
            <div class="kpi-val">{kpis.completed_jobs} / {kpis.total_jobs}</div>
        </div>
        <div class="kpi-card" style="border-left-color: #00E5FF;">
            <div class="kpi-lbl">Mean Makespan</div>
            <div class="kpi-val">{kpis.makespan_minutes:.1f} m</div>
        </div>
    </div>

    <!-- Section 1: Interactive Spindle Gantt Timeline -->
    <div class="section-title">1. Interactive Spindle Activity Timeline (Discrete-Event Gantt)</div>
    <div class="chart-box">
        {gantt_fig.to_html(full_html=False, include_plotlyjs=False)}
    </div>

    <!-- Section 2: Machine Utilization & Cause Breakdown -->
    <div class="section-title">2. Fleet Utilization Breakdown & Bottleneck Cause Pareto</div>
    <div class="grid-2">
        <div class="chart-box">
            {util_fig.to_html(full_html=False, include_plotlyjs=False)}
        </div>
        <div class="chart-box">
            {idle_fig.to_html(full_html=False, include_plotlyjs=False)}
        </div>
    </div>

    <!-- Section 3: Explainable Expert System Diagnostics -->
    <div class="section-title">3. Explainable Expert System Diagnostics & Root Causes</div>
    <table>
        <thead>
            <tr>
                <th style="width: 100px;">Severity</th>
                <th style="width: 160px;">Rule ID</th>
                <th style="width: 120px;">Target</th>
                <th>Diagnostic Finding</th>
                <th>Underlying Evidence</th>
                <th>Prescribed Engineering Action</th>
            </tr>
        </thead>
        <tbody>
            {diag_rows_html}
        </tbody>
    </table>

    <!-- Section 4: Multi-Objective Schedulers & Pareto Frontier -->
    <div class="section-title">4. Schedulers & Mathematical Optimization Pareto Trade-Off</div>
    <div class="chart-box">
        {pareto_fig.to_html(full_html=False, include_plotlyjs=False)}
    </div>

    <!-- Section 5: Cutting Tool Wear & Prognostics -->
    <div class="section-title">5. Cutting Tool Wear Prognostics & RUL Recommender</div>
    <div class="chart-box">
        {tool_fig.to_html(full_html=False, include_plotlyjs=False)}
    </div>
    <table>
        <thead>
            <tr>
                <th>Tool ID</th>
                <th>Tool Type</th>
                <th>Acc Cut Time</th>
                <th>Flank Wear (VB)</th>
                <th>Expected RUL</th>
                <th>P(Fail Next Op)</th>
                <th>Risk State</th>
                <th>Proactive Recommendation</th>
            </tr>
        </thead>
        <tbody>
            {tool_rows_html}
        </tbody>
    </table>

    <div class="footer">
        Generated by <strong>CNC VMC Shop Floor Digital Twin</strong> • 100% Offline Simulation, Expert Diagnosis & Optimization
    </div>
</div>
</body>
</html>"""

        with open(out, "w", encoding="utf-8") as f:
            f.write(html_doc)
        return out
