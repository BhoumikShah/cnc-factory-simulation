# ADR 0004: Lightweight Forward-Chaining Rule Engine for Explainable Diagnosis

## Status
Accepted

## Context
Shop floor managers need clear, explainable diagnoses for lost spindle time (starvation, tool shortages, breakdown clusters, setup churn). Unmaintained rule libraries (such as Experta/PyKnow) fail on modern Python 3.12, while heavy production engines add unnecessary dependencies.

## Decision
We implement a pure-Python forward-chaining rule engine behind the `RuleEngine` Protocol:
1. Rules evaluate a strongly-typed `FactBase` extracted from sliding event windows.
2. Every triggered rule produces a structured `ExplanationTrace` detailing the rule name, severity, exact quantitative facts, time window, machine/job IDs, and actionable remedy.
3. Automated test reports verify rule coverage and identify rule conflicts.

## Consequences
- **Positive**: 100% Python 3.12 compliant with zero external dependencies.
- **Positive**: Complete transparency—every diagnostic alert includes an exact mathematical audit trail.
- **Trade-off**: Custom forward-chaining matcher is optimized for domain facts rather than generic Rete-algorithm scale.
