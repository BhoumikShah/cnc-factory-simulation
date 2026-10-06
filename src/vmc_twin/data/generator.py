from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from vmc_twin.domain.job import Job
from vmc_twin.domain.operation import Operation, ToolRequirement


class SyntheticDataGenerator:
    """
    Deterministic, seeded generator creating realistic CNC work orders,
    multi-op routings, cutting durations, and due dates.
    """

    PART_TEMPLATES: Mapping[str, list[tuple[str, str, float, str, list[str]]]] = {
        # part_family: [(op_name, required_fixture, nominal_minutes, machine_type_req, [tool_types])]
        "AEROSPACE_BRACKET": [
            (
                "OP10_FACE_AND_DATUMS",
                "VISE_6INCH_DUAL",
                18.0,
                "VMC_3AXIS_STD",
                ["FACEMILL_50MM", "ENDMILL_12MM_CARBIDE"],
            ),
            (
                "OP20_POCKET_AND_HOLES",
                "VISE_6INCH_DUAL",
                32.0,
                "VMC_3AXIS_STD",
                ["ENDMILL_12MM_CARBIDE", "DRILL_8_5MM", "TAP_M10"],
            ),
            (
                "OP30_5AXIS_PROFILING",
                "TOMBSTONE_4SIDED",
                45.0,
                "VMC_5AXIS_HIGH_SPEED",
                ["BALLNOSE_6MM", "CHAMFER_MILL_45DEG"],
            ),
        ],
        "PRISMATIC_VALVE_BODY": [
            ("OP10_ROUGH_6FACES", "TOMBSTONE_4SIDED", 35.0, "VMC_3AXIS_HEAVY", ["FACEMILL_50MM"]),
            (
                "OP20_BORES_AND_PORTS",
                "CHUCK_4JAW_SCROLL",
                40.0,
                "VMC_3AXIS_HEAVY",
                ["ENDMILL_12MM_CARBIDE", "DRILL_8_5MM", "TAP_M10"],
            ),
            (
                "OP30_FINISH_PASSES",
                "VISE_6INCH_DUAL",
                15.0,
                "VMC_3AXIS_STD",
                ["CHAMFER_MILL_45DEG"],
            ),
        ],
        "IMPELLER_BLISK": [
            (
                "OP10_ROUGH_BLISK",
                "CHUCK_4JAW_SCROLL",
                50.0,
                "VMC_5AXIS_HIGH_SPEED",
                ["FACEMILL_50MM", "ENDMILL_12MM_CARBIDE"],
            ),
            (
                "OP20_5AXIS_BLADES",
                "CHUCK_4JAW_SCROLL",
                90.0,
                "VMC_5AXIS_HIGH_SPEED",
                ["BALLNOSE_6MM"],
            ),
            (
                "OP30_CHAMFER_DEBURR",
                "CHUCK_4JAW_SCROLL",
                12.0,
                "VMC_3AXIS_STD",
                ["CHAMFER_MILL_45DEG"],
            ),
        ],
        "THINWALL_COVER_PLATE": [
            ("OP10_SURFACE_GRID", "VACUUM_FIXTURE_PLATE", 22.0, "VMC_3AXIS_STD", ["FACEMILL_50MM"]),
            (
                "OP20_PERIMETER_SLOTS",
                "VACUUM_FIXTURE_PLATE",
                28.0,
                "VMC_3AXIS_STD",
                ["ENDMILL_12MM_CARBIDE", "CHAMFER_MILL_45DEG"],
            ),
        ],
    }

    MATERIAL_WEAR_FACTORS: Mapping[str, float] = {
        "Aluminum_6061": 0.4,
        "Steel_4140": 1.0,
        "Titanium_Gr5": 2.5,
    }

    def __init__(self, random_seed: int = 42) -> None:
        self.rng = np.random.default_rng(random_seed)

    def generate_jobs(
        self,
        count: int = 500,
        horizon_minutes: float = 43200.0,
        workpiece_mix: Mapping[str, float] | None = None,
    ) -> list[Job]:
        """Generates synthetic work orders distributed across the simulation horizon."""
        if workpiece_mix is None:
            workpiece_mix = {"Aluminum_6061": 0.5, "Steel_4140": 0.3, "Titanium_Gr5": 0.2}

        materials = list(workpiece_mix.keys())
        mat_probs = np.array(list(workpiece_mix.values()), dtype=np.float64)
        mat_probs /= mat_probs.sum()

        part_types = list(self.PART_TEMPLATES.keys())
        jobs: list[Job] = []

        # Generate arrival times using a Poisson arrival process (exponential inter-arrivals)
        mean_interarrival = (horizon_minutes * 0.85) / count
        current_arrival = 0.0

        for i in range(count):
            current_arrival += float(self.rng.exponential(scale=mean_interarrival))
            release_time = round(current_arrival, 2)

            part_type = str(self.rng.choice(part_types))
            material = str(self.rng.choice(materials, p=mat_probs))
            material_factor = self.MATERIAL_WEAR_FACTORS.get(material, 1.0)
            priority = int(self.rng.choice([1, 2, 3, 4, 5], p=[0.1, 0.2, 0.4, 0.2, 0.1]))

            template_ops = self.PART_TEMPLATES[part_type]
            operations: list[Operation] = []
            total_processing_nominal = 0.0

            job_id = f"JOB-{i + 1:04d}"

            for seq_idx, (op_name, fix_req, nom_mins, mtype_req, req_tools) in enumerate(
                template_ops
            ):
                op_id = f"{job_id}-OP{seq_idx + 1}"
                # Add minor duration variance (+- 10%)
                adjusted_nominal = nom_mins * float(self.rng.uniform(0.9, 1.1))
                total_processing_nominal += adjusted_nominal

                tool_reqs = [
                    ToolRequirement(
                        tool_type=t_type,
                        cut_minutes=adjusted_nominal / len(req_tools),
                        wear_factor=material_factor,
                    )
                    for t_type in req_tools
                ]

                # Match allowed machine types
                allowed_types = [mtype_req]
                if mtype_req == "VMC_3AXIS_STD":
                    allowed_types.extend(["VMC_3AXIS_HEAVY", "VMC_5AXIS_HIGH_SPEED"])
                elif mtype_req == "VMC_3AXIS_HEAVY":
                    allowed_types.append("VMC_5AXIS_HIGH_SPEED")

                operations.append(
                    Operation(
                        op_id=op_id,
                        job_id=job_id,
                        sequence_num=seq_idx + 1,
                        name=op_name,
                        allowed_machine_types=allowed_types,
                        required_fixture=fix_req,
                        nominal_cycle_minutes=round(adjusted_nominal, 2),
                        cycle_time_cv=0.05,
                        tool_requirements=tool_reqs,
                        base_manual_setup_minutes=15.0,
                    )
                )

            # Due date is release_time + flow factor (3.0x to 8.0x nominal processing)
            flow_factor = float(self.rng.uniform(3.0, 7.0))
            due_date = round(release_time + total_processing_nominal * flow_factor, 2)

            jobs.append(
                Job(
                    job_id=job_id,
                    part_name=f"{part_type}_{material}",
                    material=material,
                    priority=priority,
                    release_time=release_time,
                    due_date=due_date,
                    operations=operations,
                    quantity=1,
                    weight_tardiness_penalty=float(priority),
                )
            )

        return jobs
