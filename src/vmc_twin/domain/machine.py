from __future__ import annotations

from dataclasses import dataclass, field

from vmc_twin.domain.states import SpindleState


@dataclass(frozen=True, slots=True)
class MachineSpec:
    """Static capabilities and configuration of a Vertical Machining Center."""
    machine_id: str
    machine_type: str
    spindle_power_kw: float
    max_spindle_rpm: float
    magazine_capacity: int
    has_pallet_changer: bool
    mtbf_hours: float  # Mean Time Between Failures
    mttr_minutes: float  # Mean Time To Repair
    hourly_rate_usd: float = 85.0
    pallet_setup_factor: float = 0.3  # APC reduces setup time to 30%


@dataclass(slots=True)
class Machine:
    """Dynamic operational state of a physical VMC unit."""
    spec: MachineSpec
    current_state: SpindleState = SpindleState.OFF_SHIFT
    current_fixture: str | None = None
    mounted_tool_ids: list[str] = field(default_factory=list)
    accumulated_cutting_minutes: float = 0.0
    accumulated_idle_minutes: float = 0.0
    accumulated_setup_minutes: float = 0.0
    accumulated_breakdown_minutes: float = 0.0
    total_parts_produced: int = 0

    @property
    def machine_id(self) -> str:
        return self.spec.machine_id

    @property
    def machine_type(self) -> str:
        return self.spec.machine_type
