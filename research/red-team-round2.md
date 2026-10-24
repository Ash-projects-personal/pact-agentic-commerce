# Red team report, round 2: NEW attacks (2026-10-22)

Red team subagent a611533d, completed 2026-10-22 21:26 UTC. All attacks new (round 1 battery items not repeated). Live runs against a fresh demo instance on port 8011, stopped after testing.

## 1. WORST HOLE: caller picks delivery quality, buyer can force a fail and collect the bond. SUCCEEDS.
POST /deliver takes {"quality": "poor"} from whoever calls it; deliver() in pact/main.py passes req.quality straight into build_delivery in pact/scenarios.py, where "poor" forces the thin delivery on ANY scenario. No caller identity check anywhere. Live: logo_brand_kit (honest passes 5/5) forced poor -> refunded, bond slashed, seller_forma rep 82 -> 50 in one deal. Same deal with quality "auto" releases. In sandbox mode this is real money: real refund + real slash payout to buyer, triggered by buyer alone.

## 2. Bond rounds to zero: zero bond ban bypassed by arithmetic. SUCCEEDS, two vectors, live.
A: bond_percent 0.001 passes create_deal validation (>0); negotiation _money() rounds bond to 0.0 on price 222.17.
B: ordinary 20% deal with buyer_max 0.03, seller_floor 0.01 -> price 0.01, bond_amount 0.0.
create_deal validates percent range; nothing validates resulting bond amount or sets a minimum price.

## 3. Infinite money values accepted, permanently poison the deal record. PARTIAL (DoS on record, no fake money).
POST /api/deals with buyer_max 1e999: Python parses inf, Pydantic accepts float, inf <= 0 is False so validation passes, deal stored. Create returned 500 (Starlette cannot serialize inf) but deal-0004 was stored and now returns 500 on EVERY GET forever. NaN same path by code reading. No finiteness check, no upper bound in create_deal.

## 4. No authentication, no role separation anywhere. SUCCEEDS, root enabler of 1 and 5.
Every route open: create, negotiate, pay, confirm, deliver, verify, webhooks, agents. One caller plays buyer, seller, verifier trigger. Deal ids sequential from itertools counter in store.new_deal (enumerable; counter reached deal-0160 in testing). Any fix for attack 1 starts here: API must know which principal is calling.

## 5. Reputation farming. SUCCEEDS, live.
Repeat honest deals: rep is one global in memory number per persona in AGENTS (store.py), shared across deals, callers, modes. Three free demo deals took seller_copycraft 82 -> 100 (cap), zero cost, no identity check. Reverse works too: attack 1 drops a seller 32 points per forced deal. Demo rep indistinguishable from sandbox rep; nothing ties a persona to the PayPal account receiving payouts.

## 6. Forged webhooks write fake entries into a deal's audit ledger. PARTIAL (no money moves, forges evidence trail).
paypal_webhook matches by checking whether any known id appears anywhere in str(payload); first match wins. Live: payload with order id in an "unrelated_field" and event_type "PAYMENT.CAPTURE.COMPLETED <img src=x onerror=alert(1)>" returned 200, matched_deal deal-0008, stamped webhook_received entry with attacker text into that deal's ledger. Saving graces verified: deal state did not change (settlement never reads webhooks); without PAYPAL_WEBHOOK_ID the entry is honestly labeled not_configured. But default demo config has no signature check at all, and the ledger is the core evidence artifact. Unmatched payloads stored verbatim in GLOBAL_EVENTS, served at GET /api/webhooks.

## 7. Stored XSS via forged webhook text in fallback UI. PARTIAL (fallback only), payload planted live in attack 6.
Attacker event_type flows into ledger message. AG Grid path safe (textContent, grid cells as text). Fallback renderLedger in app.js builds rows by string concatenation into innerHTML using raw r.event_type and r.message: the img onerror string would execute in any browser on the plain table fallback.

