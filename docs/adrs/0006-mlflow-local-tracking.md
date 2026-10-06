# ADR 0006: Local File-Based Experiment Tracking via MLflow

## Status
Accepted

## Context
Benchmarking scheduling policies, comparing scenarios (e.g., baseline vs. capacity expansion vs. tool shortages), and logging model metrics require structured experiment tracking without relying on paid or cloud-hosted SaaS tools (e.g., Weights & Biases, Neptune).

## Decision
We utilize MLflow configured strictly with local filesystem storage (`file:///./mlruns`):
1. Runs, configuration YAMLs, KPI metrics, and HTML report artifacts are logged locally.
2. Zero external server or network connectivity is required.

## Consequences
- **Positive**: Standardized metadata, parameter, and artifact tracking without third-party accounts or telemetry.
- **Positive**: Offline analysis and comparison between multiple runs.
- **Trade-off**: Requires local disk storage for artifact persistence.
