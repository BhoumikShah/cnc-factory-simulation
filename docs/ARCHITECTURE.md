# System Architecture: CNC VMC Shop Floor Digital Twin

## 1. Architectural Style: Hexagonal (Ports & Adapters)

The CNC VMC Shop Floor Digital Twin is designed around a strictly decoupled **Hexagonal Architecture** with four distinct layers:

```mermaid
graph TD
    subgraph Layer 1: Pure Domain
        D1[Entities: Machine, Job, Op, Tool, Fixture, Operator]
        D2[Enums: SpindleState, CauseCode]
        D3[Contract: Event]
    end

    subgraph Layer 2: Core Subsystems
        S1[sim: SimPy discrete-event engine]
        S2[rules: Explainable forward-chaining expert system]
        S3[optimize: CP-SAT & Dispatch heuristics]
        S4[predict: Weibull MLE & Tool wear models]
        S5[report: KPIs & Plotly HTML visualizer]
    end

    subgraph Layer 3: Infrastructure & Data
        I1[config: Pydantic v2 + PyYAML]
        I2[data: Synthetic Generator & DuckDB/SQLite/Parquet Store]
    end

    subgraph Layer 4: Application & CLI
        A1[cli: Typer CLI interface]
        A2[streamlit_app: Interactive browser dashboard]
    end

    D1 --> S1
    D1 --> S2
    D1 --> S3
    D1 --> S4
    D1 --> S5
    D3 --> S2
    D3 --> S5
    D3 --> I2
    I1 --> S1
    I1 --> S3
    A1 --> S1
    A1 --> S2
    A1 --> S3
    A1 --> S5
```

---

## 2. Layer Isolation Rules

1. **Pure Domain Core (`src/vmc_twin/domain/`)**:
   - Zero dependencies on third-party frameworks.
   - Contains dataclasses with slots, immutable value objects, and pure domain enums.
2. **Core Subsystems (`src/vmc_twin/{sim, rules, optimize, predict, report}/`)**:
   - Depend **only** on `domain`.
   - Never import directly from sibling core subsystems (e.g., `rules` never imports `sim`; `optimize` never imports `rules`).
   - Sibling communication is achieved through domain value objects and the immutable `Event` log.
3. **Infrastructure (`src/vmc_twin/{config, data}/`)**:
   - Handles external I/O, file reading, validation, and database queries.
4. **Application (`src/vmc_twin/{cli.py, streamlit_app}/`)**:
   - Composition root wiring adapters to ports.

---

## 3. Event-Driven Lifecycle & State Transitions

A VMC machine process traverses discrete states driven by resource availability and schedule requirements:

```mermaid
stateDiagram-v2
    [*] --> OFF_SHIFT: Off-shift calendar
    OFF_SHIFT --> IDLE_STARVED: Shift start, queue empty
    OFF_SHIFT --> IDLE_WAIT_SETUP: Shift start, job available

    IDLE_STARVED --> IDLE_WAIT_SETUP: Job arrives in queue
    
    IDLE_WAIT_SETUP --> SETUP: Operator + Fixture acquired
    SETUP --> IDLE_WAIT_TOOL: Need tool from crib
    SETUP --> CUTTING: Tools verified in magazine

    IDLE_WAIT_TOOL --> TOOL_CHANGE: Crib tool acquired
    TOOL_CHANGE --> CUTTING: Spindle ready

    CUTTING --> CUTTING: Next op with same fixture/tools
    CUTTING --> IDLE_WAIT_SETUP: Next job needs different fixture
    CUTTING --> BREAKDOWN: Stochastic failure event
    CUTTING --> TOOL_CHANGE: Mid-job tool wear limit reached

    BREAKDOWN --> IDLE_WAIT_SETUP: Repair technician completes MTTR
    CUTTING --> OFF_SHIFT: Shift end
```

---

## 4. Key Architecture Decision Records (ADRs)

- **ADR-0001**: Hexagonal Architecture & Zero Circular Imports
- **ADR-0002**: Immutable Event Contract as Primary System Bus
- **ADR-0003**: OR-Tools CP-SAT as Primary Exact Finite-Capacity Scheduler
- **ADR-0004**: Custom Pure-Python Forward-Chaining Rule Engine
- **ADR-0005**: Polars & DuckDB as Local In-Process Analytical Engine
- **ADR-0006**: Local File-Based Experiment Tracking
