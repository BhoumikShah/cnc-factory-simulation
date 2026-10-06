# ADR 0003: OR-Tools CP-SAT and Pymoo for Shop Floor Optimization

## Status
Accepted

## Context
Job-shop and flexible-flow-shop scheduling on CNC VMCs involves finite machine capacity, operation precedence, release/due dates, and sequence-dependent setup times. We require exact mathematical scheduling and multi-objective Pareto analysis without commercial solvers (e.g. Gurobi, CPLEX).

## Decision
1. **Primary Exact Solver**: Google OR-Tools CP-SAT (Apache-2.0). Formulates operations as optional interval variables with sequence-dependent transition circuits.
2. **Multi-Objective Metaheuristic**: `pymoo` (Apache-2.0). Employs NSGA-II to map trade-offs between makespan, setup time, and tardiness.
3. **Dispatch Baselines**: FIFO, EDD, SPT, SLACK, and ATC heuristics provide instantaneous baseline schedules.

## Consequences
- **Positive**: 100% open-source with no license fees or cloud dependencies.
- **Positive**: CP-SAT solves realistic 10-machine 100-operation instances to provable optimality or tight bounds within seconds.
- **Trade-off**: Large combinatorial problem horizons (>500 operations) require time limits or rolling-horizon approximations.
