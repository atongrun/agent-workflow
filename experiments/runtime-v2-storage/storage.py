"""Storage backends for the disposable Runtime v2 storage comparison.

The module is intentionally experiment-local. It does not import or select the
installed ``awf`` package and it keeps the logical Workflow state independent
from the persistence representation.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable, Iterator, Protocol


FORMAT = "awf.runtime-v2-storage-comparison.v1"
SCHEMA_VERSION = 2
BUSY_OUTCOME = "AMBIGUOUS_NO_REPLAY"
BUSY_ACTION = "preserve exact writer/process evidence for owner decision"


class StateError(RuntimeError):
    """Fail-closed state error with a normalized Runtime v2 outcome."""

    def __init__(self, outcome: str, legal_next_action: str, source: str) -> None:
        super().__init__(source)
        self.outcome = outcome
        self.legal_next_action = legal_next_action
        self.source = source


class WriterBusy(StateError):
    def __init__(self, source: str = "writer lock is active") -> None:
        super().__init__(BUSY_OUTCOME, BUSY_ACTION, source)


class Store(Protocol):
    backend: str
    run_dir: Path

    def exists(self) -> bool: ...

    def initialize(self, spec: dict[str, Any]) -> dict[str, Any]: ...

    def read(self) -> dict[str, Any]: ...

    def mutate(self, update: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]: ...

    def writer_active(self) -> bool: ...

    def backup(self) -> dict[str, Any]: ...

    def restore(self) -> dict[str, Any]: ...

    def delete_derived(self) -> None: ...

    def forge_derived(self, value: dict[str, Any]) -> None: ...

    def migrate(self) -> dict[str, Any]: ...

    def hold_writer(self, seconds: float) -> None: ...


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key {key!r}")
        result[key] = value
    return result


def loads_json_object(text: str, path: Path, outcome: str, action: str) -> dict[str, Any]:
    try:
        value = json.loads(text, object_pairs_hook=reject_duplicate_keys)
    except Exception as exc:  # noqa: BLE001 - local state corruption must fail closed.
        raise StateError(outcome, action, f"cannot parse {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise StateError(outcome, action, f"{path.name} is not a JSON object")
    return value


def new_authority(spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "sequence": 1,
        "spec": spec,
        "run": {
            "run_id": spec["run_id"],
            "task_id": spec["task_id"],
            "spec_digest": digest(spec),
            "phase": "initialized",
            "authorizations": [],
            "handoff_intent": None,
            "terminal": None,
            "trusted_commit": None,
            "trusted_tree": None,
            "stop": None,
        },
        "journals": {},
        "measurements": {},
    }


def validate_authority(value: dict[str, Any], backend: str) -> None:
    if value.get("schema_version") != SCHEMA_VERSION:
        raise StateError(
            "OWNER_DECISION_REQUIRED",
            "preserve program and state evidence; use only a compatible schema",
            f"{backend} schema is not v{SCHEMA_VERSION}",
        )
    spec = value.get("spec")
    run = value.get("run")
    journals = value.get("journals")
    if not isinstance(spec, dict) or not isinstance(run, dict) or not isinstance(journals, dict):
        raise StateError(
            "DENY_BEFORE_PROVIDER",
            "preserve files and diagnose exact run identity",
            f"{backend} authority is incomplete",
        )
    expected = {
        "run_id": spec.get("run_id"),
        "task_id": spec.get("task_id"),
        "spec_digest": digest(spec),
    }
    for key, expected_value in expected.items():
        if run.get(key) != expected_value:
            raise StateError(
                "DENY_BEFORE_PROVIDER",
                "preserve files and diagnose exact run identity",
                f"{backend} RunStore {key} drift",
            )
    _validate_authorizations(run, journals, backend)
    for invocation_id, journal in journals.items():
        if not isinstance(journal, dict):
            raise StateError(
                "DENY_BEFORE_PROVIDER",
                "preserve files and diagnose exact run identity",
                f"{backend} InvocationJournal {invocation_id} invalid",
            )
        _validate_journal(invocation_id, journal, spec, backend)


def _validate_authorizations(
    run: dict[str, Any], journals: dict[str, Any], backend: str
) -> None:
    authorizations = run.get("authorizations")
    if not isinstance(authorizations, list):
        raise StateError(
            "DENY_BEFORE_PROVIDER",
            "preserve files and diagnose exact run identity",
            f"{backend} authorizations are invalid",
        )
    seen: set[tuple[str, str]] = set()
    allowed = {("implement-1", "implement"), ("review-1", "review")}
    for item in authorizations:
        if not isinstance(item, dict):
            raise StateError(
                "DENY_BEFORE_PROVIDER",
                "preserve files and diagnose exact run identity",
                f"{backend} authorization entry is invalid",
            )
        pair = (str(item.get("invocation_id")), str(item.get("role")))
        if pair not in allowed or pair in seen:
            raise StateError(
                "DENY_BEFORE_PROVIDER",
                "preserve files and diagnose exact run identity",
                f"{backend} authorization identity drift",
            )
        seen.add(pair)
        if pair[0] not in journals and run.get("phase") not in {"implement_authorized"}:
            raise StateError(
                "OWNER_DECISION_REQUIRED",
                "preserve the consumed authorization/budget and deny automatic provider replay",
                f"{backend} authorized journal is absent",
            )


def _validate_journal(
    invocation_id: str, journal: dict[str, Any], spec: dict[str, Any], backend: str
) -> None:
    role = "implement" if invocation_id == "implement-1" else "review"
    if invocation_id not in {"implement-1", "review-1"}:
        raise StateError(
            "DENY_BEFORE_PROVIDER",
            "preserve files and diagnose exact run identity",
            f"{backend} unknown journal {invocation_id}",
        )
    expected = {
        "invocation_id": invocation_id,
        "role": role,
        "spec_digest": digest(spec),
        "provider_command_digest": digest(spec["provider_command"]),
    }
    for key, expected_value in expected.items():
        if journal.get(key) != expected_value:
            raise StateError(
                "DENY_BEFORE_PROVIDER",
                "preserve files and diagnose exact run identity",
                f"{backend} InvocationJournal {invocation_id} {key} drift",
            )
    state = journal.get("state")
    if state not in {"prepared", "launch_intent", "started", "result", "validated"}:
        raise StateError(
            "DENY_BEFORE_PROVIDER",
            "preserve files and diagnose exact run identity",
            f"{backend} InvocationJournal {invocation_id} state drift",
        )
    presence = (
        journal.get("launch_intent") is not None,
        journal.get("started") is not None,
        journal.get("result") is not None,
        journal.get("validated") is not None,
    )
    expected_presence = {
        "prepared": (False, False, False, False),
        "launch_intent": (True, False, False, False),
        "started": (True, True, False, False),
        "result": (True, True, True, False),
        "validated": (True, True, True, True),
    }
    if presence != expected_presence[state]:
        raise StateError(
            "DENY_BEFORE_PROVIDER",
            "preserve files and diagnose exact run identity",
            f"{backend} InvocationJournal {invocation_id} phase consistency drift",
        )


def _atomic_envelope(payload: dict[str, Any]) -> dict[str, Any]:
    return {"format": FORMAT, "payload": payload, "checksum": digest(payload)}


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, path)


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    _write_text_atomic(path, json.dumps(_atomic_envelope(payload), indent=2, sort_keys=True) + "\n")


def _read_atomic(path: Path, backend: str) -> dict[str, Any]:
    try:
        envelope = loads_json_object(
            path.read_text(encoding="utf-8"),
            path,
            "DENY_BEFORE_PROVIDER",
            "preserve files and diagnose exact run identity",
        )
    except FileNotFoundError as exc:
        raise StateError(
            "EXTERNAL_OBSERVATION_UNKNOWN",
            "inspect the exact experiment state root",
            f"{path.name} is absent",
        ) from exc
    payload = envelope.get("payload")
    if (
        envelope.get("format") != FORMAT
        or not isinstance(payload, dict)
        or envelope.get("checksum") != digest(payload)
    ):
        raise StateError(
            "DENY_BEFORE_PROVIDER",
            "preserve files and diagnose exact run identity",
            f"{backend} checksum mismatch in {path.name}",
        )
    validate_authority(payload, backend)
    return payload


@contextlib.contextmanager
def _exclusive_file_lock(path: Path, payload: dict[str, Any]) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(str(path), flags)
    except FileExistsError as exc:
        raise WriterBusy(f"writer lock exists at {path.name}") from exc
    try:
        os.write(fd, canonical(payload))
        os.close(fd)
        fd = -1
        yield
    finally:
        if fd >= 0:
            os.close(fd)
        with contextlib.suppress(FileNotFoundError):
            path.unlink()


class AtomicStore:
    backend = "atomic"

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.path = run_dir / "authority.json"
        self.lock_path = run_dir / "authority.lock"
        self.backup_path = run_dir / "backup" / "authority.backup.json"
        self.derived_path = run_dir / "derived" / "status.json"

    def exists(self) -> bool:
        return self.path.exists()

    def initialize(self, spec: dict[str, Any]) -> dict[str, Any]:
        if self.exists():
            current = self.read()
            if digest(current["spec"]) != digest(spec):
                raise StateError(
                    "DENY_BEFORE_PROVIDER",
                    "preserve the run and diagnose the exact immutable contract binding",
                    "compiled RunSpec drift",
                )
            return current
        return self.mutate(lambda _state: new_authority(spec))

    def read(self) -> dict[str, Any]:
        return _read_atomic(self.path, self.backend)

    def mutate(self, update: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
        with _exclusive_file_lock(
            self.lock_path, {"backend": self.backend, "pid": os.getpid(), "time": time.time()}
        ):
            if self.path.exists():
                current = _read_atomic(self.path, self.backend)
            else:
                current = {}
            updated = update(current)
            updated = dict(updated)
            updated["sequence"] = int(updated.get("sequence", 0)) + 1
            validate_authority(updated, self.backend)
            _atomic_write(self.path, updated)
            return updated

    def writer_active(self) -> bool:
        return self.lock_path.exists()

    def backup(self) -> dict[str, Any]:
        current = self.read()
        _atomic_write(self.backup_path, current)
        return {
            "backend": self.backend,
            "backup": str(self.backup_path),
            "sequence": current["sequence"],
            "outcome": "SAFE_CONTINUE",
        }

    def restore(self) -> dict[str, Any]:
        backup = _read_atomic(self.backup_path, self.backend)
        if self.path.exists():
            current = self.read()
            if int(backup["sequence"]) < int(current["sequence"]):
                raise StateError(
                    "TERMINAL_CONFLICT",
                    "preserve newer authority; deny stale offline restore",
                    "backup is older than current authority",
                )
        _atomic_write(self.path, backup)
        return backup

    def delete_derived(self) -> None:
        with contextlib.suppress(FileNotFoundError):
            self.derived_path.unlink()

    def forge_derived(self, value: dict[str, Any]) -> None:
        _write_text_atomic(self.derived_path, json.dumps(value, indent=2, sort_keys=True) + "\n")

    def migrate(self) -> dict[str, Any]:
        return {"backend": self.backend, "schema_version": SCHEMA_VERSION, "migrated": False}

    def hold_writer(self, seconds: float) -> None:
        with _exclusive_file_lock(
            self.lock_path, {"backend": self.backend, "pid": os.getpid(), "hold": seconds}
        ):
            time.sleep(seconds)


class SQLiteStore:
    backend = "sqlite"

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.path = run_dir / "state.db"
        self.backup_path = run_dir / "backup" / "state.backup.db"
        self.derived_path = run_dir / "derived" / "status.json"

    def exists(self) -> bool:
        return self.path.exists()

    def _connect(self, readonly: bool = False, timeout: float = 0.2) -> sqlite3.Connection:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        if readonly:
            uri = f"file:{self.path}?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=0.0)
        else:
            conn = sqlite3.connect(self.path, timeout=timeout)
        conn.row_factory = sqlite3.Row
        return conn

    def _schema(self, conn: sqlite3.Connection) -> int:
        row = conn.execute("PRAGMA user_version").fetchone()
        return int(row[0])

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        version = self._schema(conn)
        if version == 0:
            conn.execute("PRAGMA user_version = 2")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS records ("
                "kind TEXT NOT NULL, "
                "key TEXT NOT NULL, "
                "payload TEXT NOT NULL, "
                "checksum TEXT NOT NULL, "
                "PRIMARY KEY (kind, key))"
            )
            return
        if version == 1:
            self._migrate_v1_to_v2(conn)
            return
        if version > SCHEMA_VERSION:
            raise StateError(
                "OWNER_DECISION_REQUIRED",
                "preserve program and state evidence; use only a compatible schema",
                f"sqlite schema v{version} is newer than supported v{SCHEMA_VERSION}",
            )

    def _migrate_v1_to_v2(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS records ("
            "kind TEXT NOT NULL, "
            "key TEXT NOT NULL, "
            "payload TEXT NOT NULL, "
            "checksum TEXT NOT NULL, "
            "PRIMARY KEY (kind, key))"
        )
        old = conn.execute("SELECT payload FROM authority WHERE id = 'current'").fetchone()
        if old is None:
            raise StateError(
                "DENY_BEFORE_PROVIDER",
                "preserve files and diagnose exact run identity",
                "sqlite v1 authority is absent",
            )
        payload = loads_json_object(
            old["payload"],
            self.path,
            "DENY_BEFORE_PROVIDER",
            "preserve files and diagnose exact run identity",
        )
        conn.execute(
            "INSERT OR REPLACE INTO records VALUES (?, ?, ?, ?)",
            ("authority", "current", json.dumps(payload, sort_keys=True), digest(payload)),
        )
        conn.execute("PRAGMA user_version = 2")

    def _load_from_conn(self, conn: sqlite3.Connection, readonly: bool) -> dict[str, Any]:
        if readonly:
            version = self._schema(conn)
            if version > SCHEMA_VERSION:
                raise StateError(
                    "OWNER_DECISION_REQUIRED",
                    "preserve program and state evidence; use only a compatible schema",
                    f"sqlite schema v{version} is newer than supported v{SCHEMA_VERSION}",
                )
            if version == 1:
                raise StateError(
                    "OWNER_DECISION_REQUIRED",
                    "run offline sqlite migration; status must not migrate",
                    "sqlite schema v1 requires offline migration",
                )
        else:
            self._ensure_schema(conn)
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise StateError(
                "DENY_BEFORE_PROVIDER",
                "preserve files and diagnose exact run identity",
                f"sqlite integrity_check failed: {integrity}",
            )
        row = conn.execute(
            "SELECT payload, checksum FROM records WHERE kind = ? AND key = ?",
            ("authority", "current"),
        ).fetchone()
        if row is None:
            raise StateError(
                "EXTERNAL_OBSERVATION_UNKNOWN",
                "inspect the exact experiment state root",
                "sqlite authority is absent",
            )
        payload = loads_json_object(
            row["payload"],
            self.path,
            "DENY_BEFORE_PROVIDER",
            "preserve files and diagnose exact run identity",
        )
        if row["checksum"] != digest(payload):
            raise StateError(
                "DENY_BEFORE_PROVIDER",
                "preserve files and diagnose exact run identity",
                "sqlite record checksum mismatch",
            )
        validate_authority(payload, self.backend)
        return payload

    def _save_to_conn(self, conn: sqlite3.Connection, payload: dict[str, Any]) -> None:
        validate_authority(payload, self.backend)
        conn.execute(
            "INSERT OR REPLACE INTO records VALUES (?, ?, ?, ?)",
            ("authority", "current", json.dumps(payload, sort_keys=True), digest(payload)),
        )

    def initialize(self, spec: dict[str, Any]) -> dict[str, Any]:
        if self.exists():
            current = self.read()
            if digest(current["spec"]) != digest(spec):
                raise StateError(
                    "DENY_BEFORE_PROVIDER",
                    "preserve the run and diagnose the exact immutable contract binding",
                    "compiled RunSpec drift",
                )
            return current
        return self.mutate(lambda _state: new_authority(spec))

    def read(self) -> dict[str, Any]:
        try:
            with self._connect(readonly=True) as conn:
                return self._load_from_conn(conn, readonly=True)
        except sqlite3.Error as exc:
            raise StateError(
                "DENY_BEFORE_PROVIDER",
                "preserve files and diagnose exact run identity",
                f"sqlite read failed: {exc}",
            ) from exc

    def mutate(self, update: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
        try:
            with self._connect(readonly=False, timeout=0.0) as conn:
                try:
                    conn.execute("BEGIN IMMEDIATE")
                except sqlite3.OperationalError as exc:
                    if "locked" in str(exc).lower():
                        raise WriterBusy("sqlite writer transaction is active") from exc
                    raise
                self._ensure_schema(conn)
                try:
                    current = self._load_from_conn(conn, readonly=False)
                except StateError as exc:
                    if "authority is absent" in exc.source:
                        current = {}
                    else:
                        raise
                updated = dict(update(current))
                updated["sequence"] = int(updated.get("sequence", 0)) + 1
                self._save_to_conn(conn, updated)
                conn.commit()
                return updated
        except WriterBusy:
            raise
        except sqlite3.Error as exc:
            raise StateError(
                "DENY_BEFORE_PROVIDER",
                "preserve files and diagnose exact run identity",
                f"sqlite mutation failed: {exc}",
            ) from exc

    def writer_active(self) -> bool:
        if not self.path.exists():
            return False
        try:
            with self._connect(readonly=False, timeout=0.0) as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.rollback()
                return False
        except sqlite3.OperationalError:
            return True

    def backup(self) -> dict[str, Any]:
        current = self.read()
        self.backup_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect(readonly=True) as source:
            backup = sqlite3.connect(self.backup_path)
            try:
                source.backup(backup)
            finally:
                backup.close()
        return {
            "backend": self.backend,
            "backup": str(self.backup_path),
            "sequence": current["sequence"],
            "outcome": "SAFE_CONTINUE",
        }

    def restore(self) -> dict[str, Any]:
        if not self.backup_path.exists():
            raise StateError(
                "EXTERNAL_OBSERVATION_UNKNOWN",
                "inspect the exact experiment state root",
                "sqlite backup is absent",
            )
        backup = SQLiteStore(self.run_dir / "__restore_probe__")
        backup.path = self.backup_path
        backup.backup_path = self.backup_path
        restored = backup.read()
        if self.path.exists():
            current = self.read()
            if int(restored["sequence"]) < int(current["sequence"]):
                raise StateError(
                    "TERMINAL_CONFLICT",
                    "preserve newer authority; deny stale offline restore",
                    "backup is older than current authority",
                )
        shutil.copy2(self.backup_path, self.path)
        return restored

    def delete_derived(self) -> None:
        with contextlib.suppress(FileNotFoundError):
            self.derived_path.unlink()

    def forge_derived(self, value: dict[str, Any]) -> None:
        _write_text_atomic(self.derived_path, json.dumps(value, indent=2, sort_keys=True) + "\n")

    def migrate(self) -> dict[str, Any]:
        try:
            with self._connect(readonly=False, timeout=0.0) as conn:
                conn.execute("BEGIN IMMEDIATE")
                before = self._schema(conn)
                self._ensure_schema(conn)
                after = self._schema(conn)
                conn.commit()
                return {"backend": self.backend, "before": before, "after": after}
        except sqlite3.Error as exc:
            raise StateError(
                "DENY_BEFORE_PROVIDER",
                "preserve files and diagnose exact run identity",
                f"sqlite migration failed: {exc}",
            ) from exc

    def hold_writer(self, seconds: float) -> None:
        with self._connect(readonly=False, timeout=0.0) as conn:
            conn.execute("BEGIN IMMEDIATE")
            time.sleep(seconds)
            conn.rollback()


def make_store(backend: str, state_root: Path, run_id: str) -> Store:
    run_dir = state_root / backend / run_id
    if backend == "atomic":
        return AtomicStore(run_dir)
    if backend == "sqlite":
        return SQLiteStore(run_dir)
    raise SystemExit(f"unknown store backend: {backend}")


def create_sqlite_v1(run_dir: Path, authority: dict[str, Any]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "state.db"
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA user_version = 1")
        conn.execute("CREATE TABLE authority (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        conn.execute(
            "INSERT INTO authority VALUES (?, ?)",
            ("current", json.dumps(authority, sort_keys=True)),
        )


def force_sqlite_schema(run_dir: Path, version: int) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(run_dir / "state.db") as conn:
        conn.execute(f"PRAGMA user_version = {int(version)}")
