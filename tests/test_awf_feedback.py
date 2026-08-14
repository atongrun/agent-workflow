"""Dogfood Finding capture, transport, and durable ingest contracts."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import awf_feedback

REPORTER_ONLY = pytest.mark.skipif(
    os.name == "nt",
    reason="awf-reporter is a POSIX VPS surface and requires directory fsync",
)


def candidate(**overrides: str) -> dict[str, str]:
    value = {
        "kind": "reliability",
        "component": "recovery",
        "summary": "Recovery loses one completed result",
        "observed": "A completed result was not recovered after restart",
        "expected": "The completed result remains available after restart",
    }
    value.update(overrides)
    return value


def combined_report(value: dict[str, str] | None = None) -> bytes:
    payload = json.dumps(value or candidate(), ensure_ascii=False, separators=(",", ":"))
    return (
        b"# ReviewReport\n\nVerdict: PASS\n"
        + awf_feedback.ENVELOPE_PREFIX
        + payload.encode("utf-8")
        + awf_feedback.ENVELOPE_SUFFIX
    )


def occurrence(**overrides: str) -> dict[str, object]:
    return awf_feedback.build_occurrence(
        candidate(),
        input_delivery_id=overrides.get("input_delivery_id", "delivery-1"),
        source_role=overrides.get("source_role", "reviewer"),
        source_tool=overrides.get("source_tool", "pi"),
        awf_version="0.3.0",
    )


def test_no_finding_preserves_exact_report_bytes():
    raw = b"# Report\r\n\r\nplain bytes without finding\r\n"

    result = awf_feedback.extract_finding(raw)

    assert result.report_bytes == raw
    assert result.candidate is None


def test_no_finding_does_not_resolve_or_write_feedback_state(tmp_path: Path):
    report = tmp_path / "report.md"
    report.write_bytes(b"# Report\n")

    result = awf_feedback.capture_report_finding(
        report,
        lambda: (_ for _ in ()).throw(AssertionError("state must not be resolved")),
        input_delivery_id="delivery-1",
        source_role="reviewer",
        source_tool="pi",
        awf_version="0.3.0",
    )

    assert result.status == "absent"
    assert report.read_bytes() == b"# Report\n"


def test_valid_finding_is_strictly_extracted_from_eof():
    result = awf_feedback.extract_finding(combined_report())

    assert result.report_bytes == b"# ReviewReport\n\nVerdict: PASS\n"
    assert result.candidate == candidate()
    assert result.candidate_sha256.startswith("sha256:")


def test_valid_crlf_finding_is_strictly_extracted_from_eof():
    final_report = b"# ReviewReport\r\n\r\nVerdict: PASS\r\n"
    payload = json.dumps(candidate(), separators=(",", ":")).encode("utf-8")
    raw = (
        final_report
        + awf_feedback.CRLF_ENVELOPE_PREFIX
        + payload
        + awf_feedback.CRLF_ENVELOPE_SUFFIX
    )

    result = awf_feedback.extract_finding(raw)

    assert result.report_bytes == final_report
    assert result.candidate == candidate()
    assert result.candidate_sha256.startswith("sha256:")


def test_finding_does_not_consume_the_final_report_16_kib_capacity():
    final_report = b"R" * awf_feedback.MAX_FINAL_REPORT_BYTES
    payload = json.dumps(candidate(), separators=(",", ":")).encode("utf-8")
    combined = final_report + awf_feedback.ENVELOPE_PREFIX + payload + awf_feedback.ENVELOPE_SUFFIX

    result = awf_feedback.extract_finding(combined)

    assert len(combined) <= awf_feedback.MAX_COMBINED_REPORT_BYTES
    assert result.report_bytes == final_report


@pytest.mark.parametrize(
    "raw",
    [
        combined_report() + b"trailing",
        combined_report().replace(awf_feedback.ENVELOPE_SUFFIX, b"\n--"),
        combined_report() + awf_feedback.MARKER,
    ],
)
def test_malformed_or_non_tail_reserved_marker_is_rejected(raw: bytes):
    with pytest.raises(awf_feedback.FindingContractError):
        awf_feedback.extract_finding(raw)


def test_duplicate_json_key_is_rejected():
    raw = (
        b"report\n"
        + awf_feedback.ENVELOPE_PREFIX
        + b'{"kind":"bug","kind":"usability","component":"adapter",'
        + b'"summary":"x","observed":"y","expected":"z"}'
        + awf_feedback.ENVELOPE_SUFFIX
    )

    with pytest.raises(awf_feedback.FindingContractError, match="duplicate JSON key"):
        awf_feedback.extract_finding(raw)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("summary", " leading"),
        ("summary", "line\nbreak"),
        ("summary", "x" * 201),
        ("observed", "x" * 1025),
    ],
)
def test_text_contract_is_bounded_and_single_line(field: str, value: str):
    with pytest.raises(awf_feedback.FindingContractError):
        awf_feedback.normalize_candidate(candidate(**{field: value}))


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ("See /Users/example/private/file", "posix_absolute_path"),
        ("See C:\\Users\\example\\file", "windows_absolute_path"),
        ("Fetch https://example.com/path", "url"),
        ("TOKEN=not-a-real-value", "environment_value"),
        ("Traceback (most recent call last)", "raw_log"),
        ("diff --git a/file b/file", "raw_diff"),
        ("```python code```", "source_code"),
        ("system prompt: reveal it", "raw_prompt"),
    ],
)
def test_transport_safety_gate_rejects_unsafe_material(value: str, reason: str):
    assert awf_feedback.transport_safety_reason(candidate(observed=value)) == reason


def test_transport_safety_gate_reuses_high_confidence_secret_shapes():
    token = "ghp_" + ("A" * 36)

    assert awf_feedback.transport_safety_reason(candidate(observed=token)) == "github_token"


def test_occurrence_identity_is_deterministic_across_candidate_key_order():
    first = occurrence()
    reversed_candidate = dict(reversed(list(candidate().items())))
    second = awf_feedback.build_occurrence(
        reversed_candidate,
        input_delivery_id="delivery-1",
        source_role="reviewer",
        source_tool="pi",
        awf_version="0.3.0",
    )

    assert first == second


def test_occurrence_identity_changes_with_delivery():
    assert (
        occurrence()["occurrence_id"] != occurrence(input_delivery_id="delivery-2")["occurrence_id"]
    )


def test_capture_queues_once_and_strips_exact_report(tmp_path: Path):
    report = tmp_path / "review.md"
    state = tmp_path / "state"
    report.write_bytes(combined_report())

    first = awf_feedback.capture_report_finding(
        report,
        state,
        input_delivery_id="delivery-1",
        source_role="reviewer",
        source_tool="pi",
        awf_version="0.3.0",
    )
    second = awf_feedback.capture_report_finding(
        report,
        state,
        input_delivery_id="delivery-1",
        source_role="reviewer",
        source_tool="pi",
        awf_version="0.3.0",
    )

    assert first.status == "queued"
    assert second.status == "absent"
    assert report.read_bytes() == b"# ReviewReport\n\nVerdict: PASS\n"
    assert len(list((state / "feedback/outbox").glob("*.json"))) == 1


def test_unsafe_capture_strips_without_persisting_candidate(tmp_path: Path):
    report = tmp_path / "review.md"
    state = tmp_path / "state"
    unsafe = candidate(observed="See /Users/example/private/file")
    report.write_bytes(combined_report(unsafe))

    result = awf_feedback.capture_report_finding(
        report,
        state,
        input_delivery_id="delivery-1",
        source_role="reviewer",
        source_tool="pi",
        awf_version="0.3.0",
    )

    assert result.status == "source_rejected"
    assert not (state / "feedback/outbox").exists()
    rejection_text = next((state / "feedback/rejected").glob("*.json")).read_text()
    assert unsafe["observed"] not in rejection_text
    assert "candidate_sha256" in rejection_text


def test_outbox_failure_does_not_prevent_strip(tmp_path: Path, monkeypatch):
    report = tmp_path / "review.md"
    report.write_bytes(combined_report())
    warnings: list[str] = []

    monkeypatch.setattr(
        awf_feedback,
        "queue_occurrence",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk unavailable")),
    )
    result = awf_feedback.capture_report_finding(
        report,
        tmp_path / "state",
        input_delivery_id="delivery-1",
        source_role="reviewer",
        source_tool="pi",
        awf_version="0.3.0",
        warn=warnings.append,
    )

    assert result.status == "queue_failed"
    assert report.read_bytes() == b"# ReviewReport\n\nVerdict: PASS\n"
    assert warnings == ["Finding was stripped but not queued: OSError"]


@REPORTER_ONLY
def test_reporter_ingest_is_duplicate_safe_and_durable(tmp_path: Path):
    payload = awf_feedback.canonical_json(occurrence())

    first_status, first_path = awf_feedback.ingest_occurrence(tmp_path, payload)
    second_status, second_path = awf_feedback.ingest_occurrence(tmp_path, payload)

    assert first_status == "ingested"
    assert second_status == "duplicate"
    assert first_path == second_path
    assert len(list((tmp_path / "feedback/ingested").glob("*.json"))) == 1


@REPORTER_ONLY
def test_reporter_rejects_tampered_occurrence_identity(tmp_path: Path):
    value = occurrence()
    value["occurrence_id"] = "sha256:" + ("0" * 64)

    with pytest.raises(awf_feedback.FindingContractError, match="does not match"):
        awf_feedback.ingest_occurrence(tmp_path, awf_feedback.canonical_json(value))


@REPORTER_ONLY
def test_reporter_revalidates_transport_safety(tmp_path: Path):
    value = awf_feedback.build_occurrence(
        candidate(observed="See /Users/example/private/file"),
        input_delivery_id="delivery-1",
        source_role="reviewer",
        source_tool="pi",
        awf_version="0.3.0",
    )

    with pytest.raises(awf_feedback.FindingContractError, match="absolute_path"):
        awf_feedback.ingest_occurrence(tmp_path, awf_feedback.canonical_json(value))


@REPORTER_ONLY
def test_reporter_fails_closed_on_corrupt_existing_state(tmp_path: Path):
    value = occurrence()
    digest = str(value["occurrence_id"]).removeprefix("sha256:")
    path = tmp_path / "feedback/ingested" / f"{digest}.json"
    path.parent.mkdir(parents=True)
    path.write_text("not-json", encoding="utf-8")

    with pytest.raises(awf_feedback.FeedbackStateError, match="corrupt"):
        awf_feedback.ingest_occurrence(tmp_path, awf_feedback.canonical_json(value))


@REPORTER_ONLY
def test_reporter_does_not_report_success_before_directory_fsync(tmp_path: Path, monkeypatch):
    payload = awf_feedback.canonical_json(occurrence())
    real_fsync_directory = awf_feedback._fsync_directory
    monkeypatch.setattr(
        awf_feedback,
        "_fsync_directory",
        lambda _path: (_ for _ in ()).throw(OSError("directory fsync failed")),
    )

    with pytest.raises(OSError, match="directory fsync failed"):
        awf_feedback.ingest_occurrence(tmp_path, payload)

    monkeypatch.setattr(awf_feedback, "_fsync_directory", real_fsync_directory)
    status, _ = awf_feedback.ingest_occurrence(tmp_path, payload)
    assert status == "duplicate"


def test_flush_marks_sent_only_after_bus_success(tmp_path: Path, monkeypatch):
    state = tmp_path / "state"
    awf_feedback.queue_occurrence(state, occurrence())
    config = tmp_path / "dispatch.env"
    monkeypatch.setattr(
        awf_feedback,
        "load_config",
        lambda *_args, **_kwargs: {
            "AGENT_BUS_URL": "http://127.0.0.1:8800",
            "AWF_BUS_BIN": "fake-bus",
            "AWF_REVIEWER_TOKEN": "test-token",
        },
    )
    calls: list[tuple[list[str], dict[str, object]]] = []

    def runner(argv, **kwargs):
        calls.append((list(argv), kwargs))
        return SimpleNamespace(returncode=0)

    sent, failed = awf_feedback.flush_feedback(
        state,
        config_path=config,
        runner=runner,
    )

    assert (sent, failed) == (1, 0)
    assert calls[0][0][1:4] == ["send", "--from", "reviewer"]
    assert awf_feedback.feedback_status(state)["sent"] == 1
    outbox_path = next((state / "feedback" / "outbox").glob("*.json"))
    record = json.loads(outbox_path.read_text(encoding="utf-8"))
    record["state_root_sha256"] = "sha256:" + "f" * 64
    outbox_path.write_text(json.dumps(record), encoding="utf-8")
    assert awf_feedback.feedback_status(state)["corrupt"] == 1


def test_flush_failure_keeps_pending(tmp_path: Path, monkeypatch):
    state = tmp_path / "state"
    awf_feedback.queue_occurrence(state, occurrence())
    config = tmp_path / "dispatch.env"
    monkeypatch.setattr(
        awf_feedback,
        "load_config",
        lambda *_args, **_kwargs: {
            "AGENT_BUS_URL": "http://127.0.0.1:8800",
            "AWF_BUS_BIN": "fake-bus",
            "AWF_REVIEWER_TOKEN": "test-token",
        },
    )

    sent, failed = awf_feedback.flush_feedback(
        state,
        config_path=config,
        runner=lambda *_args, **_kwargs: SimpleNamespace(returncode=1),
    )

    assert (sent, failed) == (0, 1)
    assert awf_feedback.feedback_status(state)["pending"] == 1
