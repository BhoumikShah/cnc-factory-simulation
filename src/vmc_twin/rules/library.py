from __future__ import annotations

from vmc_twin.config.schemas import DiagnosisThresholdsConfig
from vmc_twin.rules.engine import DiagnosticFinding, Rule, RuleEngine, RuleSeverity
from vmc_twin.rules.facts import ShopFloorFacts


class IdleStarvationRule(Rule):
    """Diagnoses spindle starvation caused by upstream job release or routing deficits."""

    def __init__(self) -> None:
        super().__init__(
            rule_id="R_IDLE_STARVATION",
            name="Spindle Starvation (No Queued Jobs)",
            priority=50,
            severity=RuleSeverity.WARNING,
        )

    def evaluate(
        self,
        facts: ShopFloorFacts,
        thresholds: DiagnosisThresholdsConfig,
    ) -> list[DiagnosticFinding]:
        findings: list[DiagnosticFinding] = []
        for m_id, m in facts.machine_facts.items():
            if m.idle_starve_pct >= thresholds.starvation_idle_pct:
                sev = (
                    RuleSeverity.CRITICAL
                    if m.idle_starve_pct >= thresholds.starvation_idle_pct * 1.5
                    else RuleSeverity.WARNING
                )
                findings.append(
                    DiagnosticFinding(
                        rule_id=self.rule_id,
                        rule_name=self.name,
                        severity=sev,
                        target_entity=m_id,
                        confidence=min(1.0, m.idle_starve_pct / 50.0),
                        matched_facts={
                            "idle_starve_pct": f"{m.idle_starve_pct:.1f}%",
                            "threshold_pct": f"{thresholds.starvation_idle_pct:.1f}%",
                            "total_cutting_minutes": f"{m.total_cutting_minutes:.1f}m",
                        },
                        root_cause_narrative=(
                            f"Machine {m_id} spent {m.idle_starve_pct:.1f}% of planned horizon idle "
                            f"due to job starvation with an empty inbound queue."
                        ),
                        actionable_remediation=(
                            "Increase upstream job release rate, balance dispatching across alternative "
                            "spindles, or investigate upstream machining stage bottlenecks."
                        ),
                    )
                )
        return findings


class WaitingSetupRule(Rule):
    """Diagnoses excessive spindle downtime waiting for setup crew or fixture availability."""

    def __init__(self) -> None:
        super().__init__(
            rule_id="R_WAITING_SETUP",
            name="Setup & Fixture Contention Delay",
            priority=70,
            severity=RuleSeverity.WARNING,
        )

    def evaluate(
        self,
        facts: ShopFloorFacts,
        thresholds: DiagnosisThresholdsConfig,
    ) -> list[DiagnosticFinding]:
        findings: list[DiagnosticFinding] = []
        for m_id, m in facts.machine_facts.items():
            total_setup_wait = m.idle_wait_setup_pct + m.idle_wait_fixture_pct
            if (
                m.idle_wait_setup_pct >= thresholds.setup_wait_idle_pct
                or m.idle_wait_fixture_pct >= thresholds.fixture_wait_idle_pct
            ):
                findings.append(
                    DiagnosticFinding(
                        rule_id=self.rule_id,
                        rule_name=self.name,
                        severity=RuleSeverity.WARNING,
                        target_entity=m_id,
                        confidence=min(1.0, total_setup_wait / 30.0),
                        matched_facts={
                            "idle_wait_setup_pct": f"{m.idle_wait_setup_pct:.1f}%",
                            "idle_wait_fixture_pct": f"{m.idle_wait_fixture_pct:.1f}%",
                            "threshold_pct": f"{thresholds.setup_wait_idle_pct:.1f}%",
                        },
                        root_cause_narrative=(
                            f"Machine {m_id} lost {total_setup_wait:.1f}% of planned time waiting "
                            f"for setup operators or fixture hardware to become available."
                        ),
                        actionable_remediation=(
                            "Assign dedicated setup technician to shift, cross-train Level 2/3 operators, "
                            "or procure additional duplicate fixture plates."
                        ),
                    )
                )
        return findings


