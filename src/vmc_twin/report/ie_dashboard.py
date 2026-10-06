from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import plotly.graph_objects as go

from vmc_twin.optimize.ai_scheduler import AIScheduledTask, AIScheduleResult


class IEDashboardGenerator:
    """
    Industrial Engineering Analytics & Visualizer for AI-Driven Production Schedules.
    
    Renders standalone interactive Plotly dashboard featuring:
    1. Production Schedule Gantt Timeline with Operation Telemetry
    2. Factory Continuous Electrical Power Demand Profile (kW) with Peak Shaving
    3. Order Deadlines vs Completion Times (Lateness & OTD Analysis)
    4. Energy (kWh), Carbon (kg CO2), and Production Cost Breakdown
    """

    @staticmethod
    def create_gantt_chart(tasks: Sequence[AIScheduledTask]) -> go.Figure:
        """Constructs interactive production schedule Gantt chart."""
        fig = go.Figure()
        if not tasks:
            fig.update_layout(title="No Scheduled Tasks Available", template="plotly_dark")
            return fig

        # Color palette by fixture/part
        color_map = {
            "VISE_6INCH_DUAL": "#00E676",
            "TOMBSTONE_4SIDED": "#00B0FF",
            "CHUCK_4JAW_SCROLL": "#FFD600",
            "VACUUM_FIXTURE_PLATE": "#E040FB",
        }

        # Group tasks by fixture
        fixtures = sorted({t.fixture_id for t in tasks})
        for fix in fixtures:
            fix_tasks = [t for t in tasks if t.fixture_id == fix]
            x_durations = [t.duration_minutes for t in fix_tasks]
            x_starts = [t.t_start + t.setup_minutes for t in fix_tasks]
            y_machines = [t.machine_id for t in fix_tasks]
            hover_texts = [
                f"<b>Job: {t.job_id} ({t.op_id})</b><br>"
                f"Machine: {t.machine_id}<br>"
                f"Fixture: {t.fixture_id}<br>"
                f"Start: {t.t_start:.1f}m | End: {t.t_end:.1f}m<br>"
                f"Cut Time: {t.duration_minutes:.1f}m (Setup: {t.setup_minutes:.1f}m)<br>"
                f"Power Draw: {t.power_kw:.2f} kW | Energy: {t.energy_kwh:.3f} kWh<br>"
                f"Due Date: {t.due_date:.1f}m (Lateness: {t.lateness_minutes:.1f}m)"
                for t in fix_tasks
            ]

            fig.add_trace(
                go.Bar(
                    name=fix,
                    x=x_durations,
                    y=y_machines,
                    base=x_starts,
                    orientation="h",
                    marker={"color": color_map.get(fix, "#00E676"), "line": {"width": 0.5, "color": "#121212"}},
                    hoverinfo="text",
                    hovertext=hover_texts,
                )
            )

        fig.update_layout(
            title="AI Optimal Production Schedule (Spindle Operations & Fixture Grouping)",
            barmode="stack",
            xaxis={"title": "Time (minutes)", "showgrid": True, "gridcolor": "rgba(255,255,255,0.1)"},
            yaxis={"title": "CNC VMC Machine", "autorange": "reversed"},
            template="plotly_dark",
            legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
            height=480,
            margin={"l": 80, "r": 40, "t": 60, "b": 40},
        )
        return fig

    @staticmethod
    def create_power_demand_chart(result: AIScheduleResult) -> go.Figure:
        """Constructs factory electrical power load profile P(t) with peak demand limit."""
        fig = go.Figure()
        if not result.power_profile:
            fig.update_layout(title="No Electrical Load Profile Available", template="plotly_dark")
            return fig

        times = [p[0] for p in result.power_profile]
        powers = [p[1] for p in result.power_profile]

        # Electrical Load Curve
        fig.add_trace(
            go.Scatter(
                x=times,
                y=powers,
                mode="lines",
                name="Fleet Electrical Load (kW)",
                line={"color": "#00B0FF", "width": 2},
                fill="tozeroy",
                fillcolor="rgba(0, 176, 255, 0.15)",
                hovertemplate="Time: %{x:.1f}m<br>Fleet Active Power: %{y:.2f} kW<extra></extra>",
            )
        )

        # Peak Power Threshold Line
        fig.add_trace(
            go.Scatter(
                x=[min(times), max(times)],
                y=[result.peak_power_limit_kw, result.peak_power_limit_kw],
                mode="lines",
                name=f"Peak Demand Limit ({result.peak_power_limit_kw:.1f} kW)",
                line={"color": "#D50000", "width": 2, "dash": "dash"},
            )
        )

        fig.update_layout(
            title="Factory Fleet Electrical Load Profile & Peak Power Demand Shaving",
            xaxis={"title": "Simulation Horizon (minutes)", "showgrid": True, "gridcolor": "rgba(255,255,255,0.1)"},
            yaxis={"title": "Total Fleet Active Power (kW)", "showgrid": True, "gridcolor": "rgba(255,255,255,0.1)"},
            template="plotly_dark",
            legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
            height=420,
            margin={"l": 60, "r": 40, "t": 60, "b": 40},
        )
        return fig

    @staticmethod
    def create_deadline_lateness_chart(tasks: Sequence[AIScheduledTask]) -> go.Figure:
        """Constructs scatter chart comparing Completion Time vs Customer Due Date."""
        fig = go.Figure()
        if not tasks:
            return fig

        on_time_tasks = [t for t in tasks if t.lateness_minutes <= 0.0]
        late_tasks = [t for t in tasks if t.lateness_minutes > 0.0]

        if on_time_tasks:
            fig.add_trace(
                go.Scatter(
                    x=[t.t_end for t in on_time_tasks],
                    y=[t.due_date for t in on_time_tasks],
                    mode="markers",
                    name="On-Time Delivery",
                    marker={"size": 9, "color": "#00E676", "opacity": 0.85},
                    hovertemplate="<b>Job %{text}</b><br>Completed: %{x:.1f}m<br>Due Date: %{y:.1f}m<br>Status: ON-TIME<extra></extra>",
                    text=[t.job_id for t in on_time_tasks],
                )
            )

        if late_tasks:
            fig.add_trace(
                go.Scatter(
                    x=[t.t_end for t in late_tasks],
                    y=[t.due_date for t in late_tasks],
                    mode="markers",
                    name="Tardy / Late",
                    marker={"size": 11, "color": "#D50000", "symbol": "diamond"},
                    hovertemplate="<b>Job %{text}</b><br>Completed: %{x:.1f}m<br>Due Date: %{y:.1f}m<br>Lateness: %{customdata:.1f}m<extra></extra>",
                    text=[t.job_id for t in late_tasks],
                    customdata=[t.lateness_minutes for t in late_tasks],
                )
            )

        # 45-degree on-time boundary line (Completion == Due Date)
        max_coord = max(max(t.t_end for t in tasks), max(t.due_date for t in tasks))
        fig.add_trace(
            go.Scatter(
                x=[0, max_coord],
                y=[0, max_coord],
                mode="lines",
                name="On-Time Boundary (C = d)",
                line={"color": "rgba(255,255,255,0.4)", "width": 1, "dash": "dot"},
            )
        )

        fig.update_layout(
            title="Order Fulfillment & Delivery Performance (Completion vs. Customer Deadline)",
            xaxis={"title": "Order Completion Time C_j (min)", "showgrid": True, "gridcolor": "rgba(255,255,255,0.1)"},
            yaxis={"title": "Promised Due Date d_j (min)", "showgrid": True, "gridcolor": "rgba(255,255,255,0.1)"},
            template="plotly_dark",
            legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
            height=420,
            margin={"l": 60, "r": 40, "t": 60, "b": 40},
        )
        return fig

    @classmethod
    def generate_dashboard(
        cls,
        result: AIScheduleResult,
        electricity_rate_usd_per_kwh: float = 0.16,
        carbon_intensity_kg_co2_per_kwh: float = 0.42,
        output_path: Path | str = "outputs/ie_dashboard.html",
    ) -> Path:
        """Assembles and writes the complete Industrial Engineering HTML dashboard."""
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        gantt_fig = cls.create_gantt_chart(result.scheduled_tasks)
        power_fig = cls.create_power_demand_chart(result)
        deadline_fig = cls.create_deadline_lateness_chart(result.scheduled_tasks)

        # Economic & Sustainability Calculations
        total_energy_cost_usd = result.total_energy_kwh * electricity_rate_usd_per_kwh
        carbon_footprint_kg = result.total_energy_kwh * carbon_intensity_kg_co2_per_kwh

        html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Industrial Engineering AI Scheduling & Energy Dashboard</title>
    <script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
    <style>
        :root {{
            --bg-primary: #0F172A;
            --bg-card: #1E293B;
            --bg-hover: #334155;
            --text-primary: #F8FAFC;
            --text-secondary: #94A3B8;
            --accent-green: #10B981;
            --accent-blue: #38BDF8;
            --accent-amber: #F59E0B;
            --accent-red: #EF4444;
            --border-color: #334155;
        }}
        body {{
            background-color: var(--bg-primary);
            color: var(--text-primary);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            margin: 0;
            padding: 24px;
            line-height: 1.5;
        }}
        .container {{
            max-width: 1440px;
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
            margin-top: 4px;
        }}
        .kpi-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
            gap: 16px;
            margin-bottom: 28px;
        }}
        .kpi-card {{
            background: var(--bg-card);
            border-radius: 8px;
            padding: 18px 20px;
            border-left: 4px solid var(--accent-green);
            box-shadow: 0 4px 12px rgba(0,0,0,0.25);
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
            font-size: 19px;
            font-weight: 700;
            margin: 28px 0 16px 0;
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
            box-shadow: 0 4px 12px rgba(0,0,0,0.25);
        }}
        .grid-2 {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
        }}
        @media (max-width: 900px) {{
            .grid-2 {{ grid-template-columns: 1fr; }}
        }}
        .badge {{
            display: inline-block;
            padding: 4px 10px;
            border-radius: 6px;
            font-weight: 700;
            font-size: 12px;
            text-transform: uppercase;
        }}
        .footer {{
            text-align: center;
            margin-top: 48px;
            padding-top: 20px;
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
            <h1>Industrial Engineering AI Scheduler & Energy Twin</h1>
            <div class="header-meta">
                Scenario: <strong>{result.scenario_name}</strong> | Total Production Orders: <strong>{result.total_jobs} Jobs</strong> | Calibrated with <strong>CNC Power Telemetry Dataset</strong>
            </div>
        </div>
        <div>
            <span class="badge" style="background: var(--accent-green); color: black;">AI OPTIMIZED</span>
        </div>
    </div>

    <!-- Executive KPI Grid -->
    <div class="kpi-grid">
        <div class="kpi-card" style="border-left-color: var(--accent-green);">
            <div class="kpi-lbl">On-Time Delivery (OTD)</div>
            <div class="kpi-val">{result.on_time_delivery_pct:.1f}%</div>
        </div>
        <div class="kpi-card" style="border-left-color: var(--accent-blue);">
            <div class="kpi-lbl">Total Energy Consumption</div>
            <div class="kpi-val">{result.total_energy_kwh:.1f} kWh</div>
        </div>
        <div class="kpi-card" style="border-left-color: var(--accent-amber);">
            <div class="kpi-lbl">Peak Electrical Load</div>
            <div class="kpi-val">{result.peak_power_kw:.1f} kW <span style="font-size:12px; color:var(--text-secondary);">/ {result.peak_power_limit_kw:.0f}kW cap</span></div>
        </div>
        <div class="kpi-card" style="border-left-color: #38BDF8;">
            <div class="kpi-lbl">Electricity Cost ($0.16/kWh)</div>
            <div class="kpi-val">${total_energy_cost_usd:.2f}</div>
        </div>
        <div class="kpi-card" style="border-left-color: #A855F7;">
            <div class="kpi-lbl">Carbon Emissions</div>
            <div class="kpi-val">{carbon_footprint_kg:.1f} kg CO2</div>
        </div>
        <div class="kpi-card" style="border-left-color: #EC4899;">
            <div class="kpi-lbl">Total Makespan</div>
            <div class="kpi-val">{result.makespan_minutes:.1f} m <span style="font-size:12px; color:var(--text-secondary);">({result.makespan_minutes/60.0:.1f}h)</span></div>
        </div>
    </div>

    <!-- Section 1: Gantt Schedule -->
    <div class="section-title">1. Production Scheduling Timeline (Gantt Chart & Fixture Grouping)</div>
    <div class="chart-box">
        {gantt_fig.to_html(full_html=False, include_plotlyjs=False)}
    </div>

    <!-- Section 2: Power Demand & Lateness Scatter -->
    <div class="section-title">2. Factory Electrical Power Demand Profile & Order Deadline Compliance</div>
    <div class="grid-2">
        <div class="chart-box">
            {power_fig.to_html(full_html=False, include_plotlyjs=False)}
        </div>
        <div class="chart-box">
            {deadline_fig.to_html(full_html=False, include_plotlyjs=False)}
        </div>
    </div>

    <div class="footer">
        <strong>CNC VMC Industrial Engineering Digital Twin</strong> • Multi-Objective Energy-Aware AI Scheduling Engine
    </div>
</div>
</body>
</html>"""

        with open(out, "w", encoding="utf-8") as f:
            f.write(html_doc)
        return out
