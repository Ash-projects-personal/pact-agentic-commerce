# Pact Build Report

Status: core build complete and verified locally in demo mode.
Date: October 22, 2026.

## What was built

A single FastAPI service in `pact/` with a static single page UI. A deal
runs negotiation, an agent written contract, payment with a performance
bond, delivery, rule based verification, and settlement, with every step in
an audit ledger rendered in AG Grid.

Feature checklist against the spec:

- Two agent negotiation with real offer and counteroffer logic, a
  concession strategy at 45 percent of the remaining gap per turn, a cap of
  26 price moves, a walk away outcome when the seller floor sits above the
  buyer ceiling, and a written rationale on every move.
- Agent written contract. Candidate checks are proposed by the buyer agent
  during negotiation, the seller accepts or counters, numeric counters
  settle at the midpoint, and the frozen spec carries the settled values.
  The verifier judges against exactly those settled checks.
- Payment through PayPal with the funds modeled as HELD in the app ledger.
- Performance bond with slashing. The seller posts a bond at 20 percent of
  the price through a second order and capture. Pass returns the bond with
  the payment. Final fail refunds the buyer and pays the bond to the buyer
  as a slash. Bond state shows in the payment timeline and the ledger.
- Seller delivery as stored text artifacts shown in the UI.
- Verifier agent with per check pass or fail, the measured value, the
  required value, and a plain reason. Partial pass grants one revision
  round. Total fail goes straight to refund.
- Reputation ledger. Buyer and seller personas carry reputation scores.
  Completed deal: seller +6, buyer +3. Revision round: seller 3 off.
  Refund: seller 12 off. Bond slash: seller 20 more off. Every change is a
  ledger event with its reason, and scores show next to each agent in the
  UI.
- Cheat scenario. A third scenario where the seller delivers recycled
  generic copy. The verifier catches it check by check in both rounds, the
  buyer is refunded, the bond is slashed, and the ledger shows the catch.
- Webhook stub at `POST /webhooks/paypal` that logs events to the matching
  deal ledger. Signature verification is a noted TODO.
- Deal state machine: negotiating, agreed, paid_held, delivered,
  verifying, revision, released, refunded, failed.

## How the PayPal split works

- Orders create and capture run through the official PayPal Agent Toolkit
  (PyPI `paypal-agent-toolkit` version 1.11.0). Pact calls the toolkit
  dispatch core `PayPalAPI.run` with the toolkit tool names `create_order`
  and `pay_order` from `pact/paypal_agents.py`. The framework wrappers for
  the OpenAI Agents SDK, LangChain, and CrewAI all sit on this same core.
- Payouts and capture refunds run through the direct REST client in
  `pact/payments.py`, because the toolkit tool list ships no payout tool
  and no capture refund tool. That is stated in the README, not hidden.
- If the toolkit package cannot be imported, orders fall back to REST.
  Every payment result carries a rail field and the ledger prints it.
- The PayPal MCP server is not embedded. It targets agents living inside
  an MCP host, and this backend is a single Python service. An example
  host config ships at `mcp/paypal-mcp-config.example.json`.
- The HELD state maps to PayPal delayed disbursement, the platform hold
  primitive. This build models the hold in the app ledger while the money
  movement is a real sandbox capture plus payout, as the README explains.

## Verification done in this environment

Smoke test, run with `.venv/bin/python tests/smoke_test.py`:

```text
Health: mode demo, toolkit installed True
TEST 1 happy path: brand kit deal settles as released
  price 222.17 USD, bond 44.43 USD, checks passed 5/5, ledger events 34
  PASS
TEST 2 fail path: empty delivery is refunded and the bond is slashed
  checks passed 0/5, seller reputation 88 -> 56
  PASS
TEST 3 cheat scenario: recycled copy caught, revised, caught again
  round 1 catch: 4 of 5 checks failed on recycled copy
  round 2 catch: revision failed again, refunded, bond slashed
  seller reputation 64 -> 29
  PASS
ALL SMOKE TESTS PASSED
```

