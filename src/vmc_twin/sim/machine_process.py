from __future__ import annotations

from collections.abc import Generator
from typing import Any

import simpy

from vmc_twin.domain.events import Event
from vmc_twin.domain.job import Job
from vmc_twin.domain.machine import Machine
from vmc_twin.domain.states import CauseCode, SpindleState
from vmc_twin.domain.tool import ToolInstance
from vmc_twin.sim.dispatcher import DispatchContext, DispatchPolicy
from vmc_twin.sim.event_bus import EventSink
from vmc_twin.sim.resources import ShopFloorResources
from vmc_twin.sim.rng import RNGManager


class MachineProcess:
    """
    SimPy state-machine process simulating a single Vertical Machining Center.
    Accurately captures setup transitions, tool wear, starvation, operator contention,
    and emits ordered, immutable Event records at every boundary.
    """

    def __init__(
        self,
        env: simpy.Environment,
        machine: Machine,
        resources: ShopFloorResources,
        dispatcher: DispatchPolicy,
        event_sink: EventSink,
        rng_manager: RNGManager,
        active_jobs: list[Job],
        completed_jobs: list[Job],
        in_progress_job_ids: set[str] | None = None,
    ) -> None:
        self.env = env
        self.machine = machine
        self.resources = resources
        self.dispatcher = dispatcher
        self.event_sink = event_sink
        self.rng = rng_manager.get_stream(f"machine_{machine.machine_id}")
        self.active_jobs = active_jobs
        self.completed_jobs = completed_jobs
        self.in_progress_job_ids = in_progress_job_ids if in_progress_job_ids is not None else set()

        # Spindle mounted tools: tool_type -> ToolInstance
        self.mounted_tools: dict[str, ToolInstance] = {}
        self.process = env.process(self.run())

    def run(self) -> Generator[simpy.Event, Any, None]:
        """Main spindle operational loop."""
        while True:
            # 1. Dispatching: Select next eligible Job and Operation
            context = DispatchContext(
                current_time=self.env.now,
                machine=self.machine,
                available_jobs=self.active_jobs,
                active_fixtures={self.machine.machine_id: self.machine.current_fixture or ""},
                tool_magazine=list(self.mounted_tools.keys()),
                in_progress_job_ids=frozenset(self.in_progress_job_ids),
            )

            candidate = self.dispatcher.select_next_job(context)

            # If no job is ready or eligible, wait and log IDLE_STARVED
            if candidate is None:
                t_starve_start = self.env.now
                self.machine.current_state = SpindleState.IDLE_STARVED
                # Wait 5 minutes or until next job arrives
                yield self.env.timeout(5.0)
                t_starve_end = self.env.now
                self.machine.accumulated_idle_minutes += (t_starve_end - t_starve_start)
                self.event_sink.on_event(
                    Event(
                        t_start=t_starve_start,
                        t_end=t_starve_end,
                        machine_id=self.machine.machine_id,
                        job_id=None,
                        op_id=None,
                        state=SpindleState.IDLE_STARVED,
                        cause_code=CauseCode.NO_QUEUE_JOB,
                    )
                )
                continue

            job, operation = candidate

            # Check if job release time is in the future
            if job.release_time > self.env.now:
                wait_time = job.release_time - self.env.now
                t_wait_start = self.env.now
                self.machine.current_state = SpindleState.IDLE_STARVED
                yield self.env.timeout(wait_time)
                t_wait_end = self.env.now
                self.machine.accumulated_idle_minutes += (t_wait_end - t_wait_start)
                self.event_sink.on_event(
                    Event(
                        t_start=t_wait_start,
                        t_end=t_wait_end,
                        machine_id=self.machine.machine_id,
                        job_id=job.job_id,
                        op_id=operation.op_id,
                        state=SpindleState.IDLE_STARVED,
                        cause_code=CauseCode.NO_QUEUE_JOB,
                    )
                )
                continue

            # Mark job as in-progress to prevent race conditions with other spindles
            self.in_progress_job_ids.add(job.job_id)

            try:
                # 2. Setup Phase: Fixture setup and operator acquisition
                needed_fixture = operation.required_fixture
                needs_fixture_change = (self.machine.current_fixture != needed_fixture)

                if needs_fixture_change:
                    t_wait_setup = self.env.now
                    self.machine.current_state = SpindleState.IDLE_WAIT_SETUP

                    # Request operator resource for setup
                    op_request = self.resources.operator_resource.request()
                    yield op_request

                    t_operator_acquired = self.env.now
                    if t_operator_acquired > t_wait_setup:
                        self.machine.accumulated_idle_minutes += (t_operator_acquired - t_wait_setup)
                        self.event_sink.on_event(
                            Event(
                                t_start=t_wait_setup,
                                t_end=t_operator_acquired,
                                machine_id=self.machine.machine_id,
                                job_id=job.job_id,
                                op_id=operation.op_id,
                                state=SpindleState.IDLE_WAIT_OPERATOR,
                                cause_code=CauseCode.OPERATOR_UNAVAILABLE,
                            )
                        )

                    # Compute sequence-dependent setup time
                    base_setup = self.resources.transition_matrix.get_setup_time(
                        from_fixture=self.machine.current_fixture,
                        to_fixture=needed_fixture,
                    )
                    if base_setup == 0.0:
                        base_setup = operation.base_manual_setup_minutes

                    # Apply Pallet APC modifier if applicable
                    pallet_mod = self.machine.spec.pallet_setup_factor if self.machine.spec.has_pallet_changer else 1.0
                    setup_duration = base_setup * pallet_mod

                    t_setup_start = self.env.now
                    self.machine.current_state = SpindleState.SETUP
                    yield self.env.timeout(setup_duration)
                    t_setup_end = self.env.now

                    self.machine.accumulated_setup_minutes += (t_setup_end - t_setup_start)
                    self.machine.current_fixture = needed_fixture
                    self.resources.operator_resource.release(op_request)

                    self.event_sink.on_event(
                        Event(
                            t_start=t_setup_start,
                            t_end=t_setup_end,
                            machine_id=self.machine.machine_id,
                            job_id=job.job_id,
                            op_id=operation.op_id,
                            state=SpindleState.SETUP,
                            cause_code=CauseCode.NONE,
                            metadata={
                                "fixture": needed_fixture,
                                "pallet_apc": self.machine.spec.has_pallet_changer,
                                "base_setup_min": base_setup,
                            },
                        )
                    )

                # 3. Tool Verification & Loading Phase
                for req_tool in operation.tool_requirements:
                    t_type = req_tool.tool_type
                    if t_type not in self.mounted_tools or self.mounted_tools[t_type].is_worn_out:
                        t_tool_req = self.env.now
                        if not self.resources.has_tool_in_crib(t_type):
                            self.machine.current_state = SpindleState.IDLE_WAIT_TOOL
                            # Wait for crib replenishment
                            yield self.env.timeout(10.0)
                            t_tool_ready = self.env.now
                            self.machine.accumulated_idle_minutes += (t_tool_ready - t_tool_req)
                            self.event_sink.on_event(
                                Event(
                                    t_start=t_tool_req,
                                    t_end=t_tool_ready,
                                    machine_id=self.machine.machine_id,
                                    job_id=job.job_id,
                                    op_id=operation.op_id,
                                    state=SpindleState.IDLE_WAIT_TOOL,
                                    cause_code=CauseCode.TOOL_CRIB_EMPTY,
                                    metadata={"missing_tool_type": t_type},
                                )
                            )

                        tool_inst = self.resources.checkout_tool(t_type)
                        if tool_inst is None:
                            spec = self.resources.tool_specs.get(t_type)
                            life = spec.nominal_life_minutes if spec else 120.0
                            tool_inst = ToolInstance(
                                tool_id=f"{t_type}_AUTO",
                                tool_type=t_type,
                                life_limit_minutes=life,
                            )

                        self.mounted_tools[t_type] = tool_inst

                        t_tc_start = self.env.now
                        tc_duration = 0.1 if self.machine.spec.magazine_capacity > len(self.mounted_tools) else 2.5
                        yield self.env.timeout(tc_duration)
                        t_tc_end = self.env.now
                        self.event_sink.on_event(
                            Event(
                                t_start=t_tc_start,
                                t_end=t_tc_end,
                                machine_id=self.machine.machine_id,
                                job_id=job.job_id,
                                op_id=operation.op_id,
                                state=SpindleState.TOOL_CHANGE,
                                cause_code=CauseCode.NONE,
                                metadata={"tool_type": t_type, "tool_id": tool_inst.tool_id},
                            )
                        )

                # 4. Machining / Cutting Phase
                mean_duration = operation.nominal_cycle_minutes
                cv = operation.cycle_time_cv
                sigma = (cv**2 + 1.0) ** 0.5
                mu = mean_duration / sigma
                actual_duration = float(self.rng.lognormal(mean=mu, sigma=cv))
                actual_duration = max(mean_duration * 0.5, min(mean_duration * 2.0, actual_duration))

                t_cut_start = self.env.now
                self.machine.current_state = SpindleState.CUTTING
                yield self.env.timeout(actual_duration)
                t_cut_end = self.env.now

                self.machine.accumulated_cutting_minutes += (t_cut_end - t_cut_start)

                for req_tool in operation.tool_requirements:
                    t_type = req_tool.tool_type
                    if t_type in self.mounted_tools:
                        self.mounted_tools[t_type].record_wear(
                            cut_minutes=actual_duration / len(operation.tool_requirements),
                            material_factor=req_tool.wear_factor,
                        )

                self.event_sink.on_event(
                    Event(
                        t_start=t_cut_start,
                        t_end=t_cut_end,
                        machine_id=self.machine.machine_id,
                        job_id=job.job_id,
                        op_id=operation.op_id,
                        state=SpindleState.CUTTING,
                        cause_code=CauseCode.NONE,
                        metadata={
                            "part_name": job.part_name,
                            "material": job.material,
                            "nominal_duration": operation.nominal_cycle_minutes,
                            "actual_duration": round(actual_duration, 2),
                        },
                    )
                )

                # 5. Operation Completion & Safe State Update
                job_idx = next((i for i, j in enumerate(self.active_jobs) if j.job_id == job.job_id), None)
                if job_idx is not None:
                    current_job = self.active_jobs[job_idx]
                    remaining_ops = [op for op in current_job.operations if op.op_id != operation.op_id]
                    if remaining_ops:
                        updated_job = Job(
                            job_id=current_job.job_id,
                            part_name=current_job.part_name,
                            material=current_job.material,
                            priority=current_job.priority,
                            release_time=current_job.release_time,
                            due_date=current_job.due_date,
                            operations=remaining_ops,
                            quantity=current_job.quantity,
                            weight_tardiness_penalty=current_job.weight_tardiness_penalty,
                        )
                        self.active_jobs[job_idx] = updated_job
                    else:
                        # Fully completed!
                        self.active_jobs.pop(job_idx)
                        self.completed_jobs.append(current_job)
                        self.machine.total_parts_produced += current_job.quantity
            finally:
                # Release in-progress lock on the job
                self.in_progress_job_ids.discard(job.job_id)
