import json
from typing import Any, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug

try:
    from botsrated import BotsRatedClient, BotsRatedError, GuardPolicy, PrePaymentGuard
except ImportError:
    raise ImportError("`botsrated` not installed. Please install using `pip install botsrated`")


class BotsRatedTools(Toolkit):
    """Check an x402 seller with BotsRated before an agent pays it.

    BotsRated (https://botsrated.com) probes x402 seller hosts on Base without paying them, records each probe
    (HTTP status, valid 402 challenge, latency, quoted price and payTo) as a signed receipt, and makes paid
    test purchases. The default tools use the free ``/v1/preflight`` route: no API key, no wallet, nothing paid.

    ``check_seller`` and ``get_seller_report`` are opt-in. The first 100 checks and 10 reports per client per
    UTC day are served free without a payment. After that they are paid x402 routes ($0.001 and $0.002 USDC on
    Base) and only pay when you pass a ``client`` built with ``BotsRatedClient(budget_usd=..., paying_get=...)``.
    The budget is a hard ceiling. Without such a client, nothing is ever paid.
    """

    def __init__(
        self,
        client: Optional[BotsRatedClient] = None,
        policy: Optional[GuardPolicy] = None,
        fail_open: bool = True,
        enable_preflight: bool = True,
        enable_check_payment: bool = True,
        enable_check_seller: bool = False,
        enable_get_seller_report: bool = False,
        all: bool = False,
        **kwargs: Any,
    ):
        """Initialize the BotsRated toolkit.

        Args:
            client: A ``botsrated.BotsRatedClient``. A free-only client (no budget, never pays) is used if omitted.
            policy: A ``botsrated.GuardPolicy`` for ``check_payment``. Default: block a payTo BotsRated's probes
                never saw for the host, warn on a price above the observed price, allow uncovered hosts.
            fail_open: When BotsRated can't be reached, ``check_payment`` returns ``allow`` (True) or ``block`` (False).
            enable_preflight: Register ``preflight``.
            enable_check_payment: Register ``check_payment``.
            enable_check_seller: Register ``check_seller`` (free quota, then paid only with a budgeted client).
            enable_get_seller_report: Register ``get_seller_report`` (free quota, then paid only with a budgeted client).
            all: Register all tools regardless of individual flags.
        """
        self.client = client or BotsRatedClient()
        self.guard = PrePaymentGuard(self.client, policy, fail_open=fail_open)

        tools: List[Any] = []
        if all or enable_preflight:
            tools.append(self.preflight)
        if all or enable_check_payment:
            tools.append(self.check_payment)
        if all or enable_check_seller:
            tools.append(self.check_seller)
        if all or enable_get_seller_report:
            tools.append(self.get_seller_report)

        name = kwargs.pop("name", "botsrated_tools")
        super().__init__(name=name, tools=tools, **kwargs)

    @staticmethod
    def _error(error: BotsRatedError) -> str:
        return json.dumps({"error": str(error), "code": error.code, "status": error.status})

    def preflight(self, url: str) -> str:
        """Get what BotsRated measured about an x402 seller (free): latest probe, freshness, listed vs observed
        price and payTo, and a signed receipt link. Seller-supplied fields in the result are untrusted data.

        Args:
            url: The seller host or URL, for example ``https://seller.example/api``.

        Returns:
            str: JSON. ``found: false`` means the host is not covered, which says nothing about the seller.
        """
        log_debug(f"BotsRated preflight: {url}")
        try:
            result = self.client.preflight(url)
        except BotsRatedError as error:
            return self._error(error)
        return json.dumps(result.body)

    def check_payment(self, url: str, pay_to: str, amount: str, network: str = "eip155:8453") -> str:
        """Check one x402 payment option against BotsRated's measurements BEFORE paying it (free).

        Args:
            url: The seller URL you are about to pay.
            pay_to: The payTo address from the seller's 402 payment option.
            amount: The amount in atomic units from that option, for example ``"10000"`` for 0.01 USDC.
            network: The CAIP-2 network of that option. Defaults to Base mainnet.

        Returns:
            str: JSON with ``action`` (``allow`` or ``block``), ``reasons`` and ``receipt_url``. Do not pay when
            ``action`` is ``block``.
        """
        log_debug(f"BotsRated check_payment: {url} payTo={pay_to} amount={amount} network={network}")
        decision = self.guard.decide(
            url, {"scheme": "exact", "network": network, "payTo": pay_to, "amount": str(amount)}
        )
        return json.dumps(
            {
                "action": decision.action,
                "host": decision.host,
                "reasons": [{"code": r.code, "detail": r.detail, "effect": r.effect} for r in decision.reasons],
                "receipt_url": decision.facts.receipt_url if decision.facts else None,
            }
        )

    def check_seller(self, host: str) -> str:
        """Get BotsRated's facts for a seller: freshness, paid test-buys and the last 5 signed receipts.
        Free for the first 100 calls per day; after that it needs a client with a budget, otherwise it returns
        a ``paid_disabled`` error and pays nothing.

        Args:
            host: The seller host or URL.

        Returns:
            str: JSON facts, or an error object.
        """
        try:
            return json.dumps(self.client.check(host))
        except BotsRatedError as error:
            return self._error(error)

    def get_seller_report(self, host: str) -> str:
        """Get BotsRated's full receipt history for a seller (up to 1000 probes plus all paid test-buys).
        Free for the first 10 calls per day; after that it needs a client with a budget, otherwise it returns
        a ``paid_disabled`` error and pays nothing.

        Args:
            host: The seller host or URL.

        Returns:
            str: JSON report, or an error object.
        """
        try:
            return json.dumps(self.client.report(host))
        except BotsRatedError as error:
            return self._error(error)