Server boot check: `uvicorn pact.main:app` served `/api/health` with mode
demo, the index page returned HTTP 200, the static JS returned HTTP 200,
and the AG Grid CDN script answered HTTP 200 from this environment. The UI
also has a plain table fallback if the CDN is ever unreachable.

## Toolkit environment findings, stated plainly

- The toolkit package installs and its framework independent core imports
  and constructs cleanly here. `PayPalAPI.run` dispatch was exercised
  locally and raises correctly on unknown tool names.
- A full dependency install of `paypal-agent-toolkit` did not finish in
  this environment. The package pins `openai-agents==0.0.2`,
  `langchain==0.3.23`, and `crewai-tools==0.13.2`, and the CrewAI chain
  pulls a very large tree (including chromadb) that kept the resolver busy
  past the install window. The package was installed with `--no-deps` and
  runs on the two light dependencies its core actually imports, `requests`
  and `pydantic`. The framework wrapper subpackages were not exercised
  because those framework packages are not installed here. Pact does not
  need them, since it calls the shared core the wrappers are built on.
- Toolkit order execution against the live sandbox could not be exercised
  here because this environment has no PayPal credentials, by design. No
  real credential was used, requested, or invented.

## What remains

1. Real sandbox credential test. Create the sandbox app and the buyer and
   seller sandbox accounts on the PayPal Developer Dashboard (a separate
   step for Ash), put the values in `.env`, and run one deal per scenario
   against the sandbox. Watch the orders rail report `agent_toolkit` in
   the ledger and the payouts and refunds report `rest`.
2. Render deploy using the included `render.yaml`, with the same env vars
   set in the Render dashboard.
3. Demo video under 3 minutes for the Devpost submission, showing the
   cheat scenario catch and the bond slash.
4. Webhook signature verification before any production use.
5. Buyer approval step between order create and capture for a production
   checkout flow.
6. Devpost submission text: project description and the tools used list.

## Files delivered

README.md, LICENSE (MIT, Ashish Rathnakar Shetty), requirements.txt,
render.yaml, .env.example, .gitignore, the `pact/` package, the `mcp/`
example config, and `tests/smoke_test.py`.

## Update 2026-11-11: graded settlement and delivery timeout

Settlement is no longer all or nothing. The verifier's per-check
results now split the money: if N of M acceptance checks pass, the
seller is paid N/M of the price, the buyer is refunded the rest, and
the bond slashes (M-N)/M to the buyer. All pass is the old release in
full; none pass is the old refund in full. The split is integer-cent
math with round-half-even once and the remainder to the other side, so
the four legs always sum exactly to price plus bond. Reputation on a
graded deal is one delta: the passed share of the 6 point release gain
minus the failed share of the 20 point slash hit, each rounded
half-even. New terminal state `graded`, new endpoint
behavior in `POST /api/deals/{id}/verify`, new module
`pact/settlement.py`, new tests in `tests/graded_settlement_test.py`
(12 tests, math plus end to end).

Delivery timeout is a branch of the refund, not its own outcome. The
clock starts at capture: 7 days on single-issue deals, the negotiated
window on multi-issue deals. Past the deadline the buyer may call
`POST /api/deals/{id}/timeout` for a full refund plus a full bond
slash, ending refunded with the settlement path "timeout". The
endpoint is valid only while no delivery has been submitted; a deal in
revision cannot time out. There is no demo bypass: the deadline has to
have passed.

What changed in the evidence: the cheat scenario now settles graded
1 of 5 (seller paid $36.19 of $180.96, buyer refunded $144.77,
$28.95 of the $36.19 bond slashed, reputation 64 to 46). The E3
settlement oracle stays at 10 paths: the cheat path expectation
changed to the graded outcome and it matches 10/10. The Monte Carlo
run was re-run under the new rules.
The October 22 sandbox deals in the E4 table are a frozen record of
settlements made under the old all-or-nothing rule and are unchanged.
