from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar

import numpy as np
from scipy import integrate, optimize, special


class WearRiskLevel(StrEnum):
    """Categorized risk level for cutting tool degradation."""

    NOMINAL = "NOMINAL"
    MONITOR = "MONITOR"
    MAINTENANCE_REQUIRED = "MAINTENANCE_REQUIRED"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class TaylorParameters:
    """Parameters for Extended Taylor tool life equation V * T^n * f^a * d^b = C."""

    n: float  # Taylor exponent (typically 0.20 - 0.35 for carbide)
    C: float  # Taylor cutting speed constant (m/min for 1 min life)
    a: float = 0.15  # Feed exponent
    b: float = 0.10  # Depth of cut exponent


@dataclass(frozen=True)
class ToolPrognosticAssessment:
    """Prognostic health assessment for a specific tool instance."""

    tool_id: str
    tool_type: str
    accumulated_cut_minutes: float
    expected_rul_minutes: float
    next_op_duration_minutes: float
    p_fail_next_operation: float
    flank_wear_vb_mm: float
    flank_wear_limit_mm: float
    risk_level: WearRiskLevel
    recommendation: str


class TaylorToolLifeModel:
    """Extended Taylor Tool Life equation calculator with workpiece material factors."""

    # Default Taylor parameters by workpiece material for carbide tooling
    DEFAULT_MATERIAL_PARAMS: ClassVar[dict[str, TaylorParameters]] = {
        "Aluminum_6061": TaylorParameters(n=0.35, C=850.0, a=0.12, b=0.08),
        "Steel_4140": TaylorParameters(n=0.25, C=320.0, a=0.18, b=0.12),
        "Titanium_Gr5": TaylorParameters(n=0.18, C=140.0, a=0.22, b=0.15),
    }

    @classmethod
    def calculate_tool_life_minutes(
        cls,
        cutting_speed_mpm: float,
        feed_mm_per_rev: float = 0.15,
        depth_of_cut_mm: float = 2.0,
        material: str = "Steel_4140",
        custom_params: TaylorParameters | None = None,
    ) -> float:
        """Calculates expected tool life T (minutes) using V * T^n * f^a * d^b = C."""
        params = custom_params or cls.DEFAULT_MATERIAL_PARAMS.get(
            material,
            cls.DEFAULT_MATERIAL_PARAMS["Steel_4140"],
        )

        if cutting_speed_mpm <= 0.0 or feed_mm_per_rev <= 0.0 or depth_of_cut_mm <= 0.0:
            return 0.0

        # V * T^n * f^a * d^b = C  =>  T^n = C / (V * f^a * d^b)  =>  T = (C / (V * f^a * d^b))^(1/n)
        denominator = cutting_speed_mpm * (feed_mm_per_rev**params.a) * (depth_of_cut_mm**params.b)
        if denominator <= 0.0:
            return 0.0

        ratio = params.C / denominator
        if ratio <= 0.0:
            return 0.0

        return float(ratio ** (1.0 / params.n))


class WeibullToolPrognostics:
    """Weibull distribution reliability and remaining useful life (RUL) estimator."""

    @staticmethod
    def reliability(t: float, shape_beta: float, scale_eta: float) -> float:
        """Reliability function R(t) = P(T > t) = exp(-(t/eta)^beta)."""
        if t <= 0.0:
            return 1.0
        if scale_eta <= 0.0 or shape_beta <= 0.0:
            return 0.0
        return float(math.exp(-((t / scale_eta) ** shape_beta)))

    @staticmethod
    def failure_probability(t: float, shape_beta: float, scale_eta: float) -> float:
        """Cumulative failure probability F(t) = 1 - R(t)."""
        return 1.0 - WeibullToolPrognostics.reliability(t, shape_beta, scale_eta)

    @staticmethod
    def conditional_failure_probability(
        current_age: float,
        delta_t: float,
        shape_beta: float,
        scale_eta: float,
    ) -> float:
        """Conditional probability of failure in [t, t + delta_t] given survival to t:

        P(t < T <= t + delta_t | T > t) = 1 - exp((t/eta)^beta - ((t + delta_t)/eta)^beta).
        """
        if delta_t <= 0.0:
            return 0.0
        current_age = max(current_age, 0.0)
        if scale_eta <= 0.0 or shape_beta <= 0.0:
            return 1.0

        t1 = (current_age / scale_eta) ** shape_beta
        t2 = ((current_age + delta_t) / scale_eta) ** shape_beta
        exponent_diff = t1 - t2

        if exponent_diff < -700:
            return 1.0
        return float(1.0 - math.exp(exponent_diff))

    @staticmethod
    def remaining_useful_life_expected(
        current_age: float,
        shape_beta: float,
        scale_eta: float,
    ) -> float:
        """Expected Remaining Useful Life (RUL) E[T - t | T > t] in minutes."""
        if current_age <= 0.0:
            # E[T] = eta * Gamma(1 + 1/beta)
            return float(scale_eta * special.gamma(1.0 + 1.0 / shape_beta))

        if scale_eta <= 0.0 or shape_beta <= 0.0:
            return 0.0

        # Numerically integrate R(u) from current_age to infinity / R(current_age)
        r_current = WeibullToolPrognostics.reliability(current_age, shape_beta, scale_eta)
        if r_current < 1e-9:
            return 0.0

        upper_bound = scale_eta * 3.0 + current_age
        num_steps = 100
        grid = np.linspace(current_age, upper_bound, num_steps)
        r_vals = np.array([WeibullToolPrognostics.reliability(u, shape_beta, scale_eta) for u in grid])
        integral = float(integrate.trapezoid(r_vals, grid))
        return max(0.0, float(integral / r_current))

    @staticmethod
    def estimate_weibull_mle(
        observed_lifetimes: Sequence[float],
    ) -> tuple[float, float]:
        """Maximum Likelihood Estimation of Weibull shape (beta) and scale (eta) parameters.

        Returns (shape_beta, scale_eta).
        """
        data = np.array([x for x in observed_lifetimes if x > 0.0], dtype=float)
        if len(data) < 2:
            return (3.0, float(np.mean(data)) if len(data) == 1 else 100.0)

        # Log-likelihood optimization for Weibull distribution
        def neg_log_likelihood(params: tuple[float, float]) -> float:
            beta, eta = params
            if beta <= 0.01 or eta <= 0.01:
                return 1e12
            n = len(data)
            ll = (
                n * np.log(beta)
                - n * beta * np.log(eta)
                + (beta - 1.0) * np.sum(np.log(data))
                - np.sum((data / eta) ** beta)
            )
            return float(-ll)

        initial_beta = 2.5
        initial_eta = float(np.mean(data))
        res = optimize.minimize(
            neg_log_likelihood,
            x0=np.array([initial_beta, initial_eta]),
            bounds=[(0.1, 20.0), (1.0, 10000.0)],
            method="L-BFGS-B",
        )

        if res.success:
            return (float(res.x[0]), float(res.x[1]))
        return (initial_beta, initial_eta)


