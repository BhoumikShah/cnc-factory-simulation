from __future__ import annotations

from collections.abc import Generator
from typing import Any

import simpy

from vmc_twin.domain.events import Event
from vmc_twin.domain.machine import Machine
from vmc_twin.domain.states import CauseCode, SpindleState
from vmc_twin.sim.event_bus import EventSink
from vmc_twin.sim.rng import RNGManager


class BreakdownProcess:
    """
    Simulates stochastic machine breakdowns (MTBF) and maintenance repairs (MTTR).
    MTBF follows an exponential distribution based on cutting hours.
    MTTR follows a lognormal repair distribution requiring a maintenance resource.
    """

    def __init__(
        self,
        env: simpy.Environment,
        machine: Machine,
        maintenance_resource: simpy.Resource,
        event_sink: EventSink,
        rng_manager: RNGManager,
    ) -> None:
        self.env = env
        self.machine = machine
        self.maintenance_resource = maintenance_resource
        self.event_sink = event_sink
        self.rng = rng_manager.get_stream(f"breakdown_{machine.machine_id}")

        # Mean Time Between Failures in minutes
        self.mtbf_minutes = max(60.0, machine.spec.mtbf_hours * 60.0)
        self.mttr_mean_minutes = max(5.0, machine.spec.mttr_minutes)

        self.process = env.process(self.run())

    def run(self) -> Generator[simpy.Event, Any, None]:
        while True:
            # Draw time until next breakdown (exponential)
            time_to_fail = float(self.rng.exponential(scale=self.mtbf_minutes))
            yield self.env.timeout(time_to_fail)

            # Initiate Breakdown
            t_fail_start = self.env.now
            self.machine.current_state = SpindleState.BREAKDOWN

            # Request maintenance technician
            maint_req = self.maintenance_resource.request()
            yield maint_req

            # Draw repair duration (lognormal with CV = 0.25)
            cv = 0.25
            sigma = (cv**2 + 1.0) ** 0.5
            mu = self.mttr_mean_minutes / sigma
            repair_duration = float(self.rng.lognormal(mean=mu, sigma=cv))
            repair_duration = max(5.0, min(self.mttr_mean_minutes * 3.0, repair_duration))

            yield self.env.timeout(repair_duration)
            t_fail_end = self.env.now

            self.machine.accumulated_breakdown_minutes += t_fail_end - t_fail_start
            self.maintenance_resource.release(maint_req)

            # Log breakdown event
            self.event_sink.on_event(
                Event(
                    t_start=t_fail_start,
                    t_end=t_fail_end,
                    machine_id=self.machine.machine_id,
                    job_id=None,
                    op_id=None,
                    state=SpindleState.BREAKDOWN,
                    cause_code=CauseCode.SPINDLE_BEARING_FAULT,
                    metadata={
                        "repair_minutes": round(repair_duration, 2),
                        "mtbf_spec_hours": self.machine.spec.mtbf_hours,
                    },
                )
            )
