from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from vmc_twin.domain.events import Event
from vmc_twin.domain.states import CauseCode, SpindleState
from vmc_twin.report.kpis import FleetKPIs


@dataclass(frozen=True)
class MachineFacts:
    """Aggregated behavioral and performance facts for a single machine."""

    machine_id: str
    utilization_pct: float
    setup_pct: float
    idle_pct: float
    breakdown_pct: float
    idle_starve_pct: float
    idle_wait_setup_pct: float
    idle_wait_tool_pct: float
    idle_wait_operator_pct: float
    idle_wait_fixture_pct: float
    total_cutting_minutes: float
    total_setup_minutes: float
    total_breakdown_minutes: float
    breakdown_count: int
    mtbf_observed_hours: float
    mttr_observed_minutes: float
    has_pallet_changer: bool
    completed_ops_count: int


@dataclass(frozen=True)
class WindowMachineFacts:
    """Spindle engagement metric over a specific rolling time window."""

    window_idx: int
    t_start: float
    t_end: float
    spindle_cutting_minutes: dict[str, float]
    bottleneck_machine_id: str | None


@dataclass(frozen=True)
class ShopFloorFacts:
    """Master facts model consumed by the explainable expert rule engine."""

    scenario_name: str
    horizon_hours: float
    fleet_kpis: FleetKPIs
    machine_facts: dict[str, MachineFacts]
    window_facts: list[WindowMachineFacts]
    tool_wait_minutes: dict[str, float] = field(default_factory=dict)
    operator_wait_minutes: dict[str, float] = field(default_factory=dict)


