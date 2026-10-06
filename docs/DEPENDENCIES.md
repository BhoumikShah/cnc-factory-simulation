# Software Dependencies & Licensing Audit

All dependencies are strictly open-source (OSI-approved), free from proprietary or commercial solver licenses, and require zero cloud accounts or API keys.

## Direct Dependencies

| Package | Pinned Version | License | Category | Capability Enabled & ADR Summary |
| :--- | :--- | :--- | :--- | :--- |
| **simpy** | `4.1.2` | MIT | Core Simulation | Discrete-event simulation kernel with generator-based processes. |
| **pydantic** | `2.13.5` | MIT | Config & Schema | High-speed type checking and YAML validation with custom validators. |
| **pyyaml** | `6.0.3` | MIT | Serialization | Human-readable configuration for shop assets and simulation scenarios. |
| **polars** | `0.20.31` | MIT | Data Processing | Vectorized, multithreaded columnar dataframes for high-volume event logs. |
| **pandas** | `3.0.2` | BSD-3-Clause | Data Processing | Ecosystem bridge for visualization and statistical analysis. |
| **duckdb** | `1.0.0` | MIT | Persistence / OLAP | In-process columnar SQL database for sub-millisecond event queries. |
| **ortools** | `9.10.4067` | Apache-2.0 | Optimization | Industrial-grade CP-SAT constraint programming solver. |
| **pymoo** | `0.6.1` | Apache-2.0 | Optimization | Multi-objective genetic algorithms (NSGA-II) for Pareto frontier search. |
| **scikit-learn**| `1.8.0` | BSD-3-Clause | Machine Learning | Regression and predictive modeling baselines. |
| **scipy** | `1.17.1` | BSD-3-Clause | Scientific | Statistical distributions (Weibull MLE, lognormal parameter fitting). |
| **plotly** | `6.6.0` | MIT | Visualization | Standalone interactive HTML charts (Gantt, Pareto, utilization). |
| **typer** | `0.24.1` | MIT | CLI Interface | Type-hinted command-line parsing and terminal workflow execution. |
| **rich** | `13.7.1` | MIT | Terminal Formatting | ANSI styled tables, progress meters, and structured logs. |
| **structlog** | `24.4.0` | MIT / Apache-2.0 | Logging | Structured contextual logging with JSON/terminal formatting. |

## Development & Testing Dependencies

| Package | Pinned Version | License | Category | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| **pytest** | `8.2.2` | MIT | Testing | Test framework, fixture injection, and assertions. |
| **pytest-cov** | `5.0.0` | MIT | Testing | Code coverage instrumentation and enforcement. |
| **hypothesis** | `6.103.1` | MPL-2.0 | Testing | Property-based testing for simulation temporal invariants. |
| **ruff** | `0.5.0` | MIT / Apache-2.0 | Quality | Lightning-fast static analysis and code formatting. |
| **mypy** | `1.10.1` | MIT | Quality | Static type checking with `--strict` mode. |
| **pip-licenses**| `4.4.0` | MIT | Compliance | Automated verification of OSI licenses in CI pipeline. |
| **streamlit** | `1.55.0` | Apache-2.0 | UI / Dashboard | Optional local interactive browser dashboard. |

## License Allowlist Policy
- **Permitted Licenses**: `MIT`, `BSD-2-Clause`, `BSD-3-Clause`, `Apache-2.0`, `MPL-2.0`, `ISC`, `PSF`, `HPND`, `LGPL-2.1` (dynamic linking only).
- **Prohibited Licenses**: `GPL-3.0`, `AGPL-3.0`, `SSPL`, proprietary commercial licenses.
- **Verification Command**:
  ```bash
  pip-licenses --fail-on "GPL;AGPL;Commercial"
  ```
