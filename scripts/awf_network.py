"""Network environment helpers shared by Agent Workflow entry points."""

from __future__ import annotations

from urllib.parse import urlsplit


def add_url_host_to_no_proxy(environment: dict[str, str], url: str) -> None:
    """Preserve existing proxy exclusions and add the URL host to both variants."""
    host = urlsplit(url).hostname
    if not host:
        return

    entries: list[str] = []
    seen: set[str] = set()
    for key in ("NO_PROXY", "no_proxy"):
        for entry in environment.get(key, "").split(","):
            value = entry.strip()
            folded = value.casefold()
            if value and folded not in seen:
                entries.append(value)
                seen.add(folded)
    if host.casefold() not in seen:
        entries.append(host)

    merged = ",".join(entries)
    environment["NO_PROXY"] = merged
    environment["no_proxy"] = merged