class FlankWearDegradationModel:
    """ISO 3685 Flank Wear (VB) Progression Model.

    VB(t) = VB_0 + k_wear * t^gamma (progressive tool wear with rapid terminal acceleration).
    """

    DEFAULT_VB_LIMIT_MM: float = 0.30  # Standard catastrophic wear threshold

    @classmethod
    def estimate_flank_wear_mm(
        cls,
        cut_minutes: float,
        nominal_life_minutes: float,
        vb_limit_mm: float = DEFAULT_VB_LIMIT_MM,
        initial_vb_mm: float = 0.02,
        gamma: float = 1.4,
    ) -> float:
        """Calculates current flank wear VB (mm) based on cutting duration."""
        if cut_minutes <= 0.0:
            return initial_vb_mm
        if nominal_life_minutes <= 0.0:
            return vb_limit_mm

        wear_fraction = cut_minutes / nominal_life_minutes
        flank_wear = initial_vb_mm + (vb_limit_mm - initial_vb_mm) * (wear_fraction**gamma)
        return float(min(flank_wear, vb_limit_mm * 1.5))


class ToolReplacementRecommender:
    """Analyzes cutting tool inventory & state to generate proactive replacement schedules."""

    @classmethod
    def evaluate_tool(
        cls,
        tool_id: str,
        tool_type: str,
        accumulated_cut_minutes: float,
        nominal_life_minutes: float,
        weibull_shape: float,
        weibull_scale: float,
        next_op_duration_minutes: float = 15.0,
        max_failure_prob_threshold: float = 0.15,
        flank_wear_limit_mm: float = 0.30,
    ) -> ToolPrognosticAssessment:
        """Evaluates single tool instance and recommends proactive actions."""
        p_fail = WeibullToolPrognostics.conditional_failure_probability(
            current_age=accumulated_cut_minutes,
            delta_t=next_op_duration_minutes,
            shape_beta=weibull_shape,
            scale_eta=weibull_scale,
        )

        rul = WeibullToolPrognostics.remaining_useful_life_expected(
            current_age=accumulated_cut_minutes,
            shape_beta=weibull_shape,
            scale_eta=weibull_scale,
        )

        flank_wear = FlankWearDegradationModel.estimate_flank_wear_mm(
            cut_minutes=accumulated_cut_minutes,
            nominal_life_minutes=nominal_life_minutes,
            vb_limit_mm=flank_wear_limit_mm,
        )

        # Risk level determination
        if flank_wear >= flank_wear_limit_mm or p_fail >= 0.40 or rul <= 0.0:
            risk = WearRiskLevel.CRITICAL
            rec = (
                f"CRITICAL: Tool {tool_id} exceeds wear limit ({flank_wear:.2f}mm / "
                f"{flank_wear_limit_mm:.2f}mm) or failure risk ({p_fail * 100:.1f}%). Replace immediately before next cut."
            )
        elif p_fail >= max_failure_prob_threshold or rul < next_op_duration_minutes:
            risk = WearRiskLevel.MAINTENANCE_REQUIRED
            rec = (
                f"REPLACE: Predicted RUL ({rul:.1f}m) insufficient for next operation ({next_op_duration_minutes:.1f}m) "
                f"with failure risk {p_fail * 100:.1f}%. Stage replacement from crib."
            )
        elif p_fail >= 0.05 or flank_wear >= flank_wear_limit_mm * 0.75:
            risk = WearRiskLevel.MONITOR
            rec = f"MONITOR: Tool has {rul:.1f}m expected RUL. Flank wear {flank_wear:.2f}mm. Proceed with standard monitoring."
        else:
            risk = WearRiskLevel.NOMINAL
            rec = f"HEALTHY: Tool {tool_id} is in nominal state with {rul:.1f}m RUL (failure risk {p_fail * 100:.2f}%)."

        return ToolPrognosticAssessment(
            tool_id=tool_id,
            tool_type=tool_type,
            accumulated_cut_minutes=accumulated_cut_minutes,
            expected_rul_minutes=rul,
            next_op_duration_minutes=next_op_duration_minutes,
            p_fail_next_operation=p_fail,
            flank_wear_vb_mm=flank_wear,
            flank_wear_limit_mm=flank_wear_limit_mm,
            risk_level=risk,
            recommendation=rec,
        )
