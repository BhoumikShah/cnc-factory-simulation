from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FixtureSpec:
    """Fixture model for clamping workpieces onto machine table/pallet."""

    fixture_id: str
    fixture_type: str
    description: str
    total_quantity: int = 2


@dataclass(frozen=True, slots=True)
class FixtureTransitionMatrix:
    """Sequence-dependent setup transition times between fixture types in minutes."""

    transitions: Mapping[str, Mapping[str, float]]
    default_setup_minutes: float = 15.0

    def get_setup_time(self, from_fixture: str | None, to_fixture: str) -> float:
        """Returns base setup minutes between two fixture configurations."""
        if from_fixture is None or from_fixture == to_fixture:
            return 0.0
        from_map = self.transitions.get(from_fixture)
        if from_map and to_fixture in from_map:
            return from_map[to_fixture]
        return self.default_setup_minutes
