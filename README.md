# CNC VMC Shop Floor Digital Twin

A production-quality, open-source industrial simulation, prognostic, diagnostic, and optimization digital twin for fleets of Vertical Machining Centers (VMCs).

Built in pure Python 3.12 following a strictly decoupled **Hexagonal (Ports-and-Adapters)** architecture.

---

## 🌟 Key Features

- **Discrete-Event Simulation (SimPy)**: State machine accurately tracking `CUTTING`, `SETUP`, `TOOL_CHANGE`, `IDLE_STARVED`, `IDLE_WAIT_SETUP`, `IDLE_WAIT_TOOL`, `IDLE_WAIT_OPERATOR`, `BREAKDOWN`, and `OFF_SHIFT`.
- **Reproducible Determinism**: Named hierarchical RNG streams guarantee identical event logs across executions.
- **Sequence-Dependent Setups**: Multi-variable transition modeling considering fixture types, part families, operator skill levels, and Automatic Pallet Changers (APC).
- **Tool Wear & Crib Reliability**: Flank wear tracking using 2-parameter Weibull failure physics and crib stock management.
- **Explainable Expert Diagnostics**: Forward-chaining rule engine generating structured `ExplanationTrace` findings with quantitative metrics and actionable remediation steps.
- **Mathematical Optimization (OR-Tools CP-SAT)**: Finite-capacity job scheduling with sequence-dependent setup matrices and objective-term breakdowns.
- **Prognostics**: Weibull MLE, Lifelines survival regression, and conformal risk intervals for premature tool failure prevention.
- **100% Offline & Open-Source**: Permissive OSI licenses (`MIT`, `BSD`, `Apache-2.0`), zero paid API keys or cloud dependencies.

---

## 🚀 Quickstart

### 1. Installation
```bash
# Clone the repository
git clone https://github.com/example/vmc-twin.git
cd vmc-twin

# Sync dependencies with uv or pip
uv sync
# or
pip install -e .
```

### 2. Running Simulations
```bash
# Run isolated single-machine foundation demo
python -m vmc_twin.cli run-single configs/scenarios/baseline.yaml --machine VMC-01

# Run full 10-machine fleet simulation with SQLite persistence
python -m vmc_twin.cli run configs/scenarios/baseline.yaml --db outputs/events.db
```

### 3. Running Test Suite
```bash
# Run all unit, architecture, integration, and property tests
pytest --cov=src/vmc_twin tests/
```

---

## 🏛 Architecture

```text
src/vmc_twin/
├── domain/       # Pure domain models (zero external dependencies)
├── sim/          # Discrete-event simulation kernel & machine state processes
├── rules/        # Explainable forward-chaining expert system & rule library
├── optimize/     # CP-SAT finite capacity scheduler & dispatch heuristics
├── predict/      # Tool life reliability & cycle-time prognostics
├── report/       # KPI calculation, Plotly HTML visualizer & MLflow tracking
├── config/       # Pydantic v2 schemas and YAML loaders
├── data/         # Synthetic data generator & persistence store
└── cli.py        # Typer CLI application
```

---

## 📜 Licensing
All dependencies are audited and strictly adhere to OSI-approved permissive licenses (MIT, BSD, Apache-2.0). See [docs/LICENSES.md](docs/LICENSES.md) and [docs/DEPENDENCIES.md](docs/DEPENDENCIES.md) for details.
