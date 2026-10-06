from vmc_twin.data.store import EventStore
from vmc_twin.domain.events import Event
from vmc_twin.domain.states import CauseCode, SpindleState


def test_event_store_in_memory() -> None:
    store = EventStore(":memory:")
    assert store.count_events() == 0

    events = [
        Event(
            t_start=0.0,
            t_end=15.0,
            machine_id="VMC-01",
            job_id="JOB-01",
            op_id="OP1",
            state=SpindleState.CUTTING,
            cause_code=CauseCode.NONE,
        ),
        Event(
            t_start=15.0,
            t_end=20.0,
            machine_id="VMC-01",
            job_id=None,
            op_id=None,
            state=SpindleState.IDLE_STARVED,
            cause_code=CauseCode.NO_QUEUE_JOB,
        ),
    ]

    store.insert_events(events)
    assert store.count_events() == 2

    retrieved = store.get_all_events()
    assert len(retrieved) == 2
    assert retrieved[0].state == SpindleState.CUTTING
    assert retrieved[1].state == SpindleState.IDLE_STARVED

    # Window query
    window_evts = store.get_events_in_window(5.0, 10.0)
    assert len(window_evts) == 1
    assert window_evts[0].job_id == "JOB-01"

    store.close()
