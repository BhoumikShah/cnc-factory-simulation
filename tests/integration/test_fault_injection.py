from __future__ import annotations

from pathlib import Path

from vmc_twin.report.kpis import KPICalculator
from vmc_twin.rules.engine import RuleSeverity
from vmc_twin.rules.facts import FactExtractor
from vmc_twin.rules.library import create_default_rule_engine
from vmc_twin.sim.engine import SimulationEngine


def test_tool_shortage_fault_injection() -> None:
    scenario_path = Path("configs/scenarios/tool_shortage.yaml")
    engine = SimulationEngine.from_scenario_file(scenario_path)
    result = engine.run()

    kpis = KPICalculator.calculate(
        scenario_name=result.scenario_name,
        horizon_minutes=result.duration_minutes,
        events=result.events,
        jobs=engine.jobs,
    )

    facts = FactExtractor.extract(
        kpis=kpis,
        events=result.events,
        window_minutes=engine.scenario.diagnosis.window_duration_minutes,
    )

    rule_engine = create_default_rule_engine()
    trace = rule_engine.diagnose(facts, thresholds=engine.scenario.diagnosis)

    # Validate that WAITING_TOOL was caught
    tool_findings = [f for f in trace.findings if f.rule_id == "R_WAITING_TOOL"]
    assert len(tool_findings) >= 1
    assert any(f.severity == RuleSeverity.CRITICAL for f in tool_findings)


def test_unreliable_machine_fault_injection() -> None:
    scenario_path = Path("configs/scenarios/unreliable_machine.yaml")
    engine = SimulationEngine.from_scenario_file(scenario_path)
    result = engine.run()

    kpis = KPICalculator.calculate(
        scenario_name=result.scenario_name,
        horizon_minutes=result.duration_minutes,
        events=result.events,
        jobs=engine.jobs,
    )

    facts = FactExtractor.extract(
        kpis=kpis,
        events=result.events,
        window_minutes=engine.scenario.diagnosis.window_duration_minutes,
    )

    rule_engine = create_default_rule_engine()
    trace = rule_engine.diagnose(facts, thresholds=engine.scenario.diagnosis)

    # Validate that BREAKDOWN_DOMINATED was diagnosed
    bd_findings = [f for f in trace.findings if f.rule_id == "R_BREAKDOWN_DOMINATED"]
    assert len(bd_findings) >= 1
    assert any(f.severity == RuleSeverity.CRITICAL for f in bd_findings)


def test_operator_bottleneck_fault_injection() -> None:
    scenario_path = Path("configs/scenarios/operator_bottleneck.yaml")
    engine = SimulationEngine.from_scenario_file(scenario_path)
    result = engine.run()

    kpis = KPICalculator.calculate(
        scenario_name=result.scenario_name,
        horizon_minutes=result.duration_minutes,
        events=result.events,
        jobs=engine.jobs,
    )

    facts = FactExtractor.extract(
        kpis=kpis,
        events=result.events,
        window_minutes=engine.scenario.diagnosis.window_duration_minutes,
    )

    rule_engine = create_default_rule_engine()
    trace = rule_engine.diagnose(facts, thresholds=engine.scenario.diagnosis)

    assert len(trace.findings) > 0
    assert trace.scenario_name == "operator_bottleneck"
