"""Cost per incident: priced from evals/pricing.yaml by the model recorded on the investigation."""

from __future__ import annotations

from dataclasses import replace

import pytest

from tests.api.support import TERMINAL, build_app, serve, wait_for

ALERT = {"alert": "Checkout error rate above SLO", "target": "storefront", "firing_minutes": 4}


async def test_fake_playbook_costs_exactly_zero(settings, tools):
    # settings.model is "fake:playbook" (see conftest.py), priced at 0/0 in evals/pricing.yaml:
    # a real, known zero, not a stand-in for "we didn't track it".
    async with serve(build_app(settings, tools, "escalate")) as client:
        created = await client.post("/investigations", json=ALERT)
        done = await wait_for(client, created.json()["id"], TERMINAL)
        assert done["usage"]["cost_usd"] == 0.0


async def test_priced_model_cost_follows_the_tokens_and_the_price_table(tmp_path, tools):
    pricing = tmp_path / "pricing.yaml"
    pricing.write_text("custom:priced:\n  input: 2.0\n  output: 8.0\n")
    settings = replace(_base_settings(tmp_path), model="custom:priced", pricing_file=pricing)
    async with serve(build_app(settings, tools, "escalate")) as client:
        created = await client.post("/investigations", json=ALERT)
        done = await wait_for(client, created.json()["id"], TERMINAL)
    usage = done["usage"]
    assert usage["input_tokens"] > 0
    assert usage["output_tokens"] > 0
    expected = (usage["input_tokens"] * 2.0 + usage["output_tokens"] * 8.0) / 1_000_000
    assert usage["cost_usd"] == pytest.approx(expected)
    assert usage["cost_usd"] > 0


async def test_unpriced_model_reports_unknown_cost(tmp_path, tools):
    settings = replace(
        _base_settings(tmp_path),
        model="custom:not-in-the-price-table",
    )
    async with serve(build_app(settings, tools, "escalate")) as client:
        created = await client.post("/investigations", json=ALERT)
        done = await wait_for(client, created.json()["id"], TERMINAL)
        assert done["usage"]["input_tokens"] > 0
        assert done["usage"]["cost_usd"] is None


async def test_missing_pricing_file_reports_unknown_cost_for_every_model(tmp_path, tools):
    settings = replace(_base_settings(tmp_path), pricing_file=tmp_path / "does-not-exist.yaml")
    async with serve(build_app(settings, tools, "escalate")) as client:
        created = await client.post("/investigations", json=ALERT)
        done = await wait_for(client, created.json()["id"], TERMINAL)
        assert done["usage"]["cost_usd"] is None


async def test_investigation_detail_carries_a_trace_id(settings, tools):
    # The root span (and so trace_parent/trace_id) is only set once the background run starts,
    # which happens after the create response is sent; check the settled record instead.
    async with serve(build_app(settings, tools, "escalate")) as client:
        created = await client.post("/investigations", json=ALERT)
        done = await wait_for(client, created.json()["id"], TERMINAL)
        assert done["trace_id"] is not None
        assert len(done["trace_id"]) == 32
        int(done["trace_id"], 16)  # a valid hex trace id, not a placeholder string


def _base_settings(tmp_path):
    from opspilot_api.settings import ApiSettings

    return ApiSettings(
        data_dir=tmp_path / "state", model="fake:playbook", results_dir=tmp_path / "results"
    )
