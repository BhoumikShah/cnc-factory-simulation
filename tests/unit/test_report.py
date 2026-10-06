from __future__ import annotations

from pathlib import Path

from vmc_twin.data.generator import SyntheticDataGenerator
from vmc_twin.domain.events import CauseCode, Event
from vmc_twin.domain.states import SpindleState
from vmc_twin.optimize.pareto import PolicyBenchmarkResult
from vmc_twin.predict.tool_wear import ToolReplacementRecommender
from vmc_twin.report.dashboard import UnifiedDashboardGenerator
from vmc_twin.report.kpis import KPICalculator
from vmc_twin.rules.engine import DiagnosticFinding, ExplanationTrace, RuleSeverity


def test_unified_dashboard_generator(tmp_path: Path) -> None:
    # 1. Create synthetic KPIs and events
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
            t_end=60.0,
            machine_id="VMC-01",
            job_id="J002",
            op_id="OP2",
            state=SpindleState.SETUP,
            cause_code=CauseCode.NONE,
        ),
        Event(
            t_start=60.0,
            t_end=80.0,
            machine_id="VMC-01",
            job_id=None,
            op_id=None,
            state=SpindleState.BREAKDOWN,
            cause_code=CauseCode.SPINDLE_BEARING_FAULT,
        ),
    ]

    jobs = SyntheticDataGenerator(42).generate_jobs(count=2)

    kpis = KPICalculator.calculate(
        scenario_name="Test_Scenario",
        horizon_minutes=100.0,
        events=events,
        jobs=jobs,
    )

    # 2. Synthetic Diagnostic Trace
    diag = DiagnosticFinding(
        rule_id="BREAKDOWN_DOMINATED",
        rule_name="Breakdown Dominated",
        severity=RuleSeverity.CRITICAL,
        target_entity="VMC-01",
        confidence=1.0,
        matched_facts={"breakdown_pct": 20.0},
        root_cause_narrative="Spindle breakdown exceeded threshold",
        actionable_remediation="Inspect spindle bearings",
    )
    trace = ExplanationTrace(
        scenario_name="Test_Scenario",
        findings=[diag],
    )

    # 3. Synthetic Benchmarks
    benchmarks = [
        PolicyBenchmarkResult("FIFO", 42, 100.0, 75.0, 10.0, 20.0, 95.0, 2, 0.5),
        PolicyBenchmarkResult("CP-SAT", 42, 90.0, 80.0, 8.0, 0.0, 100.0, 2, 1.2),
    ]

    # 4. Synthetic Tool Assessments
    assessments = [
        ToolReplacementRecommender.evaluate_tool(
            tool_id="TL-FACE-01",
            tool_type="FACEMILL_50MM",
            accumulated_cut_minutes=100.0,
            nominal_life_minutes=180.0,
            weibull_shape=3.0,
            weibull_scale=195.0,
        )
    ]

    # 5. Generate Unified Dashboard
    out_file = tmp_path / "unified_report.html"
    res_path = UnifiedDashboardGenerator.generate_report(
        kpis=kpis,
        events=events,
        diagnostic_trace=trace,
        benchmarks=benchmarks,
        tool_assessments=assessments,
        output_path=out_file,
    )

    assert res_path.exists()
    content = res_path.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in content
    assert "CNC VMC Digital Twin" in content
    assert "BREAKDOWN_DOMINATED" in content
    assert "FACEMILL_50MM" in content
    assert "Spindle Utilization" in content
