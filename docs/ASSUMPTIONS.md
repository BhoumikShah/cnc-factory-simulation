# Simulation Assumptions & Modeling Constants

All physical, mechanical, operational, and mathematical assumptions are cataloged explicitly below to prevent magic numbers or hidden assumptions in application code.

---

## 1. Temporal & Computational Domain
- **Time Base**: Continuous floating-point minutes ($1.0 = 60.0 \text{ seconds}$).
- **Precision**: Clock comparisons utilize an epsilon of $\epsilon = 10^{-6}$ minutes.
- **Random Number Generation**: Every stochastic entity (machine, process, operator, crib) holds an independent, named `numpy.random.Generator` stream derived from a master scenario seed. Adding or removing machines does not alter the random realization of other machines.

---

## 2. Machining & Spindle Dynamics
- **Cutting Time Stochasticity**: Operation cutting times follow a log-normal distribution parameterized by $(\mu_{\text{cut}}, \sigma_{\text{cut}})$, where the coefficient of variation (CV) defaults to $0.05$ unless overridden in configuration.
- **Power & RPM Suitability**: An operation can only execute on a machine whose spindle rated power (kW) and maximum spindle speed (RPM) meet or exceed the operation's requirements.
- **Spindle State Mutex**: At any instant $t$, a spindle occupies exactly one `SpindleState` (e.g., cannot be both `CUTTING` and `TOOL_CHANGE` simultaneously).

---

## 3. Sequence-Dependent Setups & Tooling
- **Fixture Transition Time**:
  - $T_{\text{setup}}(F_i \to F_j) = 0$ if $F_i = F_j$ and job parameters match.
  - $T_{\text{setup}}(F_i \to F_j) = \text{BaseMatrix}[F_i][F_j] \times \text{PalletModifier} \times \text{OperatorSkillModifier}$.
- **Pallet / Automatic Pallet Changer (APC)**:
  - Machines with APC capability execute offline fixture mounting during cutting cycles; spindle transition setup penalty is reduced by $70\%$ ($\text{PalletModifier} = 0.3$).
  - Non-APC machines require spindle downtime for the entire physical teardown and clamping ($\text{PalletModifier} = 1.0$).
- **Operator Skill Modifier**:
  - Level 1 (Junior): $1.25\times$ setup duration.
  - Level 2 (Standard): $1.00\times$ setup duration.
  - Level 3 (Senior): $0.80\times$ setup duration.

---

## 4. Tool Wear & Crib Reliability
- **Wear Accumulation**: Cutting wear accrues in effective cut-minutes:
  $$\Delta W = \Delta t \times M_{\text{material}} \times F_{\text{feed\_speed}}$$
  where $M_{\text{material}}$ is the workpiece machinability factor (e.g., Titanium Gr5 = 2.5, Inconel 718 = 3.0, Aluminum 6061 = 0.4, 4140 Steel = 1.0).
- **Tool Life Distribution**: Tool degradation to catastrophic failure or excessive flank wear ($VB > 0.3\text{ mm}$) follows a 2-parameter Weibull distribution with shape parameter $\beta \in [2.5, 3.5]$ and scale parameter $\eta \in [60, 240]\text{ minutes}$.
- **Tool Change Duration**:
  - Auto-tool change (ATC from local magazine): $0.1\text{ minutes}$ ($6\text{ seconds}$).
  - Manual reload / replacement from tool crib: $3.0\text{ minutes}$ base $+$ crib transit time.

---

## 5. Machine Reliability (MTBF / MTTR)
- **Breakdown Arrival (MTBF)**: Time-between-failures follows an exponential or Weibull distribution based on spindle cutting hours.
- **Repair Duration (MTTR)**: Repair times follow a lognormal distribution with mean MTTR specified per machine class and requires 1 maintenance technician resource.

---

## 6. Shifts & Operational Calendars
- **Shift Structure**: Default 2-shift operation ($2 \times 8\text{ hr} = 16\text{ hr/day}$) or 3-shift 24/7.
- **Break Pauses**: Planned breaks (e.g., 30-min lunch, 15-min tea break) pause active non-automated operations, or allow automated APC cutting to continue unattended if configured.
