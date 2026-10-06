from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from vmc_twin.domain.events import Event
from vmc_twin.domain.job import Job
from vmc_twin.domain.states import SpindleState


@dataclass(frozen=True, slots=True)
class MachineKPIs:
    """Quantitative performance and utilization metrics for a single VMC."""

    machine_id: str
    machine_type: str
    total_horizon_minutes: float
    cutting_minutes: float
    setup_minutes: float
    breakdown_minutes: float
    idle_starved_minutes: float
    idle_wait_setup_minutes: float
    idle_wait_tool_minutes: float
    idle_wait_operator_minutes: float
    idle_wait_fixture_minutes: float
    off_shift_minutes: float

    # Key Ratios
    utilization_pct: float
    setup_pct: float
    idle_pct: float
    breakdown_pct: float
    availability_pct: float
    oee_pct: float
    parts_produced: int
    total_operating_cost_usd: float


@dataclass(frozen=True, slots=True)
class FleetKPIs:
    """Aggregate fleet-wide operational KPIs and delivery performance metrics."""

    scenario_name: str
    horizon_hours: float
    fleet_size: int
    mean_spindle_utilization_pct: float
    mean_setup_pct: float
    mean_idle_pct: float
    mean_breakdown_pct: float
    mean_oee_pct: float

    # Delivery & Queue Metrics
    total_jobs: int
    completed_jobs: int
    wip_jobs: int
    on_time_delivery_pct: float
    mean_tardiness_minutes: float
    max_tardiness_minutes: float
    total_weighted_tardiness: float
    makespan_minutes: float

    # Per-Machine Breakdown
    machine_kpis: Mapping[str, MachineKPIs] = field(default_factory=dict)
    idle_time_by_cause: Mapping[str, float] = field(default_factory=dict)


