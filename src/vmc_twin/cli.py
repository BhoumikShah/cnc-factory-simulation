from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from vmc_twin.data.store import EventStore
from vmc_twin.report.kpis import KPICalculator
from vmc_twin.report.plots import PlotlyVisualizer
from vmc_twin.sim.engine import SimulationEngine

app = typer.Typer(
    name="vmc",
    help="CNC VMC Shop Floor Digital Twin: Simulation, Diagnostics, Optimization & Tool Life",
    add_completion=False,
)
console = Console()


@app.command()
def info() -> None:
    """Displays system architecture, version, and environment status."""
    console.print(
        Panel.fit(
            "[bold cyan]CNC VMC Shop Floor Digital Twin[/bold cyan]\n"
            "[green]Version: 0.1.0[/green]\n"
            "[yellow]Architecture: Hexagonal (Ports & Adapters)[/yellow]\n"
            "[blue]Python: 3.12 (Strict Typing)[/blue]\n"
            "[magenta]Status: 100% Offline / Open-Source[/magenta]",
            title="System Info",
            border_style="cyan",
        )
    )


@app.command()
def run(
    scenario_path: str = typer.Argument(
        "configs/scenarios/baseline.yaml", help="Path to scenario YAML"
    ),
    db_path: str | None = typer.Option(
        None, "--db", help="SQLite database path for event log persistence"
    ),
    html_out: str = typer.Option(
        "outputs/gantt.html", "--html", help="Path for interactive HTML dashboard"
    ),
) -> None:
    """Executes a simulation scenario across the entire VMC fleet."""
    p = Path(scenario_path)
    if not p.exists():
        console.print(f"[bold red]Error: Scenario file not found at {p}[/bold red]")
        raise typer.Exit(code=1)

    console.print(f"[bold green]Loading scenario from {p}...[/bold green]")
    store = EventStore(db_path) if db_path else None
    engine = SimulationEngine.from_scenario_file(p, event_store=store)

    console.print(
        f"[bold blue]Starting simulation: {engine.scenario.scenario_name} "
        f"({engine.scenario.duration_minutes:.1f} minutes, {len(engine.machine_specs)} machines, "
        f"{len(engine.jobs)} jobs)...[/bold blue]"
    )

    result = engine.run()
    kpis = KPICalculator.calculate(
        scenario_name=result.scenario_name,
        horizon_minutes=result.duration_minutes,
        events=result.events,
        jobs=engine.jobs,
    )

    table = Table(
        title=f"Fleet KPIs: {kpis.scenario_name}", show_header=True, header_style="bold magenta"
    )
    table.add_column("Metric", style="dim")
    table.add_column("Value", justify="right")

    table.add_row("Simulated Horizon", f"{kpis.horizon_hours:.1f} hrs")
    table.add_row("Total Events Emitted", str(result.total_events))
    table.add_row("Jobs Completed / Total", f"{kpis.completed_jobs} / {kpis.total_jobs}")
    table.add_row("Fleet Mean Spindle Utilization", f"{kpis.mean_spindle_utilization_pct:.1f}%")
    table.add_row("Fleet Mean Setup Time %", f"{kpis.mean_setup_pct:.1f}%")
    table.add_row("Fleet Mean Idle Time %", f"{kpis.mean_idle_pct:.1f}%")
    table.add_row("Fleet Mean Breakdown %", f"{kpis.mean_breakdown_pct:.1f}%")
    table.add_row("Fleet Mean OEE", f"{kpis.mean_oee_pct:.1f}%")
    table.add_row("On-Time Delivery (OTD)", f"{kpis.on_time_delivery_pct:.1f}%")
    table.add_row("Mean Job Tardiness", f"{kpis.mean_tardiness_minutes:.1f} min")
    table.add_row("Makespan", f"{kpis.makespan_minutes:.1f} min")

    console.print(table)

    machine_table = Table(
        title="Machine-by-Machine Utilization & OEE", show_header=True, header_style="bold cyan"
    )
    machine_table.add_column("Machine ID")
    machine_table.add_column("Cutting %", justify="right")
    machine_table.add_column("Setup %", justify="right")
    machine_table.add_column("Idle %", justify="right")
    machine_table.add_column("Down %", justify="right")
    machine_table.add_column("OEE %", justify="right")
    machine_table.add_column("Parts Done", justify="right")

    for m_id, m_kpi in kpis.machine_kpis.items():
        machine_table.add_row(
            m_id,
            f"{m_kpi.utilization_pct:.1f}%",
            f"{m_kpi.setup_pct:.1f}%",
            f"{m_kpi.idle_pct:.1f}%",
            f"{m_kpi.breakdown_pct:.1f}%",
            f"{m_kpi.oee_pct:.1f}%",
            str(m_kpi.parts_produced),
        )

    console.print(machine_table)

    # Export Plotly interactive dashboard
    html_file = PlotlyVisualizer.export_dashboard_html(kpis, result.events, output_path=html_out)
    console.print(
        f"[bold green]Interactive Plotly Gantt Dashboard exported to {html_file.resolve()}[/bold green]"
    )


