from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from vmc_twin.config.schemas import DiagnosisThresholdsConfig
from vmc_twin.rules.facts import ShopFloorFacts


class RuleSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class DiagnosticFinding:
    """A structured finding emitted when an expert diagnostic rule matches facts."""

    rule_id: str
    rule_name: str
    severity: RuleSeverity
    target_entity: str
    confidence: float
    matched_facts: dict[str, Any]
    root_cause_narrative: str
    actionable_remediation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "severity": self.severity.value,
            "target_entity": self.target_entity,
            "confidence": round(self.confidence, 3),
            "matched_facts": self.matched_facts,
            "root_cause_narrative": self.root_cause_narrative,
            "actionable_remediation": self.actionable_remediation,
        }


@dataclass
class ExplanationTrace:
    """Complete diagnostic explanation trace containing active and suppressed findings."""

    scenario_name: str
    findings: list[DiagnosticFinding] = field(default_factory=list)
    suppressed_findings: list[DiagnosticFinding] = field(default_factory=list)

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == RuleSeverity.CRITICAL)

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == RuleSeverity.WARNING)

    @property
    def info_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == RuleSeverity.INFO)

    def to_markdown(self) -> str:
        """Renders a clean, formatted Markdown explanation report."""
        lines = [
            f"# Expert Diagnostic Report: {self.scenario_name}",
            f"**Summary**: {self.critical_count} Critical, {self.warning_count} Warnings, {self.info_count} Info",
            "",
            "## Active Diagnostic Findings",
            "",
        ]

        if not self.findings:
            lines.append(
                " No operational anomalies or bottlenecks detected. System operating within nominal parameters."
            )
            return "\n".join(lines)

        for i, f in enumerate(self.findings, start=1):
            sev_tag = f"[{f.severity.value}]"
            lines.append(f"### {i}. {sev_tag} {f.rule_name} ({f.target_entity})")
            lines.append(f"- **Rule ID**: `{f.rule_id}` (Confidence: {f.confidence * 100:.1f}%)")
            lines.append(f"- **Root Cause**: {f.root_cause_narrative}")
            lines.append(f"- **Actionable Remediation**: {f.actionable_remediation}")
            lines.append("- **Matched Metrics**:")
            for k, v in f.matched_facts.items():
                lines.append(f"  - `{k}`: {v}")
            lines.append("")

        if self.suppressed_findings:
            lines.append("## Suppressed / Subsumed Findings")
            for sf in self.suppressed_findings:
                lines.append(
                    f"- *[{sf.severity.value}] {sf.rule_name} on {sf.target_entity} (Subsumed by higher-priority root cause)*"
                )
            lines.append("")

        return "\n".join(lines)


class Rule(ABC):
    """Abstract base class for diagnostic rules."""

    def __init__(self, rule_id: str, name: str, priority: int, severity: RuleSeverity) -> None:
        self.rule_id = rule_id
        self.name = name
        self.priority = priority
        self.severity = severity

    @abstractmethod
    def evaluate(
        self,
        facts: ShopFloorFacts,
        thresholds: DiagnosisThresholdsConfig,
    ) -> list[DiagnosticFinding]:
        """Evaluates facts against the rule conditions and returns findings."""


class RuleEngine:
    """Forward-chaining, explainable expert system rule engine."""

    def __init__(self, rules: Sequence[Rule] | None = None) -> None:
        self._rules: list[Rule] = list(rules) if rules else []

    def register(self, rule: Rule) -> None:
        """Registers a rule in the engine."""
        self._rules.append(rule)

    @property
    def rules(self) -> Sequence[Rule]:
        return list(self._rules)

    def diagnose(
        self,
        facts: ShopFloorFacts,
        thresholds: DiagnosisThresholdsConfig | None = None,
    ) -> ExplanationTrace:
        """Executes rules, applies conflict resolution/suppression, and produces an ExplanationTrace."""
        active_thresholds = thresholds or DiagnosisThresholdsConfig()

        # Sort rules by priority descending
        sorted_rules = sorted(self._rules, key=lambda r: r.priority, reverse=True)

        raw_findings: list[DiagnosticFinding] = []
        for rule in sorted_rules:
            findings = rule.evaluate(facts, active_thresholds)
            raw_findings.extend(findings)

        # Conflict resolution and suppression
        active_findings, suppressed = self._resolve_conflicts(raw_findings, facts)

        return ExplanationTrace(
            scenario_name=facts.scenario_name,
            findings=active_findings,
            suppressed_findings=suppressed,
        )

    def _resolve_conflicts(
        self,
        raw_findings: list[DiagnosticFinding],
        facts: ShopFloorFacts,
    ) -> tuple[list[DiagnosticFinding], list[DiagnosticFinding]]:
        """Applies domain suppression and deduplication heuristics."""
        active: list[DiagnosticFinding] = []
        suppressed: list[DiagnosticFinding] = []

        # Check if fleet-wide breakdown dominated exists
        critical_bd_machines = {
            f.target_entity
            for f in raw_findings
            if f.rule_id == "R_BREAKDOWN_DOMINATED" and f.severity == RuleSeverity.CRITICAL
        }

        # Check if setup waste is diagnosed
        setup_waste_machines = {
            f.target_entity for f in raw_findings if f.rule_id == "R_SETUP_WASTE"
        }

        for f in raw_findings:
            # If machine is in critical breakdown, suppress mild starvation or wait warnings on the same machine
            if f.target_entity in critical_bd_machines and f.rule_id in (
                "R_IDLE_STARVATION",
                "R_WAITING_OPERATOR",
            ):
                suppressed.append(f)
                continue

            # If machine has severe setup waste, WAITING_SETUP is secondary to SETUP_WASTE
            if (
                f.target_entity in setup_waste_machines
                and f.rule_id == "R_WAITING_SETUP"
                and f.severity != RuleSeverity.CRITICAL
            ):
                suppressed.append(f)
                continue

            active.append(f)

        # Sort active findings: CRITICAL first, then WARNING, then INFO
        severity_order = {
            RuleSeverity.CRITICAL: 0,
            RuleSeverity.WARNING: 1,
            RuleSeverity.INFO: 2,
        }
        active.sort(key=lambda x: (severity_order[x.severity], -x.confidence))

        return active, suppressed
