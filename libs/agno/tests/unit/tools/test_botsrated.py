"""Unit tests for BotsRatedTools (no network: the BotsRated HTTP calls are stubbed)."""

import json
from unittest.mock import MagicMock

import pytest

try:
    import botsrated  # noqa: F401
    from botsrated import BotsRatedError, GuardPolicy

    from agno.tools.botsrated import BotsRatedTools
except ImportError:
    pytest.skip("botsrated not installed", allow_module_level=True)

SELLER = "https://seller.example/api"
OBSERVED = "0x1111111111111111111111111111111111111111"
PREFLIGHT_BODY = {
    "found": True,
    "host": "seller.example",
    "latest_probe": {
        "url": SELLER,
        "status": 402,
        "live_payTo": OBSERVED,
        "live_network": "eip155:8453",
        "live_amount": "10000",
        "receipt_url": "https://botsrated.com/receipt/abc?host=seller.example&day=2026-10-23",
    },
    "listing": {"payTo": OBSERVED, "network": "eip155:8453"},
    "freshness": {"stale": False, "last_probe_at": "2026-10-23T20:00:00Z"},
}


def _client(body=PREFLIGHT_BODY):
    client = MagicMock()
    client.host = "botsrated.com"
    client.preflight.return_value = MagicMock(found=body.get("found", True), host="seller.example", body=body)
    return client


def test_default_tools_are_free_only():
    tools = BotsRatedTools(client=_client())
    assert tools.name == "botsrated_tools"
    assert set(tools.functions) == {"preflight", "check_payment"}


def test_all_registers_quota_tools():
    tools = BotsRatedTools(client=_client(), all=True)
    assert set(tools.functions) == {"preflight", "check_payment", "check_seller", "get_seller_report"}


def test_default_client_never_pays():
    tools = BotsRatedTools()
    assert tools.client.paid_enabled is False


def test_preflight_returns_body():
    client = _client()
    out = json.loads(BotsRatedTools(client=client).preflight(SELLER))
    assert out["found"] is True
    client.preflight.assert_called_once_with(SELLER)


def test_check_payment_allows_observed_pay_to():
    out = json.loads(BotsRatedTools(client=_client()).check_payment(SELLER, OBSERVED, "10000"))
    assert out["action"] == "allow"
    assert out["receipt_url"].startswith("https://botsrated.com/receipt/")


def test_check_payment_blocks_unseen_pay_to():
    out = json.loads(BotsRatedTools(client=_client()).check_payment(SELLER, "0x" + "2" * 40, "10000"))
    assert out["action"] == "block"
    assert out["reasons"][0]["code"] == "payto_mismatch"


def test_check_payment_listing_only_never_confirms():
    body = dict(PREFLIGHT_BODY, latest_probe={"url": SELLER, "status": 200})
    out = json.loads(BotsRatedTools(client=_client(body)).check_payment(SELLER, OBSERVED, "10000"))
    assert out["action"] == "allow"
    assert out["reasons"][0]["code"] == "payto_listing_only"
    other = json.loads(BotsRatedTools(client=_client(body)).check_payment(SELLER, "0x" + "3" * 40, "10000"))
    assert other["action"] == "block"


def test_check_payment_warns_on_higher_price():
    out = json.loads(BotsRatedTools(client=_client()).check_payment(SELLER, OBSERVED, "99999"))
    assert out["action"] == "allow"
    assert [r["code"] for r in out["reasons"]] == ["price_above_observed"]
    assert out["reasons"][0]["effect"] == "warn"


def test_check_payment_policy_can_block_higher_price():
    tools = BotsRatedTools(client=_client(), policy=GuardPolicy(price_above_observed="block"))
    assert json.loads(tools.check_payment(SELLER, OBSERVED, "99999"))["action"] == "block"


def test_unreachable_fails_open_by_default_and_closed_on_request():
    client = _client()
    client.preflight.side_effect = BotsRatedError("BotsRated unreachable: timeout", "unreachable")
    assert json.loads(BotsRatedTools(client=client).check_payment(SELLER, OBSERVED, "1"))["action"] == "allow"
    closed = json.loads(BotsRatedTools(client=client, fail_open=False).check_payment(SELLER, OBSERVED, "1"))
    assert closed["action"] == "block"
    assert closed["reasons"][0]["code"] == "botsrated_unavailable"


def test_check_seller_returns_error_instead_of_paying():
    client = _client()
    client.check.side_effect = BotsRatedError("free quota used; paid routes are disabled", "paid_disabled", 402)
    out = json.loads(BotsRatedTools(client=client, all=True).check_seller("seller.example"))
    assert out == {"error": "free quota used; paid routes are disabled", "code": "paid_disabled", "status": 402}


def test_report_passes_through():
    client = _client()
    client.report.return_value = {"host": "seller.example", "charged": False}
    out = json.loads(BotsRatedTools(client=client, all=True).get_seller_report("seller.example"))
    assert out["charged"] is False