@app.command("run-single")
def run_single(
    scenario_path: str = typer.Argument(
        "configs/scenarios/baseline.yaml", help="Path to scenario YAML"
    ),
    machine_id: str = typer.Option(
        "VMC-01", "--machine", help="Target machine ID for isolated run"
    ),
) -> None:
    """Executes single-machine isolated foundation demo."""
    p = Path(scenario_path)
    if not p.exists():
        console.print(f"[bold red]Error: Scenario file not found at {p}[/bold red]")
        raise typer.Exit(code=1)

    console.print(f"[bold green]Running single-machine simulation for {machine_id}...[/bold green]")
    engine = SimulationEngine.from_scenario_file(p)
    result = engine.run(single_machine_id=machine_id)

    console.print(
        f"[bold green]Run completed successfully! {result.total_events} events generated.[/bold green]"
    )
    m = result.machines[0]
    util_pct = (m.accumulated_cutting_minutes / max(1.0, result.duration_minutes)) * 100.0

    console.print(
        f"[cyan]Machine {m.machine_id}: Cutting = {m.accumulated_cutting_minutes:.1f}m | "
        f"Setup = {m.accumulated_setup_minutes:.1f}m | Idle = {m.accumulated_idle_minutes:.1f}m | "
        f"Utilization = {util_pct:.1f}% | Completed Parts = {m.total_parts_produced}[/cyan]"
    )


@app.command()
def diagnose(
    scenario_path: str = typer.Argument(
        "configs/scenarios/baseline.yaml", help="Path to scenario YAML"
    ),
    md_out: str | None = typer.Option(
        None, "--md", help="Path to export Markdown diagnostic report"
    ),
    json_out: str | None = typer.Option(
        None, "--json", help="Path to export JSON diagnostic findings"
    ),
) -> None:
    """Runs simulation and executes explainable expert diagnostic rules."""
    import json

    p = Path(scenario_path)
    if not p.exists():
        console.print(f"[bold red]Error: Scenario file not found at {p}[/bold red]")
        raise typer.Exit(code=1)

    console.print(f"[bold green]Running simulation for diagnosis: {p}...[/bold green]")
    engine = SimulationEngine.from_scenario_file(p)
    result = engine.run()

    kpis = KPICalculator.calculate(
        scenario_name=result.scenario_name,
        horizon_minutes=result.duration_minutes,
        events=result.events,
        jobs=engine.jobs,
    )

    from vmc_twin.rules import FactExtractor, RuleSeverity, create_default_rule_engine

    facts = FactExtractor.extract(
        kpis=kpis,
        events=result.events,
        window_minutes=engine.scenario.diagnosis.window_duration_minutes,
    )

    rule_engine = create_default_rule_engine()
    trace = rule_engine.diagnose(facts, thresholds=engine.scenario.diagnosis)

    # Display Rich Diagnostic Report
    console.print(
        Panel.fit(
            f"[bold cyan]Scenario: {trace.scenario_name}[/bold cyan]\n"
            f"[red]Critical Issues: {trace.critical_count}[/red] | "
            f"[yellow]Warnings: {trace.warning_count}[/yellow] | "
            f"[blue]Informational: {trace.info_count}[/blue]",
            title="Expert System Diagnostic Summary",
            border_style="magenta",
        )
    )

    if not trace.findings:
        console.print(
            "[bold green]✓ No operational anomalies detected. Shop floor operating efficiently.[/bold green]"
        )
    else:
        for idx, finding in enumerate(trace.findings, start=1):
            color = (
                "red"
                if finding.severity == RuleSeverity.CRITICAL
                else ("yellow" if finding.severity == RuleSeverity.WARNING else "blue")
            )
            table = Table(show_header=False, border_style=color)
            table.add_column("Field", style="bold")
            table.add_column("Detail")

            table.add_row("Severity", f"[{color}]{finding.severity.value}[/{color}]")
            table.add_row("Target", finding.target_entity)
            table.add_row("Confidence", f"{finding.confidence * 100:.1f}%")
            table.add_row("Root Cause", finding.root_cause_narrative)
            table.add_row(
                "Actionable Remediation",
                f"[bold green]{finding.actionable_remediation}[/bold green]",
            )

            console.print(
                Panel(
                    table,
                    title=f"[{color}]Finding #{idx}: {finding.rule_name} ({finding.rule_id})[/{color}]",
                    border_style=color,
                )
            )

    if md_out:
        md_path = Path(md_out)
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(trace.to_markdown(), encoding="utf-8")
        console.print(f"[bold green]Markdown report saved to {md_path.resolve()}[/bold green]")

    if json_out:
        json_path = Path(json_out)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "scenario": trace.scenario_name,
            "critical_count": trace.critical_count,
            "warning_count": trace.warning_count,
            "info_count": trace.info_count,
            "findings": [f.to_dict() for f in trace.findings],
            "suppressed": [f.to_dict() for f in trace.suppressed_findings],
        }
        json_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        console.print(f"[bold green]JSON findings saved to {json_path.resolve()}[/bold green]")


