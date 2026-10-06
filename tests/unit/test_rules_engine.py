from __future__ import annotations

from vmc_twin.config.schemas import DiagnosisThresholdsConfig
from vmc_twin.domain.events import Event
from vmc_twin.domain.states import CauseCode, RuleSeverity, SpindleState
from vmc_twin.report.kpis import FleetKPIs, MachineKPIs
from vmc_twin.rules.engine import DiagnosticFinding, ExplanationTrace
from vmc_twin.rules.facts import (
    FactExtractor,
    MachineFacts,
    ShopFloorFacts,
)
from vmc_twin.rules.library import (
    BreakdownDominatedRule,
    IdleStarvationRule,
    WaitingSetupRule,
    create_default_rule_engine,
)


def test_fact_extraction() -> None:
    events = [
        Event(
            t_start=0.0,
            t_end=50.0,
            machine_id="VMC-01",
            job_id="J001",
            op_id="OP1",
            state=SpindleState.CUTTING,
            cause_code=CauseCode.NONE,
        ),
        Event(
            t_start=50.0,
            t_end=70.0,
            machine_id="VMC-01",
            job_id="J001",
            op_id="OP1",
            state=SpindleState.IDLE_WAIT_TOOL,
            cause_code=CauseCode.TOOL_CRIB_EMPTY,
            metadata={"tool_type": "ENDMILL_10MM"},
        ),
        Event(
            t_start=70.0,
            t_end=100.0,
            machine_id="VMC-01",
            job_id=None,
            op_id=None,
            state=SpindleState.IDLE_STARVED,
            cause_code=CauseCode.NO_QUEUE_JOB,
        ),
    ]

    m_kpi = MachineKPIs(
        machine_id="VMC-01",
        machine_type="3AX_STANDARD",
        total_horizon_minutes=100.0,
        cutting_minutes=50.0,
        setup_minutes=0.0,
        breakdown_minutes=0.0,
        idle_starved_minutes=30.0,
        idle_wait_setup_minutes=0.0,
        idle_wait_tool_minutes=20.0,
        idle_wait_operator_minutes=0.0,
        idle_wait_fixture_minutes=0.0,
        off_shift_minutes=0.0,
        utilization_pct=50.0,
        setup_pct=0.0,
        idle_pct=50.0,
        breakdown_pct=0.0,
        availability_pct=100.0,
        oee_pct=50.0,
        parts_produced=1,
        total_operating_cost_usd=140.0,
    )
    fleet_kpis = FleetKPIs(
        scenario_name="test_facts",
        horizon_hours=100.0 / 60.0,  # exactly 100 min
        fleet_size=1,
        mean_spindle_utilization_pct=50.0,
        mean_setup_pct=0.0,
        mean_idle_pct=50.0,
        mean_breakdown_pct=0.0,
        mean_oee_pct=50.0,
        total_jobs=1,
        completed_jobs=1,
        wip_jobs=0,
        on_time_delivery_pct=100.0,
        mean_tardiness_minutes=0.0,
        max_tardiness_minutes=0.0,
        total_weighted_tardiness=0.0,
        makespan_minutes=100.0,
        machine_kpis={"VMC-01": m_kpi},
        idle_time_by_cause={
            CauseCode.TOOL_CRIB_EMPTY.value: 20.0,
            CauseCode.NO_QUEUE_JOB.value: 30.0,
        },
    )

    facts = FactExtractor.extract(fleet_kpis, events, window_minutes=60.0)
    assert facts.scenario_name == "test_facts"
    assert "VMC-01" in facts.machine_facts
    m_facts = facts.machine_facts["VMC-01"]
    assert m_facts.total_cutting_minutes == 50.0
    assert abs(m_facts.idle_wait_tool_pct - 20.0) < 1e-5
    assert abs(m_facts.idle_starve_pct - 30.0) < 1e-5
    assert facts.tool_wait_minutes.get("ENDMILL_10MM") == 20.0


