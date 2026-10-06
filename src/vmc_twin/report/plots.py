from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from vmc_twin.domain.events import Event
from vmc_twin.domain.states import SpindleState
from vmc_twin.report.kpis import FleetKPIs

# Color mapping for Spindle states (Dark modern theme)
STATE_COLORS: dict[SpindleState, str] = {
    SpindleState.CUTTING: "#00E676",  # Bright Green
    SpindleState.SETUP: "#FFD600",  # Amber Yellow
    SpindleState.TOOL_CHANGE: "#00B0FF",  # Vivid Sky Blue
    SpindleState.IDLE_STARVED: "#9E9E9E",  # Neutral Gray
    SpindleState.IDLE_WAIT_SETUP: "#FF9100",  # Deep Orange
    SpindleState.IDLE_WAIT_TOOL: "#FF5252",  # Coral Red
    SpindleState.IDLE_WAIT_OPERATOR: "#E040FB",  # Purple
    SpindleState.IDLE_WAIT_FIXTURE: "#7C4DFF",  # Deep Indigo
    SpindleState.BREAKDOWN: "#D50000",  # Crimson Red
    SpindleState.PLANNED_MAINT: "#651FFF",  # Electric Violet
    SpindleState.OFF_SHIFT: "#212121",  # Dark Charcoal
}


