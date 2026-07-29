#!/usr/bin/env python3
"""Canonical Agent Workflow delivery metadata shared by dispatch and handlers."""

from __future__ import annotations

import hashlib
import json


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_payload_sha256(payload: dict[str, object]) -> str:
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def make_delivery_id(
    source_role: str,
    event_type: str,
    payload_sha256: str,
    source_event_id: int,
) -> str:
    seed = {
        "format": "awf.delivery.v1",
        "source_role": source_role,
        "event_type": event_type,
        "payload_sha256": payload_sha256,
        "source_event_id": source_event_id,
    }
    return f"awf:{hashlib.sha256(canonical_json(seed).encode('utf-8')).hexdigest()}"
