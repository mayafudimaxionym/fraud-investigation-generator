"""Stable seed derivation for deterministic generator components."""

from __future__ import annotations

import hashlib


def derive_seed(master_seed: int, namespace: str) -> int:
    """Return a reproducible component seed derived from a master seed."""
    if not isinstance(master_seed, int) or isinstance(master_seed, bool):
        raise TypeError("master_seed must be an integer")
    if not isinstance(namespace, str) or not namespace:
        raise ValueError("namespace must be a non-empty string")

    payload = f"{master_seed}:{namespace}".encode("utf-8")
    digest = hashlib.blake2b(payload, digest_size=8).digest()
    return int.from_bytes(digest, byteorder="big")
