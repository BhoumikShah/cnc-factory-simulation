from __future__ import annotations

from collections.abc import Mapping, Sequence

import simpy

from vmc_twin.domain.fixture import FixtureSpec, FixtureTransitionMatrix
from vmc_twin.domain.operator import Operator
from vmc_twin.domain.tool import ToolInstance, ToolSpec


class ShopFloorResources:
    """
    Shared shop floor physical and human resources managed in the SimPy environment:
    - Operator pool with skill qualifications
    - Tool crib stock with wear tracking and replenishments
    - Shared fixture units
    - Maintenance technician pool
    """

    def __init__(
        self,
        env: simpy.Environment,
        operators: Sequence[Operator],
        fixture_specs: Sequence[FixtureSpec],
        transition_matrix: FixtureTransitionMatrix,
        tool_specs: Sequence[ToolSpec],
        initial_crib_stock: Mapping[str, int] | None = None,
        maintenance_tech_count: int = 2,
    ) -> None:
        self.env = env
        self.operators = list(operators)
        self.transition_matrix = transition_matrix

        # Operator resource pool
        self.operator_resource = simpy.Resource(env, capacity=max(1, len(operators)))

        # Maintenance technicians
        self.maintenance_resource = simpy.Resource(env, capacity=max(1, maintenance_tech_count))

        # Fixture resources by fixture_id
        self.fixtures: dict[str, simpy.Resource] = {}
        for f in fixture_specs:
            self.fixtures[f.fixture_id] = simpy.Resource(env, capacity=f.total_quantity)

        # Tool crib stock: tool_type -> list of ToolInstance
        self.tool_crib: dict[str, list[ToolInstance]] = {}
        self.tool_specs: dict[str, ToolSpec] = {ts.tool_type: ts for ts in tool_specs}

        default_stock = initial_crib_stock or {}
        for ts in tool_specs:
            qty = default_stock.get(ts.tool_type, 10)
            self.tool_crib[ts.tool_type] = [
                ToolInstance(
                    tool_id=f"{ts.tool_type}_{i + 1:03d}",
                    tool_type=ts.tool_type,
                    life_limit_minutes=ts.nominal_life_minutes,
                )
                for i in range(qty)
            ]

    def has_tool_in_crib(self, tool_type: str) -> bool:
        """Checks if an unworn tool of the required type is available."""
        available = self.tool_crib.get(tool_type, [])
        return any(not t.is_worn_out for t in available)

    def checkout_tool(self, tool_type: str) -> ToolInstance | None:
        """Checks out a ready tool from the crib."""
        available = self.tool_crib.get(tool_type, [])
        for tool in available:
            if not tool.is_worn_out:
                available.remove(tool)
                return tool
        return None

    def return_tool(self, tool: ToolInstance) -> None:
        """Returns a tool instance back to the crib or triggers refurbishment."""
        if tool.tool_type in self.tool_crib:
            self.tool_crib[tool.tool_type].append(tool)
