from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import simpy

from vmc_twin.config.loader import ConfigLoader
from vmc_twin.config.schemas import ScenarioConfig
from vmc_twin.data.generator import SyntheticDataGenerator
from vmc_twin.data.store import EventStore
from vmc_twin.domain.events import Event
from vmc_twin.domain.fixture import FixtureSpec, FixtureTransitionMatrix
from vmc_twin.domain.job import Job
from vmc_twin.domain.machine import Machine, MachineSpec
from vmc_twin.domain.operator import Operator
from vmc_twin.domain.tool import ToolSpec
from vmc_twin.sim.breakdowns import BreakdownProcess
from vmc_twin.sim.dispatcher import (
    DispatchPolicy,
    EDDDispatchPolicy,
    FIFODispatchPolicy,
    SPTDispatchPolicy,
)
from vmc_twin.sim.event_bus import (
    BroadcastEventSink,
    EventSink,
    InMemoryEventSink,
    StoreEventSink,
)
from vmc_twin.sim.machine_process import MachineProcess
from vmc_twin.sim.resources import ShopFloorResources
from vmc_twin.sim.rng import RNGManager
from vmc_twin.sim.shifts import ShiftCalendarManager


@dataclass
class SimulationRunResult:
    """Encapsulates the execution results of a simulation run."""

    scenario_name: str
    duration_minutes: float
    total_events: int
    completed_jobs_count: int
    wip_jobs_count: int
    events: list[Event]
    machines: list[Machine]


