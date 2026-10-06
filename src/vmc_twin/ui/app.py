from __future__ import annotations

from pathlib import Path

import pandas as pd  # type: ignore[import-untyped]
import streamlit as st

from vmc_twin.config.loader import ConfigLoader
from vmc_twin.data.generator import SyntheticDataGenerator
from vmc_twin.domain.fixture import FixtureSpec, FixtureTransitionMatrix
from vmc_twin.domain.job import Job
from vmc_twin.domain.machine import MachineSpec
from vmc_twin.optimize.ai_scheduler import EnergyAwareAIScheduler
from vmc_twin.report.ie_dashboard import IEDashboardGenerator

st.set_page_config(
    page_title="AI CNC Shop Floor Scheduler & Energy Twin",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Styling
st.markdown(
    """
    <style>
    .main-header {
        font-size: 26px;
        font-weight: 800;
        color: #F8FAFC;
        margin-bottom: 2px;
    }
    .sub-header {
        font-size: 14px;
        color: #94A3B8;
        margin-bottom: 20px;
    }
    .metric-container {
        background-color: #1E293B;
        border-radius: 8px;
        padding: 14px 16px;
        border-left: 4px solid #10B981;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def load_base_fixtures() -> tuple[list[FixtureSpec], FixtureTransitionMatrix]:
    scenario = ConfigLoader.load_scenario("configs/scenarios/baseline.yaml")
    shop_dir = Path(scenario.shop_config_dir)
    return ConfigLoader.load_fixtures(shop_dir / "fixtures.yaml")


# --- SIDEBAR PARAMETERS ---
st.sidebar.title("🎛️ AI Scheduler Control Panel")
st.sidebar.markdown("Customize all production, machine, and energy constraints:")

# 1. Fleet Architecture
with st.sidebar.expander("🏭 1. Machine Fleet Configuration", expanded=True):
    n_std_3axis = st.slider("VMC 3-Axis Standard (VMC-01..)", min_value=1, max_value=12, value=5)
    n_heavy_3axis = st.slider("VMC 3-Axis Heavy Duty", min_value=1, max_value=8, value=3)
    n_5axis = st.slider("VMC 5-Axis High Speed", min_value=1, max_value=6, value=2)
    pallet_factor = st.slider("APC Pallet Setup Factor", min_value=0.1, max_value=1.0, value=0.3, step=0.05)

# 2. Energy & Power Caps
with st.sidebar.expander("⚡ 2. Energy & Peak Demand Limits", expanded=True):
    peak_power_cap_kw = st.slider(
        "Max Fleet Peak Power Limit (kW)",
        min_value=10.0,
        max_value=60.0,
        value=25.0,
        step=2.5,
        help="Simultaneous active electrical load cap across all machines",
    )
    electricity_tariff = st.number_input("Electricity Tariff ($/kWh)", min_value=0.01, max_value=1.0, value=0.16, step=0.01)
    carbon_intensity = st.number_input("Grid Carbon Factor (kg CO2/kWh)", min_value=0.05, max_value=1.5, value=0.42, step=0.02)

# 3. Production Work Orders & Deadlines
with st.sidebar.expander("📦 3. Production Orders & Material Mix", expanded=True):
    job_count = st.slider("Total Production Jobs", min_value=10, max_value=1000, value=200, step=10)
    horizon_days = st.slider("Target Horizon (Days)", min_value=1, max_value=60, value=30)
    horizon_minutes = float(horizon_days * 24 * 60)

    st.markdown("**Workpiece Material Mix (%)**")
    pct_al = st.slider("Aluminum 6061 (%)", 0, 100, 50)
    pct_steel = st.slider("Steel 4140 (%)", 0, 100, 30)
    pct_ti = st.slider("Titanium Gr5 (%)", 0, 100, 20)

    total_pct = pct_al + pct_steel + pct_ti
    if total_pct == 0:
        pct_al, pct_steel, pct_ti = 50, 30, 20
        total_pct = 100

    material_mix = {
        "Aluminum_6061": pct_al / total_pct,
        "Steel_4140": pct_steel / total_pct,
        "Titanium_Gr5": pct_ti / total_pct,
    }

# 4. Multi-Objective AI Weights
with st.sidebar.expander("🧠 4. AI Optimization Weights", expanded=False):
    w_tardiness = st.slider("Urgency & OTD Weight (w_tard)", 1.0, 30.0, 10.0, step=1.0)
    w_setup = st.slider("Setup Minimization Weight (w_setup)", 0.0, 10.0, 2.0, step=0.5)
    w_peak_power = st.slider("Peak Load Shaving Weight (w_peak)", 0.0, 15.0, 4.0, step=0.5)
    w_energy = st.slider("Energy Cost Weight (w_energy)", 0.0, 5.0, 1.0, step=0.5)
    transfer_time = st.slider("Part Transfer Buffer (min)", 0.0, 15.0, 2.0, step=0.5)
    random_seed = st.number_input("Random Seed", min_value=1, max_value=99999, value=42)

# --- HEADER ---
st.markdown("<div class='main-header'>🏭 Industrial Engineering AI Scheduler & Energy Twin</div>", unsafe_allow_html=True)
st.markdown(
    "<div class='sub-header'>Multi-Objective Production Optimizer • Real-World Time & Precedence Constraints • CNC Power Telemetry Model</div>",
    unsafe_allow_html=True,
)

# Build Dynamic Fleet
machines: list[MachineSpec] = []
idx = 1
for _ in range(n_std_3axis):
    machines.append(
        MachineSpec(
            machine_id=f"VMC-{idx:02d}",
            machine_type="VMC_3AXIS_STD",
            spindle_power_kw=15.0,
            max_spindle_rpm=10000.0,
            magazine_capacity=24,
            has_pallet_changer=True,
            mtbf_hours=350.0,
            mttr_minutes=90.0,
            hourly_rate_usd=75.0,
            pallet_setup_factor=pallet_factor,
        )
    )
    idx += 1

for _ in range(n_heavy_3axis):
    machines.append(
        MachineSpec(
            machine_id=f"VMC-{idx:02d}",
            machine_type="VMC_3AXIS_HEAVY",
            spindle_power_kw=22.0,
            max_spindle_rpm=8000.0,
            magazine_capacity=30,
            has_pallet_changer=True,
            mtbf_hours=320.0,
            mttr_minutes=120.0,
            hourly_rate_usd=95.0,
            pallet_setup_factor=pallet_factor,
        )
    )
    idx += 1

for _ in range(n_5axis):
    machines.append(
        MachineSpec(
            machine_id=f"VMC-{idx:02d}",
            machine_type="VMC_5AXIS_HIGH_SPEED",
            spindle_power_kw=30.0,
            max_spindle_rpm=18000.0,
            magazine_capacity=40,
            has_pallet_changer=True,
            mtbf_hours=280.0,
            mttr_minutes=150.0,
            hourly_rate_usd=135.0,
            pallet_setup_factor=pallet_factor,
        )
    )
    idx += 1

fixtures, transition_matrix = load_base_fixtures()

# Generate Jobs
gen = SyntheticDataGenerator(random_seed=int(random_seed))
jobs: list[Job] = gen.generate_jobs(
    count=int(job_count),
    horizon_minutes=horizon_minutes,
    workpiece_mix=material_mix,
)

col_btn, col_info = st.columns([1, 4])
with col_btn:
    run_btn = st.button("🚀 Run AI Optimizer", type="primary", use_container_width=True)

with col_info:
    st.info(
        f"**Active Configuration:** {len(jobs)} Work Orders | {len(machines)} VMCs ({n_std_3axis} Std, {n_heavy_3axis} Heavy, {n_5axis} 5-Axis) | Peak Cap: {peak_power_cap_kw:.1f} kW | Material: {material_mix['Aluminum_6061']*100:.0f}% Al, {material_mix['Steel_4140']*100:.0f}% Steel, {material_mix['Titanium_Gr5']*100:.0f}% Ti"
    )

if run_btn or "last_result" not in st.session_state:
    with st.spinner("AI Engine is solving multi-stage schedule, shaving electrical peaks, and optimizing OTD..."):
        ai_scheduler = EnergyAwareAIScheduler(
            machines=machines,
            fixtures=fixtures,
            transition_matrix=transition_matrix,
            peak_power_limit_kw=float(peak_power_cap_kw),
            w_tardiness=float(w_tardiness),
            w_setup=float(w_setup),
            w_peak_power=float(w_peak_power),
            w_energy=float(w_energy),
            transfer_time_minutes=float(transfer_time),
        )
        result = ai_scheduler.solve(jobs=jobs, scenario_name="User_Custom_Run")
        st.session_state["last_result"] = result

result = st.session_state["last_result"]

# --- EXECUTIVE KPI METRICS ---
m_col1, m_col2, m_col3, m_col4, m_col5, m_col6 = st.columns(6)

otd_color = "normal" if result.on_time_delivery_pct >= 95.0 else "inverse"
m_col1.metric("🎯 On-Time Delivery (OTD)", f"{result.on_time_delivery_pct:.1f}%", f"{result.completed_jobs} orders")
m_col2.metric("⚡ Total Energy (kWh)", f"{result.total_energy_kwh:.1f} kWh", f"${result.total_energy_kwh * electricity_tariff:.2f}")
m_col3.metric("🔌 Observed Peak Power", f"{result.peak_power_kw:.1f} kW", f"Cap: {result.peak_power_limit_kw:.1f} kW")
m_col4.metric("⏱️ Makespan (C_max)", f"{result.makespan_minutes/60.0:.1f} hrs", f"{result.makespan_minutes/1440.0:.1f} days")
m_col5.metric("🔧 Setup Downtime", f"{result.total_setup_minutes/60.0:.1f} hrs", f"{len(result.scheduled_tasks)} ops")
m_col6.metric("🌱 Carbon Emissions", f"{result.total_energy_kwh * carbon_intensity:.1f} kg", "CO2 equivalent")

st.markdown("---")

# --- INTERACTIVE TABS ---
tab1, tab2, tab3, tab4 = st.tabs([
    "📊 Production Schedule (Gantt)",
    "⚡ Fleet Electrical Load Curve P(t)",
    "🎯 Order Deadlines & Tardiness",
    "📋 Dispatch Table & Export",
])

with tab1:
    st.subheader("Interactive Production Gantt Timeline")
    gantt_fig = IEDashboardGenerator.create_gantt_chart(result.scheduled_tasks)
    st.plotly_chart(gantt_fig, use_container_width=True)

with tab2:
    st.subheader("Factory Continuous Electrical Load Profile P(t) vs. Peak Cap")
    power_fig = IEDashboardGenerator.create_power_demand_chart(result)
    st.plotly_chart(power_fig, use_container_width=True)

with tab3:
    st.subheader("Customer Due Date Compliance (Completion Time vs. Deadline)")
    deadline_fig = IEDashboardGenerator.create_deadline_lateness_chart(result.scheduled_tasks)
    st.plotly_chart(deadline_fig, use_container_width=True)

with tab4:
    st.subheader("Scheduled Operations Master Dispatch Table")
    tasks_data = [
        {
            "Job ID": t.job_id,
            "Operation": t.op_id,
            "Machine": t.machine_id,
            "Start (min)": t.t_start,
            "Setup (min)": t.setup_minutes,
            "Cut (min)": t.duration_minutes,
            "End (min)": t.t_end,
            "Fixture": t.fixture_id,
            "Power (kW)": t.power_kw,
            "Energy (kWh)": t.energy_kwh,
            "Due Date (min)": t.due_date,
            "Lateness (min)": t.lateness_minutes,
        }
        for t in result.scheduled_tasks
    ]
    df_tasks = pd.DataFrame(tasks_data)
    st.dataframe(df_tasks, use_container_width=True, height=400)

    csv_bytes = df_tasks.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="📥 Download Schedule as CSV",
        data=csv_bytes,
        file_name="ai_production_schedule.csv",
        mime="text/csv",
    )
