from __future__ import annotations

from enum import IntEnum, StrEnum


class SpindleState(StrEnum):
    """Mutually exclusive states of a CNC VMC spindle."""

    CUTTING = "CUTTING"
    SETUP = "SETUP"
    TOOL_CHANGE = "TOOL_CHANGE"
    IDLE_STARVED = "IDLE_STARVED"
    IDLE_WAIT_SETUP = "IDLE_WAIT_SETUP"
    IDLE_WAIT_TOOL = "IDLE_WAIT_TOOL"
    IDLE_WAIT_OPERATOR = "IDLE_WAIT_OPERATOR"
    IDLE_WAIT_FIXTURE = "IDLE_WAIT_FIXTURE"
    BREAKDOWN = "BREAKDOWN"
    PLANNED_MAINT = "PLANNED_MAINT"
    OFF_SHIFT = "OFF_SHIFT"


class CauseCode(StrEnum):
    """Detailed causal categorization for idle, setup, or breakdown states."""

    NONE = "NONE"
    NO_QUEUE_JOB = "NO_QUEUE_JOB"
    OPERATOR_UNAVAILABLE = "OPERATOR_UNAVAILABLE"
    TOOL_CRIB_EMPTY = "TOOL_CRIB_EMPTY"
    TOOL_WORN_OUT = "TOOL_WORN_OUT"
    FIXTURE_IN_USE = "FIXTURE_IN_USE"
    SPINDLE_BEARING_FAULT = "SPINDLE_BEARING_FAULT"
    COOLANT_PUMP_FAILURE = "COOLANT_PUMP_FAILURE"
    CHIP_CONVEYOR_JAM = "CHIP_CONVEYOR_JAM"
    SCHEDULED_LUBRICATION = "SCHEDULED_LUBRICATION"
    SHIFT_END = "SHIFT_END"
    MEAL_BREAK = "MEAL_BREAK"


class RuleSeverity(StrEnum):
    """Severity classification for expert diagnostic findings."""

    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class SkillLevel(IntEnum):
    """Operator proficiency tier affecting setup duration."""

    JUNIOR = 1
    STANDARD = 2
    SENIOR = 3

    def setup_multiplier(self) -> float:
        match self:
            case SkillLevel.JUNIOR:
                return 1.25
            case SkillLevel.STANDARD:
                return 1.00
            case SkillLevel.SENIOR:
                return 0.80