class WaitingToolRule(Rule):
    """Diagnoses spindle idle waiting due to tool crib stockouts or reload delays."""

    def __init__(self) -> None:
        super().__init__(
            rule_id="R_WAITING_TOOL",
            name="Tool Crib Stockout Delay",
            priority=80,
            severity=RuleSeverity.CRITICAL,
        )

    def evaluate(
        self,
        facts: ShopFloorFacts,
        thresholds: DiagnosisThresholdsConfig,
    ) -> list[DiagnosticFinding]:
        findings: list[DiagnosticFinding] = []
        for m_id, m in facts.machine_facts.items():
            if m.idle_wait_tool_pct >= thresholds.tool_wait_idle_pct:
                findings.append(
                    DiagnosticFinding(
                        rule_id=self.rule_id,
                        rule_name=self.name,
                        severity=RuleSeverity.CRITICAL,
                        target_entity=m_id,
                        confidence=min(1.0, m.idle_wait_tool_pct / 20.0),
                        matched_facts={
                            "idle_wait_tool_pct": f"{m.idle_wait_tool_pct:.1f}%",
                            "threshold_pct": f"{thresholds.tool_wait_idle_pct:.1f}%",
                            "tool_wait_minutes": facts.tool_wait_minutes,
                        },
                        root_cause_narrative=(
                            f"Machine {m_id} experienced {m.idle_wait_tool_pct:.1f}% idle downtime "
                            f"waiting for cutting tool replacement from the tool crib."
                        ),
                        actionable_remediation=(
                            "Increase tool crib safety stock copies for frequently depleted tools, "
                            "reduce vendor replenishment lead time, or pre-stage sister tools in magazine."
                        ),
                    )
                )
        return findings


class WaitingOperatorRule(Rule):
    """Diagnoses spindle idle waiting for part load/unload operator."""

    def __init__(self) -> None:
        super().__init__(
            rule_id="R_WAITING_OPERATOR",
            name="Operator Pool Starvation (Load/Unload)",
            priority=60,
            severity=RuleSeverity.WARNING,
        )

    def evaluate(
        self,
        facts: ShopFloorFacts,
        thresholds: DiagnosisThresholdsConfig,
    ) -> list[DiagnosticFinding]:
        findings: list[DiagnosticFinding] = []
        for m_id, m in facts.machine_facts.items():
            if m.idle_wait_operator_pct >= thresholds.operator_wait_idle_pct:
                findings.append(
                    DiagnosticFinding(
                        rule_id=self.rule_id,
                        rule_name=self.name,
                        severity=RuleSeverity.WARNING,
                        target_entity=m_id,
                        confidence=min(1.0, m.idle_wait_operator_pct / 25.0),
                        matched_facts={
                            "idle_wait_operator_pct": f"{m.idle_wait_operator_pct:.1f}%",
                            "threshold_pct": f"{thresholds.operator_wait_idle_pct:.1f}%",
                        },
                        root_cause_narrative=(
                            f"Machine {m_id} completed machining cycles but was blocked for "
                            f"{m.idle_wait_operator_pct:.1f}% of horizon waiting for an operator to unload/load parts."
                        ),
                        actionable_remediation=(
                            "Increase operator staffing per shift, optimize operator routing zones, "
                            "or install automated pallet changers (APC) for offline loading."
                        ),
                    )
                )
        return findings


