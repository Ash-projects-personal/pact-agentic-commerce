"""An agent drives a full Pact deal through the APIMatic Python SDK.

This is the working example for queue item K. It uses the generated SDK
in sdk/pact-python-sdk.zip (61 files, built by APIMatic from the spec at
sdk/pact-openapi.json) to run one deal end to end: create, negotiate,
pay, deliver, verify, then download the dispute packet.

Run it with: sdk/.venv/bin/python sdk/agent_example.py

By default it boots its own demo-mode server on 127.0.0.1:8123 with a
throwaway database, so no PayPal account is touched and the whole deal
settles on the local simulator. Set PACT_BASE_URL to point it at another
server instead; that server must be in demo mode, because a sandbox
server stops at the human approval step by design (PayPal requires the
account holder to approve a wallet payment before capture, and Pact
keeps that checkpoint on purpose).

Three honest notes about the SDK itself:

1. The generated client assumes https. A local demo server speaks
   http, so the example patches the SDK's base URI template to http
   for the local run. Against the hosted Render demo (https) no patch
   is needed.
2. The OpenAPI spec does not declare the per-deal role token header,
   so the generated methods take no token argument. The example works
   around it the way a real client would: one requests Session per
   role, with X-Deal-Token set on the session after the create call
   returns both tokens. The buyer session drives negotiate, pay, and
   verify; the seller session drives deliver.
3. The hosted APIMatic developer portal is not published yet. The SDK
   in this repo is the generated artifact; the portal needs a
   Docs-as-Code build that runs on a developer machine, not here.

Exit code 0 means the deal settled to released and the dispute packet
downloaded. Anything else exits 1 with the failing step printed.
"""

import os
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
PROJ = HERE.parent
SDK_ZIP = HERE / "pact-python-sdk.zip"
DEFAULT_PORT = 8123


def extract_sdk():
    extract = Path(tempfile.mkdtemp(prefix="pact_sdk_"))
    with zipfile.ZipFile(SDK_ZIP) as zf:
        zf.extractall(extract)
    sys.path.insert(0, str(extract))


def boot_demo_server(port):
    """Start a throwaway demo-mode server. Returns the process."""
    db = f"/tmp/pact_sdk_example_{port}.db"
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(db + suffix)
        except FileNotFoundError:
            pass
    env = dict(os.environ)
    for var in ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "LLM_API_KEY"):
        env.pop(var, None)
    env["PACT_DB_PATH"] = db
    env["NO_PROXY"] = "localhost,127.0.0.1"
    env["no_proxy"] = "localhost,127.0.0.1"
    proc = subprocess.Popen(
        [str(PROJ / ".venv" / "bin" / "python"), "-m", "uvicorn",
         "pact.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(PROJ), env=env, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, start_new_session=True)
    for _ in range(40):
        try:
            r = requests.get(f"http://127.0.0.1:{port}/api/health",
                             timeout=2)
            if r.status_code == 200:
                return proc
        except requests.RequestException:
            pass
        time.sleep(0.5)
    proc.kill()
    raise RuntimeError("demo server did not come up")


def main():
    extract_sdk()
    from pact.configuration import Configuration, Environment, Server
    from pact.models.create_deal_request import CreateDealRequest
    from pact.models.deliver_request import DeliverRequest
    from pact.pact_client import PactClient

    base_url = os.environ.get("PACT_BASE_URL")
    server_proc = None
    if base_url:
        host = base_url.replace("https://", "").replace("http://", "")
        scheme = "https" if base_url.startswith("https://") else "http"
    else:
        host = f"127.0.0.1:{DEFAULT_PORT}"
        scheme = "http"
        server_proc = boot_demo_server(DEFAULT_PORT)
        print(f"Demo server up on {host} (throwaway DB, simulator money).")

    if scheme == "http":
        Configuration.environments = {
            Environment.PRODUCTION: {
                Server.DEFAULT: "http://{defaultHost}",
            },
        }

    def step(name, resp):
        if not resp.is_success():
            print(f"FAILED at {name}: status {resp.status_code}, "
                  f"errors {resp.errors}")
            raise SystemExit(1)
        print(f"{name}: ok (HTTP {resp.status_code})")
        return resp.body

    try:
        buyer_session = requests.Session()
        seller_session = requests.Session()
        buyer = PactClient(http_client_instance=buyer_session,
                           default_host=host).client
        seller = PactClient(http_client_instance=seller_session,
                            default_host=host).client

        health = step("health", buyer.health_api_health_get())
        if health.get("mode") != "demo":
            print("This example needs a demo-mode server; the server at "
                  f"{host} reports mode {health.get('mode')!r}. A sandbox "
                  "server stops at the human approval step by design.")
            raise SystemExit(1)

        created = step("create deal", buyer.create_deal_api_deals_post(
            CreateDealRequest(scenario_id="logo_brand_kit",
                              multi_issue=True)))
        deal_id = created["id"]
        buyer_session.headers["X-Deal-Token"] = created["buyer_token"]
        seller_session.headers["X-Deal-Token"] = created["seller_token"]
        print(f"Deal {deal_id} created; buyer and seller role tokens set.")

        negotiated = step(
            "negotiate", buyer.negotiate_api_deals_deal_id_negotiate_run_post(
                deal_id))
        spec = negotiated["spec"]
        print(f"Agreed: ${spec['price']} with terms "
              f"{spec['terms']['delivery_days']} days, "
              f"{spec['terms']['revision_rounds']} revision rounds, "
              f"{spec['terms']['bond_percent']}% bond.")

        step("pay", buyer.pay_api_deals_deal_id_pay_post(deal_id))
        step("deliver", seller.deliver_api_deals_deal_id_deliver_post(
            deal_id, DeliverRequest(quality="auto")))
        step("verify", buyer.verify_api_deals_deal_id_verify_post(deal_id))
        final = step("get deal",
                     buyer.get_deal_api_deals_deal_id_get(deal_id))
        if final["state"] != "released":
            print(f"FAILED: deal ended in {final['state']!r}, not "
                  "'released'.")
            raise SystemExit(1)
        print(f"Deal settled: {final['state']}, "
              f"contract hash {final['contract_hash'][:16]}..., "
              f"price ${final['spec']['price']:.2f}, "
              f"bond ${final['spec']['bond_amount']:.2f}.")

        packet = buyer.dispute_packet_api_deals_deal_id_dispute_packet_get(
            deal_id)
        if not packet.is_success():
            print(f"FAILED at dispute packet: status {packet.status_code}.")
            raise SystemExit(1)
        print(f"Dispute packet downloaded: {len(packet.body)} bytes of "
              "Markdown evidence.")
        print("Done. The SDK drove a full deal to released.")
    finally:
        if server_proc is not None:
            server_proc.kill()
            print("Demo server stopped.")


if __name__ == "__main__":
    main()
