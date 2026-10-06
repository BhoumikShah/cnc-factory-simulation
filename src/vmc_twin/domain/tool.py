from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Specification of a CNC cutting tool class."""

    tool_type: str
    description: str
    nominal_life_minutes: float
    weibull_shape: float  # beta parameter (typically 2.5 - 3.5 for tool wear)
    weibull_scale: float  # eta parameter (characteristic life in minutes)
    base_change_time_minutes: float = 3.0
    auto_change_time_minutes: float = 0.1  # ATC magazine change


@dataclass(slots=True)
class ToolInstance:
    """Individual physical cutting tool tracking accumulated cut time."""

    tool_id: str
    tool_type: str
    accumulated_cut_minutes: float = 0.0
    life_limit_minutes: float = 120.0
    is_worn_out: bool = False

    def record_wear(self, cut_minutes: float, material_factor: float = 1.0) -> float:
        """Accrues wear based on cut time and material factor, returning remaining life."""
        effective_wear = cut_minutes * material_factor
        self.accumulated_cut_minutes += effective_wear
        if self.accumulated_cut_minutes >= self.life_limit_minutes:
            self.is_worn_out = True
        return max(0.0, self.life_limit_minutes - self.accumulated_cut_minutes)

    @property
    def remaining_life(self) -> float:
        return max(0.0, self.life_limit_minutes - self.accumulated_cut_minutes)


@dataclass(frozen=True, slots=True)
class ToolState:
    """Observed operational state of a tool for prognostic models."""

    tool_id: str
    tool_type: str
    accumulated_cut_minutes: float
    workpiece_material: str
    flute_count: int = 4
    feed_rate_factor: float = 1.0


@dataclass(frozen=True, slots=True)
class ToolLifeDistribution:
    """Predicted tool life probability parameters."""

    mean_remaining_minutes: float
    std_remaining_minutes: float
    p_failure_next_operation: float  # probability of failure during next planned cut
    confidence_interval_95: tuple[float, float]
