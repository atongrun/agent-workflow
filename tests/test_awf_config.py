from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

from scripts import awf_config


def write_config(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)
    return path


def host_uid(path: Path) -> int:
    getter = getattr(os, "geteuid", None)
    return getter() if getter is not None else path.stat().st_uid


def owner_acl_runner(path: Path):
    def run_acl(argv, **_kwargs):
        if argv[0] == "whoami":
            return subprocess.CompletedProcess(argv, 0, "HOST\\owner\n", "")
        return subprocess.CompletedProcess(argv, 0, f"{path} HOST\\owner:(F)\n", "")

    return run_acl


def test_parse_accepts_legacy_export_without_shell_interpretation(tmp_path):
    path = write_config(
        tmp_path / "dispatch.env",
        "\n".join(
            [
                "# legacy files remain readable",
                "export AGENT_BUS_URL=http://bus.invalid:8800",
                "export AWF_CODER_TOKEN=controlled-token",
                "AWF_BUS_BIN=${HOME}/bin/agent-bus",
                "",
            ]
        ),
    )

    loaded = awf_config.parse_config_text(path.read_text(encoding="utf-8"))

    assert loaded["AGENT_BUS_URL"] == "http://bus.invalid:8800"
    assert loaded["AWF_CODER_TOKEN"] == "controlled-token"
    assert loaded["AWF_BUS_BIN"] == "${HOME}/bin/agent-bus"


def test_parse_accepts_pi_binary_configuration():
    loaded = awf_config.parse_config_text(
        "AGENT_BUS_URL=http://bus.invalid\n"
        "AWF_REVIEWER_TOKEN=controlled-token\n"
        "AWF_PI_BIN=/opt/homebrew/bin/pi\n"
    )

    assert loaded["AWF_PI_BIN"] == "/opt/homebrew/bin/pi"


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("AGENT_BUS_URL=http://bus.invalid\nAGENT_BUS_URL=http://other.invalid\n", "duplicate"),
        ("AWF_CODER_TOKEN=one\nAWF_CODER_TOKEN=two\n", "duplicate"),
        ("AWF_UNKNOWN_CRITICAL=value\n", "unknown"),
        ("UNKNOWN=value\n", "unknown"),
        ("AGENT_BUS_URL\n", "assignment"),
        ("export  AWF_CODER_TOKEN=value\n", "assignment"),
        ("AWF_CODER_TOKEN=\n", "empty"),
        ("AWF_CODER_TOKEN=value\x00tail\n", "NUL"),
    ],
)
def test_parse_fails_closed_without_echoing_values(text, reason):
    with pytest.raises(awf_config.ConfigError) as exc:
        awf_config.parse_config_text(text)

    assert reason.casefold() in str(exc.value).casefold()
    assert "one" not in str(exc.value)
    assert "two" not in str(exc.value)
    assert "value\x00tail" not in str(exc.value)


@pytest.mark.skipif(os.name == "nt", reason="POSIX ownership and mode contract")
def test_posix_permissions_owner_and_regular_path_are_fail_closed(tmp_path, monkeypatch):
    path = write_config(tmp_path / "dispatch.env", "AWF_CODER_TOKEN=secret\n")
    path.chmod(0o640)
    with pytest.raises(awf_config.ConfigError, match="owner-only"):
        awf_config.load_config(path, platform="posix", expected_uid=host_uid(path))

    path.chmod(0o600)
    with pytest.raises(awf_config.ConfigError, match="owner"):
        awf_config.load_config(path, platform="posix", expected_uid=host_uid(path) + 1)

    target = write_config(tmp_path / "target.env", "AWF_CODER_TOKEN=secret\n")
    link = tmp_path / "link.env"
    link.symlink_to(target)
    with pytest.raises(awf_config.ConfigError, match="symbolic link"):
        awf_config.load_config(link, platform="posix", expected_uid=host_uid(target))

    relative = Path("dispatch.env")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(awf_config.ConfigError, match="absolute"):
        awf_config.load_config(relative, platform="posix", expected_uid=host_uid(path))


