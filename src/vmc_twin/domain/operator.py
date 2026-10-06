from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from vmc_twin.domain.states import SkillLevel


@dataclass(frozen=True, slots=True)
class Operator:
    """Operator entity responsible for fixture setups and tool maintenance."""
    operator_id: str
    name: str
    skill_level: SkillLevel
    shift_ids: Sequence[str]
    certified_fixtures: Sequence[str]