class PlotlyVisualizer:
    """Generates standalone, interactive Plotly HTML visualizations for digital twin runs."""

    @staticmethod
    def create_gantt_chart(events: Sequence[Event], max_events: int = 5000) -> go.Figure:
        """Constructs an interactive Spindle timeline Gantt chart."""
        fig = go.Figure()

        # Sample if event list is massive to maintain high browser frame rate
        sampled_events = events[:max_events] if len(events) > max_events else events

        # Group by state for legend categorization
        state_groups: dict[SpindleState, list[Event]] = {}
        for e in sampled_events:
            state_groups.setdefault(e.state, []).append(e)

        for state, evts in state_groups.items():
            color = STATE_COLORS.get(state, "#9E9E9E")
            x_durations = [e.duration() for e in evts]
            x_starts = [e.t_start for e in evts]
            y_machines = [e.machine_id for e in evts]
            hover_texts = [
                f"Machine: {e.machine_id}<br>"
                f"State: {e.state.value}<br>"
                f"Job: {e.job_id or 'None'}<br>"
                f"Op: {e.op_id or 'None'}<br>"
                f"Start: {e.t_start:.1f}m | End: {e.t_end:.1f}m<br>"
                f"Duration: {e.duration():.1f}m<br>"
                f"Cause: {e.cause_code.value}"
                for e in evts
            ]

            fig.add_trace(
                go.Bar(
                    name=state.value,
                    x=x_durations,
                    y=y_machines,
                    base=x_starts,
                    orientation="h",
                    marker={"color": color, "line": {"color": "rgba(0,0,0,0.3)", "width": 0.5}},
                    textposition="none",
                    hoverinfo="text",
                    hovertext=hover_texts,
                )
            )

        fig.update_layout(
            title="CNC VMC Fleet Spindle Activity Timeline (Gantt Chart)",
            barmode="stack",
            xaxis={"title": "Time (minutes)", "showgrid": True, "gridcolor": "rgba(255,255,255,0.1)"},
            yaxis={"title": "Machine", "autorange": "reversed"},
            template="plotly_dark",
            legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
            height=500,
            margin={"l": 80, "r": 40, "t": 80, "b": 40},
        )
        return fig

    @staticmethod
    def create_utilization_chart(kpis: FleetKPIs) -> go.Figure:
        """Constructs a stacked bar chart of cutting, setup, idle, and breakdown time."""
        machines = list(kpis.machine_kpis.keys())
        cutting = [kpis.machine_kpis[m].utilization_pct for m in machines]
        setup = [kpis.machine_kpis[m].setup_pct for m in machines]
        idle = [kpis.machine_kpis[m].idle_pct for m in machines]
        down = [kpis.machine_kpis[m].breakdown_pct for m in machines]

        fig = go.Figure()
        fig.add_trace(
            go.Bar(name="Cutting (Spindle)", x=machines, y=cutting, marker_color="#00E676")
        )
        fig.add_trace(go.Bar(name="Setup", x=machines, y=setup, marker_color="#FFD600"))
        fig.add_trace(go.Bar(name="Idle (Starve/Wait)", x=machines, y=idle, marker_color="#9E9E9E"))
        fig.add_trace(go.Bar(name="Breakdown", x=machines, y=down, marker_color="#D50000"))

        fig.update_layout(
            title=f"Machine Utilization & State Breakdown ({kpis.scenario_name})",
            barmode="stack",
            yaxis={"title": "Percentage of Planned Time (%)", "range": [0, 100]},
            xaxis={"title": "Machine ID"},
            template="plotly_dark",
            legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
            height=450,
        )
        return fig

    @staticmethod
    def create_idle_pareto_chart(kpis: FleetKPIs) -> go.Figure:
        """Constructs an idle cause Pareto chart."""
        causes = sorted(kpis.idle_time_by_cause.items(), key=lambda x: x[1], reverse=True)
        names = [c[0] for c in causes]
        minutes = [c[1] for c in causes]
        total = sum(minutes) if sum(minutes) > 0 else 1.0
        cum_pct = [sum(minutes[: i + 1]) / total * 100.0 for i in range(len(minutes))]

        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(
            go.Bar(name="Idle Minutes", x=names, y=minutes, marker_color="#FF9100"),
            secondary_y=False,
        )
        fig.add_trace(
            go.Scatter(
                name="Cumulative %",
                x=names,
                y=cum_pct,
                mode="lines+markers",
                marker_color="#00E676",
            ),
            secondary_y=True,
        )

        fig.update_layout(
            title="Fleet Idle-Time Cause Pareto Analysis",
            template="plotly_dark",
            height=450,
        )
        fig.update_yaxes(title_text="Lost Spindle Minutes", secondary_y=False)
        fig.update_yaxes(title_text="Cumulative %", range=[0, 105], secondary_y=True)
        return fig

    @classmethod
    def export_dashboard_html(
        cls,
        kpis: FleetKPIs,
        events: Sequence[Event],
        output_path: Path | str = "outputs/gantt.html",
    ) -> Path:
        """Builds and exports a single combined static HTML interactive dashboard."""
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)

        gantt_fig = cls.create_gantt_chart(events)
        util_fig = cls.create_utilization_chart(kpis)
        pareto_fig = cls.create_idle_pareto_chart(kpis)

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>CNC VMC Digital Twin: {kpis.scenario_name}</title>
    <script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
    <style>
        body {{
            background-color: #121212;
            color: #E0E0E0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            margin: 0;
            padding: 24px;
        }}
        .header {{
            border-bottom: 2px solid #333;
            padding-bottom: 16px;
            margin-bottom: 24px;
        }}
        .kpi-cards {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }}
        .kpi-card {{
            background: #1E1E1E;
            padding: 16px;
            border-radius: 8px;
            border-left: 4px solid #00E676;
        }}
        .kpi-val {{
            font-size: 24px;
            font-weight: bold;
            color: #FFF;
        }}
        .kpi-lbl {{
            font-size: 12px;
            color: #AAA;
            text-transform: uppercase;
        }}
        .chart-box {{
            background: #1E1E1E;
            padding: 16px;
            border-radius: 8px;
            margin-bottom: 24px;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>CNC VMC Digital Twin - Scenario Report</h1>
        <p>Scenario: <strong>{kpis.scenario_name}</strong> | Simulated Horizon: <strong>{kpis.horizon_hours} hrs</strong> | Fleet: <strong>{kpis.fleet_size} VMCs</strong></p>
    </div>

    <div class="kpi-cards">
        <div class="kpi-card">
            <div class="kpi-lbl">Fleet Utilization</div>
            <div class="kpi-val">{kpis.mean_spindle_utilization_pct:.1f}%</div>
        </div>
        <div class="kpi-card" style="border-left-color: #FFD600;">
            <div class="kpi-lbl">Mean Setup %</div>
            <div class="kpi-val">{kpis.mean_setup_pct:.1f}%</div>
        </div>
        <div class="kpi-card" style="border-left-color: #9E9E9E;">
            <div class="kpi-lbl">Mean Idle %</div>
            <div class="kpi-val">{kpis.mean_idle_pct:.1f}%</div>
        </div>
        <div class="kpi-card" style="border-left-color: #00B0FF;">
            <div class="kpi-lbl">On-Time Delivery</div>
            <div class="kpi-val">{kpis.on_time_delivery_pct:.1f}%</div>
        </div>
        <div class="kpi-card" style="border-left-color: #E040FB;">
            <div class="kpi-lbl">Jobs Done / Total</div>
            <div class="kpi-val">{kpis.completed_jobs} / {kpis.total_jobs}</div>
        </div>
    </div>

    <div class="chart-box">
        {gantt_fig.to_html(full_html=False, include_plotlyjs=False)}
    </div>

    <div class="chart-box">
        {util_fig.to_html(full_html=False, include_plotlyjs=False)}
    </div>

    <div class="chart-box">
        {pareto_fig.to_html(full_html=False, include_plotlyjs=False)}
    </div>
</body>
</html>"""

        with open(p, "w", encoding="utf-8") as f:
            f.write(html_content)
        return p