@app.command()
def optimize(
    scenario_path: str = typer.Argument(
        "configs/scenarios/baseline.yaml", help="Path to scenario YAML"
    ),
    time_limit: float = typer.Option(
        30.0, "--time-limit", help="CP-SAT optimizer time limit in seconds"
    ),
    html_out: str = typer.Option(
        "outputs/optimized_gantt.html", "--html", help="Path for optimized interactive HTML dashboard"
    ),
) -> None:
    """Solves mathematical CP-SAT scheduling optimization and simulates the optimal dispatch schedule."""
    p = Path(scenario_path)
    if not p.exists():
        console.print(f"[bold red]Error: Scenario file not found at {p}[/bold red]")
        raise typer.Exit(code=1)

    console.print(f"[bold green]Formulating mathematical model for: {p}...[/bold green]")
    engine = SimulationEngine.from_scenario_file(p)

    from vmc_twin.optimize import CPSATScheduler
    from vmc_twin.sim.dispatcher import ScheduleDispatchPolicy

    scheduler = CPSATScheduler(
        machines=engine.machine_specs,
        fixtures=engine.fixture_specs,
        transition_matrix=engine.transition_matrix,
    )

    console.print(
        f"[bold blue]Solving CP-SAT constraint programming model ({len(engine.jobs)} jobs, "
        f"{len(engine.machine_specs)} machines, time limit={time_limit}s)...[/bold blue]"
    )
    opt_result = scheduler.solve(engine.jobs, time_limit_seconds=time_limit)

    console.print(
        Panel.fit(
            f"[bold cyan]CP-SAT Solver Status: {opt_result.status}[/bold cyan]\n"
            f"[green]Solve Time: {opt_result.solver_time_seconds:.2f}s[/green]\n"
            f"[yellow]Theoretical Makespan: {opt_result.makespan_minutes:.1f}m[/yellow]\n"
            f"[magenta]Total Weighted Tardiness: {opt_result.total_weighted_tardiness:.1f}[/magenta]",
            title="CP-SAT Mathematical Optimization Summary",
            border_style="cyan",
        )
    )

    # Execute simulation using the CP-SAT schedule dispatch policy
    custom_disp = ScheduleDispatchPolicy(opt_result.machine_job_sequences)
    sim_result = engine.run(custom_dispatcher=custom_disp)

    kpis = KPICalculator.calculate(
        scenario_name=f"{sim_result.scenario_name}_CPSAT_Optimized",
        horizon_minutes=sim_result.duration_minutes,
        events=sim_result.events,
        jobs=engine.jobs,
    )

    table = Table(
        title="Simulated Optimal Schedule Performance",
        show_header=True,
        header_style="bold green",
    )
    table.add_column("Metric", style="dim")
    table.add_column("Optimized Value", justify="right")

    table.add_row("Makespan", f"{kpis.makespan_minutes:.1f} min")
    table.add_row("Jobs Completed", f"{kpis.completed_jobs} / {kpis.total_jobs}")
    table.add_row("On-Time Delivery (OTD)", f"{kpis.on_time_delivery_pct:.1f}%")
    table.add_row("Mean Tardiness", f"{kpis.mean_tardiness_minutes:.1f} min")
    table.add_row("Spindle Utilization %", f"{kpis.mean_spindle_utilization_pct:.1f}%")
    table.add_row("Setup Time %", f"{kpis.mean_setup_pct:.1f}%")

    console.print(table)

    html_file = PlotlyVisualizer.export_dashboard_html(kpis, sim_result.events, output_path=html_out)
    console.print(f"[bold green]Interactive Optimized Dashboard exported to {html_file.resolve()}[/bold green]")


