from __future__ import annotations

import math

from vmc_twin.predict.tool_wear import (
    FlankWearDegradationModel,
    TaylorParameters,
    TaylorToolLifeModel,
    ToolReplacementRecommender,
    WearRiskLevel,
    WeibullToolPrognostics,
)


def test_taylor_tool_life_calculation() -> None:
    # 1. Standard Steel 4140: V=150 m/min, f=0.15 mm/rev, d=2.0 mm
    t_steel = TaylorToolLifeModel.calculate_tool_life_minutes(
        cutting_speed_mpm=150.0,
        feed_mm_per_rev=0.15,
        depth_of_cut_mm=2.0,
        material="Steel_4140",
    )
    assert t_steel > 0.0

    # 2. Higher cutting speed should result in shorter tool life
    t_steel_fast = TaylorToolLifeModel.calculate_tool_life_minutes(
        cutting_speed_mpm=250.0,
        feed_mm_per_rev=0.15,
        depth_of_cut_mm=2.0,
        material="Steel_4140",
    )
    assert t_steel_fast < t_steel

    # 3. Custom Taylor parameters
    custom = TaylorParameters(n=0.30, C=500.0, a=0.10, b=0.10)
    t_custom = TaylorToolLifeModel.calculate_tool_life_minutes(
        cutting_speed_mpm=200.0,
        feed_mm_per_rev=0.1,
        depth_of_cut_mm=1.0,
        custom_params=custom,
    )
    assert t_custom > 0.0

    # 4. Zero/invalid inputs
    assert TaylorToolLifeModel.calculate_tool_life_minutes(0.0) == 0.0


def test_weibull_reliability_and_conditional_failure() -> None:
    beta = 3.0
    eta = 120.0

    # At t=0, reliability is 1.0 and failure prob is 0.0
    assert math.isclose(WeibullToolPrognostics.reliability(0.0, beta, eta), 1.0)
    assert math.isclose(WeibullToolPrognostics.failure_probability(0.0, beta, eta), 0.0)

    # At t=eta, reliability is exp(-1) ~= 0.367879
    r_eta = WeibullToolPrognostics.reliability(eta, beta, eta)
    assert math.isclose(r_eta, math.exp(-1.0), rel_tol=1e-5)

    # Conditional failure probability: at age 100m for next 20m cut
    p_cond = WeibullToolPrognostics.conditional_failure_probability(
        current_age=100.0, delta_t=20.0, shape_beta=beta, scale_eta=eta
    )
    assert 0.0 < p_cond < 1.0
    assert p_cond > WeibullToolPrognostics.failure_probability(20.0, beta, eta)


def test_weibull_expected_rul_and_mle() -> None:
    beta = 3.0
    eta = 120.0

    # RUL at age 0 should be approximately eta * Gamma(1 + 1/3) ~= 120 * 0.892979 = 107.15m
    rul_0 = WeibullToolPrognostics.remaining_useful_life_expected(0.0, beta, eta)
    assert 100.0 < rul_0 < 115.0

    # RUL at age 80m should decrease
    rul_80 = WeibullToolPrognostics.remaining_useful_life_expected(80.0, beta, eta)
    assert 0.0 < rul_80 < rul_0

    # Test MLE fitting on synthetic sample from Weibull(3.0, 150.0)
    samples = [125.0, 140.0, 155.0, 160.0, 130.0, 145.0, 170.0, 135.0]
    fit_beta, fit_eta = WeibullToolPrognostics.estimate_weibull_mle(samples)
    assert fit_beta > 1.0
    assert 100.0 < fit_eta < 200.0


def test_flank_wear_and_tool_recommender() -> None:
    # 1. Flank wear model
    vb_start = FlankWearDegradationModel.estimate_flank_wear_mm(
        cut_minutes=0.0, nominal_life_minutes=120.0
    )
    assert vb_start == 0.02

    vb_half = FlankWearDegradationModel.estimate_flank_wear_mm(
        cut_minutes=60.0, nominal_life_minutes=120.0
    )
    assert 0.02 < vb_half < 0.30

    # 2. Tool replacement recommender
    # Young tool -> NOMINAL
    eval_young = ToolReplacementRecommender.evaluate_tool(
        tool_id="TL-01",
        tool_type="ENDMILL_12MM_CARBIDE",
        accumulated_cut_minutes=15.0,
        nominal_life_minutes=120.0,
        weibull_shape=3.0,
        weibull_scale=130.0,
        next_op_duration_minutes=15.0,
    )
    assert eval_young.risk_level in (WearRiskLevel.NOMINAL, WearRiskLevel.MONITOR)

    # Heavily worn tool -> MAINTENANCE_REQUIRED or CRITICAL
    eval_worn = ToolReplacementRecommender.evaluate_tool(
        tool_id="TL-02",
        tool_type="ENDMILL_12MM_CARBIDE",
        accumulated_cut_minutes=128.0,
        nominal_life_minutes=120.0,
        weibull_shape=3.0,
        weibull_scale=130.0,
        next_op_duration_minutes=25.0,
    )
    assert eval_worn.risk_level in (WearRiskLevel.MAINTENANCE_REQUIRED, WearRiskLevel.CRITICAL)
    assert "Replace" in eval_worn.recommendation or "CRITICAL" in eval_worn.recommendation