class FactExtractor:
    """Extracts typed ShopFloorFacts from simulation events and calculated KPIs."""

    @classmethod
    def extract(
        cls,
        kpis: FleetKPIs,
        events: Sequence[Event],
        window_minutes: float = 240.0,
    ) -> ShopFloorFacts:
        """Computes comprehensive facts across the fleet and sliding time windows."""
        machine_facts: dict[str, MachineFacts] = {}
        tool_wait: dict[str, float] = {}
        operator_wait: dict[str, float] = {}

        # Aggregate event level metrics
        machine_events: dict[str, list[Event]] = {}
        for e in events:
            machine_events.setdefault(e.machine_id, []).append(e)
            dur = e.duration()

            if e.state == SpindleState.IDLE_WAIT_TOOL:
                t_key = str(e.metadata.get("tool_type", "GENERIC_TOOL"))
                tool_wait[t_key] = tool_wait.get(t_key, 0.0) + dur
            elif e.state in (SpindleState.IDLE_WAIT_OPERATOR, SpindleState.IDLE_WAIT_SETUP):
                op_key = str(e.metadata.get("operator_id", "OPERATOR_POOL"))
                operator_wait[op_key] = operator_wait.get(op_key, 0.0) + dur

        horizon_m = kpis.horizon_hours * 60.0 if kpis.horizon_hours > 0 else 1.0

        for m_id, m_kpi in kpis.machine_kpis.items():
            evts = machine_events.get(m_id, [])
            starve_m = sum(
                e.duration()
                for e in evts
                if e.state == SpindleState.IDLE_STARVED or e.cause_code == CauseCode.NO_QUEUE_JOB
            )
            setup_wait_m = sum(
                e.duration() for e in evts if e.state == SpindleState.IDLE_WAIT_SETUP
            )
            tool_wait_m = sum(
                e.duration()
                for e in evts
                if e.state == SpindleState.IDLE_WAIT_TOOL
                or e.cause_code in (CauseCode.TOOL_CRIB_EMPTY, CauseCode.TOOL_WORN_OUT)
            )
            op_wait_m = sum(
                e.duration()
                for e in evts
                if e.state == SpindleState.IDLE_WAIT_OPERATOR
                or e.cause_code == CauseCode.OPERATOR_UNAVAILABLE
            )
            fixture_wait_m = sum(
                e.duration()
                for e in evts
                if e.state == SpindleState.IDLE_WAIT_FIXTURE
                or e.cause_code == CauseCode.FIXTURE_IN_USE
            )

            bd_evts = [
                e
                for e in evts
                if e.state == SpindleState.BREAKDOWN
                or e.cause_code
                in (
                    CauseCode.SPINDLE_BEARING_FAULT,
                    CauseCode.COOLANT_PUMP_FAILURE,
                    CauseCode.CHIP_CONVEYOR_JAM,
                )
            ]
            bd_count = len(bd_evts)
            bd_minutes = sum(e.duration() for e in bd_evts)
            cut_minutes = sum(e.duration() for e in evts if e.state == SpindleState.CUTTING)

            observed_mtbf_hrs = (
                (cut_minutes / 60.0) / bd_count if bd_count > 0 else kpis.horizon_hours
            )
            observed_mttr_min = bd_minutes / bd_count if bd_count > 0 else 0.0

            machine_facts[m_id] = MachineFacts(
                machine_id=m_id,
                utilization_pct=m_kpi.utilization_pct,
                setup_pct=m_kpi.setup_pct,
                idle_pct=m_kpi.idle_pct,
                breakdown_pct=m_kpi.breakdown_pct,
                idle_starve_pct=(starve_m / horizon_m) * 100.0,
                idle_wait_setup_pct=(setup_wait_m / horizon_m) * 100.0,
                idle_wait_tool_pct=(tool_wait_m / horizon_m) * 100.0,
                idle_wait_operator_pct=(op_wait_m / horizon_m) * 100.0,
                idle_wait_fixture_pct=(fixture_wait_m / horizon_m) * 100.0,
                total_cutting_minutes=cut_minutes,
                total_setup_minutes=sum(
                    e.duration() for e in evts if e.state == SpindleState.SETUP
                ),
                total_breakdown_minutes=bd_minutes,
                breakdown_count=bd_count,
                mtbf_observed_hours=observed_mtbf_hrs,
                mttr_observed_minutes=observed_mttr_min,
                has_pallet_changer=False,  # default / can be overridden if machines passed
                completed_ops_count=len([e for e in evts if e.state == SpindleState.CUTTING]),
            )

        # Compute sliding window facts
        window_facts: list[WindowMachineFacts] = []
        if window_minutes > 0:
            num_windows = max(1, int(horizon_m // window_minutes))
            for w in range(num_windows):
                w_start = w * window_minutes
                w_end = (w + 1) * window_minutes
                cutting_by_m: dict[str, float] = {}

                for m_id, evts in machine_events.items():
                    cut_m = 0.0
                    for e in evts:
                        if e.state == SpindleState.CUTTING:
                            # Intersection of [e.t_start, e.t_end] and [w_start, w_end]
                            overlap_start = max(e.t_start, w_start)
                            overlap_end = min(e.t_end, w_end)
                            if overlap_end > overlap_start:
                                cut_m += overlap_end - overlap_start
                    cutting_by_m[m_id] = cut_m

                # Identify bottleneck in this window (max cutting/active load)
                sorted_machines = sorted(cutting_by_m.items(), key=lambda x: x[1], reverse=True)
                top_m, top_cut = sorted_machines[0] if sorted_machines else (None, 0.0)
                bottleneck_id = top_m if top_cut > 0.0 else None

                window_facts.append(
                    WindowMachineFacts(
                        window_idx=w,
                        t_start=w_start,
                        t_end=w_end,
                        spindle_cutting_minutes=cutting_by_m,
                        bottleneck_machine_id=bottleneck_id,
                    )
                )

        return ShopFloorFacts(
            scenario_name=kpis.scenario_name,
            horizon_hours=kpis.horizon_hours,
            fleet_kpis=kpis,
            machine_facts=machine_facts,
            window_facts=window_facts,
            tool_wait_minutes=tool_wait,
            operator_wait_minutes=operator_wait,
        )
