"""End-to-end FastAPI TestClient integration tests for the public API.

Why this file exists
--------------------
We previously shipped a regression where ``GET /api/v1/pzu/typical-day``
returned HTTP 500 because the route called a service method that did not
exist. Unit-tested services + Pydantic models did not catch it because the
breakage was at the route-binding layer.

These tests exercise every public route through the real FastAPI app +
TestClient, asserting status codes and response shape. They are intentionally
loose on numeric values (data-dependent) and tight on structure / status —
the kind of contract checks that catch wiring bugs.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Make ``app`` importable when pytest is invoked from the backend root.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import app  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def client() -> TestClient:
    """Module-scoped TestClient. Reused across every test in this module so
    we pay the FastAPI startup cost once."""
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Root + detailed health
# ---------------------------------------------------------------------------
def test_root_health(client: TestClient):
    r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "healthy"
    assert "service" in body
    assert "version" in body


def test_api_health(client: TestClient):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "healthy"
    assert "data_available" in body
    assert "data_dir" in body


# ---------------------------------------------------------------------------
# PZU routes
# ---------------------------------------------------------------------------
def test_pzu_stats(client: TestClient):
    r = client.get("/api/v1/pzu/stats")
    assert r.status_code == 200, r.text
    body = r.json()
    # Stats is a free-form dict but must be a non-empty object.
    assert isinstance(body, dict)
    assert len(body) > 0


def test_pzu_history_daily(client: TestClient):
    r = client.get("/api/v1/pzu/history", params={"aggregate": "daily"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "data" in body
    assert isinstance(body["data"], list)
    assert body["count"] > 0
    assert body["count"] == len(body["data"])


def test_pzu_typical_day(client: TestClient):
    """Regression lock-in: this route previously 500ed because the route
    called a service method that didn't exist. End-to-end TestClient call
    is the layer that actually catches that class of bug."""
    r = client.get(
        "/api/v1/pzu/typical-day",
        params={
            "start_date": "2024-01-01",
            "end_date": "2024-06-01",
            "num_charge_hours": 2,
            "num_discharge_hours": 2,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "hourly_pattern" in body
    assert "charge_hours" in body
    assert "discharge_hours" in body
    assert len(body["charge_hours"]) == 2
    assert len(body["discharge_hours"]) == 2


def test_pzu_monthly_optimal(client: TestClient):
    r = client.get(
        "/api/v1/pzu/monthly-optimal",
        params={"start_date": "2025-01-01", "end_date": "2025-06-01"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "monthly_schedules" in body
    assert isinstance(body["monthly_schedules"], list)


def test_pzu_daily_breakdown(client: TestClient):
    r = client.get(
        "/api/v1/pzu/daily-breakdown/2025-01",
        params={"power_mw": 10, "capacity_mwh": 20},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "daily_results" in body or "month" in body


def test_pzu_simulate(client: TestClient):
    payload = {
        "power_mw": 10,
        "capacity_mwh": 20,
        "round_trip_efficiency": 0.88,
        "start_date": "2025-01-01",
        "end_date": "2025-06-01",
    }
    r = client.post("/api/v1/pzu/simulate", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_profit_eur"] >= 0
    assert body["days_input_count"] > 0
    assert "monthly_results" in body


# ---------------------------------------------------------------------------
# FR routes
# ---------------------------------------------------------------------------
def test_fr_products(client: TestClient):
    r = client.get("/api/v1/fr/products")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "products" in body
    assert isinstance(body["products"], list)
    assert len(body["products"]) > 0


def test_fr_stats(client: TestClient):
    r = client.get("/api/v1/fr/stats")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "total_slots" in body


def test_fr_product_catalog(client: TestClient):
    r = client.get("/api/v1/fr/product-catalog")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "products" in body


def test_fr_simulate(client: TestClient):
    payload = {
        "capacity_mwh": 20,
        "afrr_up": {"enabled": True, "power_mw": 10},
        "afrr_down": {"enabled": True, "power_mw": 10},
        "start_date": "2024-09-01",
        "end_date": "2024-12-01",
    }
    r = client.post("/api/v1/fr/simulate", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    # A-1: regime breakdowns must surface
    assert "regime_breakdowns" in body
    # A-5: bankability summary surfaces at top level
    assert "bankability_summary" in body
    assert "monthly_results" in body


def test_fr_multi_product(client: TestClient):
    payload = {
        "products": ["aFRR"],
        "power_mw": 10,
        "capacity_mwh": 20,
        "start_date": "2025-01-01",
        "end_date": "2025-06-01",
    }
    r = client.post("/api/v1/fr/multi-product", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "products" in body
    assert isinstance(body["products"], list)


# ---------------------------------------------------------------------------
# Investment routes
# ---------------------------------------------------------------------------
def test_investment_defaults(client: TestClient):
    r = client.get("/api/v1/investment/defaults")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["power_mw"] == 10
    assert body["capacity_mwh"] == 20


def test_investment_financing(client: TestClient):
    payload = {
        "total_investment_eur": 3_500_000,
        "equity_percentage": 30,
        "loan_interest_rate": 6,
        "loan_term_years": 10,
        "power_mw": 10,
        "capacity_mwh": 20,
    }
    r = client.post("/api/v1/investment/financing", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "equity_eur" in body
    assert "debt_eur" in body
    assert body["total_investment_eur"] == 3_500_000


def test_investment_analyze(client: TestClient):
    # Pydantic defaults give a complete InvestmentParams; pass empty body.
    r = client.post("/api/v1/investment/analyze", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "compliance_gates" in body
    assert "dscr_violation_years" in body
    assert "fr_scenario" in body
    assert "pzu_scenario" in body


def test_investment_tariff_exemption(client: TestClient):
    payload = {
        "power_mw": 10,
        "capacity_mwh": 20,
        "cycles_per_day": 1,
        "operating_days_per_year": 365,
    }
    r = client.post("/api/v1/investment/tariff-exemption", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["avoided_cost_eur"] > 0
    assert "breakdown_eur_mwh" in body


def test_investor_summary_endpoint(client: TestClient):
    """``POST /investment/investor-summary`` must return a flat one-page
    payload suitable for external rendering (PDF / lender portal / Slack).

    Asserts: 200 status, all key fields present, types correct, IRR tier
    in the allowed enum, gate counts coherent.
    """
    payload = {
        "power_mw": 10,
        "capacity_mwh": 20,
        "total_investment_eur": 3_500_000,
    }
    r = client.post("/api/v1/investment/investor-summary", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()

    # Core identity
    assert isinstance(body["generated_at_utc"], str)
    assert "MW" in body["project_sizing"] and "MWh" in body["project_sizing"]
    assert body["capex_eur"] == 3_500_000

    # Headline metrics — types
    for key in (
        "fr_y1_net_profit_eur",
        "pzu_y1_net_profit_eur",
        "combined_y1_net_profit_eur",
        "dscr_y1",
        "dscr_worst_year",
        "fr_capacity_revenue_y1",
        "fr_activation_revenue_y1",
        "pzu_arbitrage_y1",
        "tariff_exemption_y1",
    ):
        assert isinstance(body[key], (int, float)), f"{key} must be numeric"

    # Combined = FR + PZU (within float tolerance)
    assert abs(
        body["combined_y1_net_profit_eur"]
        - (body["fr_y1_net_profit_eur"] + body["pzu_y1_net_profit_eur"])
    ) < 1e-3

    # IRR tier enum
    assert body["irr_tier"] in {"high", "medium", "low", "unknown"}

    # Compliance gates
    assert body["compliance_gates_total"] == 11
    assert 0 <= body["compliance_gates_qualified_count"] <= body["compliance_gates_total"]
    # All-default gates: at least one not-qualified, so most_blocking_gate set.
    assert body["most_blocking_gate"] is not None
    assert isinstance(body["blocked_revenue_streams"], list)

    # Bankability + provenance
    assert isinstance(body["bankability_level"], str) and body["bankability_level"]
    assert isinstance(body["settlement_grade"], bool)
    assert isinstance(body["pricing_basis"], str) and body["pricing_basis"]
    assert isinstance(body["revenue_source"], str) and body["revenue_source"]

    # Risk indicators
    assert isinstance(body["dscr_violation_count"], int)
    assert body["dscr_violation_count"] >= 0
    assert isinstance(body["picasso_compression_modeled"], bool)

    # Disclaimers / audit
    assert isinstance(body["disclaimer"], str) and len(body["disclaimer"]) > 0
    assert body["audit_reference"].endswith(".md")


def test_investment_sensitivity(client: TestClient):
    """Monte Carlo over financial drivers. Use a small ``runs`` for speed."""
    payload = {
        "params": {},
        "config": {"runs": 50, "seed": 42},
    }
    r = client.post("/api/v1/investment/sensitivity", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "p10_irr" in body
    assert "p50_irr" in body
    assert "p90_irr" in body
    assert body["runs"] == 50


# ---------------------------------------------------------------------------
# Data routes
# ---------------------------------------------------------------------------
def test_data_manifest(client: TestClient):
    r = client.get("/api/v1/data/manifest")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "datasets" in body
    assert isinstance(body["datasets"], list)


def test_data_status(client: TestClient):
    r = client.get("/api/v1/data/status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "data_dir" in body
    assert "manifest_exists" in body


def test_health_detailed_returns_subsystems(client: TestClient):
    """Extended health-check must expose per-sub-system diagnostics so
    investors / SREs can see at a glance which dataset is fresh, whether
    simulators are runnable, and the regime split. Each sub-system runs in
    its own try/except — one broken piece must never 500 the endpoint."""
    r = client.get("/api/v1/data/health-detailed")
    assert r.status_code == 200, r.text
    body = r.json()
    expected_top_level = {
        "app_version",
        "data_dir",
        "manifest_present",
        "as_of",
        "pzu",
        "damas",
        "simulator_pzu_smoke",
        "simulator_fr_smoke",
        "compliance_gates_default",
    }
    assert expected_top_level.issubset(body.keys()), sorted(body.keys())
    assert body["pzu"]["available"] is True
    # D-1: damas_clean.csv carries fcr_activated_mwh=0 across all rows.
    assert body["damas"]["fcr_activated_total_mwh"] == 0


# ---------------------------------------------------------------------------
# Error path tests
# ---------------------------------------------------------------------------
def test_pzu_simulate_negative_power_rejected(client: TestClient):
    """Pydantic field validator (``ge=0.1``) must reject negative power
    with HTTP 422 rather than silently producing nonsense."""
    payload = {
        "power_mw": -10,
        "capacity_mwh": 20,
        "round_trip_efficiency": 0.88,
    }
    r = client.post("/api/v1/pzu/simulate", json=payload)
    assert r.status_code == 422, r.text


def test_pzu_daily_breakdown_out_of_range_month(client: TestClient):
    """Querying a month with no data should return either 200 with an empty
    result set or a 4xx — never 500."""
    r = client.get("/api/v1/pzu/daily-breakdown/2099-01")
    assert r.status_code in (200, 400, 404, 422), r.text
    if r.status_code == 200:
        body = r.json()
        # Empty results expected.
        assert body.get("daily_results", []) == []