def test_windows_acl_validation_is_deterministic_and_does_not_echo_secrets(tmp_path):
    path = write_config(tmp_path / "dispatch.env", "AWF_CODER_TOKEN=do-not-print\n")

    def run_ok(argv, **_kwargs):
        if argv[0] == "whoami":
            return subprocess.CompletedProcess(argv, 0, "HOST\\owner\n", "")
        return subprocess.CompletedProcess(
            argv,
            0,
            f"{path} HOST\\owner:(F)\n\nSuccessfully processed 1 files\n",
            "",
        )

    loaded = awf_config.load_config(path, platform="windows", runner=run_ok)
    assert loaded["AWF_CODER_TOKEN"] == "do-not-print"

    def run_bad(argv, **_kwargs):
        if argv[0] == "whoami":
            return subprocess.CompletedProcess(argv, 0, "HOST\\owner\n", "")
        return subprocess.CompletedProcess(
            argv,
            0,
            f"{path} HOST\\owner:(F)\nBUILTIN\\Users:(RX)\n",
            "",
        )

    with pytest.raises(awf_config.ConfigError) as exc:
        awf_config.load_config(path, platform="windows", runner=run_bad)
    assert "do-not-print" not in str(exc.value)


def test_apply_config_overrides_only_allowlisted_keys(tmp_path, monkeypatch):
    path = write_config(
        tmp_path / "dispatch.env",
        "AGENT_BUS_URL=http://bus.invalid\nAWF_REVIEWER_TOKEN=from-file\n",
    )
    monkeypatch.setenv("AWF_REVIEWER_TOKEN", "old")

    kwargs = (
        {"platform": "windows", "runner": owner_acl_runner(path)}
        if os.name == "nt"
        else {"platform": "posix", "expected_uid": host_uid(path)}
    )
    loaded = awf_config.load_into_environment(path, **kwargs)

    assert loaded["AWF_REVIEWER_TOKEN"] == "from-file"
    assert os.environ["AWF_REVIEWER_TOKEN"] == "old"
    assert os.environ["AGENT_BUS_URL"] == "http://bus.invalid"


def test_serialize_config_is_stable_and_rejects_unknown_keys():
    values = {
        "AWF_CODER_TOKEN": "controlled-token",
        "AGENT_BUS_URL": "http://bus.invalid",
    }
    assert awf_config.serialize_config(values) == (
        "AGENT_BUS_URL=http://bus.invalid\nAWF_CODER_TOKEN=controlled-token\n"
    )
    with pytest.raises(awf_config.ConfigError, match="unknown"):
        awf_config.serialize_config({"AWF_NEW_TOKEN": "secret"})


def test_config_module_never_uses_shell_execution():
    source = Path(awf_config.__file__).read_text(encoding="utf-8")
    assert "shell=True" not in source
    assert "os.system" not in source
    assert "expandvars" not in source
    assert stat.S_ISREG(Path(awf_config.__file__).stat().st_mode)


def test_production_entrypoints_use_native_python_without_sourcing_configuration():
    root = Path(__file__).resolve().parents[1]
    sources = {
        path: (root / path).read_text(encoding="utf-8").casefold()
        for path in (
            "scripts/awf-dispatch.sh",
            "scripts/awf_dispatch.py",
            "scripts/service/awf-listen-service.sh",
            "scripts/service/awf-listen-service.cmd",
            "scripts/awf_service.py",
        )
    }
    assert '. "$dispatch_env"' not in sources["scripts/service/awf-listen-service.sh"]
    assert "source dispatch.env" not in "\n".join(sources.values())
    assert "awf_gitbash" not in sources["scripts/service/awf-listen-service.cmd"]
    assert "awf_dispatch.py" in sources["scripts/awf-dispatch.sh"]
    assert "load_into_environment" in sources["scripts/awf_dispatch.py"]
    assert "shell=true" not in sources["scripts/awf_dispatch.py"]
    assert "load_profile" in sources["scripts/awf_service.py"]
    assert "awf_profile" in sources["scripts/awf_service.py"]