class SimulationEngine:
    """
    Simulation Engine orchestrator. Builds SimPy environments, mounts machines,
    binds dispatch policies, resources, and event sinks, and executes scenarios.
    """

    def __init__(
        self,
        scenario: ScenarioConfig,
        machines: Sequence[MachineSpec],
        tools: Sequence[ToolSpec],
        fixtures: Sequence[FixtureSpec],
        transition_matrix: FixtureTransitionMatrix,
        operators: Sequence[Operator],
        jobs: Sequence[Job] | None = None,
        event_store: EventStore | None = None,
    ) -> None:
        self.scenario = scenario
        self.machine_specs = list(machines)
        self.tool_specs = list(tools)
        self.fixture_specs = list(fixtures)
        self.transition_matrix = transition_matrix
        self.operators = list(operators)
        self.jobs = list(jobs) if jobs is not None else []
        self.event_store = event_store

        self.rng_manager = RNGManager(master_seed=scenario.random_seed)

    @classmethod
    def from_scenario_file(
        cls,
        scenario_path: Path | str,
        event_store: EventStore | None = None,
    ) -> SimulationEngine:
        """Constructs an engine directly by loading scenario and shop YAML files."""
        p = Path(scenario_path)
        scenario_cfg = ConfigLoader.load_scenario(p)
        shop_dir = Path(scenario_cfg.shop_config_dir)

        machines = ConfigLoader.load_machines(shop_dir / "machines.yaml")
        if scenario_cfg.injected_faults.get("high_failure_rate", False):
            # Reduced MTBF to 4 hours to simulate severe unreliability
            machines = [
                MachineSpec(
                    machine_id=m.machine_id,
                    machine_type=m.machine_type,
                    spindle_power_kw=m.spindle_power_kw,
                    max_spindle_rpm=m.max_spindle_rpm,
                    magazine_capacity=m.magazine_capacity,
                    has_pallet_changer=m.has_pallet_changer,
                    mtbf_hours=4.0,
                    mttr_minutes=90.0,
                    hourly_rate_usd=m.hourly_rate_usd,
                    pallet_setup_factor=m.pallet_setup_factor,
                )
                for m in machines
            ]

        tools = ConfigLoader.load_tools(shop_dir / "tools.yaml")
        fixtures, matrix = ConfigLoader.load_fixtures(shop_dir / "fixtures.yaml")
        operators = ConfigLoader.load_operators(shop_dir / "shifts.yaml")

        # Generate synthetic jobs if not loaded externally
        gen = SyntheticDataGenerator(random_seed=scenario_cfg.random_seed)
        jobs = gen.generate_jobs(
            count=scenario_cfg.synthetic_job_count,
            horizon_minutes=scenario_cfg.duration_minutes,
            workpiece_mix=scenario_cfg.workpiece_mix,
        )

        return cls(
            scenario=scenario_cfg,
            machines=machines,
            tools=tools,
            fixtures=fixtures,
            transition_matrix=matrix,
            operators=operators,
            jobs=jobs,
            event_store=event_store,
        )

    def _resolve_dispatcher(self, policy_name: str) -> DispatchPolicy:
        match policy_name.upper():
            case "FIFO":
                return FIFODispatchPolicy()
            case "EDD":
                return EDDDispatchPolicy()
            case "SPT":
                return SPTDispatchPolicy()
            case "SLACK":
                from vmc_twin.sim.dispatcher import SlackDispatchPolicy

                return SlackDispatchPolicy()
            case "ATC":
                from vmc_twin.sim.dispatcher import ATCDispatchPolicy

                return ATCDispatchPolicy()
            case _:
                return FIFODispatchPolicy()

    def run(
        self,
        single_machine_id: str | None = None,
        custom_dispatcher: DispatchPolicy | None = None,
    ) -> SimulationRunResult:
        """Executes the simulation run until scenario.duration_minutes."""
        env = simpy.Environment()

        # Build Event Sinks
        mem_sink = InMemoryEventSink()
        sinks: list[EventSink] = [mem_sink]
        if self.event_store is not None:
            sinks.append(StoreEventSink(self.event_store))
        broadcast_sink = BroadcastEventSink(sinks)

        # Handle Fault Injections
        crib_stocks: dict[str, int] = {}
        if self.scenario.injected_faults.get("starve_tool_crib", False):
            # Injected fault: completely empty tool crib
            crib_stocks = {ts.tool_type: 0 for ts in self.tool_specs}

        operators_to_use = list(self.operators)
        if self.scenario.injected_faults.get("operator_bottleneck", False):
            # Injected fault: restrict pool to single operator
            operators_to_use = [self.operators[0]] if self.operators else []

        # Initialize shared resources
        resources = ShopFloorResources(
            env=env,
            operators=operators_to_use,
            fixture_specs=self.fixture_specs,
            transition_matrix=self.transition_matrix,
            tool_specs=self.tool_specs,
            initial_crib_stock=crib_stocks,
        )

        # Filter machine specs if single_machine_id specified
        specs_to_run = self.machine_specs
        if single_machine_id is not None:
            specs_to_run = [m for m in self.machine_specs if m.machine_id == single_machine_id]
            if not specs_to_run:
                specs_to_run = [self.machine_specs[0]]

        # Instantiate dynamic machine states
        machines = [Machine(spec=spec) for spec in specs_to_run]
        dispatcher = custom_dispatcher or self._resolve_dispatcher(self.scenario.dispatch_policy)

        active_jobs = list(self.jobs)
        completed_jobs: list[Job] = []
        in_progress_jobs: set[str] = set()

        # Launch machine processes in SimPy
        for m in machines:
            MachineProcess(
                env=env,
                machine=m,
                resources=resources,
                dispatcher=dispatcher,
                event_sink=broadcast_sink,
                rng_manager=self.rng_manager,
                active_jobs=active_jobs,
                completed_jobs=completed_jobs,
                in_progress_job_ids=in_progress_jobs,
            )
            # Launch stochastic breakdown process for each machine if enabled
            if self.scenario.enable_breakdowns:
                BreakdownProcess(
                    env=env,
                    machine=m,
                    maintenance_resource=resources.maintenance_resource,
                    event_sink=broadcast_sink,
                    rng_manager=self.rng_manager,
                )

        # Launch shift calendar manager
        ShiftCalendarManager(
            env=env,
            shift_configs=[],
            machines=machines,
            event_sink=broadcast_sink,
            enable_shift_downtime=False,
        )

        # Execute simulation
        env.run(until=self.scenario.duration_minutes)
        broadcast_sink.flush()

        return SimulationRunResult(
            scenario_name=self.scenario.scenario_name,
            duration_minutes=self.scenario.duration_minutes,
            total_events=len(mem_sink.events),
            completed_jobs_count=len(completed_jobs),
            wip_jobs_count=len(active_jobs),
            events=mem_sink.events,
            machines=machines,
        )