@app.command()
def tournament(
    scenario_path: str = typer.Argument(
        "configs/scenarios/baseline.yaml", help="Path to scenario YAML"
    ),
    seeds: int = typer.Option(3, "--seeds", help="Number of random seeds"),
    time_limit: float = typer.Option(10.0, "--time-limit", help="Solver time limit per run in seconds"),
) -> None:
    """Executes multi-scheduler bake-off tournament comparing FIFO, EDD, SPT, SLACK, ATC, and CP-SAT."""
    p = Path(scenario_path)
    if not p.exists():
        console.print(f"[bold red]Error: Scenario file not found at {p}[/bold red]")
        raise typer.Exit(code=1)

    console.print(
        f"[bold cyan]Running Scheduling Tournament on {p} across {seeds} random seeds...[/bold cyan]"
    )

    from vmc_twin.optimize.pareto import TournamentRunner

    seed_list = [42 + i * 100 for i in range(seeds)]
    benchmarks = TournamentRunner.run_bakeoff(
        scenario_path=p,
        policies=("FIFO", "EDD", "SPT", "SLACK", "ATC", "CP-SAT"),
        seeds=seed_list,
        optimizer_time_limit=time_limit,
    )

    # Aggregate by policy
    policy_names = ["FIFO", "EDD", "SPT", "SLACK", "ATC", "CP-SAT"]
    table = Table(
        title="Optimizer & Dispatcher Tournament Leaderboard",
        show_header=True,
        header_style="bold magenta",
    )
    table.add_column("Policy / Model", style="bold")
    table.add_column("Mean Makespan (m)", justify="right")
    table.add_column("Mean Utilization %", justify="right")
    table.add_column("Mean Setup %", justify="right")
    table.add_column("Weighted Tardiness", justify="right")
    table.add_column("OTD %", justify="right")
    table.add_column("Avg Compute Time (s)", justify="right")

    for pol in policy_names:
        records = [r for r in benchmarks if r.policy_name == pol]
        if not records:
            continue
        n_rec = len(records)
        avg_makespan = sum(r.makespan_minutes for r in records) / n_rec
        avg_util = sum(r.mean_spindle_utilization_pct for r in records) / n_rec
        avg_setup = sum(r.mean_setup_pct for r in records) / n_rec
        avg_wt = sum(r.total_weighted_tardiness for r in records) / n_rec
        avg_otd = sum(r.on_time_delivery_pct for r in records) / n_rec
        avg_cpu = sum(r.computation_time_seconds for r in records) / n_rec

        table.add_row(
            pol,
            f"{avg_makespan:.1f}",
            f"{avg_util:.1f}%",
            f"{avg_setup:.1f}%",
            f"{avg_wt:.1f}",
            f"{avg_otd:.1f}%",
            f"{avg_cpu:.2f}s",
        )

    console.print(table)


if __name__ == "__main__":
    app()