class KPICalculator:
    """Computes all machine and fleet KPIs directly from the discrete Event log."""

    @staticmethod
    def calculate(
        scenario_name: str,
        horizon_minutes: float,
        events: Sequence[Event],
        jobs: Sequence[Job],
        completed_jobs: Sequence[Job] | None = None,
        machine_hourly_rates: Mapping[str, float] | None = None,
    ) -> FleetKPIs:
        rates = machine_hourly_rates or {}
        machine_events: dict[str, list[Event]] = {}
        for e in events:
            machine_events.setdefault(e.machine_id, []).append(e)

        machine_kpis_map: dict[str, MachineKPIs] = {}
        total_fleet_cutting = 0.0
        total_fleet_setup = 0.0
        total_fleet_idle = 0.0
        total_fleet_breakdown = 0.0
        total_fleet_oee = 0.0
        idle_causes_agg: dict[str, float] = {
            "NO_QUEUE_JOB": 0.0,
            "WAITING_SETUP": 0.0,
            "WAITING_TOOL": 0.0,
            "WAITING_OPERATOR": 0.0,
            "WAITING_FIXTURE": 0.0,
        }

        cutting_ends = [
            e.t_end for e in events if e.state in {SpindleState.CUTTING, SpindleState.SETUP}
        ]
        makespan = max(cutting_ends) if cutting_ends else 0.0

        for m_id, evts in machine_events.items():
            t_cut = sum(e.duration() for e in evts if e.state == SpindleState.CUTTING)
            t_setup = sum(e.duration() for e in evts if e.state == SpindleState.SETUP)
            t_down = sum(
                e.duration()
                for e in evts
                if e.state in {SpindleState.BREAKDOWN, SpindleState.PLANNED_MAINT}
            )
            t_off = sum(e.duration() for e in evts if e.state == SpindleState.OFF_SHIFT)

            t_starve = sum(e.duration() for e in evts if e.state == SpindleState.IDLE_STARVED)
            t_w_setup = sum(e.duration() for e in evts if e.state == SpindleState.IDLE_WAIT_SETUP)
            t_w_tool = sum(e.duration() for e in evts if e.state == SpindleState.IDLE_WAIT_TOOL)
            t_w_op = sum(e.duration() for e in evts if e.state == SpindleState.IDLE_WAIT_OPERATOR)
            t_w_fix = sum(e.duration() for e in evts if e.state == SpindleState.IDLE_WAIT_FIXTURE)

            t_idle_total = t_starve + t_w_setup + t_w_tool + t_w_op + t_w_fix

            idle_causes_agg["NO_QUEUE_JOB"] += t_starve
            idle_causes_agg["WAITING_SETUP"] += t_w_setup
            idle_causes_agg["WAITING_TOOL"] += t_w_tool
            idle_causes_agg["WAITING_OPERATOR"] += t_w_op
            idle_causes_agg["WAITING_FIXTURE"] += t_w_fix

            planned_time = max(1.0, horizon_minutes - t_off)
            util_pct = (t_cut / planned_time) * 100.0
            setup_pct = (t_setup / planned_time) * 100.0
            idle_pct = (t_idle_total / planned_time) * 100.0
            down_pct = (t_down / planned_time) * 100.0

            # OEE Calculation
            availability = max(0.0, (planned_time - t_down - t_idle_total) / planned_time)
            performance = max(0.0, min(1.0, t_cut / max(1.0, t_cut + t_setup)))
            quality = 1.0  # Quality factor baseline
            oee_pct = availability * performance * quality * 100.0

            hourly_rate = rates.get(m_id, 85.0)
            cost_usd = (planned_time / 60.0) * hourly_rate

            m_kpi = MachineKPIs(
                machine_id=m_id,
                machine_type="",
                total_horizon_minutes=horizon_minutes,
                cutting_minutes=t_cut,
                setup_minutes=t_setup,
                breakdown_minutes=t_down,
                idle_starved_minutes=t_starve,
                idle_wait_setup_minutes=t_w_setup,
                idle_wait_tool_minutes=t_w_tool,
                idle_wait_operator_minutes=t_w_op,
                idle_wait_fixture_minutes=t_w_fix,
                off_shift_minutes=t_off,
                utilization_pct=round(util_pct, 2),
                setup_pct=round(setup_pct, 2),
                idle_pct=round(idle_pct, 2),
                breakdown_pct=round(down_pct, 2),
                availability_pct=round(availability * 100.0, 2),
                oee_pct=round(oee_pct, 2),
                parts_produced=len(
                    {e.job_id for e in evts if e.job_id and e.state == SpindleState.CUTTING}
                ),
                total_operating_cost_usd=round(cost_usd, 2),
            )
            machine_kpis_map[m_id] = m_kpi

            total_fleet_cutting += util_pct
            total_fleet_setup += setup_pct
            total_fleet_idle += idle_pct
            total_fleet_breakdown += down_pct
            total_fleet_oee += oee_pct

        fleet_count = max(1, len(machine_kpis_map))

        # Job Delivery & Tardiness Metrics
        # Map last completion time per job from cutting events
        job_completion_times: dict[str, float] = {}
        for e in events:
            if e.job_id and e.state == SpindleState.CUTTING:
                job_completion_times[e.job_id] = max(
                    job_completion_times.get(e.job_id, 0.0), e.t_end
                )

        tardiness_list: list[float] = []
        weighted_tardiness = 0.0
        on_time_count = 0

        for j in jobs:
            c_time = job_completion_times.get(j.job_id)
            if c_time is not None:
                tard = max(0.0, c_time - j.due_date)
                tardiness_list.append(tard)
                weighted_tardiness += tard * j.weight_tardiness_penalty
                if tard <= 1e-6:
                    on_time_count += 1
            else:
                # Job not completed before horizon end
                tard = max(0.0, horizon_minutes - j.due_date)
                tardiness_list.append(tard)
                weighted_tardiness += tard * j.weight_tardiness_penalty

        otd_pct = (on_time_count / max(1, len(jobs))) * 100.0
        mean_tard = sum(tardiness_list) / max(1, len(tardiness_list)) if tardiness_list else 0.0
        max_tard = max(tardiness_list) if tardiness_list else 0.0

        done_count = len(job_completion_times)
        wip_count = max(0, len(jobs) - done_count)

        return FleetKPIs(
            scenario_name=scenario_name,
            horizon_hours=round(horizon_minutes / 60.0, 2),
            fleet_size=fleet_count,
            mean_spindle_utilization_pct=round(total_fleet_cutting / fleet_count, 2),
            mean_setup_pct=round(total_fleet_setup / fleet_count, 2),
            mean_idle_pct=round(total_fleet_idle / fleet_count, 2),
            mean_breakdown_pct=round(total_fleet_breakdown / fleet_count, 2),
            mean_oee_pct=round(total_fleet_oee / fleet_count, 2),
            total_jobs=len(jobs),
            completed_jobs=done_count,
            wip_jobs=wip_count,
            on_time_delivery_pct=round(otd_pct, 2),
            mean_tardiness_minutes=round(mean_tard, 2),
            max_tardiness_minutes=round(max_tard, 2),
            total_weighted_tardiness=round(weighted_tardiness, 2),
            makespan_minutes=round(makespan, 2),
            machine_kpis=machine_kpis_map,
            idle_time_by_cause=idle_causes_agg,
        )
