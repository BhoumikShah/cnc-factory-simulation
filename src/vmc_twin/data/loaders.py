from __future__ import annotations

import json
from pathlib import Path

from vmc_twin.domain.job import Job
from vmc_twin.domain.operation import Operation, ToolRequirement


class JobDataLoader:
    """Imports job routings and work orders from external CSV or JSON files."""

    @staticmethod
    def load_from_json(file_path: Path | str) -> list[Job]:
        p = Path(file_path)
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        jobs: list[Job] = []
        for j_dict in data:
            ops: list[Operation] = []
            for op_dict in j_dict.get("operations", []):
                tool_reqs = [
                    ToolRequirement(
                        tool_type=tr["tool_type"],
                        cut_minutes=tr["cut_minutes"],
                        wear_factor=tr.get("wear_factor", 1.0),
                    )
                    for tr in op_dict.get("tool_requirements", [])
                ]
                ops.append(
                    Operation(
                        op_id=op_dict["op_id"],
                        job_id=j_dict["job_id"],
                        sequence_num=op_dict["sequence_num"],
                        name=op_dict["name"],
                        allowed_machine_types=op_dict["allowed_machine_types"],
                        required_fixture=op_dict["required_fixture"],
                        nominal_cycle_minutes=op_dict["nominal_cycle_minutes"],
                        cycle_time_cv=op_dict.get("cycle_time_cv", 0.05),
                        required_power_kw=op_dict.get("required_power_kw", 7.5),
                        required_rpm=op_dict.get("required_rpm", 8000.0),
                        tool_requirements=tool_reqs,
                        base_manual_setup_minutes=op_dict.get("base_manual_setup_minutes", 10.0),
                    )
                )
            jobs.append(
                Job(
                    job_id=j_dict["job_id"],
                    part_name=j_dict["part_name"],
                    material=j_dict["material"],
                    priority=j_dict.get("priority", 3),
                    release_time=j_dict["release_time"],
                    due_date=j_dict["due_date"],
                    operations=ops,
                    quantity=j_dict.get("quantity", 1),
                    weight_tardiness_penalty=j_dict.get("weight_tardiness_penalty", 1.0),
                )
            )
        return jobs
