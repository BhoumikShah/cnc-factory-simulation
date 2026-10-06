from __future__ import annotations

import hashlib

import numpy as np


class RNGManager:
    """
    Hierarchical Random Number Generator Stream Manager.
    Guarantees that adding or removing a machine/entity does not perturb
    the independent random stream of other entities.
    """

    def __init__(self, master_seed: int = 42) -> None:
        self.master_seed = master_seed
        self._streams: dict[str, np.random.Generator] = {}

    def get_stream(self, stream_name: str) -> np.random.Generator:
        """Returns or instantiates a named RNG generator."""
        if stream_name not in self._streams:
            # Deterministically derive 32-bit seed from master_seed and stream_name
            name_hash = int(
                hashlib.sha256(f"{self.master_seed}_{stream_name}".encode()).hexdigest()[:8],
                16,
            )
            derived_seed = (self.master_seed + name_hash) & 0xFFFFFFFF
            self._streams[stream_name] = np.random.default_rng(derived_seed)
        return self._streams[stream_name]
