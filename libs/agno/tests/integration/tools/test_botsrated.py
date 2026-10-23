"""Live tests for BotsRatedTools. They call BotsRated's free preflight; nothing is paid."""

import json

import pytest

try:
    from agno.tools.botsrated import BotsRatedTools
except ImportError:
    pytest.skip("botsrated not installed", allow_module_level=True)

SELLER = "https://blockrun.ai/api/v1/chat/completions"


def test_live_preflight_and_check_payment():
    tools = BotsRatedTools()
    body = json.loads(tools.preflight(SELLER))
    assert body["found"] is True
    observed = body["latest_probe"]["live_payTo"]

    allowed = json.loads(tools.check_payment(SELLER, observed, "1000"))
    assert allowed["action"] == "allow"

    blocked = json.loads(tools.check_payment(SELLER, "0x000000000000000000000000000000000000dEaD", "1000"))
    assert blocked["action"] == "block"
    assert blocked["reasons"][0]["code"] == "payto_mismatch"


def test_live_uncovered_host_is_allowed_with_info():
    out = json.loads(BotsRatedTools().check_payment("https://not-a-seller.invalid/x", "0x" + "1" * 40, "1000"))
    assert out["action"] == "allow"
    assert out["reasons"][0]["code"] in ("not_covered", "botsrated_unavailable")
