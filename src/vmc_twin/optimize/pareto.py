from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from vmc_twin.config.loader import ConfigLoader
from vmc_twin.data.generator import SyntheticDataGenerator
from vmc_twin.optimize.cpsat_scheduler import CPSATScheduler
from vmc_twin.report.kpis import KPICalculator
from vmc_twin.sim.dispatcher import DispatchPolicy, ScheduleDispatchPolicy
from vmc_twin.sim.engine import SimulationEngine


@dataclass(frozen=True)
class PolicyBenchmarkResult:
    """Benchmark performance metrics for a single dispatch policy or optimization model."""

    policy_name: str
    seed: int
    makespan_minutes: float
    mean_spindle_utilization_pct: float
    mean_setup_pct: float
    total_weighted_tardiness: float
    on_time_delivery_pct: float
    completed_jobs: int
    computation_time_seconds: float


class ParetoFrontier:
    """Computes Pareto-optimal non-dominated solutions for multi-objective trade-off analysis."""

    @staticmethod
    def identify_non_dominated_2d(
        points: Sequence[tuple[float, float]],
        minimize_x: bool = True,
        minimize_y: bool = True,
    ) -> list[int]:
        """Returns the indices of points that form the non-dominated Pareto frontier."""
        n = len(points)
        non_dominated_indices: list[int] = []

        for i in range(n):
            x_i, y_i = points[i]
            dominated = False

            for j in range(n):
                if i == j:
                    continue
                x_j, y_j = points[j]

                # Check if j dominates i
                x_better = (x_j <= x_i) if minimize_x else (x_j >= x_i)
                y_better = (y_j <= y_i) if minimize_y else (y_j >= y_i)
                strict_better = (
                    ((x_j < x_i) if minimize_x else (x_j > x_i))
                    or ((y_j < y_i) if minimize_y else (y_j > y_i))
                )

                if x_better and y_better and strict_better:
                    dominated = True
                    break

            if not dominated:
                non_dominated_indices.append(i)

        return non_dominated_indices

    @classmethod
    def calculate_frontier_from_benchmarks(
        cls,
        benchmarks: Sequence[PolicyBenchmarkResult],
        x_metric: str = "makespan_minutes",
        y_metric: str = "total_weighted_tardiness",
        minimize_x: bool = True,
        minimize_y: bool = True,
    ) -> list[PolicyBenchmarkResult]:
        """Filters a sequence of benchmark results to only the non-dominated Pareto frontier."""
        if not benchmarks:
            return []
        points = [
            (float(getattr(b, x_metric)), float(getattr(b, y_metric)))
            for b in benchmarks
        ]
        frontier_indices = cls.identify_non_dominated_2d(
            points, minimize_x=minimize_x, minimize_y=minimize_y
        )
        return [benchmarks[i] for i in frontier_indices]


class TournamentRunner:
    """Executes a multi-policy scheduler bake-off across identical random seeds."""

    @classmethod
    def run_bakeoff(
        cls,
        scenario_path: Path | str,
        policies: Sequence[str] = ("FIFO", "EDD", "SPT", "SLACK", "ATC", "CP-SAT"),
        seeds: Sequence[int] = (42,),
        optimizer_time_limit: float = 15.0,
    ) -> list[PolicyBenchmarkResult]:
        """Runs all policies on the scenario across specified seeds and collects benchmarks."""
        results: list[PolicyBenchmarkResult] = []
        p = Path(scenario_path)

        for seed in seeds:
            scenario_cfg = ConfigLoader.load_scenario(p)
            shop_dir = Path(scenario_cfg.shop_config_dir)

            machines = ConfigLoader.load_machines(shop_dir / "machines.yaml")
            tools = ConfigLoader.load_tools(shop_dir / "tools.yaml")
            fixtures, matrix = ConfigLoader.load_fixtures(shop_dir / "fixtures.yaml")
            operators = ConfigLoader.load_operators(shop_dir / "shifts.yaml")

            # Generate identical job sets for this seed
            gen = SyntheticDataGenerator(random_seed=seed)
            jobs = gen.generate_jobs(
                count=scenario_cfg.synthetic_job_count,
                horizon_minutes=scenario_cfg.duration_minutes,
                workpiece_mix=scenario_cfg.workpiece_mix,
            )

            for policy in policies:
                t0 = time.perf_counter()
                engine = SimulationEngine(
                    scenario=scenario_cfg,
                    machines=machines,
                    tools=tools,
                    fixtures=fixtures,
                    transition_matrix=matrix,
                    operators=operators,
                    jobs=jobs,
                )

                custom_disp: DispatchPolicy
                if policy.upper() == "CP-SAT":
                    scheduler = CPSATScheduler(
                        machines=machines,
                        fixtures=fixtures,
                        transition_matrix=matrix,
                    )
                    sched_res = scheduler.solve(
                        jobs=jobs,
                        time_limit_seconds=optimizer_time_limit,
                    )
                    custom_disp = ScheduleDispatchPolicy(sched_res.machine_job_sequences)
                    sim_result = engine.run(custom_dispatcher=custom_disp)
                else:
                    custom_disp = engine._resolve_dispatcher(policy)
                    sim_result = engine.run(custom_dispatcher=custom_disp)

                elapsed = time.perf_counter() - t0

                kpis = KPICalculator.calculate(
                    scenario_name=sim_result.scenario_name,
                    horizon_minutes=sim_result.duration_minutes,
                    events=sim_result.events,
                    jobs=jobs,
                )

                results.append(
                    PolicyBenchmarkResult(
                        policy_name=policy.upper(),
                        seed=seed,
                        makespan_minutes=kpis.makespan_minutes,
                        mean_spindle_utilization_pct=kpis.mean_spindle_utilization_pct,
                        mean_setup_pct=kpis.mean_setup_pct,
                        total_weighted_tardiness=kpis.total_weighted_tardiness,
                        on_time_delivery_pct=kpis.on_time_delivery_pct,
                        completed_jobs=kpis.completed_jobs,
                        computation_time_seconds=elapsed,
                    )
                )

        return results
