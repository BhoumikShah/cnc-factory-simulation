from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from vmc_twin.data.store import EventStore
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
    scenario_path: str = typer.Argument("configs/scenarios/baseline.yaml", help="Path to scenario YAML"),
    db_path: str | None = typer.Option(None, "--db", help="SQLite database path for event log persistence"),
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

    table = Table(title="Simulation Execution Summary", show_header=True, header_style="bold magenta")
    table.add_column("Metric", style="dim")
    table.add_column("Value", justify="right")

    table.add_row("Scenario Name", result.scenario_name)
    table.add_row("Simulated Horizon (hours)", f"{result.duration_minutes / 60.0:.1f} hrs")
    table.add_row("Total Discrete Events Emitted", str(result.total_events))
    table.add_row("Jobs Completed", str(result.completed_jobs_count))
    table.add_row("WIP Jobs In Progress", str(result.wip_jobs_count))

    console.print(table)

    machine_table = Table(title="Machine Utilization & Production", show_header=True, header_style="bold cyan")
    machine_table.add_column("Machine ID")
    machine_table.add_column("Type")
    machine_table.add_column("Cutting (min)", justify="right")
    machine_table.add_column("Setup (min)", justify="right")
    machine_table.add_column("Idle (min)", justify="right")
    machine_table.add_column("Utilization %", justify="right")
    machine_table.add_column("Parts Done", justify="right")

    for m in result.machines:
        total_time = max(1.0, result.duration_minutes)
        util_pct = (m.accumulated_cutting_minutes / total_time) * 100.0
        machine_table.add_row(
            m.machine_id,
            m.machine_type,
            f"{m.accumulated_cutting_minutes:.1f}",
            f"{m.accumulated_setup_minutes:.1f}",
            f"{m.accumulated_idle_minutes:.1f}",
            f"{util_pct:.1f}%",
            str(m.total_parts_produced),
        )

    console.print(machine_table)


@app.command("run-single")
def run_single(
    scenario_path: str = typer.Argument("configs/scenarios/baseline.yaml", help="Path to scenario YAML"),
    machine_id: str = typer.Option("VMC-01", "--machine", help="Target machine ID for isolated run"),
) -> None:
    """Executes single-machine isolated foundation demo."""
    p = Path(scenario_path)
    if not p.exists():
        console.print(f"[bold red]Error: Scenario file not found at {p}[/bold red]")
        raise typer.Exit(code=1)

    console.print(f"[bold green]Running single-machine simulation for {machine_id}...[/bold green]")
    engine = SimulationEngine.from_scenario_file(p)
    result = engine.run(single_machine_id=machine_id)

    console.print(f"[bold green]Run completed successfully! {result.total_events} events generated.[/bold green]")
    m = result.machines[0]
    util_pct = (m.accumulated_cutting_minutes / max(1.0, result.duration_minutes)) * 100.0

    console.print(
        f"[cyan]Machine {m.machine_id}: Cutting = {m.accumulated_cutting_minutes:.1f}m | "
        f"Setup = {m.accumulated_setup_minutes:.1f}m | Idle = {m.accumulated_idle_minutes:.1f}m | "
        f"Utilization = {util_pct:.1f}% | Completed Parts = {m.total_parts_produced}[/cyan]"
    )


if __name__ == "__main__":
    app()
