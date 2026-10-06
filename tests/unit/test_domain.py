from vmc_twin.domain.events import Event
from vmc_twin.domain.fixture import FixtureTransitionMatrix
from vmc_twin.domain.states import SkillLevel, SpindleState
from vmc_twin.domain.tool import ToolInstance


def test_tool_wear_accrual() -> None:
    tool = ToolInstance(tool_id="T01", tool_type="ENDMILL", life_limit_minutes=100.0)
    assert tool.remaining_life == 100.0
    assert not tool.is_worn_out

    # Machine aluminum (0.4 factor) for 50 minutes -> 20 min effective wear
    rem = tool.record_wear(cut_minutes=50.0, material_factor=0.4)
    assert rem == 80.0
    assert tool.accumulated_cut_minutes == 20.0
    assert not tool.is_worn_out

    # Machine titanium (2.5 factor) for 35 minutes -> 87.5 min effective wear -> total 107.5 min (exceeds 100)
    rem2 = tool.record_wear(cut_minutes=35.0, material_factor=2.5)
    assert rem2 == 0.0
    assert tool.is_worn_out


def test_fixture_transition_matrix() -> None:
    matrix = FixtureTransitionMatrix(
        transitions={
            "F1": {"F2": 25.0, "F1": 0.0},
            "F2": {"F1": 20.0, "F2": 0.0},
        },
        default_setup_minutes=15.0,
    )
    assert matrix.get_setup_time("F1", "F1") == 0.0
    assert matrix.get_setup_time(None, "F1") == 0.0
    assert matrix.get_setup_time("F1", "F2") == 25.0
    assert matrix.get_setup_time("F2", "F1") == 20.0
    assert matrix.get_setup_time("F1", "F3") == 15.0  # default fallback


def test_event_duration_and_helpers() -> None:
    evt = Event(
        t_start=10.0,
        t_end=25.5,
        machine_id="VMC-01",
        job_id="JOB-01",
        op_id="OP1",
        state=SpindleState.CUTTING,
    )
    assert evt.duration() == 15.5
    assert evt.is_cutting()
    assert not evt.is_setup()
    assert not evt.is_idle()
    assert not evt.is_down()


def test_skill_level_multipliers() -> None:
    assert SkillLevel.JUNIOR.setup_multiplier() == 1.25
    assert SkillLevel.STANDARD.setup_multiplier() == 1.00
    assert SkillLevel.SENIOR.setup_multiplier() == 0.80
