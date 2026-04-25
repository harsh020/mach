from __future__ import annotations

import hashlib
from typing import Any

from mach.utils import canonical_json


def hash_payload(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def chain_hash(payload: dict[str, Any], previous_hash: str | None) -> str:
    base = canonical_json(payload)
    if previous_hash:
        base = f"{base}{previous_hash}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()

