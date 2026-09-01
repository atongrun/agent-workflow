"""Initial local provider and GitHub effects owned by the one Run Coordinator."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from .contracts import TypedResult, canonical_bytes, parse_typed_result


class CoordinatorError(RuntimeError):
    """A provider or external effect is unavailable, ambiguous or drifted."""


def _run(
    argv: list[str], *, cwd: Path, stdin: bytes | None = None
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            argv,
            cwd=cwd,
            shell=False,
            input=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as exc:
        raise CoordinatorError(f"trusted process could not start: {argv[0]}") from exc


class PiProvider:
    """Pi structured fallback for local Author and terminal Decision calls."""

    def __init__(self, binary: str = "pi", model: str = "") -> None:
        self.binary = binary
        self.model = model

    def execute(self, kind: str, request: dict[str, object], cwd: Path) -> TypedResult:
        argv = [
            self.binary,
            "--print",
            "--mode",
            "text",
            "--no-session",
            "--no-approve",
            "--no-extensions",
            "--no-skills",
            "--no-prompt-templates",
            "--no-context-files",
            "--no-tools",
        ]
        if self.model:
            argv += ["--model", self.model]
        argv += [
            "Return exactly one JSON object matching the supplied contract. "
            + json.dumps(request, ensure_ascii=False, sort_keys=True)
        ]
        completed = _run(argv, cwd=cwd)
        if completed.returncode != 0:
            raise CoordinatorError(completed.stderr.decode(errors="replace")[:4096])
        return parse_typed_result(kind, completed.stdout)


class CodexProvider:
    """Codex native output-schema/result-file boundary for local Review."""

    def __init__(self, binary: str = "codex", model: str = "") -> None:
        self.binary = binary
        self.model = model

    def execute(self, request: dict[str, object], cwd: Path) -> TypedResult:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["verdict", "findings", "blocked_reason", "rationale"],
            "properties": {
                "verdict": {"enum": ["approve", "request_changes", "blocked"]},
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["required_correction", "evidence"],
                        "properties": {
                            "required_correction": {"type": "string"},
                            "evidence": {"type": "string"},
                        },
                    },
                },
                "blocked_reason": {"type": "string"},
                "rationale": {"type": "string"},
            },
        }
        with tempfile.TemporaryDirectory(prefix="awf-review-") as temporary:
            root = Path(temporary)
            schema_path, result_path = root / "schema.json", root / "result.json"
            schema_path.write_bytes(canonical_bytes(schema))
            argv = [
                self.binary,
                "exec",
                "-C",
                str(cwd),
                "--sandbox",
                "read-only",
                "--ephemeral",
                "--output-schema",
                str(schema_path),
                "--output-last-message",
                str(result_path),
            ]
            if self.model:
                argv += ["--model", self.model]
            argv += ["-"]
            prompt = (
                "Review only the exact committed comparison described by this request. "
                "Return the typed ReviewResult. "
                + json.dumps(request, ensure_ascii=False, sort_keys=True)
            ).encode()
            completed = _run(argv, cwd=cwd, stdin=prompt)
            if completed.returncode != 0 or not result_path.is_file():
                raise CoordinatorError(completed.stderr.decode(errors="replace")[:4096])
            return parse_typed_result("review", result_path.read_bytes())


class GitHubEffects:
    """Exact Task-ref, PR, CI, merge and fresh-base observations."""

    def __init__(self, repo: Path, repository: str, remote: str = "origin") -> None:
        self.repo = repo.resolve()
        self.repository = repository
        self.remote = remote

    def task_head(self, task_ref: str) -> str:
        completed = self._command(["git", "ls-remote", self.remote, f"refs/heads/{task_ref}"])
        fields = completed.stdout.decode().split()
        if completed.returncode != 0 or len(fields) != 2:
            raise CoordinatorError("exact remote Task ref is unavailable")
        return fields[0]

    def ensure_pr(
        self,
        *,
        task_ref: str,
        base_ref: str,
        head_sha: str,
        title: str,
        head_owner: str = "",
    ) -> int:
        head = f"{head_owner}:{task_ref}" if head_owner else task_ref
        query = self._json(
            [
                "gh",
                "pr",
                "list",
                "--repo",
                self.repository,
                "--state",
                "all",
                "--head",
                head,
                "--base",
                base_ref,
                "--json",
                "number,headRefOid,state",
            ]
        )
        if len(query) > 1:
            raise CoordinatorError("multiple PRs match the frozen base/head tuple")
        if query:
            if query[0].get("headRefOid") != head_sha or query[0].get("state") != "OPEN":
                raise CoordinatorError("existing PR is closed or its head drifted")
            return int(query[0]["number"])
        created = self._command(
            [
                "gh",
                "pr",
                "create",
                "--repo",
                self.repository,
                "--base",
                base_ref,
                "--head",
                head,
                "--title",
                title,
                "--body",
                "Created by the bounded Agent Workflow VNext Coordinator.",
            ]
        )
        if created.returncode != 0:
            raise CoordinatorError("PR create effect is ambiguous; reconcile before retry")
        url = created.stdout.decode().strip()
        created_pr = self._json(
            [
                "gh",
                "pr",
                "view",
                url,
                "--repo",
                self.repository,
                "--json",
                "number,headRefOid,state",
            ]
        )
        if created_pr.get("headRefOid") != head_sha or created_pr.get("state") != "OPEN":
            raise CoordinatorError("created PR observation does not match the frozen head")
        return int(created_pr["number"])

    def require_ci(self, pr: int, head_sha: str) -> None:
        value = self._json(
            [
                "gh",
                "pr",
                "view",
                str(pr),
                "--repo",
                self.repository,
                "--json",
                "headRefOid,statusCheckRollup",
            ]
        )
        if value.get("headRefOid") != head_sha:
            raise CoordinatorError("CI observation head drifted")
        checks = value.get("statusCheckRollup")
        if not checks or any(check.get("conclusion") != "SUCCESS" for check in checks):
            raise CoordinatorError("exact-head CI is not successful")

    def merge(self, pr: int, head_sha: str, base_ref: str) -> str:
        completed = self._command(
            [
                "gh",
                "pr",
                "merge",
                str(pr),
                "--repo",
                self.repository,
                "--squash",
                "--match-head-commit",
                head_sha,
            ]
        )
        if completed.returncode != 0:
            raise CoordinatorError("merge effect is ambiguous; reconcile before retry")
        return self.fresh_base(base_ref)

    def fresh_base(self, base_ref: str) -> str:
        fetched = self._command(["git", "fetch", self.remote, base_ref])
        resolved = self._command(["git", "rev-parse", f"{self.remote}/{base_ref}^{{commit}}"])
        if fetched.returncode != 0 or resolved.returncode != 0:
            raise CoordinatorError("fresh base observation is unavailable")
        return resolved.stdout.decode().strip()

    def _command(self, argv: list[str]) -> subprocess.CompletedProcess[bytes]:
        return _run(argv, cwd=self.repo)

    def _json(self, argv: list[str]):
        completed = self._command(argv)
        if completed.returncode != 0:
            raise CoordinatorError("GitHub read is unavailable")
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise CoordinatorError("GitHub read returned invalid JSON") from exc