## 8. Approval flow: nobody checks who approved which order; approval links are public. PARTIAL, code reading (sandbox only).
pay() stores both approval URLs on the deal; public_deal returns the entire deal dict incl. URLs to any reader; ledger events carry URLs too. Approval link is a bearer capability. pay_confirm captures both orders without asking PayPal for state or payer of either order; capture_order returns only capture id/status, payer identity discarded; ToolkitOrders.get_order_details exists but is never called. Nothing distinguishes buyer approved price order vs buyer approved both vs third party approved them. If buyer approves both links, confirm captures both; on a pass seller is paid price plus bond return for a bond the seller never posted. Only PayPal's own ORDER_NOT_APPROVED rejection stands in the way; Pact contributes no check.

## 9. Race conditions: state checks hold in demo, break where money is real. BLOCKED in demo live; SUCCEEDS by code reading in sandbox.
Demo live: 6 parallel negotiate -> one 200, five 409, moves written once; 6 parallel pay -> one 200, five 409, one payment_held event. Demo survives by accident: handlers never await between _require_state and state write (llm.polish instant without key, simulator never blocks). Sandbox: pay() passes state check while "agreed", then awaits order creation (asyncio.to_thread in ToolkitOrders.create_order, or httpx in PayPalClient); a second parallel pay passes the same check in that window and creates a second independent order pair; last response overwrites stored ids, other pair orphaned but live, its approval links already in ledger. Same shape for negotiate with LLM key (polish awaits per move) and captures in /pay/confirm. No per deal lock anywhere; the one lock in store.py guards only the id counter.

## 10. Settlement not atomic: failure on second money call bricks deal mid payment. SUCCEEDS as consistency break, code reading (demo simulator never fails).
verify() sets "verifying", _settle_release pays price first, bond return second. If bond payout raises: 502, price already landed, payment.status already released, state stuck at "verifying" which no endpoint accepts. Deal can never finish, retry, or refund via API. _settle_refund mirror: refund lands, slash fails, buyer whole but bond never slashed, deal stuck. pay() same pattern: price order created, bond create fails, price order orphaned, retry creates a second. (Same finding as PayPal platform expert gap 2, independent confirmation.)

## 11. Unbounded creation. SUCCEEDS, live.
150 back to back POST /api/deals -> 150x 200, no 429, no cap, no cost. DEALS, ledgers, GLOBAL_EVENTS in memory only grow, no eviction. With LLM key: run_negotiation makes one paid polish call per move, so mass create + negotiate is a direct quota burn. No account or money needed (see attack 4).

## 12. Deliver quality is an unvalidated free form string. SUCCEEDS, minor alone, live.
DeliverRequest.quality accepts any string; {"quality": "whatever-i-want"} accepted, silently treated as scenario default (cheat copy delivered, deal landed in revision). Only exact "poor" is special. The deliver contract is a demo knob with no validation; same surface attack 1 abuses.

## Smaller notes
- Negotiation rounding tilts to buyer: check values settle with int((demand + seller_offer) / 2 + 0.5) in run_negotiation; every exact half case rounds up toward buyer demand rather than splitting. Systematic bias in the "fair midpoint" claim.
- Sequential second negotiate/pay correctly refused 409; state machine sound when calls do not overlap and caller plays honestly. Problems are who may call, what caller may choose, and what happens when calls overlap or money calls fail halfway.

## Fix sketch (Max, for reconciliation pass)
- Deliver: validate quality as enum (auto/good/poor/cheat per scenario); in sandbox (live money) mode ignore caller quality and always use the scenario seller behavior; keep quality knob in demo mode only, labeled as a demo control. Long term: role tokens per agent.
- Bond floor: after negotiation computes bond, reject/fail if bond_amount < minimum (e.g. 0.50 or 1.00); also minimum deal price at create.
- create_deal: math.isfinite checks on all money inputs + sane upper bound.
- Fallback UI: escape HTML in renderLedger fallback (or build rows with textContent). Cheap, do it regardless.
- Webhooks: in demo mode label stays; do not write attacker event_type raw into message without sanitizing length/characters.
- Settlement: record legs individually, allow verify retry from "verifying" when settlement incomplete (with PayPal expert idempotency fixes).
- Races: per deal asyncio lock around state transitions in sandbox paths.
- Approval: call get_order_details at confirm; check payer email matches expected buyer for price order and seller for bond order before capturing each.
- Rate/size caps: cap total deals and ledger growth for the hosted demo; document as demo limits.
- Reputation: label demo vs sandbox earned reputation separately in UI, or reset rep on mode; document farming limit honestly in paper/README.
