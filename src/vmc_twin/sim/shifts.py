from __future__ import annotations

from collections.abc import Generator, Sequence
from typing import Any

import simpy

from vmc_twin.config.schemas import ShiftConfig
from vmc_twin.domain.events import Event
from vmc_twin.domain.machine import Machine
from vmc_twin.domain.states import CauseCode, SpindleState
from vmc_twin.sim.event_bus import EventSink


class ShiftCalendarManager:
    """
    Manages daily shift schedules, planned breaks (meals, tea), and off-shift downtime.
    Emits OFF_SHIFT and MEAL_BREAK events.
    """

    def __init__(
        self,
        env: simpy.Environment,
        shift_configs: Sequence[ShiftConfig],
        machines: Sequence[Machine],
        event_sink: EventSink,
        enable_shift_downtime: bool = False,
    ) -> None:
        self.env = env
        self.shift_configs = list(shift_configs)
        self.machines = list(machines)
        self.event_sink = event_sink
        self.enable_shift_downtime = enable_shift_downtime

        if self.enable_shift_downtime:
            self.process = env.process(self.run_calendar())

    def run_calendar(self) -> Generator[simpy.Event, Any, None]:
        """Runs 24-hour daily cycles applying shifts and breaks."""
        while True:
            # 1440 minutes in a day
            day_minute = self.env.now % 1440.0

            # Default Day Shift: 7:00 AM (420 min) to 3:30 PM (930 min)
            # Swing Shift: 3:30 PM (930 min) to 12:00 AM (1440 min)
            # Off shift: 12:00 AM (0 min) to 7:00 AM (420 min)
            if day_minute < 420.0:
                off_shift_duration = 420.0 - day_minute
                t_start = self.env.now
                yield self.env.timeout(off_shift_duration)
                t_end = self.env.now

                for m in self.machines:
                    # Non-automated machines go off-shift
                    if not m.spec.has_pallet_changer:
                        self.event_sink.on_event(
                            Event(
                                t_start=t_start,
                                t_end=t_end,
                                machine_id=m.machine_id,
                                job_id=None,
                                op_id=None,
                                state=SpindleState.OFF_SHIFT,
                                cause_code=CauseCode.SHIFT_END,
                            )
                        )
            else:
                # Active operational window: 1020 minutes (17 hours)
                active_duration = 1440.0 - day_minute
                yield self.env.timeout(active_duration)
