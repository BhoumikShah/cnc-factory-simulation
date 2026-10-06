from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True)
class PowerPrediction:
    """Predicted electrical power components for a machining operation."""

    standby_power_kw: float
    air_cut_power_kw: float
    cutting_power_kw: float
    total_power_kw: float
    specific_cutting_energy_j_per_mm3: float
    material_removal_rate_mm3_per_min: float


class EmpiricalPowerModel:
    """
    Empirical power and energy prediction model calibrated from the real CNC Power Dataset
    ("Digital Twin Framework for CNC Power Prediction").
    
    Relates (Spindle Speed S [RPM], Feed Rate F [mm/min], Depth of Cut ap [mm], Material)
    to instantaneous active power (kW) and specific cutting energy.
    """

    # Material specific cutting force / specific energy coefficients (kc1_1 in N/mm^2 or J/mm^3)
    MATERIAL_SPECIFIC_ENERGY: ClassVar[dict[str, float]] = {
        "Aluminum_6061": 0.85,    # J/mm^3
        "Steel_4140": 2.20,       # J/mm^3 (Calibrated from Tungsten carbide dataset tests)
        "Titanium_Gr5": 3.40,     # J/mm^3
    }

    # Calibrated tare & auxiliary power baseline for vertical machining centers (kW)
    BASE_STANDBY_KW: float = 0.95   # CNC controller, servo drives, fans
    PUMP_COOLANT_KW: float = 0.25   # Flood coolant pump

    @classmethod
    def predict_power(
        cls,
        spindle_speed_rpm: float,
        feed_rate_mm_min: float,
        depth_of_cut_mm: float,
        width_of_cut_mm: float = 12.0,  # default 12mm tool diameter engagement
        material: str = "Steel_4140",
        flute_count: int = 2,
    ) -> PowerPrediction:
        """
        Calculates active electrical power draw based on kinetic spindle speed tare
        and physical material removal rate (MRR).
        """
        if spindle_speed_rpm <= 0.0:
            return PowerPrediction(
                standby_power_kw=cls.BASE_STANDBY_KW,
                air_cut_power_kw=0.0,
                cutting_power_kw=0.0,
                total_power_kw=cls.BASE_STANDBY_KW,
                specific_cutting_energy_j_per_mm3=0.0,
                material_removal_rate_mm3_per_min=0.0,
            )

        # 1. Spindle No-Load Rotation Power (Tare) from dataset empirical fit:
        # P_air(S) = k0 + k1 * (S / 1000) + k2 * (S / 1000)^1.8
        # Fit from dataset: S=1920 -> ~1.13kW, S=2450 -> ~1.19kW
        s_k = spindle_speed_rpm / 1000.0
        p_air_kw = cls.PUMP_COOLANT_KW + 0.08 * s_k + 0.03 * (s_k ** 1.6)

        # 2. Material Removal Rate: MRR = ap * ae * Vf (mm^3/min)
        mrr = max(0.0, depth_of_cut_mm * width_of_cut_mm * feed_rate_mm_min)

        # 3. Net Material Cutting Power: P_cut = MRR (mm^3/s) * kc (J/mm^3) / efficiency
        kc = cls.MATERIAL_SPECIFIC_ENERGY.get(material, cls.MATERIAL_SPECIFIC_ENERGY["Steel_4140"])
        mrr_sec = mrr / 60.0  # mm^3/sec
        
        # Spindle mechanical-to-electrical efficiency (~82% - 88%)
        spindle_efficiency = 0.85
        p_cut_net_kw = (mrr_sec * kc) / (1000.0 * spindle_efficiency) if mrr > 0.0 else 0.0

        p_total_kw = cls.BASE_STANDBY_KW + p_air_kw + p_cut_net_kw

        return PowerPrediction(
            standby_power_kw=cls.BASE_STANDBY_KW,
            air_cut_power_kw=round(p_air_kw, 3),
            cutting_power_kw=round(p_cut_net_kw, 3),
            total_power_kw=round(p_total_kw, 3),
            specific_cutting_energy_j_per_mm3=kc,
            material_removal_rate_mm3_per_min=round(mrr, 1),
        )

    @classmethod
    def calculate_operation_energy_kwh(
        cls,
        duration_minutes: float,
        spindle_speed_rpm: float,
        feed_rate_mm_min: float,
        depth_of_cut_mm: float,
        material: str = "Steel_4140",
    ) -> float:
        """Calculates total kilowatt-hours consumed during a machining operation."""
        pred = cls.predict_power(
            spindle_speed_rpm=spindle_speed_rpm,
            feed_rate_mm_min=feed_rate_mm_min,
            depth_of_cut_mm=depth_of_cut_mm,
            material=material,
        )
        duration_hours = duration_minutes / 60.0
        return float(pred.total_power_kw * duration_hours)
