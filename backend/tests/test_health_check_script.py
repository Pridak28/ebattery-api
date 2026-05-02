"""Tests for scripts/health_check.py — pure unit tests, no backend required."""

from __future__ import annotations

import importlib

import pytest


def _healthy_payload() -> dict:
    return {
        "app_version": "1.0.0",
        "manifest_present": True,
        "as_of": "2026-05-02",
        "pzu": {
            "available": True,
            "row_count": 1000,
            "max_date": "2026-05-01",
            "days_stale": 1,
        },
        "damas": {
            "available": True,
            "row_count": 5000,
            "max_date": "2026-05-01",
            "days_stale": 1,
            "fcr_activated_total_mwh": 12.5,
        },
        "simulator_pzu_smoke": {"ok": True, "total_profit_eur": 1234.5},
        "simulator_fr_smoke": {"ok": True, "total_profit_eur": 2345.6},
    }


def test_script_imports():
    """The module must import cleanly without side effects."""
    mod = importlib.import_module("scripts.health_check")
    assert hasattr(mod, "evaluate_alerts")
    assert hasattr(mod, "fetch_health")
    assert hasattr(mod, "main")
    assert mod.DEFAULT_THRESHOLD_STALE == 7


def test_evaluate_alerts_pzu_stale():
    from scripts.health_check import evaluate_alerts

    payload = _healthy_payload()
    payload["pzu"]["days_stale"] = 30  # very stale

    alerts = evaluate_alerts(payload)
    pzu_alerts = [a for a in alerts if a.subsystem == "pzu" and a.level == "ALERT"]
    assert len(pzu_alerts) == 1
    assert "30 days stale" in pzu_alerts[0].message
    assert "PZU" in pzu_alerts[0].message


def test_evaluate_alerts_all_ok():
    from scripts.health_check import evaluate_alerts

    payload = _healthy_payload()
    alerts = evaluate_alerts(payload)
    alert_lines = [a for a in alerts if a.level == "ALERT"]
    assert alert_lines == [], f"expected zero ALERTs, got {alert_lines}"


def test_evaluate_alerts_simulator_failed():
    from scripts.health_check import evaluate_alerts

    payload = _healthy_payload()
    payload["simulator_pzu_smoke"] = {"ok": False, "error": "ValueError: boom"}
    payload["simulator_fr_smoke"] = {"ok": False, "error": "RuntimeError: nope"}

    alerts = evaluate_alerts(payload)
    sim_alerts = [a for a in alerts if a.level == "ALERT" and a.subsystem.startswith("simulator")]
    assert len(sim_alerts) == 2
    messages = " | ".join(a.message for a in sim_alerts)
    assert "ValueError: boom" in messages
    assert "RuntimeError: nope" in messages


def test_evaluate_alerts_fcr_zero():
    from scripts.health_check import evaluate_alerts

    payload = _healthy_payload()
    payload["damas"]["fcr_activated_total_mwh"] = 0.0

    alerts = evaluate_alerts(payload)
    info_lines = [a for a in alerts if a.level == "INFO" and a.subsystem == "damas.fcr"]
    assert len(info_lines) == 1
    assert "FCR data unavailable" in info_lines[0].message


def test_evaluate_alerts_manifest_missing():
    from scripts.health_check import evaluate_alerts

    payload = _healthy_payload()
    payload["manifest_present"] = False

    alerts = evaluate_alerts(payload)
    manifest_alerts = [a for a in alerts if a.subsystem == "manifest" and a.level == "ALERT"]
    assert len(manifest_alerts) == 1


def test_evaluate_alerts_threshold_override():
    """A 5-day-stale dataset is OK at default 7 but ALERT at threshold=3."""
    from scripts.health_check import evaluate_alerts

    payload = _healthy_payload()
    payload["pzu"]["days_stale"] = 5

    default_alerts = [a for a in evaluate_alerts(payload) if a.level == "ALERT"]
    assert default_alerts == []

    strict_alerts = [
        a for a in evaluate_alerts(payload, threshold_stale=3) if a.level == "ALERT"
    ]
    assert any(a.subsystem == "pzu" for a in strict_alerts)


def test_render_text_quiet_suppresses_info_and_ok():
    from scripts.health_check import evaluate_alerts, render_text

    payload = _healthy_payload()
    payload["pzu"]["days_stale"] = 30  # ensure one ALERT
    alerts = evaluate_alerts(payload)

    full = render_text(alerts, quiet=False)
    quiet = render_text(alerts, quiet=True)

    assert "[OK]" in full
    assert "[OK]" not in quiet
    assert "[INFO]" not in quiet
    assert "[ALERT]" in quiet


def test_render_json_is_valid():
    import json as _json

    from scripts.health_check import evaluate_alerts, render_json

    payload = _healthy_payload()
    alerts = evaluate_alerts(payload)
    out = render_json(alerts, url="http://x/y", ok=True)
    parsed = _json.loads(out)
    assert parsed["ok"] is True
    assert parsed["alert_count"] == 0
    assert isinstance(parsed["alerts"], list)


def test_main_unreachable_returns_exit_2(capsys):
    """main() must return 2 when the endpoint cannot be reached."""
    from scripts.health_check import main

    # Use a port that won't be listening.
    rc = main(["--url", "http://127.0.0.1:1/does-not-exist"])
    assert rc == 2
    captured = capsys.readouterr()
    assert "[ALERT]" in captured.err
    assert "unreachable" in captured.err.lower()


def test_main_with_mocked_fetch_returns_1_on_alerts(monkeypatch, capsys):
    from scripts import health_check

    payload = _healthy_payload()
    payload["pzu"]["days_stale"] = 99
    monkeypatch.setattr(health_check, "fetch_health", lambda url, timeout=10.0: payload)

    rc = health_check.main(["--quiet"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "[ALERT]" in out
    assert "[OK]" not in out


def test_main_with_mocked_fetch_returns_0_on_clean(monkeypatch, capsys):
    from scripts import health_check

    monkeypatch.setattr(
        health_check, "fetch_health", lambda url, timeout=10.0: _healthy_payload()
    )
    rc = health_check.main(["--json"])
    assert rc == 0
    parsed_out = capsys.readouterr().out
    import json as _json

    parsed = _json.loads(parsed_out)
    assert parsed["ok"] is True


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