def test_rule_evaluations() -> None:
    thresholds = DiagnosisThresholdsConfig()

    m_facts_starved = MachineFacts(
        machine_id="VMC-01",
        utilization_pct=10.0,
        setup_pct=5.0,
        idle_pct=85.0,
        breakdown_pct=0.0,
        idle_starve_pct=75.0,
        idle_wait_setup_pct=0.0,
        idle_wait_tool_pct=0.0,
        idle_wait_operator_pct=0.0,
        idle_wait_fixture_pct=0.0,
        total_cutting_minutes=60.0,
        total_setup_minutes=30.0,
        total_breakdown_minutes=0.0,
        breakdown_count=0,
        mtbf_observed_hours=100.0,
        mttr_observed_minutes=0.0,
        has_pallet_changer=False,
        completed_ops_count=5,
    )

    m_facts_breakdown = MachineFacts(
        machine_id="VMC-02",
        utilization_pct=20.0,
        setup_pct=5.0,
        idle_pct=25.0,
        breakdown_pct=50.0,
        idle_starve_pct=0.0,
        idle_wait_setup_pct=0.0,
        idle_wait_tool_pct=0.0,
        idle_wait_operator_pct=0.0,
        idle_wait_fixture_pct=0.0,
        total_cutting_minutes=120.0,
        total_setup_minutes=30.0,
        total_breakdown_minutes=300.0,
        breakdown_count=4,
        mtbf_observed_hours=0.5,
        mttr_observed_minutes=75.0,
        has_pallet_changer=False,
        completed_ops_count=4,
    )

    fleet_kpi = FleetKPIs(
        scenario_name="unit_test_rules",
        horizon_hours=10.0,
        fleet_size=2,
        mean_spindle_utilization_pct=15.0,
        mean_setup_pct=5.0,
        mean_idle_pct=55.0,
        mean_breakdown_pct=25.0,
        mean_oee_pct=15.0,
        total_jobs=10,
        completed_jobs=5,
        wip_jobs=5,
        on_time_delivery_pct=50.0,
        mean_tardiness_minutes=20.0,
        max_tardiness_minutes=40.0,
        total_weighted_tardiness=100.0,
        makespan_minutes=600.0,
        machine_kpis={},
        idle_time_by_cause={},
    )

    facts = ShopFloorFacts(
        scenario_name="unit_test_rules",
        horizon_hours=10.0,
        fleet_kpis=fleet_kpi,
        machine_facts={"VMC-01": m_facts_starved, "VMC-02": m_facts_breakdown},
        window_facts=[],
        tool_wait_minutes={},
        operator_wait_minutes={},
    )

    # 1. Test IdleStarvationRule
    r_starve = IdleStarvationRule()
    findings_starve = r_starve.evaluate(facts, thresholds)
    assert len(findings_starve) == 1
    assert findings_starve[0].target_entity == "VMC-01"
    assert findings_starve[0].severity == RuleSeverity.CRITICAL

    # 2. Test BreakdownDominatedRule
    r_bd = BreakdownDominatedRule()
    findings_bd = r_bd.evaluate(facts, thresholds)
    assert len(findings_bd) == 1
    assert findings_bd[0].target_entity == "VMC-02"
    assert findings_bd[0].severity == RuleSeverity.CRITICAL

    # 3. Test WaitingSetupRule
    r_setup = WaitingSetupRule()
    assert len(r_setup.evaluate(facts, thresholds)) == 0


def test_conflict_resolution_and_trace() -> None:
    engine = create_default_rule_engine()
    assert len(engine.rules) == 8

    # Create dummy finding trace
    finding = DiagnosticFinding(
        rule_id="R_IDLE_STARVATION",
        rule_name="Spindle Starvation",
        severity=RuleSeverity.CRITICAL,
        target_entity="VMC-01",
        confidence=0.95,
        matched_facts={"idle_pct": 80.0},
        root_cause_narrative="Starved upstream",
        actionable_remediation="Increase order release",
    )
    trace = ExplanationTrace(
        scenario_name="trace_demo",
        findings=[finding],
        suppressed_findings=[],
    )

    assert trace.critical_count == 1
    assert trace.warning_count == 0
    assert trace.info_count == 0

    md = trace.to_markdown()
    assert "# Expert Diagnostic Report: trace_demo" in md
    assert "[CRITICAL] Spindle Starvation (VMC-01)" in md
    assert "Increase order release" in md

    d = finding.to_dict()
    assert d["rule_id"] == "R_IDLE_STARVATION"
    assert d["confidence"] == 0.95