class BreakdownDominatedRule(Rule):
    """Diagnoses severe spindle unreliability and MTBF/MTTR degradation."""

    def __init__(self) -> None:
        super().__init__(
            rule_id="R_BREAKDOWN_DOMINATED",
            name="Excessive Machine Breakdown / Reliability Degradation",
            priority=95,
            severity=RuleSeverity.CRITICAL,
        )

    def evaluate(
        self,
        facts: ShopFloorFacts,
        thresholds: DiagnosisThresholdsConfig,
    ) -> list[DiagnosticFinding]:
        findings: list[DiagnosticFinding] = []
        for m_id, m in facts.machine_facts.items():
            is_breakdown_high = m.breakdown_pct >= thresholds.breakdown_pct
            is_mtbf_low = (
                m.breakdown_count > 1 and m.mtbf_observed_hours < thresholds.mtbf_critical_hours
            )

            if is_breakdown_high or is_mtbf_low:
                findings.append(
                    DiagnosticFinding(
                        rule_id=self.rule_id,
                        rule_name=self.name,
                        severity=RuleSeverity.CRITICAL,
                        target_entity=m_id,
                        confidence=min(1.0, max(m.breakdown_pct / 30.0, 0.85)),
                        matched_facts={
                            "breakdown_pct": f"{m.breakdown_pct:.1f}%",
                            "breakdown_count": m.breakdown_count,
                            "mtbf_observed_hours": f"{m.mtbf_observed_hours:.1f}h",
                            "mttr_observed_minutes": f"{m.mttr_observed_minutes:.1f}m",
                        },
                        root_cause_narrative=(
                            f"Machine {m_id} suffered {m.breakdown_count} unscheduled breakdowns "
                            f"totaling {m.breakdown_pct:.1f}% downtime (MTBF: {m.mtbf_observed_hours:.1f}h, MTTR: {m.mttr_observed_minutes:.1f}m)."
                        ),
                        actionable_remediation=(
                            "Execute comprehensive preventive maintenance overhaul, inspect spindle bearing "
                            "vibration, and ensure critical spare parts are on hand."
                        ),
                    )
                )
        return findings


class SetupWasteRule(Rule):
    """Diagnoses excessive setup time resulting from inefficient sequencing or lack of APC."""

    def __init__(self) -> None:
        super().__init__(
            rule_id="R_SETUP_WASTE",
            name="Excessive Setup & Changeover Waste",
            priority=75,
            severity=RuleSeverity.WARNING,
        )

    def evaluate(
        self,
        facts: ShopFloorFacts,
        thresholds: DiagnosisThresholdsConfig,
    ) -> list[DiagnosticFinding]:
        findings: list[DiagnosticFinding] = []
        for m_id, m in facts.machine_facts.items():
            if m.setup_pct >= thresholds.setup_waste_pct:
                sev = (
                    RuleSeverity.CRITICAL
                    if m.setup_pct >= thresholds.setup_waste_pct * 1.5
                    else RuleSeverity.WARNING
                )
                findings.append(
                    DiagnosticFinding(
                        rule_id=self.rule_id,
                        rule_name=self.name,
                        severity=sev,
                        target_entity=m_id,
                        confidence=min(1.0, m.setup_pct / 40.0),
                        matched_facts={
                            "setup_pct": f"{m.setup_pct:.1f}%",
                            "threshold_pct": f"{thresholds.setup_waste_pct:.1f}%",
                            "total_setup_minutes": f"{m.total_setup_minutes:.1f}m",
                        },
                        root_cause_narrative=(
                            f"Machine {m_id} consumed {m.setup_pct:.1f}% of total horizon performing "
                            f"fixture changeovers ({m.total_setup_minutes:.1f} minutes spent in setup)."
                        ),
                        actionable_remediation=(
                            "Group work orders into part family batches to minimize fixture transitions, "
                            "use CP-SAT optimization with sequence-dependent setup matrix, or retrofit APC."
                        ),
                    )
                )
        return findings


