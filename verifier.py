"""Verifier stage for ClassPrep Autopilot.

Checks curator items — dicts with ``title``, ``source_name`` and
``source_url`` — and returns a JSON-serialisable report. For each item
it reports whether the URL is well-formed and whether it is reachable
(HEAD request, 5s timeout), plus a summary count of pass/flag.

The Verifier flags, never silently fixes: a malformed or unreachable
URL is reported as ``flag`` with a reason, and the item is left as-is.

Uses only the standard library (``urllib``) so it needs no extra
dependency beyond the Flask app's existing requirements.
"""
from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from typing import Literal, TypedDict

__all__ = [
    "CuratorItem",
    "ItemResult",
    "VerifyReport",
    "VerifySummary",
    "verify_items",
]

HEAD_TIMEOUT: float = 5.0
_USER_AGENT: str = "ClassPrep-Autopilot-Verifier/1.0"


class CuratorItem(TypedDict, total=False):
    """One item as produced by the Curator stage."""

    title: str
    source_name: str
    source_url: str


class ItemResult(TypedDict):
    """Verification result for a single curator item."""

    title: str
    source_name: str
    source_url: str
    well_formed: bool
    url_well_formed: bool  # alias of ``well_formed``
    reachable: bool
    status: Literal["pass", "flag"]
    status_code: int | None
    error: str | None


# ``pass`` is a keyword, so the summary TypedDict is built via the
# functional form to allow that key.
VerifySummary = TypedDict(
    "VerifySummary",
    {
        "total": int,
        "pass": int,
        "flag": int,
        "passed": int,
        "flagged": int,
    },
)


class VerifyReport(TypedDict):
    """Full report returned by :func:`verify_items`."""

    items: list[ItemResult]
    summary: VerifySummary


def _is_well_formed_url(url: object) -> bool:
    """Return True if *url* is a well-formed absolute http(s) URL."""
    if not isinstance(url, str):
        return False
    candidate = url.strip()
    if not candidate or candidate != url:
        return False
    if any(ch.isspace() for ch in candidate):
        return False
    # Reject control characters.
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in candidate):
        return False
    try:
        parsed = urllib.parse.urlparse(candidate)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    if not parsed.netloc:
        return False
    try:
        hostname = parsed.hostname
        # Accessing .port can raise ValueError for a malformed port.
        _ = parsed.port
    except ValueError:
        return False
    if not hostname:
        return False
    return True


def _check_reachable(url: str, timeout: float = HEAD_TIMEOUT) -> tuple[bool, int | None, str | None]:
    """HEAD *url*; return (reachable, status_code, error).

    Reachable means the server answered with a 2xx or 3xx status.
    Any HTTP error status, connection error, or timeout is flagged.
    """
    request = urllib.request.Request(
        url,
        method="HEAD",
        headers={"User-Agent": _USER_AGENT, "Accept": "*/*"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status_code: int | None = response.getcode()
    except urllib.error.HTTPError as exc:
        # An HTTP response was received; judge it by its status code.
        status_code = exc.code
        if 200 <= status_code < 400:
            return True, status_code, None
        return False, status_code, f"HTTP {status_code}"
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        return False, None, str(reason) or exc.__class__.__name__
    if status_code is None:
        return False, None, "no response"
    if 200 <= status_code < 400:
        return True, status_code, None
    return False, status_code, f"HTTP {status_code}"


def verify_items(items: list[CuratorItem]) -> VerifyReport:
    """Verify a list of curator items.

    Args:
        items: Curator items, each a dict with ``title``,
            ``source_name`` and ``source_url``.

    Returns:
        A report ``{"items": [...], "summary": {...}}``. Each entry
        keeps the item's ``title``/``source_name``/``source_url`` and
        adds ``well_formed`` (alias ``url_well_formed``), ``reachable``,
        ``status`` (``"pass"`` only when the URL is both well-formed
        and reachable, otherwise ``"flag"``), ``status_code`` (HTTP
        status when a response was received, else ``None``) and
        ``error`` (reason when flagged, else ``None``). ``summary``
        holds ``total``/``pass``/``flag`` counts (with ``passed`` /
        ``flagged`` aliases).
    """
    results: list[ItemResult] = []

    for item in items or []:
        # Tolerate missing keys / non-dict rows by flagging them.
        if isinstance(item, dict):
            title = item.get("title") or ""
            source_name = item.get("source_name") or ""
            source_url = item.get("source_url") or ""
        else:
            title, source_name, source_url = "", "", ""
        if not isinstance(title, str):
            title = str(title)
        if not isinstance(source_name, str):
            source_name = str(source_name)
        if not isinstance(source_url, str):
            source_url = "" if source_url is None else str(source_url)

        well_formed = _is_well_formed_url(source_url)
        if not well_formed:
            results.append(
                ItemResult(
                    title=title,
                    source_name=source_name,
                    source_url=source_url,
                    well_formed=False,
                    url_well_formed=False,
                    reachable=False,
                    status="flag",
                    status_code=None,
                    error="malformed URL",
                )
            )
            continue

        reachable, status_code, error = _check_reachable(source_url.strip())
        status: Literal["pass", "flag"] = "pass" if reachable else "flag"
        results.append(
            ItemResult(
                title=title,
                source_name=source_name,
                source_url=source_url,
                well_formed=True,
                url_well_formed=True,
                reachable=reachable,
                status=status,
                status_code=status_code,
                error=error,
            )
        )

    passed = sum(1 for r in results if r["status"] == "pass")
    flagged = len(results) - passed
    summary: VerifySummary = {
        "total": len(results),
        "pass": passed,
        "flag": flagged,
        "passed": passed,
        "flagged": flagged,
    }
    return VerifyReport(items=results, summary=summary)
