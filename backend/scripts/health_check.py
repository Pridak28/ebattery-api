"""Operational health-check poller for battery-analytics-pro backend.

CLI script (not a route) that polls ``/api/v1/data/health-detailed`` and
emits structured alert lines when sub-systems are stale or failing.

Stdlib-only (urllib + json + argparse). Designed for cron-driven ops use:
exit code 0 = clean, 1 = alerts present, 2 = backend unreachable.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any, Dict, List

DEFAULT_URL = "http://127.0.0.1:8000/api/v1/data/health-detailed"
DEFAULT_THRESHOLD_STALE = 7


@dataclass
class Alert:
    """A single structured alert/info/ok line."""

    level: str  # "ALERT" | "INFO" | "OK"
    subsystem: str
    message: str

    def format_text(self) -> str:
        return f"[{self.level}] {self.subsystem}: {self.message}"


def evaluate_alerts(
    health_payload: Dict[str, Any],
    *,
    threshold_stale: int = DEFAULT_THRESHOLD_STALE,
) -> List[Alert]:
    """Pure evaluator — turns a health payload dict into a list of Alerts.

    No I/O. Safe to unit-test with synthesized payloads.
    """
    alerts: List[Alert] = []

    # ---- manifest ----
    manifest_present = health_payload.get("manifest_present")
    if manifest_present is False:
        alerts.append(Alert("ALERT", "manifest", "manifest.json is missing"))
    elif manifest_present is True:
        alerts.append(Alert("OK", "manifest", "manifest present"))

    # ---- pzu staleness ----
    pzu = health_payload.get("pzu") or {}
    pzu_stale = pzu.get("days_stale")
    if isinstance(pzu_stale, (int, float)) and pzu_stale > threshold_stale:
        alerts.append(
            Alert("ALERT", "pzu", f"PZU data is {int(pzu_stale)} days stale")
        )
    elif isinstance(pzu_stale, (int, float)):
        alerts.append(
            Alert("OK", "pzu", f"fresh ({int(pzu_stale)}d stale)")
        )

    # ---- damas staleness ----
    damas = health_payload.get("damas") or {}
    damas_stale = damas.get("days_stale")
    if isinstance(damas_stale, (int, float)) and damas_stale > threshold_stale:
        alerts.append(
            Alert("ALERT", "damas", f"DAMAS data is {int(damas_stale)} days stale")
        )
    elif isinstance(damas_stale, (int, float)):
        alerts.append(
            Alert("OK", "damas", f"fresh ({int(damas_stale)}d stale)")
        )

    # ---- damas FCR availability (informational, expected zero) ----
    fcr_total = damas.get("fcr_activated_total_mwh")
    if fcr_total == 0 or fcr_total == 0.0:
        alerts.append(
            Alert(
                "INFO",
                "damas.fcr",
                "FCR data unavailable (expected, see audit doc)",
            )
        )

    # ---- simulator smokes ----
    for key, label in (
        ("simulator_pzu_smoke", "simulator.pzu"),
        ("simulator_fr_smoke", "simulator.fr"),
    ):
        sim = health_payload.get(key) or {}
        ok = sim.get("ok")
        if ok is False:
            err = sim.get("error", "unknown error")
            alerts.append(Alert("ALERT", label, f"smoke failed: {err}"))
        elif ok is True:
            alerts.append(Alert("OK", label, "smoke passed"))

    return alerts


def fetch_health(url: str, timeout: float = 10.0) -> Dict[str, Any]:
    """Fetch the health-detailed endpoint with stdlib urllib only."""
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        raw = resp.read().decode("utf-8")
    return json.loads(raw)


def render_text(alerts: List[Alert], *, quiet: bool) -> str:
    visible = [a for a in alerts if not quiet or a.level == "ALERT"]
    return "\n".join(a.format_text() for a in visible)


def render_json(alerts: List[Alert], *, url: str, ok: bool) -> str:
    return json.dumps(
        {
            "url": url,
            "ok": ok,
            "alert_count": sum(1 for a in alerts if a.level == "ALERT"),
            "alerts": [asdict(a) for a in alerts],
        },
        indent=2,
    )


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="scripts.health_check",
        description="Poll /api/v1/data/health-detailed and emit ops alerts.",
    )
    p.add_argument("--url", default=DEFAULT_URL, help="Health endpoint URL.")
    p.add_argument(
        "--threshold-stale",
        type=int,
        default=DEFAULT_THRESHOLD_STALE,
        help="Day threshold above which data is considered stale.",
    )
    p.add_argument("--quiet", action="store_true", help="Suppress INFO/OK lines.")
    p.add_argument("--json", action="store_true", help="Output JSON instead of text.")
    return p


def main(argv: List[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    try:
        payload = fetch_health(args.url)
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
        print(f"[ALERT] Backend unreachable at {args.url}: {exc}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"[ALERT] Backend returned invalid JSON at {args.url}: {exc}", file=sys.stderr)
        return 2

    alerts = evaluate_alerts(payload, threshold_stale=args.threshold_stale)
    has_alert = any(a.level == "ALERT" for a in alerts)

    if args.json:
        print(render_json(alerts, url=args.url, ok=not has_alert))
    else:
        text = render_text(alerts, quiet=args.quiet)
        if text:
            print(text)

    return 1 if has_alert else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
