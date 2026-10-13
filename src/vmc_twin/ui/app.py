from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import plotly.graph_objects as go
import streamlit as st

from vmc_twin.config.loader import ConfigLoader
from vmc_twin.data.generator import SyntheticDataGenerator
from vmc_twin.domain.fixture import FixtureSpec, FixtureTransitionMatrix
from vmc_twin.domain.job import Job
from vmc_twin.domain.machine import MachineSpec
from vmc_twin.domain.operation import Operation, ToolRequirement
from vmc_twin.optimize.ai_scheduler import AIScheduledTask, AIScheduleResult, EnergyAwareAIScheduler
from vmc_twin.predict.power_model import EmpiricalPowerModel
from vmc_twin.predict.tool_wear import TaylorParameters, TaylorToolLifeModel, WeibullToolPrognostics
from vmc_twin.report.ie_dashboard import IEDashboardGenerator

st.set_page_config(
    page_title="AI CNC Shop Floor Scheduler & Energy Twin",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Styling for Premium Engineering & Shop-Floor UX
st.markdown(
    """
    <style>
    .main-header {
        font-size: 28px;
        font-weight: 800;
        color: #F8FAFC;
        margin-bottom: 2px;
        letter-spacing: -0.5px;
    }
    .sub-header {
        font-size: 14px;
        color: #94A3B8;
        margin-bottom: 18px;
    }
    .labor-card {
        background: linear-gradient(135deg, rgba(30, 41, 59, 0.85), rgba(15, 23, 42, 0.95));
        border-radius: 10px;
        padding: 16px 20px;
        border-left: 5px solid #F59E0B;
        box-shadow: 0 4px 14px rgba(0,0,0,0.3);
        margin-bottom: 16px;
    }
    .labor-card h4 {
        color: #FCD34D;
        margin: 0 0 8px 0;
        font-size: 16px;
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .order-card {
        background: #1E293B;
        border-radius: 8px;
        padding: 14px 18px;
        border: 1px solid #334155;
        border-left: 4px solid #38BDF8;
        margin-bottom: 14px;
    }
    .badge {
        display: inline-block;
        padding: 3px 8px;
        border-radius: 4px;
        font-weight: 700;
        font-size: 11px;
        text-transform: uppercase;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def load_base_fixtures() -> tuple[list[FixtureSpec], FixtureTransitionMatrix]:
    scenario = ConfigLoader.load_scenario("configs/scenarios/baseline.yaml")
    shop_dir = Path(scenario.shop_config_dir)
    return ConfigLoader.load_fixtures(shop_dir / "fixtures.yaml")


def safe_float(val, default: float) -> float:
    if val is None or pd.isna(val) or str(val).strip() == "" or str(val).lower() == "nan":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def safe_int(val, default: int) -> int:
    if val is None or pd.isna(val) or str(val).strip() == "" or str(val).lower() == "nan":
        return default
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return default


def create_jobs_from_orders(orders_df: pd.DataFrame, random_seed: int = 42) -> list[Job]:
    """
    Converts custom user orders (Order A requires Machine B with Deadline C, Quantity D)
    into individual physical Job objects with strict machine routing constraints.
    """
    rng = np.random.default_rng(random_seed)
    jobs: list[Job] = []

    for _, row in orders_df.iterrows():
        raw_name = str(row.get("Order Name (A)", "")).strip()
        if not raw_name or raw_name.lower() in ["nan", "none"]:
            continue
        order_name = raw_name
        req_machine = str(row.get("Required Machine (B)", "Any Available VMC")).strip()
        if not req_machine or req_machine.lower() in ["nan", "none"]:
            req_machine = "Any Available VMC"

        due_days = max(0.1, safe_float(row.get("Deadline C (Days)"), 10.0))
        due_minutes = due_days * 1440.0
        qty = max(1, safe_int(row.get("Quantity D (Parts)"), 1))
        cut_time = max(1.0, safe_float(row.get("Part Cut Time (min)"), 25.0))
        material = str(row.get("Material", "Steel_4140")).strip()
        if not material or material.lower() in ["nan", "none"]:
            material = "Steel_4140"
        priority = min(5, max(1, safe_int(row.get("Priority"), 3)))
        rel_days = max(0.0, safe_float(row.get("Release Day"), 0.0))
        rel_minutes = rel_days * 1440.0

        # Parse allowed machine types / machine IDs
        if "Any Available" in req_machine or req_machine.upper() in ["ANY", "ALL"]:
            allowed_machines = ["VMC_3AXIS_STD", "VMC_3AXIS_HEAVY", "VMC_5AXIS_HIGH_SPEED", "ANY"]
        elif "3-Axis Standard" in req_machine or "3AXIS_STD" in req_machine:
            allowed_machines = ["VMC_3AXIS_STD"]
        elif "Heavy" in req_machine or "3AXIS_HEAVY" in req_machine:
            allowed_machines = ["VMC_3AXIS_HEAVY"]
        elif "5-Axis" in req_machine or "5AXIS" in req_machine:
            allowed_machines = ["VMC_5AXIS_HIGH_SPEED"]
        elif req_machine.startswith("VMC-"):
            clean_m_id = req_machine.split()[0]
            allowed_machines = [clean_m_id]
        else:
            allowed_machines = [req_machine]

        material_factor = SyntheticDataGenerator.MATERIAL_WEAR_FACTORS.get(material, 1.0)

        for k in range(qty):
            job_id = f"{order_name}-P{k+1:03d}"
            part_release = rel_minutes + (k * 2.0)
            nom_time = cut_time * float(rng.uniform(0.96, 1.04))

            tool_reqs = [
                ToolRequirement(
                    tool_type="ENDMILL_12MM_CARBIDE",
                    cut_minutes=nom_time,
                    wear_factor=material_factor,
                )
            ]

            op = Operation(
                op_id=f"{job_id}-OP1",
                job_id=job_id,
                sequence_num=1,
                name=f"{order_name}_CUT",
                allowed_machine_types=allowed_machines,
                required_fixture="VISE_6INCH_DUAL",
                nominal_cycle_minutes=round(nom_time, 2),
                cycle_time_cv=0.05,
                tool_requirements=tool_reqs,
                base_manual_setup_minutes=15.0,
            )

            jobs.append(
                Job(
                    job_id=job_id,
                    part_name=f"{order_name} [{req_machine}]",
                    material=material,
                    priority=priority,
                    release_time=round(part_release, 1),
                    due_date=round(due_minutes, 1),
                    operations=[op],
                    quantity=1,
                )
            )

    return jobs


# Initialize Default Orders: Order A, Machine B, Deadline C, Quantity D
if "custom_orders" not in st.session_state:
    st.session_state["custom_orders"] = pd.DataFrame([
        {
            "Order Name (A)": "Order A (Boeing Brackets)",
            "Required Machine (B)": "VMC-01",
            "Deadline C (Days)": 5.0,
            "Quantity D (Parts)": 20,
            "Part Cut Time (min)": 25.0,
            "Material": "Aluminum_6061",
            "Priority": 4,
            "Release Day": 0.0,
        },
        {
            "Order Name (A)": "Order B (CAT Valves)",
            "Required Machine (B)": "VMC-06",
            "Deadline C (Days)": 10.0,
            "Quantity D (Parts)": 30,
            "Part Cut Time (min)": 35.0,
            "Material": "Steel_4140",
            "Priority": 3,
            "Release Day": 1.0,
        },
        {
            "Order Name (A)": "Order C (GE Turbine Blisks)",
            "Required Machine (B)": "VMC-09",
            "Deadline C (Days)": 8.0,
            "Quantity D (Parts)": 15,
            "Part Cut Time (min)": 45.0,
            "Material": "Titanium_Gr5",
            "Priority": 5,
            "Release Day": 0.0,
        },
        {
            "Order Name (A)": "Order D (Tesla Enclosures)",
            "Required Machine (B)": "VMC-02",
            "Deadline C (Days)": 16.0,
            "Quantity D (Parts)": 50,
            "Part Cut Time (min)": 18.0,
            "Material": "Aluminum_6061",
            "Priority": 2,
            "Release Day": 0.0,
        },
        {
            "Order Name (A)": "Order E (Hydraulic Flanges)",
            "Required Machine (B)": "Any Available VMC",
            "Deadline C (Days)": 22.0,
            "Quantity D (Parts)": 40,
            "Part Cut Time (min)": 22.0,
            "Material": "Steel_4140",
            "Priority": 2,
            "Release Day": 2.0,
        },
    ])


# --- TOP LEVEL PRESET SELECTION ---
st.sidebar.title("🎛️ Shop Floor Control Panel")

preset = st.sidebar.selectbox(
    "⚡ Quick Factory Presets",
    [
        "🛠️ Custom (Full Manual Control)",
        "🏭 Standard Balanced Job Shop",
        "⚡ Green Factory (Max Peak Shaving)",
        "🔥 Rush Production (100% OTD Priority)",
        "🛩️ Aerospace Titanium Intensive",
    ],
    index=0,
    help="Select a pre-tuned factory scenario or adjust every parameter manually below.",
)

# Preset Default Value Mappings
defaults = {
    "n_std": 5, "n_heavy": 3, "n_5axis": 2, "pallet": 0.3,
    "peak_kw": 25.0, "tariff": 0.16, "carbon": 0.42,
    "w_tard": 10.0, "w_setup": 2.0, "w_peak": 4.0, "w_energy": 1.0,
    "transfer": 2.0, "std_kw": 15.0, "heavy_kw": 22.0, "five_kw": 30.0,
    "std_rpm": 10000.0, "heavy_rpm": 8000.0, "five_rpm": 18000.0,
    "std_cost": 75.0, "heavy_cost": 95.0, "five_cost": 135.0,
    "mtbf_hrs": 350.0, "mttr_min": 90.0, "v_c": 180.0, "feed": 0.15,
}

if preset == "🏭 Standard Balanced Job Shop":
    defaults.update({"peak_kw": 28.0})
elif preset == "⚡ Green Factory (Max Peak Shaving)":
    defaults.update({"peak_kw": 18.0, "w_peak": 8.0, "w_energy": 3.0, "w_setup": 3.0})
elif preset == "🔥 Rush Production (100% OTD Priority)":
    defaults.update({"w_tard": 25.0, "w_peak": 1.0, "peak_kw": 40.0})
elif preset == "🛩️ Aerospace Titanium Intensive":
    defaults.update({"n_heavy": 5, "n_5axis": 4, "v_c": 75.0, "peak_kw": 35.0})

# Mode Toggle for Plain-English Explanations
show_labor_guide = st.sidebar.checkbox(
    "👷‍♂️ Show Shop Floor / Labor Guide (ELI5)",
    value=True,
    help="Explains every engineering parameter in simple, relatable shop-floor language.",
)

# --- SIDEBAR PARAMETER INPUTS ---

# 1. Machine Fleet Architecture
with st.sidebar.expander("🏭 1. Machine Fleet & Hardware Specs", expanded=True):
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        n_std_3axis = st.number_input("Standard 3-Axis VMCs", min_value=1, max_value=20, value=defaults["n_std"], step=1)
        n_heavy_3axis = st.number_input("Heavy 3-Axis VMCs", min_value=0, max_value=15, value=defaults["n_heavy"], step=1)
    with col_f2:
        n_5axis = st.number_input("High-Speed 5-Axis VMCs", min_value=0, max_value=10, value=defaults["n_5axis"], step=1)
        pallet_factor = st.slider("Pallet Setup Factor (APC)", min_value=0.1, max_value=1.0, value=defaults["pallet"], step=0.05,
                                  help="Setup multiplier for pallet changers (0.3 = 70% reduction in setup downtime).")

    with st.expander("⚙️ Advanced Machine Capabilities", expanded=False):
        st.markdown("**Spindle Power & Rates per Machine Class:**")
        p_std = st.number_input("Std 3-Axis Spindle Power (kW)", 5.0, 30.0, defaults["std_kw"], 1.0)
        p_heavy = st.number_input("Heavy 3-Axis Spindle Power (kW)", 10.0, 45.0, defaults["heavy_kw"], 1.0)
        p_5ax = st.number_input("5-Axis Spindle Power (kW)", 15.0, 60.0, defaults["five_kw"], 1.0)

        rate_std = st.number_input("Std 3-Axis Rate ($/hr)", 20.0, 200.0, defaults["std_cost"], 5.0)
        rate_heavy = st.number_input("Heavy 3-Axis Rate ($/hr)", 30.0, 300.0, defaults["heavy_cost"], 5.0)
        rate_5ax = st.number_input("5-Axis Rate ($/hr)", 50.0, 500.0, defaults["five_cost"], 5.0)

        rpm_std = st.number_input("Std Max Spindle RPM", 4000.0, 15000.0, defaults["std_rpm"], 1000.0)
        rpm_heavy = st.number_input("Heavy Max Spindle RPM", 3000.0, 12000.0, defaults["heavy_rpm"], 1000.0)
        rpm_5ax = st.number_input("5-Axis Max Spindle RPM", 8000.0, 30000.0, defaults["five_rpm"], 1000.0)

        mtbf_val = st.number_input("Fleet MTBF (Mean Time Between Failures, hrs)", 50.0, 1000.0, defaults["mtbf_hrs"], 25.0)
        mttr_val = st.number_input("Fleet MTTR (Mean Time to Repair, min)", 15.0, 300.0, defaults["mttr_min"], 15.0)

# 2. Energy & Power Caps
with st.sidebar.expander("⚡ 2. Power Caps & Energy Economics", expanded=True):
    peak_power_cap_kw = st.number_input(
        "Max Fleet Peak Power Cap (kW)",
        min_value=10.0,
        max_value=100.0,
        value=defaults["peak_kw"],
        step=2.5,
        help="Simultaneous electrical power limit across all running spindles.",
    )
    col_e1, col_e2 = st.columns(2)
    with col_e1:
        electricity_tariff = st.number_input("Electricity Tariff ($/kWh)", 0.01, 1.00, defaults["tariff"], 0.01)
    with col_e2:
        carbon_intensity = st.number_input("Grid Carbon (kg CO2/kWh)", 0.05, 1.50, defaults["carbon"], 0.02)
    base_standby_kw = st.number_input("Standby Tare Power per Machine (kW)", 0.2, 5.0, 0.95, 0.05)

# 3. Orders Creation Method
with st.sidebar.expander("📦 3. Production Orders & Multi-Order Mode", expanded=True):
    order_mode = st.radio(
        "Order Creation Mode:",
        ["📋 Custom Orders (Order A -> Machine B, Deadline C, Qty D)", "🎲 High-Volume Bulk Generator"],
        index=0,
        help="Define specific orders (Order A requires Machine B with Deadline C, Quantity D) or generate bulk synthetic jobs.",
    )

    transfer_time = st.number_input("Part Transfer Transit Buffer (min)", 0.0, 30.0, defaults["transfer"], 0.5)

    if order_mode == "🎲 High-Volume Bulk Generator":
        bulk_job_count = st.number_input("Total Production Jobs", min_value=10, max_value=1000, value=200, step=10)
        bulk_horizon_days = st.number_input("Planning Horizon (Days)", min_value=1, max_value=90, value=30, step=1)
        bulk_horizon_minutes = float(bulk_horizon_days * 24 * 60)

        st.markdown("**Bulk Workpiece Material Mix (%)**")
        pct_al = st.slider("Aluminum 6061 (%)", 0, 100, 50)
        pct_steel = st.slider("Steel 4140 (%)", 0, 100, 30)
        pct_ti = st.slider("Titanium Gr5 (%)", 0, 100, 20)

        tot_pct = pct_al + pct_steel + pct_ti
        if tot_pct == 0:
            pct_al, pct_steel, pct_ti = 50, 30, 20
            tot_pct = 100

        bulk_material_mix = {
            "Aluminum_6061": pct_al / tot_pct,
            "Steel_4140": pct_steel / tot_pct,
            "Titanium_Gr5": pct_ti / tot_pct,
        }
    else:
        st.caption(f"Currently defining **{len(st.session_state['custom_orders'])}** orders ({st.session_state['custom_orders']['Quantity D (Parts)'].sum()} total parts).")

# 4. Tool Life & Physics Parameters
with st.sidebar.expander("🔪 4. Tool Life & Machining Physics", expanded=False):
    cutting_speed_input = st.number_input("Nominal Cutting Speed V_c (m/min)", 20.0, 500.0, defaults["v_c"], 10.0)
    feed_per_rev = st.number_input("Feed per Tooth / Rev f (mm/rev)", 0.02, 0.60, defaults["feed"], 0.02)
    depth_of_cut = st.number_input("Axial Depth of Cut a_p (mm)", 0.5, 10.0, 3.0, 0.5)
    flank_wear_limit = st.number_input("ISO 3685 Flank Wear Limit VB_crit (mm)", 0.10, 0.60, 0.30, 0.05)
    atc_swap_sec = st.number_input("Auto Tool Changer Swap (sec)", 2.0, 30.0, 6.0, 1.0)
    crib_swap_min = st.number_input("Manual Crib Tool Reload (min)", 1.0, 15.0, 3.0, 0.5)

# 5. Multi-Objective AI Weights
with st.sidebar.expander("🧠 5. AI Optimizer Objective Weights", expanded=False):
    w_tardiness = st.slider("Urgency & OTD Weight (w_tard)", 1.0, 40.0, defaults["w_tard"], step=1.0)
    w_setup = st.slider("Setup Minimization Weight (w_setup)", 0.0, 15.0, defaults["w_setup"], step=0.5)
    w_peak_power = st.slider("Peak Load Shaving Weight (w_peak)", 0.0, 20.0, defaults["w_peak"], step=0.5)
    w_energy = st.slider("Energy Cost Weight (w_energy)", 0.0, 10.0, defaults["w_energy"], step=0.5)
    random_seed = st.number_input("Scenario Random Seed", min_value=1, max_value=99999, value=42)

# --- HEADER SECTION ---
st.markdown("<div class='main-header'>🏭 AI CNC Factory Digital Twin & Shop Floor Scheduler</div>", unsafe_allow_html=True)
st.markdown(
    "<div class='sub-header'>Multi-Order Routing (Order A on Machine B with Deadline C, Quantity D) • Peak Shaving • ISO 3685 Tool Wear</div>",
    unsafe_allow_html=True,
)

# Build Dynamic Fleet early so machine options are available to the orders table
machines: list[MachineSpec] = []
idx = 1
for _ in range(n_std_3axis):
    machines.append(
        MachineSpec(
            machine_id=f"VMC-{idx:02d}",
            machine_type="VMC_3AXIS_STD",
            spindle_power_kw=float(p_std),
            max_spindle_rpm=float(rpm_std),
            magazine_capacity=30,
            has_pallet_changer=True,
            mtbf_hours=float(mtbf_val),
            mttr_minutes=float(mttr_val),
            hourly_rate_usd=float(rate_std),
            pallet_setup_factor=float(pallet_factor),
        )
    )
    idx += 1

for _ in range(n_heavy_3axis):
    machines.append(
        MachineSpec(
            machine_id=f"VMC-{idx:02d}",
            machine_type="VMC_3AXIS_HEAVY",
            spindle_power_kw=float(p_heavy),
            max_spindle_rpm=float(rpm_heavy),
            magazine_capacity=40,
            has_pallet_changer=True,
            mtbf_hours=float(mtbf_val * 0.9),
            mttr_minutes=float(mttr_val * 1.2),
            hourly_rate_usd=float(rate_heavy),
            pallet_setup_factor=float(pallet_factor),
        )
    )
    idx += 1

for _ in range(n_5axis):
    machines.append(
        MachineSpec(
            machine_id=f"VMC-{idx:02d}",
            machine_type="VMC_5AXIS_HIGH_SPEED",
            spindle_power_kw=float(p_5ax),
            max_spindle_rpm=float(rpm_5ax),
            magazine_capacity=50,
            has_pallet_changer=True,
            mtbf_hours=float(mtbf_val * 0.8),
            mttr_minutes=float(mttr_val * 1.4),
            hourly_rate_usd=float(rate_5ax),
            pallet_setup_factor=float(pallet_factor),
        )
    )
    idx += 1

# List of available machines for user selection
available_machines_list = ["Any Available VMC"]
for m in machines:
    available_machines_list.append(m.machine_id)
available_machines_list.extend([
    "Any 3-Axis Standard (VMC_3AXIS_STD)",
    "Any 3-Axis Heavy Duty (VMC_3AXIS_HEAVY)",
    "Any 5-Axis High Speed (VMC_5AXIS_HIGH_SPEED)",
])

# --- LABOR FRIENDLY OVERVIEW BANNER (IF TOGGLED) ---
if show_labor_guide:
    st.markdown(
        """
        <div class="labor-card">
            <h4>👷‍♂️ Shop Floor Labor & Operator Guide: How Multiple Orders Work in Our Shop</h4>
            <div style="font-size:14px; color:#E2E8F0; line-height:1.6;">
                • <strong>Order Name (A):</strong> What customer part batch are we making? (e.g., <em>Order A: Boeing Brackets</em>).<br>
                • <strong>Required Machine (B):</strong> Which specific spindle on the shop floor must cut it? (e.g., <em>Locked to VMC-01</em>). The AI will not allow other machines to touch it unless set to <em>Any Available VMC</em>.<br>
                • <strong>Deadline C (Days):</strong> When does the customer shipment truck arrive? (e.g., <em>Day 5.0 = 120 hours</em>). The AI sequences jobs to guarantee on-time shipping.<br>
                • <strong>Quantity D (Parts):</strong> How many physical parts need to be machined? (e.g., <em>20 pieces</em>). Each part has its own clamp, cycle time, and tool wear tracked.<br>
                • <strong>Main Electrical Breaker:</strong> The AI staggers heavy cuts across spindles so the factory's main breaker never trips.<br>
                • <strong>Automatic Pallet Changers (No Idle Spindles):</strong> Operators clamp parts on the outer door while the spindle cuts inside, eliminating idle clamping delay.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# --- MULTI-ORDER INTERACTIVE EDITOR ---
if order_mode == "📋 Custom Orders (Order A -> Machine B, Deadline C, Qty D)":
    st.markdown("### 📋 Multiple Production Orders: (Order A requires Machine B with Deadline C, Quantity D)")
    st.markdown(
        "Define and configure multiple customer work orders below. Each order specifies the **Order Name (A)**, the **Required Machine (B)**, the promised **Deadline (C)**, and the **Quantity (D)**."
    )

    # 1. Quick Add Single Order Form
    with st.expander("➕ Quick-Add a New Order (Order A ➔ Machine B ➔ Deadline C ➔ Quantity D)", expanded=False):
        with st.form("quick_add_order_form", clear_on_submit=False):
            st.markdown("**Enter Parameters for a Single Customer Order:**")
            qa_col1, qa_col2 = st.columns(2)
            next_num = len(st.session_state["custom_orders"]) + 1
            new_letter = chr(ord('A') + (next_num - 1) % 26)

            with qa_col1:
                f_order_name = st.text_input("Order Name (A):", value=f"Order {new_letter} (New Batch)")
                f_req_machine = st.selectbox(
                    "Required Machine (B):",
                    options=available_machines_list,
                    index=1 if len(available_machines_list) > 1 else 0,
                    help="Target spindle that must cut this job (e.g. VMC-01, VMC-06) or Any Available VMC.",
                )
                f_deadline_days = st.number_input("Deadline C (Days):", min_value=0.5, max_value=90.0, value=7.0, step=0.5)
                f_qty = st.number_input("Quantity D (Number of Parts):", min_value=1, value=25, step=5)

            with qa_col2:
                f_cut_time = st.number_input("Part Cut Time (min):", min_value=1.0, max_value=300.0, value=30.0, step=5.0)
                f_material = st.selectbox("Material:", ["Aluminum_6061", "Steel_4140", "Titanium_Gr5"], index=1)
                f_priority = st.slider("Priority (1=Normal..5=Rush):", 1, 5, 3)
                f_rel_day = st.number_input("Release Day (Stock arrival):", min_value=0.0, max_value=60.0, value=0.0, step=0.5)

            form_submitted = st.form_submit_button("➕ Add This Order to Table", type="primary", use_container_width=True)
            if form_submitted:
                new_row_df = pd.DataFrame([{
                    "Order Name (A)": f_order_name.strip() if f_order_name.strip() else f"Order {new_letter}",
                    "Required Machine (B)": f_req_machine,
                    "Deadline C (Days)": float(f_deadline_days),
                    "Quantity D (Parts)": int(f_qty),
                    "Part Cut Time (min)": float(f_cut_time),
                    "Material": f_material,
                    "Priority": int(f_priority),
                    "Release Day": float(f_rel_day),
                }])
                st.session_state["custom_orders"] = pd.concat([st.session_state["custom_orders"], new_row_df], ignore_index=True)
                st.success(f"Added {f_order_name} (Machine: {f_req_machine}, Deadline: Day {f_deadline_days}, Qty: {f_qty} pcs)!")
                st.rerun()

    # 2. Action Buttons
    col_btn_add, col_btn_reset, col_btn_clear = st.columns([1.5, 1.5, 1.2])
    with col_btn_add:
        if st.button("➕ Quick Add Rush Order (5-Axis)", use_container_width=True):
            next_num = len(st.session_state["custom_orders"]) + 1
            new_letter = chr(ord('A') + (next_num - 1) % 26)
            new_row = pd.DataFrame([{
                "Order Name (A)": f"Order {new_letter} (Rush Blisks)",
                "Required Machine (B)": "VMC-09",
                "Deadline C (Days)": 7.0,
                "Quantity D (Parts)": 15,
                "Part Cut Time (min)": 40.0,
                "Material": "Titanium_Gr5",
                "Priority": 5,
                "Release Day": 0.0,
            }])
            st.session_state["custom_orders"] = pd.concat([st.session_state["custom_orders"], new_row], ignore_index=True)
            st.rerun()

    with col_btn_reset:
        if st.button("🔄 Reset to Default Orders (A, B, C, D, E)", use_container_width=True):
            st.session_state["custom_orders"] = pd.DataFrame([
                {
                    "Order Name (A)": "Order A (Boeing Brackets)",
                    "Required Machine (B)": "VMC-01",
                    "Deadline C (Days)": 5.0,
                    "Quantity D (Parts)": 20,
                    "Part Cut Time (min)": 25.0,
                    "Material": "Aluminum_6061",
                    "Priority": 4,
                    "Release Day": 0.0,
                },
                {
                    "Order Name (A)": "Order B (CAT Valves)",
                    "Required Machine (B)": "VMC-06",
                    "Deadline C (Days)": 10.0,
                    "Quantity D (Parts)": 30,
                    "Part Cut Time (min)": 35.0,
                    "Material": "Steel_4140",
                    "Priority": 3,
                    "Release Day": 1.0,
                },
                {
                    "Order Name (A)": "Order C (GE Turbine Blisks)",
                    "Required Machine (B)": "VMC-09",
                    "Deadline C (Days)": 8.0,
                    "Quantity D (Parts)": 15,
                    "Part Cut Time (min)": 45.0,
                    "Material": "Titanium_Gr5",
                    "Priority": 5,
                    "Release Day": 0.0,
                },
                {
                    "Order Name (A)": "Order D (Tesla Enclosures)",
                    "Required Machine (B)": "VMC-02",
                    "Deadline C (Days)": 16.0,
                    "Quantity D (Parts)": 50,
                    "Part Cut Time (min)": 18.0,
                    "Material": "Aluminum_6061",
                    "Priority": 2,
                    "Release Day": 0.0,
                },
                {
                    "Order Name (A)": "Order E (Hydraulic Flanges)",
                    "Required Machine (B)": "Any Available VMC",
                    "Deadline C (Days)": 22.0,
                    "Quantity D (Parts)": 40,
                    "Part Cut Time (min)": 22.0,
                    "Material": "Steel_4140",
                    "Priority": 2,
                    "Release Day": 2.0,
                },
            ])
            st.rerun()

    with col_btn_clear:
        if st.button("🗑️ Clear All Orders", use_container_width=True):
            st.session_state["custom_orders"] = pd.DataFrame(columns=[
                "Order Name (A)", "Required Machine (B)", "Deadline C (Days)",
                "Quantity D (Parts)", "Part Cut Time (min)", "Material", "Priority", "Release Day"
            ])
            st.rerun()

    # 3. Main Interactive Data Editor
    st.markdown("✏️ **Editable Multi-Orders Table (Click any cell to edit, click '+' at bottom to add rows):**")
    edited_orders = st.data_editor(
        st.session_state["custom_orders"],
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "Order Name (A)": st.column_config.TextColumn("Order Name (A)", required=True),
            "Required Machine (B)": st.column_config.SelectboxColumn(
                "Required Machine (B)",
                options=available_machines_list,
                required=True,
                help="Lock this order onto a specific machine (e.g. VMC-01) or allow Any Available VMC.",
            ),
            "Deadline C (Days)": st.column_config.NumberColumn("Deadline C (Days)", min_value=0.5, max_value=90.0, step=0.5, required=True),
            "Quantity D (Parts)": st.column_config.NumberColumn("Quantity D (Parts)", min_value=1, step=1, required=True),
            "Part Cut Time (min)": st.column_config.NumberColumn("Cut Time/Part (min)", min_value=1.0, max_value=300.0, step=5.0, required=True),
            "Material": st.column_config.SelectboxColumn(
                "Workpiece Material",
                options=["Aluminum_6061", "Steel_4140", "Titanium_Gr5"],
                required=True,
            ),
            "Priority": st.column_config.NumberColumn("Priority (1=Low..5=Rush)", min_value=1, max_value=5, step=1, required=True),
            "Release Day": st.column_config.NumberColumn("Release (Day)", min_value=0.0, max_value=60.0, step=1.0, required=True),
        },
        key="orders_editor",
    )
    st.session_state["custom_orders"] = edited_orders

    # 4. Summary Badges for active orders
    if len(st.session_state["custom_orders"]) > 0:
        summary_pills = []
        for _, ord_r in st.session_state["custom_orders"].iterrows():
            o_n = str(ord_r.get("Order Name (A)", "Order"))
            m_r = str(ord_r.get("Required Machine (B)", "Any"))
            d_c = ord_r.get("Deadline C (Days)", 0)
            q_d = ord_r.get("Quantity D (Parts)", 0)
            lock_emoji = "🔒" if m_r.startswith("VMC-") else "🌐"
            summary_pills.append(f"**{o_n}**: {q_d} pcs ➔ {lock_emoji} `{m_r}` ➔ Due: Day {d_c}")
        st.caption(" • ".join(summary_pills))

# --- DEDICATED MATHEMATICAL & AI FORMULAS DROPDOWN ---
st.markdown("### 📐 Mathematical Formulations & AI Algorithm Deep-Dive")
formula_selection = st.selectbox(
    "Select AI / Mathematical Formula to Inspect:",
    [
        "📌 Complete Mathematical Architecture Summary (All Equations)",
        "1️⃣ Multi-Objective AI Cost Function & Dispatching Score",
        "2️⃣ Continuous CNC Spindle Power Telemetry & Specific Cutting Energy",
        "3️⃣ Extended Taylor Tool Life Equation (ISO 3685)",
        "4️⃣ Flank Wear Progression VB(t) & Weibull Tool Reliability",
        "5️⃣ Sequence-Dependent Setup Matrix & Pallet Changer Dynamics",
        "6️⃣ Fleet Peak Electrical Power Shaving Constraint",
        "7️⃣ Machine Inherent Availability & Reliability (MTBF / MTTR)",
        "8️⃣ Precedence-Constrained Multi-Stage Job Flow Routing",
    ],
    index=0,
)

with st.expander("🔍 Click to Expand / Collapse Detailed Mathematical Proof & Formulas", expanded=False):
    if formula_selection == "📌 Complete Mathematical Architecture Summary (All Equations)":
        st.markdown(
            r"""
            #### 🏭 Comprehensive Twin Formulation Overview
            This Digital Twin couples discrete-event operational logistics with continuous physical machining telemetry:
            
            1. **Production Scheduling:** Minimizes weighted tardiness $\sum w_j T_j$, makespan $C_{\max}$, and changeovers $\sum S_k$.
            2. **Electrical Power Telemetry:** Enforces continuous electrical load caps: $P_{\text{fleet}}(t) = \sum_{m} P_m(t) \le P_{\text{cap}}$.
            3. **Tool Tribology:** Models flank wear $VB(t)$ and predicts remaining tool life $T$ using Taylor's equation and Weibull survival.
            4. **Machine Availability:** Formulates inherent availability $A = \frac{\text{MTBF}}{\text{MTBF} + \text{MTTR}}$.
            """
        )
        st.latex(
            r"""
            \min \mathcal{J} = w_{\text{tard}} \sum_{j=1}^N \max(0, C_j - d_j) + w_{\text{setup}} \sum_{k=1}^K S_k + w_{\text{peak}} \max_{t} P_{\text{fleet}}(t) + w_{\text{energy}} \int_0^{C_{\max}} P_{\text{fleet}}(t) \, dt
            """
        )

    elif formula_selection == "1️⃣ Multi-Objective AI Cost Function & Dispatching Score":
        st.markdown(
            r"""
            #### 1. Multi-Objective AI Cost Function $\mathcal{J}$
            The AI engine evaluates scheduling decisions using a composite objective function balancing on-time delivery, setup minimization, and electrical peak shaving:
            """
        )
        st.latex(
            r"""
            \min \mathcal{J} = w_{\text{tard}} \sum_{j=1}^{N} \max(0, C_j - d_j) + w_{\text{setup}} \sum_{k=1}^{K} S_k + w_{\text{peak}} \max_{t \in [0, C_{\max}]} P_{\text{fleet}}(t) + w_{\text{energy}} \int_0^{C_{\max}} P_{\text{fleet}}(t) \, dt
            """
        )

    elif formula_selection == "2️⃣ Continuous CNC Spindle Power Telemetry & Specific Cutting Energy":
        st.markdown(
            r"""
            #### 2. CNC Electrical Power Telemetry & MRR Cutting Physics
            The power draw of a vertical machining center is partitioned into tare base power, kinetic no-load rotation, and chip-shearing power:
            """
        )
        st.latex(
            r"""
            P_{\text{total}}(t) = P_{\text{standby}} + P_{\text{air}}(\text{RPM}) + P_{\text{cut}}(Q_{\text{MRR}})
            """
        )
        st.latex(
            r"""
            Q_{\text{MRR}} = a_p \cdot a_e \cdot v_f = a_p \cdot a_e \cdot (f_z \cdot z \cdot n) \quad \left[\frac{\text{mm}^3}{\text{min}}\right]
            """
        )
        st.latex(
            r"""
            P_{\text{cut}} = \frac{k_c \cdot Q_{\text{MRR}}}{60 \times 10^3 \times \eta_{\text{spindle}}} \quad [\text{kW}]
            """
        )

    elif formula_selection == "3️⃣ Extended Taylor Tool Life Equation (ISO 3685)":
        st.markdown(
            r"""
            #### 3. Extended Taylor Tool Life Formulation
            Relates cutting speed $V_c$, feed $f$, and axial depth of cut $a_p$ to expected tool cutting life $T$:
            """
        )
        st.latex(
            r"""
            V_c \cdot T^n \cdot f^a \cdot a_p^b = C \implies T = \left( \frac{C}{V_c \cdot f^a \cdot a_p^b} \right)^{1/n}
            """
        )

    elif formula_selection == "4️⃣ Flank Wear Progression VB(t) & Weibull Tool Reliability":
        st.markdown(
            r"""
            #### 4. ISO 3685 Flank Wear Growth & Weibull Failure Reliability
            Tool wear accrues nonlinearly through initial break-in, steady-state abrasion, and rapid tertiary failure:
            """
        )
        st.latex(
            r"""
            VB(t) = VB_0 + (VB_{\text{limit}} - VB_0) \cdot \left( \frac{t}{T_{\text{nominal}}} \right)^\gamma
            """
        )
        st.latex(
            r"""
            R(t) = \exp\left( - \left( \frac{t}{\eta} \right)^\beta \right), \quad F(t) = 1 - R(t)
            """
        )

    elif formula_selection == "5️⃣ Sequence-Dependent Setup Matrix & Pallet Changer Dynamics":
        st.markdown(
            r"""
            #### 5. Changeover Transition Matrix with Automatic Pallet Changer (APC) Discounting
            The physical downtime required to tear down fixture $F_i$ and mount fixture $F_j$:
            """
        )
        st.latex(
            r"""
            T_{\text{setup}}(F_i \to F_j) = \mathbf{M}_{ij} \times \phi_{\text{pallet}} \times \psi_{\text{skill}}
            """
        )

    elif formula_selection == "6️⃣ Fleet Peak Electrical Power Shaving Constraint":
        st.markdown(
            r"""
            #### 6. Factory Peak Electrical Power Demand Cap Shaving
            Prevents simultaneous high-power cuts from tripping utility peak-demand billing thresholds:
            """
        )
        st.latex(
            r"""
            \sum_{m \in \mathcal{M}} P_m(t) \le P_{\text{cap}}, \quad \forall t \in [0, C_{\max}]
            """
        )

    elif formula_selection == "7️⃣ Machine Inherent Availability & Reliability (MTBF / MTTR)":
        st.markdown(
            r"""
            #### 7. Machine Reliability & Inherent Operational Availability
            """
        )
        st.latex(
            r"""
            A_i = \frac{\text{MTBF}}{\text{MTBF} + \text{MTTR}} \times 100\%
            """
        )

    elif formula_selection == "8️⃣ Precedence-Constrained Multi-Stage Job Flow Routing":
        st.markdown(
            r"""
            #### 8. Multi-Stage Operation Precedence & Inter-Machine Transfer
            Ensures that roughing finishes before semi-finishing, and semi-finishing completes before grinding/tapping:
            """
        )
        st.latex(
            r"""
            t_{\text{start}}(O_{j, k+1}) \ge t_{\text{end}}(O_{j, k}) + \Delta t_{\text{transfer}}
            """
        )

st.markdown("---")

# Load fixtures
fixtures, transition_matrix = load_base_fixtures()

# Generate Jobs depending on selected mode
if order_mode == "📋 Custom Orders (Order A -> Machine B, Deadline C, Qty D)":
    jobs = create_jobs_from_orders(st.session_state["custom_orders"], random_seed=int(random_seed))
    info_str = f"**Multi-Order Active:** {len(st.session_state['custom_orders'])} Orders ({len(jobs)} Parts) | {len(machines)} VMCs | Peak Cap: **{peak_power_cap_kw:.1f} kW**"
else:
    gen = SyntheticDataGenerator(random_seed=int(random_seed))
    jobs = gen.generate_jobs(
        count=int(bulk_job_count),
        horizon_minutes=bulk_horizon_minutes,
        workpiece_mix=bulk_material_mix,
    )
    info_str = f"**Bulk Active:** {len(jobs)} Synthetic Work Orders | {len(machines)} VMCs | Peak Cap: **{peak_power_cap_kw:.1f} kW**"

col_run, col_cfg_info = st.columns([1, 4])
with col_run:
    run_btn = st.button("🚀 Run AI Optimizer", type="primary", use_container_width=True)

with col_cfg_info:
    st.info(info_str)

state_fingerprint = (
    order_mode,
    str(st.session_state["custom_orders"].to_dict()) if order_mode.startswith("📋") else f"{bulk_job_count}_{bulk_horizon_days}",
    n_std_3axis, n_heavy_3axis, n_5axis, pallet_factor, peak_power_cap_kw,
    w_tardiness, w_setup, w_peak_power, w_energy, random_seed
)

needs_solve = (
    run_btn
    or "last_result" not in st.session_state
    or st.session_state.get("last_state_fingerprint") != state_fingerprint
)

if needs_solve:
    with st.spinner("AI Engine is optimizing order schedules, machine routing constraints, and power peaks..."):
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
        result = ai_scheduler.solve(jobs=jobs, scenario_name="Custom_User_Run")
        st.session_state["last_result"] = result
        st.session_state["last_state_fingerprint"] = state_fingerprint
        st.session_state["cached_gantt_fig"] = None
        st.session_state["cached_power_fig"] = None
        st.session_state["cached_deadline_fig"] = None

result = st.session_state["last_result"]

# --- EXECUTIVE KPI METRICS ---
m_col1, m_col2, m_col3, m_col4, m_col5, m_col6 = st.columns(6)

otd_badge = "🟢" if result.on_time_delivery_pct >= 95.0 else "🔴"
m_col1.metric("🎯 On-Time Delivery (OTD)", f"{result.on_time_delivery_pct:.1f}%", f"{otd_badge} {result.completed_jobs} parts")
m_col2.metric("⚡ Total Energy (kWh)", f"{result.total_energy_kwh:.1f} kWh", f"${result.total_energy_kwh * electricity_tariff:.2f}")
m_col3.metric("🔌 Observed Peak Power", f"{result.peak_power_kw:.1f} kW", f"Cap: {result.peak_power_limit_kw:.1f} kW")
m_col4.metric("⏱️ Makespan (C_max)", f"{result.makespan_minutes/60.0:.1f} hrs", f"{result.makespan_minutes/1440.0:.1f} days")
m_col5.metric("🔧 Setup Downtime", f"{result.total_setup_minutes/60.0:.1f} hrs", f"{len(result.scheduled_tasks)} ops")
m_col6.metric("🌱 Carbon Emissions", f"{result.total_energy_kwh * carbon_intensity:.1f} kg", "CO2 equivalent")

# --- DAILY SHOP FLOOR SHIFT BRIEFING (FOR MACHINISTS & LABOR) ---
if show_labor_guide:
    peak_ok = result.peak_power_kw <= result.peak_power_limit_kw + 0.1
    status_icon = "🟢" if (result.on_time_delivery_pct >= 95.0 and peak_ok) else "🟡"
    status_title = "FACTORY RUNNING AT PEAK HEALTH" if status_icon == "🟢" else "FACTORY RUNNING WITH OPERATIONAL CAUTION"

    st.markdown(
        f"""
        <div class="labor-card" style="border-left-color: {'#10B981' if status_icon == '🟢' else '#F59E0B'};">
            <h4>{status_icon} Daily Shop Floor Worker Briefing: {status_title}</h4>
            <div style="font-size:14px; color:#E2E8F0; line-height:1.6;">
                • <strong>Customer Delivery Status:</strong> <strong>{result.on_time_delivery_pct:.1f}%</strong> of parts are scheduled to ship on or before deadline!<br>
                • <strong>Target Machine Routing:</strong> Machines executed their assigned orders without bottlenecking the line.<br>
                • <strong>Main Electrical Breaker:</strong> The highest electric draw across the factory is <strong>{result.peak_power_kw:.1f} kW</strong> (safe limit is <strong>{result.peak_power_limit_kw:.1f} kW</strong>). {'The circuit breaker will NOT trip!' if peak_ok else 'Warning: Spindle load touched the breaker cap.'}<br>
                • <strong>Total Electricity Cost:</strong> <strong>${result.total_energy_kwh * electricity_tariff:.2f}</strong> for this entire production run.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.markdown("---")

# --- INTERACTIVE VISUAL TABS ---
tab_orders, tab_gantt, tab_power, tab_deadlines, tab_labor, tab_dispatch = st.tabs([
    "🎯 Multi-Order Delivery & Machine Compliance Scorecard",
    "📊 Production Schedule (Gantt)",
    "⚡ Continuous Electrical Load Profile P(t)",
    "🎯 Order Deadlines & Customer Tardiness",
    "👷‍♂️ Shop Floor Labor & Machine Utilization",
    "📋 Dispatch Master Table & Reports",
])

with tab_orders:
    st.subheader("🎯 Customer Work Order Delivery & Machine Assignment Scorecard")
    st.markdown("Confirms whether each order was processed on its **Required Machine (B)** and finished before **Deadline (C)**:")

    # Map tasks by Order Name
    task_order_map: dict[str, list[AIScheduledTask]] = {}
    for task in result.scheduled_tasks:
        # job_id is formatted like Order A-P001
        order_key = task.job_id.split("-P")[0] if "-P" in task.job_id else task.job_id.split("-")[0]
        task_order_map.setdefault(order_key, []).append(task)

    order_metrics = []
    if order_mode == "📋 Custom Orders (Order A -> Machine B, Deadline C, Qty D)":
        for _, ord_row in st.session_state["custom_orders"].iterrows():
            o_name = str(ord_row.get("Order Name (A)", "Order")).strip()
            if not o_name or o_name.lower() in ["nan", "none"]:
                continue
            req_m = str(ord_row.get("Required Machine (B)", "Any Available VMC")).strip()
            due_days = safe_float(ord_row.get("Deadline C (Days)"), 10.0)
            due_min = due_days * 1440.0
            o_qty = safe_int(ord_row.get("Quantity D (Parts)"), 1)
            cut_time = safe_float(ord_row.get("Part Cut Time (min)"), 25.0)
            o_mat = str(ord_row.get("Material", "Steel_4140"))

            tasks_for_order = task_order_map.get(o_name, [])
            if tasks_for_order:
                start_time_min = min(t.t_start for t in tasks_for_order)
                end_time_min = max(t.t_end for t in tasks_for_order)
                tot_energy = sum(t.energy_kwh for t in tasks_for_order)
                tot_cut_hrs = sum(t.duration_minutes for t in tasks_for_order) / 60.0
                machines_used = sorted(list({t.machine_id for t in tasks_for_order}))
                is_on_time = end_time_min <= due_min
                lateness_hrs = max(0.0, (end_time_min - due_min) / 60.0)
                early_hrs = max(0.0, (due_min - end_time_min) / 60.0)

                # Check if machine requirement was honored
                if req_m.startswith("VMC-"):
                    clean_target = req_m.split()[0]
                    target_match = "🔒 " + ", ".join(machines_used) if clean_target in machines_used else ", ".join(machines_used)
                else:
                    target_match = "🌐 " + ", ".join(machines_used)

                order_metrics.append({
                    "Order Name (A)": o_name,
                    "Required Machine (B)": req_m,
                    "Actual Machine Assigned": target_match,
                    "Quantity D": f"{o_qty} pcs",
                    "Cut Time/Part": f"{cut_time:.0f}m",
                    "Deadline C": f"Day {due_days:.1f}",
                    "Completed At": f"Day {end_time_min/1440.0:.1f} ({end_time_min/60.0:.1f}h)",
                    "Delivery Status": f"🟢 ON-TIME ({early_hrs:.1f}h early)" if is_on_time else f"🔴 LATE by {lateness_hrs:.1f}h",
                    "Machining Hours": f"{tot_cut_hrs:.1f} h",
                    "Energy (kWh)": f"{tot_energy:.1f} kWh",
                    "Cost ($)": f"${tot_energy * electricity_tariff:.2f}",
                })
            else:
                order_metrics.append({
                    "Order Name (A)": o_name,
                    "Required Machine (B)": req_m,
                    "Actual Machine Assigned": "⏳ Pending Run / No Compatible Machine",
                    "Quantity D": f"{o_qty} pcs",
                    "Cut Time/Part": f"{cut_time:.0f}m",
                    "Deadline C": f"Day {due_days:.1f}",
                    "Completed At": "N/A",
                    "Delivery Status": "⏳ Pending Run",
                    "Machining Hours": "0.0 h",
                    "Energy (kWh)": "0.0 kWh",
                    "Cost ($)": "$0.00",
                })
        df_orders_scorecard = pd.DataFrame(order_metrics)
        st.dataframe(df_orders_scorecard, use_container_width=True)
    else:
        st.info("Currently in Bulk Synthetic Mode. Showing order breakdown for top synthetic batches:")
        for o_prefix, tasks_for_order in list(task_order_map.items())[:10]:
            start_time_min = min(t.t_start for t in tasks_for_order)
            end_time_min = max(t.t_end for t in tasks_for_order)
            tot_energy = sum(t.energy_kwh for t in tasks_for_order)
            due_min = max(t.due_date for t in tasks_for_order)
            is_on_time = end_time_min <= due_min
            order_metrics.append({
                "Batch ID": o_prefix,
                "Operations Count": len(tasks_for_order),
                "First Start": f"{start_time_min/60.0:.1f}h",
                "Final Completion": f"{end_time_min/60.0:.1f}h",
                "Due Date": f"{due_min/60.0:.1f}h",
                "Status": "🟢 ON-TIME" if is_on_time else "🔴 LATE",
                "Total Energy": f"{tot_energy:.1f} kWh",
                "Cost": f"${tot_energy * electricity_tariff:.2f}",
            })
        st.dataframe(pd.DataFrame(order_metrics), use_container_width=True)

with tab_gantt:
    st.subheader("Interactive Production Gantt Timeline (Job Sequencing & Machine Allocation)")
    if st.session_state.get("cached_gantt_fig") is None:
        st.session_state["cached_gantt_fig"] = IEDashboardGenerator.create_gantt_chart(result.scheduled_tasks)
    st.plotly_chart(st.session_state["cached_gantt_fig"], use_container_width=True)

with tab_power:
    st.subheader("Factory Continuous Electrical Load Profile P(t) vs. Peak Cap")
    if st.session_state.get("cached_power_fig") is None:
        st.session_state["cached_power_fig"] = IEDashboardGenerator.create_power_demand_chart(result)
    st.plotly_chart(st.session_state["cached_power_fig"], use_container_width=True)

with tab_deadlines:
    st.subheader("Customer Due Date Compliance (Completion Timestamp vs. Deadline)")
    if st.session_state.get("cached_deadline_fig") is None:
        st.session_state["cached_deadline_fig"] = IEDashboardGenerator.create_deadline_lateness_chart(result.scheduled_tasks)
    st.plotly_chart(st.session_state["cached_deadline_fig"], use_container_width=True)

with tab_labor:
    st.subheader("👷‍♂️ Shop Floor Labor & Machine Utilization Analytics")
    m_tasks_count = {m.machine_id: 0 for m in machines}
    m_cut_time = {m.machine_id: 0.0 for m in machines}
    m_setup_time = {m.machine_id: 0.0 for m in machines}
    for t in result.scheduled_tasks:
        if t.machine_id in m_tasks_count:
            m_tasks_count[t.machine_id] += 1
            m_cut_time[t.machine_id] += t.duration_minutes
            m_setup_time[t.machine_id] += t.setup_minutes

    m_summary = []
    for m in machines:
        util_pct = (m_cut_time[m.machine_id] / max(1.0, result.makespan_minutes)) * 100.0
        m_summary.append({
            "Machine Center": m.machine_id,
            "Type": m.machine_type,
            "Hourly Rate": f"${m.hourly_rate_usd:.0f}/hr",
            "Operations Assigned": m_tasks_count[m.machine_id],
            "Spindle Cutting Time (hrs)": f"{m_cut_time[m.machine_id]/60.0:.1f} h",
            "Fixture Setup Time (hrs)": f"{m_setup_time[m.machine_id]/60.0:.1f} h",
            "Spindle Utilization %": f"{util_pct:.1f}%",
        })
    df_m = pd.DataFrame(m_summary)
    st.dataframe(df_m, use_container_width=True)

    col_w1, col_w2 = st.columns(2)
    with col_w1:
        st.markdown(
            r"""
            **👷‍♂️ Operator Takeaway:**
            - **Target Machines:** Orders locked onto specific machines are scheduled sequentially without overlap.
            - **Setup Burden:** Machines with multiple orders use automatic fixture preservation to minimize changeover downtime.
            """
        )
    with col_w2:
        st.markdown(
            f"""
            **⚡ Energy & Cost Takeaway:**
            - Total Spindle Run Time: **{sum(m_cut_time.values())/60.0:.1f} machine-hours**
            - Total Setup Labor Time: **{sum(m_setup_time.values())/60.0:.1f} man-hours**
            - Electricity Cost: **${result.total_energy_kwh * electricity_tariff:.2f}**
            """
        )

with tab_dispatch:
    st.subheader("Scheduled Operations Master Dispatch Table")
    tasks_data = [
        {
            "Order / Job": t.job_id,
            "Operation": t.op_id,
            "Machine Assigned": t.machine_id,
            "Start (min)": round(t.t_start, 1),
            "Setup (min)": round(t.setup_minutes, 1),
            "Cut (min)": round(t.duration_minutes, 1),
            "End (min)": round(t.t_end, 1),
            "Fixture": t.fixture_id,
            "Power (kW)": round(t.power_kw, 2),
            "Energy (kWh)": round(t.energy_kwh, 3),
            "Deadline (min)": round(t.due_date, 1),
            "Lateness (min)": round(t.lateness_minutes, 1),
        }
        for t in result.scheduled_tasks
    ]
    df_tasks = pd.DataFrame(tasks_data)
    st.dataframe(df_tasks, use_container_width=True, height=350)

    col_d1, col_d2 = st.columns(2)
    with col_d1:
        csv_bytes = df_tasks.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📥 Download Schedule as CSV",
            data=csv_bytes,
            file_name="ai_production_schedule.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with col_d2:
        export_html = st.button("🌐 Generate Standalone HTML Report", use_container_width=True)
        if export_html:
            report_path = IEDashboardGenerator.generate_dashboard(result=result, output_path="outputs/custom_ie_dashboard.html")
            st.success(f"Report exported to `{report_path.resolve()}`!")
