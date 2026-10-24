"""Configuration for Pact.

Every value comes from environment variables. Nothing is hardcoded and no
credential lives in the source tree. When the PayPal variables are absent the
app runs in demo mode with a local payment simulator, and that mode is labeled
in the UI, in the API health response, and in the audit ledger.
"""

import os
from dataclasses import dataclass


@dataclass
class Settings:
    paypal_client_id: str = ""
    paypal_client_secret: str = ""
    paypal_base_url: str = "https://api-m.sandbox.paypal.com"
    paypal_webhook_id: str = ""
    seller_sandbox_email: str = ""
    buyer_sandbox_email: str = ""
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    bond_percent: float = 20.0
    channel3_api_key: str = ""
    channel3_base_url: str = "https://api.trychannel3.com"

    @property
    def paypal_live(self) -> bool:
        """True only when real sandbox credentials are configured."""
        return bool(self.paypal_client_id and self.paypal_client_secret)

    @property
    def mode(self) -> str:
        return "sandbox" if self.paypal_live else "demo"

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key)


def validate_config(settings):
    """Fail loudly when live mode is misconfigured.

    Live mode is when PAYPAL_CLIENT_ID or PAYPAL_CLIENT_SECRET is present.
    The approval payer check needs the sandbox account identities, so live
    mode requires both sandbox emails. The webhook id stays optional: the
    webhook endpoint only verifies signatures when it is configured, and
    settlement never depends on webhooks. Demo mode requires nothing.
    Raises RuntimeError naming the missing vars.
    """
    live = bool(settings.paypal_client_id or settings.paypal_client_secret)
    missing = []
    if live:
        if not settings.paypal_client_id:
            missing.append("PAYPAL_CLIENT_ID")
        if not settings.paypal_client_secret:
            missing.append("PAYPAL_CLIENT_SECRET")
        if not settings.seller_sandbox_email:
            missing.append("SELLER_SANDBOX_EMAIL")
        if not settings.buyer_sandbox_email:
            missing.append("BUYER_SANDBOX_EMAIL")
    if missing:
        raise RuntimeError(
            "Pact refuses to boot in live PayPal mode: missing required "
            "environment variables: " + ", ".join(missing) + ". Live mode "
            "starts when PAYPAL_CLIENT_ID or PAYPAL_CLIENT_SECRET is set."
        )
    return live


def load_settings() -> Settings:
    return Settings(
        paypal_client_id=os.environ.get("PAYPAL_CLIENT_ID", "").strip(),
        paypal_client_secret=os.environ.get("PAYPAL_CLIENT_SECRET", "").strip(),
        paypal_base_url=os.environ.get(
            "PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com"
        ).rstrip("/"),
        paypal_webhook_id=os.environ.get("PAYPAL_WEBHOOK_ID", "").strip(),
        seller_sandbox_email=os.environ.get("SELLER_SANDBOX_EMAIL", "").strip(),
        buyer_sandbox_email=os.environ.get("BUYER_SANDBOX_EMAIL", "").strip(),
        llm_api_key=os.environ.get("LLM_API_KEY", "").strip(),
        llm_base_url=os.environ.get(
            "LLM_BASE_URL", "https://api.openai.com/v1"
        ).rstrip("/"),
        llm_model=os.environ.get("LLM_MODEL", "gpt-4o-mini").strip(),
        bond_percent=float(os.environ.get("BOND_PERCENT", "20")),
        channel3_api_key=os.environ.get("CHANNEL3_API_KEY", "").strip(),
        channel3_base_url=os.environ.get(
            "CHANNEL3_BASE_URL", "https://api.trychannel3.com"
        ).rstrip("/"),
    )


SETTINGS = load_settings()