class BottleneckDetectionRule(Rule):
    """Detects the primary bottleneck machine governing shop floor throughput."""

    def __init__(self) -> None:
        super().__init__(
            rule_id="R_BOTTLENECK_DETECTION",
            name="Primary Shop Floor Spindle Bottleneck",
            priority=90,
            severity=RuleSeverity.CRITICAL,
        )

    def evaluate(
        self,
        facts: ShopFloorFacts,
        thresholds: DiagnosisThresholdsConfig,
    ) -> list[DiagnosticFinding]:
        findings: list[DiagnosticFinding] = []
        if not facts.machine_facts:
            return findings

        # Find machine with highest active load (cutting + setup)
        sorted_by_load = sorted(
            facts.machine_facts.items(),
            key=lambda item: item[1].utilization_pct + item[1].setup_pct,
            reverse=True,
        )
        top_id, top_m = sorted_by_load[0]
        top_load = top_m.utilization_pct + top_m.setup_pct

        mean_fleet_load = sum(
            m.utilization_pct + m.setup_pct for m in facts.machine_facts.values()
        ) / len(facts.machine_facts)

        if top_load >= thresholds.bottleneck_utilization_pct and (
            top_load >= mean_fleet_load * 1.2 or top_load >= 80.0
        ):
            findings.append(
                DiagnosticFinding(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=RuleSeverity.CRITICAL,
                    target_entity=top_id,
                    confidence=min(1.0, top_load / 100.0),
                    matched_facts={
                        "machine_load_pct": f"{top_load:.1f}%",
                        "cutting_pct": f"{top_m.utilization_pct:.1f}%",
                        "setup_pct": f"{top_m.setup_pct:.1f}%",
                        "fleet_mean_load_pct": f"{mean_fleet_load:.1f}%",
                    },
                    root_cause_narrative=(
                        f"Machine {top_id} is the primary factory bottleneck with {top_load:.1f}% "
                        f"active load ({top_m.utilization_pct:.1f}% cutting + {top_m.setup_pct:.1f}% setup), "
                        f"significantly exceeding the fleet average of {mean_fleet_load:.1f}%."
                    ),
                    actionable_remediation=(
                        f"Offload compatible operations from {top_id} to secondary spindles, "
                        "schedule overtime shifts on this machine, or prioritize tooling upgrades to shorten cycle times."
                    ),
                )
            )
        return findings


class ShiftingBottleneckRule(Rule):
    """Detects whether the plant bottleneck dynamically shifts across time windows."""

    def __init__(self) -> None:
        super().__init__(
            rule_id="R_SHIFTING_BOTTLENECK",
            name="Dynamic Shifting Bottleneck Phenomenon",
            priority=85,
            severity=RuleSeverity.WARNING,
        )

    def evaluate(
        self,
        facts: ShopFloorFacts,
        thresholds: DiagnosisThresholdsConfig,
    ) -> list[DiagnosticFinding]:
        findings: list[DiagnosticFinding] = []
        if len(facts.window_facts) < 4:
            return findings

        # Track bottleneck sequence across consecutive windows
        bottlenecks = [
            w.bottleneck_machine_id for w in facts.window_facts if w.bottleneck_machine_id
        ]
        if not bottlenecks:
            return findings

        distinct_bottlenecks = set(bottlenecks)
        # Count transitions where bottleneck changed from previous window
        transitions = sum(
            1 for i in range(1, len(bottlenecks)) if bottlenecks[i] != bottlenecks[i - 1]
        )

        shift_rate = transitions / (len(bottlenecks) - 1) if len(bottlenecks) > 1 else 0.0

        if len(distinct_bottlenecks) >= 3 and shift_rate >= 0.40:
            findings.append(
                DiagnosticFinding(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=RuleSeverity.WARNING,
                    target_entity="FLEET",
                    confidence=min(1.0, shift_rate),
                    matched_facts={
                        "distinct_bottleneck_machines": list(distinct_bottlenecks),
                        "bottleneck_transitions": transitions,
                        "shift_rate_pct": f"{shift_rate * 100:.1f}%",
                        "total_windows_evaluated": len(facts.window_facts),
                    },
                    root_cause_narrative=(
                        f"The primary bottleneck shifts dynamically across {len(distinct_bottlenecks)} machines "
                        f"({', '.join(sorted(distinct_bottlenecks))}) with a transition rate of {shift_rate * 100:.1f}%."
                    ),
                    actionable_remediation=(
                        "Static dispatching rules (FIFO) underperform when bottlenecks shift; switch to dynamic "
                        "look-ahead dispatching (ATC or CP-SAT) and maintain flexible operator cross-training."
                    ),
                )
            )
        return findings


def create_default_rule_engine() -> RuleEngine:
    """Instantiates and registers the complete standard diagnostic rule suite."""
    engine = RuleEngine()
    engine.register(IdleStarvationRule())
    engine.register(WaitingSetupRule())
    engine.register(WaitingToolRule())
    engine.register(WaitingOperatorRule())
    engine.register(BreakdownDominatedRule())
    engine.register(SetupWasteRule())
    engine.register(BottleneckDetectionRule())
    engine.register(ShiftingBottleneckRule())
    return engine
