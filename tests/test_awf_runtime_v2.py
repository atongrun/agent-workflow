from __future__ import annotations

import hashlib
import json
from pathlib import Path

from agent_workflow.runtime import ResultEnvelope
from scripts import awf_runtime_v2


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def test_readiness_result_handler_persists_exact_payload_before_success(tmp_path: Path) -> None:
    payload = {
        "nonce": "a" * 32,
        "expires_at": 2_000_000_000,
        "binding": {"role": "coder"},
        "source_commit": "b" * 40,
    }
    argv = [
        "readiness-result",
        "--payload-json",
        json.dumps(payload),
        "--state-root",
        str(tmp_path),
    ]

    assert awf_runtime_v2.main(argv) == 0
    assert awf_runtime_v2.main(argv) == 0
    path = tmp_path / "runtime-v2" / "readiness" / ("a" * 32) / "coder.json"
    assert json.loads(path.read_text(encoding="utf-8")) == payload

    conflict = {**payload, "source_commit": "c" * 40}
    assert awf_runtime_v2.main(
        [
            "readiness-result",
            "--payload-json",
            json.dumps(conflict),
            "--state-root",
            str(tmp_path),
        ]
    ) == 2


def test_source_result_handler_persists_canonical_envelope_before_ack(tmp_path: Path) -> None:
    envelope = ResultEnvelope.create(
        run_id="fresh-card-abcdef123456",
        task_id="card",
        run_spec_sha256=digest("spec"),
        source_role="coder",
        target_role="architect",
        route="result:awf-runtime-v2-result-v1",
        source_invocation_id="invoke-coder",
        source_authorization_sha256=digest("authorization"),
        target_invocation_id="source-invoke-coder",
        causation_delivery_id="awfv2:" + digest("command"),
        payload={"kind": "coder", "result_sha256": digest("result")},
    )
    argv = [
        "result",
        "--payload-json",
        json.dumps({"envelope": envelope.encode().decode("utf-8")}),
        "--state-root",
        str(tmp_path),
    ]

    assert awf_runtime_v2.main(argv) == 0
    path = (
        tmp_path
        / "runtime-v2"
        / "inbox"
        / envelope.run_id
        / f"{envelope.delivery_id.removeprefix('awfv2:')}.json"
    )
    assert path.read_bytes() == envelope.encode()
