# Pact

Agent to agent commerce with verified settlement.

Two software agents agree a deal for a digital service, write the contract
checks themselves, put real money behind the deal through PayPal, and let a
third agent judge the delivered work against the contract before anyone gets
paid. If the work fails, the buyer is refunded and the seller loses a
performance bond on top.

Built for the PayPal AI Hackathon on Devpost. Submission deadline November
12, 2026 at 12:00 PM PT.

## For the hiring reader

A note for the PayPal engineer or hiring manager reading this. Three design
decisions carry the project, and every one is backed by a test or a live
sandbox run you can check.

First, the money moves on the deterministic verifier's verdict, never on a
model's word. The optional language model layer only rewrites the wording
of negotiation rationales and verdict reasons. Prices, check values,
verdicts, and every money movement come from the deterministic engine. The
accuracy battery judged 275 checks across 55 deliveries with zero errors.

Second, cheating costs money, not just a refund. The seller posts a
performance bond of 20 percent of the price. On a failed deal the buyer is
refunded in full and the bond is paid to the buyer. The sandbox run on
October 22, 2026 shows it: a cheat deal at $180.96 was caught in both
rounds, the buyer was refunded, and the seller's $36.19 bond was slashed.
The cheat seller's reputation fell from 64 to 29 on that one deal.

Third, the contract travels with the money. When the agents freeze the
spec, the app computes its SHA-256 and writes the deal id plus that hash
onto both PayPal orders, in the purchase unit custom_id on the REST path
and in the line item name on the Agent Toolkit path. The verification
summary records the same hash. A judge can compare the hash on PayPal's
own order record against the hash of the frozen spec. Change any single
check value and the hash changes. Twenty hardening checks cover this.

The production path, in five lines: Pact registers as a Commerce Platform
partner with a BN code and multiparty scopes. Sellers onboard through
Partner Referrals before any deal. The price order is created with the
seller as payee and payment_instruction.disbursement_mode set to DELAYED.
On a pass the price is released with a referenced-payouts call against the
capture, so the price leg never touches the Payouts API. The bond runs as
intent AUTHORIZE: voided on a pass, captured and paid to the buyer on a
fail. The 28 day auto-disbursement clock means verification and the one
revision round have to finish inside that window.

What comes next, with a team: real seller onboarding and identity, the
largest single change from this build. A dispute flow that fits the 28 day
window and produces the dispute packet automatically. Mandates for repeat
buyers, so a pre-approved bounded budget replaces per deal approval.
Richer checks, starting with schema checks on structured artifacts and
test based checks on code. And PactBench, the scale program: a 314 delivery
verifier battery, 10,000 simulated settlement deals against two money
invariants, and a chaos suite over every settlement leg.

Read the cheat scenario run first. It is the fastest way to see the whole
system work. In demo mode it runs end to end with no credentials.

## My part

I am Ashish, the person behind this entry. I chose the problem and I
directed the build. An AI assistant wrote most of the code with me; the
decisions, the experiments, and the results are mine. I read every test
output, and the places where the tools were wrong are recorded in the test
suite rather than hidden.

The calls that are mine: the pitch line, that a cheating seller must lose
money and not just a refund. The 20 percent bond slash on a failed deal.
The cheat scenario as the flagship case, because a trust system is only
worth showing if it survives an adversary. Keeping PayPal's human approval
step instead of working around it, because agents proposing and people
approving is PayPal's own model for agentic payments. The scenario and
sponsor calls: the Channel3 procurement scenario grounded in live market
data, and the AG Grid table as the audit ledger. The bar I set from
October 22: production depth over feature count, worked on until
submission day, with a secret scan as the gate before the code goes
public. The security boundary is mine too: sandbox test accounts only,
never a real account or card.

## How a deal runs

1. A buyer agent and a seller agent negotiate the price. Each side concedes
   a share of the gap on its turn, every move carries a written rationale,
   and the round cap is real. If the seller floor sits above the buyer
   ceiling the deal walks away and no money moves.
   Optionally, the agents then trade terms. This is multi-issue mode,
   turned on per deal with `multi_issue: true` at creation. After the
   price is locked the sides negotiate three terms: the delivery window
   in days (buyer wants fewer, seller wants more), the revision rounds
   included (buyer wants more, seller wants fewer), and the bond percent
   (buyer wants higher, seller wants lower, inside the sane 10 to 30
   band). Each side carries simple utility weights over the terms. On
   each turn the side to move concedes on the issue where its concession
   buys the other side the most utility per unit of its own given up, so
   concessions trade across issues. In practice this produces real
   logrolling: across the whole sweep grid the buyer concedes the
   delivery window and the seller concedes revision rounds, while the
   bond settles near the middle at 23.54 percent. The agreed terms freeze
   into the contract and the spec hash covers them. The negotiated bond
   percent is what the payment code charges, and the negotiated revision
   rounds are what the verify endpoint allows. The delivery window is
   contractual only: the demo delivers instantly, so no clock enforces
   it. The terms phase runs after the price is locked, so it can never
   undo a price agreement.
2. The agents then write the contract. The acceptance checks are not a fixed
   template. The buyer proposes a value for each check, the seller accepts
   or counters, and numeric counters settle at the midpoint. The settled
   checks freeze into the deal spec.
3. The buyer pays the agreed price through a PayPal order. The seller
   posts a performance bond, a percent of the price, through a second
   order. PayPal asks the account holder to approve each order before it
   can be captured, so the buyer approves one link and the seller
   approves the other. After both approvals the app captures both
   payments and marks the price HELD in the ledger.
4. The seller agent produces the deliverable as a text artifact inside the
   app.
5. A verifier agent tests the delivery against every negotiated check and
   records a pass or fail per check with the measured value and a reason.
6. All checks pass: the price is paid out to the seller and the bond is
   returned to the seller.
7. Some checks pass and some fail: the seller gets exactly one revision
   round. A delivery that passes nothing skips revision and settles at once.
8. A final fail: the buyer is refunded in full and the bond is slashed,
   paid out to the buyer.
9. Every event lands in an audit ledger shown in the UI in an AG Grid
   table: each negotiation move, the frozen contract, each order, capture,
   delivery, verification check, payout, refund, bond move, and reputation
   change.

Reputation sits next to each agent in the UI. A completed deal raises it.
A revision costs 3 points. A refund costs 12. A slashed bond costs 20 more.

## Scenarios

- Logo and brand kit. An honest studio seller builds to the settled spec.
- Landing page copy. A second honest seller and a different check set.
- Scoped coding task. A CSV cleaner script with a named function, a
  validation section, worked examples, and a README section as checks.
- Market research brief. Named sources and data points are checks, so a
  brief full of general claims with no sources fails on its own terms.
- Cheat attempt. The seller delivers recycled generic copy that ignores the
  agreed checks. The verifier catches it check by check, the seller burns
  its one revision with nearly the same copy, the buyer is refunded, the
  bond is slashed, and the seller reputation takes the full hit. This
  scenario runs end to end in demo mode.
- Procurement. A buyer agent hires a seller agent to buy one real
  retail product, a Sony WH-1000XM5 headphones unit, at a real
  retailer. Market data comes from Channel3 and grounds the whole
  deal, as the next section explains.
- Data labeling batch. Labeled product titles with a labeling guide, a
  distribution summary, and flagged ambiguous rows.
- Podcast episode edit package. Chapters, timestamps, a cleaned
  transcript, and show notes for one episode.
- Email newsletter issue. Subject line, sections, calls to action, and
  an unsubscribe footer.
- Product photography set. A shot manifest with per photo specs, one
  hero shot, a usage license, and retouch notes.
- Book cover design package. Concepts, a spine design, back cover
  layout, a hex palette, and typography.
- API integration task. Wrapped endpoints with authentication, error
  handling, worked examples, and a README.
- Spreadsheet cleanup and report. Per column fixes, findings, a
  methodology section, and a duplicate count.
- AC repair service job. A written service report for a residential
  central AC capacitor replacement plus tune-up: diagnosis, the part
  replaced, system readings after the fix, and warranty terms.

Every scenario ships three delivery builders: an honest one that meets
the settled spec, a weak first draft that fails some checks, and a
cheat that ignores the contract. The deliver endpoint exposes the
weak and cheat builders through its quality parameter in demo mode,
so a judge can watch a thin draft go to revision and a cheat burn
its bond without touching the UI.

## Procurement grounded in live market data (Channel3)

The procurement scenario is the one deal in Pact where the product is
physical and the prices are not invented. When a procurement deal is
created, Pact calls the Channel3 API once and searches for the product
the buyer wants. Channel3 returns real products with real offers from
real retailers, each with a current price and a buy link.

Those offers set the deal. The buyer ceiling is the median offer
price. The seller floor is the lowest offer price. The lowest offer
becomes the chosen offer, and its product title, retailer, and buy
link are written into the candidate contract checks. One more check
caps the purchase: the price paid must come in at or under the agreed
contract price, and the delivery has to state the price it paid.

The delivery is a procurement report. It names the exact product, the
retailer, the buy link, and the price paid, plus an order reference.
The verifier checks the report against the frozen contract like any
other deal. A report that names the wrong product, the wrong retailer,
or a price over the ceiling fails, and the usual rules follow: one
revision round, then a refund and a slashed bond.

One honest note on data. Live mode needs a Channel3 API key in the
environment variable `CHANNEL3_API_KEY`, and the grounding ledger
event says the data came from a live search and when. With no key
configured, Pact grounds the deal in a Channel3 response captured
from the live API on October 22, 2026 and shipped in the repo at
`pact/fixtures/channel3_procurement_search.json`. The ledger event
labels that data as cached and gives the capture date. Cached data is
never presented as live.

## Testing (for hackathon judges)

Try the hosted demo first: https://pact-agentic-commerce.onrender.com.
It runs in PayPal sandbox mode with test money only. One step needs you:
PayPal requires the account holder to approve each order before it can
be captured, so a deal parks at an approval panel on purpose. Use these
PayPal generated sandbox test accounts:

- Buyer account: `sb-v47e3z53491657@personal.example.com` / `RB%_"1jJ`
- Seller account: `sb-krgz753508017@personal.example.com` / `SU_6sPa,`

Click path:

1. In the setup card, pick a scenario and create the deal, then run the
   negotiation.
2. Press Pay. The deal parks in awaiting approval with two PayPal links.
3. Open the payment link, sign in with the buyer account, and approve.
   Open the bond link, sign in with the seller account, and approve.
   Keep each account's pre selected funding source as it is.
4. Back in Pact, press the capture button. Then run delivery and
   verification, and watch the settlement and the audit ledger.

The cheat attempt scenario shows the full fail path: refund, slashed
bond, and the reputation hit. If you run the app locally with no
credentials in `.env`, the same flow runs in a clearly labeled demo mode
with a local payment simulator instead.

The guided tour: in demo mode, press Play the tour in the demo UI. It
runs one real logo and brand kit deal end to end, a $222.17 price with a
$44.43 bond and 5 checks, and narrates each step while the ledger fills
in. Pause, resume, and replay controls sit under the caption. The tour
runs in demo mode only. On the hosted sandbox demo it stays off, since
the approval step needs a person. The narration script lives at
`research/demo-tour-script.md`.

## Evidence (PactBench)

Every number below was generated by a run, not typed by hand. The frozen studies (E1, E2, E3, E4) never change retroactively. New suites extend the evidence, they do not rewrite it.

| Suite | Size | Result | Source |
|---|---|---|---|
| E1 verifier accuracy (frozen) | 55 deliveries, 275 checks judged | check accuracy 100.0%, delivery accuracy 100.0%, traps 4/4 | `experiments/results.json` |
| PactBench verifier battery (extended) | 314 deliveries across all 14 scenarios, 1570 checks judged, seed 20261023 | check accuracy 99.5% (TP 65 TN 139 FP 1 FN 0); delivery accuracy 90.6% (TP 13 TN 265 FP 29 FN 0) | `experiments/verifier_battery_results.json` |
| E2 negotiation sweep (frozen) | 196 runs on the buyer ceiling by seller floor grid | in-zone agreement 100.0%, walk away correct 100.0%, mean price position 0.3776 | `experiments/results.json` |
| Multi-issue negotiation sweep | 196 runs, seed fixed in the sweep script | agreement in zone 100.0%, match vs single-issue twins 100.0%, walk away correct 100.0%, bond consistent 100.0%, cap hits 0.0%, mean 25.0 terms moves, settled terms 12 days / 3 rounds / 23.54% bond | `experiments/results_multi_issue.json` |
| E3 settlement oracle (frozen) | 10 end-to-end deal paths | 10/10 match the rules oracle, 331 ledger events total | `experiments/results.json` |
| Monte Carlo settlement integrity | 10,000 simulated deals, seed 20261023, randomized prices, bond percents, delivery qualities, injected leg failures | verdict-state violations 0, money conservation violations 0, terminal states released 4,591 / refunded 5,237 / failed 172 | `experiments/monte_carlo_settlement_results.json` |
| Property tests (randomized API) | 342 randomized cases, 4935 checks, seed 20261023 | end-to-end deals across scenarios and qualities, illegal transitions rejected, malformed bodies fuzzed, state machine invariants hold | `tests/pactbench_property_test.py` |
| Chaos suite | 8 cases, 107 checks | every settlement leg killed and resumed to the right terminal state, duplicate webhooks idempotent, out-of-order webhooks handled, replayed pay/pay-confirm on terminal deals rejected with 409 | `tests/pactbench_chaos_test.py` |
| Load check | 50 parallel deals settled in demo mode, concurrency 10, seed 20261023 | end-to-end p50 2915 ms / p95 6273 ms / p99 6335 ms, total wall time 6.5 s, 46 released / 4 refunded, zero failures | `experiments/pactbench_load_results.json` |
| E4 live sandbox deals (frozen) | 4 deals settled on PayPal sandbox, api-m.sandbox.paypal.com on 2026-10-22 | price payouts, bond returns, refund plus bond slash all executed with real sandbox transaction ids, recorded in the paper table | `experiments/results.json` |

## Proven on the live sandbox

The full loop has run against the real PayPal sandbox, not only the demo
simulator. Four deals settled end to end on October 22, 2026: toolkit
order creation, account holder approval, capture, and then payout, refund,
and bond moves, all with real PayPal sandbox transaction IDs.

| Deal | Scenario | Price | Bond | Outcome | Key PayPal IDs |
| --- | --- | --- | --- | --- | --- |
| deal-0001 | Logo and brand kit | $222.17 | $44.43 | Released, 5 of 5 checks | Captures 2XX57477S7535341X and 76U34250RE4380745, payouts DZNF5GE6AEUHN and Y4BT2Q3N8QR7J |
| deal-0002 | Landing page copy | $324.21 | $64.84 | Released, 5 of 5 checks | Captures 5V6374204C639882V and 0FJ792206C854335V, payouts A2EXK2WL4D4BG and L35MAUZEMNY92 |
| deal-0003 | Logo kit, poor delivery | $222.17 | $44.43 | Refunded, bond slashed, 0 of 5 checks | Refund 02S348440D980433R, slash payout PWMV585KHNEM6 |
| deal-0004 | Cheat attempt | $180.96 | $36.19 | Caught twice, refunded, bond slashed | Refund 9VH98649B6022315A, slash payout X3BT5KNKEF8CL |

## Use cases

Pact is built for any market where a buyer pays a stranger for digital
work and has no practical way to check the work before the money moves.

- **Freelance marketplaces.** A buyer hiring a logo, copy, code, or
  research today pays into a platform escrow and argues with a human
  support queue when the work is thin. In Pact the checks are written
  into the deal before payment, the verdict is computed, and a seller
  who delivers recycled work loses the bond on top of the refund.
- **Agents buying from agents.** An agent procuring data, content, or a
  sub task from another agent cannot sit on a support call. It needs a
  contract it can verify in code and a settlement rule that runs without
  a human. That is exactly the loop here.
- **Small businesses buying digital services.** A shop owner buying a
  website or a social pack usually pays half up front and hopes. A bond
  backed contract gives the owner the same protection a large company
  gets from a procurement department, at no extra headcount.
- **Platforms that want fewer disputes.** Every Pact verdict comes with
  measured values against checks both sides agreed to, in a full audit
  ledger. A dispute starts from evidence instead of opinions.

## Why this is good business for PayPal

One Pact deal puts up to four paid money movements on PayPal rails
instead of one: the payment capture, the bond capture, and then two
payouts (or a refund and one payout). At PayPal's published US rates
(3.49 percent plus $0.49 to receive a commercial transaction, $0.25 per
Payouts API payout, refund fees not returned), a completed $250 deal
with a $50 bond earns PayPal about $11.95 in gross fees. A refunded
deal earns about $11.70, because the two capture fees are collected up
front and never returned. Failure costs PayPal almost nothing.

That is an effective take of about 4.0 percent on the $300 captured per
deal, using one definition everywhere: total gross fees per deal over
captured volume. The same definition is used in
`research/paypal-business-case.md`. Against a blended PayPal take rate
of roughly 1.6 percent, at a million deals a month, on stated
assumptions (rack rates, US parties, an 85/15 pass to refund mix), the
demo plumbing gives roughly $143 million a year in gross fees on $3.6
billion of new volume. On the Commerce Platform production path, where
the two $0.25 payout fees disappear and the bond authorization is voided
on a pass, the same volume earns about $115 million a year. In the demo
the platform absorbs both capture fees; production puts the fee on the
seller's receipt and gives the platform its own line, the platform fee
in the disbursement instruction. The fuller version of this analysis,
with sources, lives in `research/paypal-business-case.md`, section 6
for the production model.

The strategic point matters more than the fee point. The crypto agent
payment rails settle instantly and finally, which means no refunds, no
recourse, and no answer when an agent delivers junk. PayPal's own CEO
has said trust is the position PayPal needs to hold in an agentic
world. Verified settlement with a seller bond is that position, built
as a product.

## PayPal: what runs where, and why

Pact uses PayPal's own platform tooling first and hand written REST only
where PayPal ships nothing for the job.

**Agent Toolkit (primary rail for orders).** Orders run through PayPal's
official Agent Toolkit, PyPI package `paypal-agent-toolkit`. Pact calls
its dispatch core, `PayPalAPI.run`, from `pact/paypal_agents.py`.
Creating an order runs the toolkit tool `create_order`, capturing runs
`pay_order`, and reads run `get_order_details`. The toolkit builds the
payloads and checks the parameters against its own schemas. If the
toolkit cannot be imported in some environment, order actions fall back
to the direct REST client, and the ledger records which rail actually
ran.

**MCP server.** PayPal also publishes an MCP server, `@paypal/mcp`, for
agents that live inside an MCP host. Pact's backend is one Python service
and does not embed an MCP host, so the MCP server is not part of the
runtime path. A ready to paste host configuration lives at
`mcp/paypal-mcp-config.example.json` for anyone who wants to drive the
same PayPal tools from an MCP host instead.

**Direct REST (payouts, refunds, fallback).** The toolkit tool list has no
payout tool and no capture refund tool. Its only refund tool records a
refund against an invoice, which is not this flow. So settlement payouts
and the buyer refund run through a small direct REST client in
`pact/payments.py`: OAuth token, Orders create and capture, Payouts
create, and capture refund, all against the base URL from the environment.

**The hold.** The HELD state in the app ledger maps to PayPal delayed
disbursement, the native hold primitive on the PayPal platform, where a
capture is disbursed to the seller only when the platform is told to
release it. This build models the hold in the app ledger and moves the
money with a real sandbox capture, then releases with a real payout. On a
full PayPal Commerce Platform integration the same step would capture with
delayed disbursement and disburse on verification pass.

**One honest limit on custody.** In this build both orders are created
with the platform's own credentials and no payee. Both captures land in
the platform's own account, and Pact pays the seller out at full price
from it. That means the platform is holding both sides' money and
absorbing both capture fees on every deal. It is not a custody model a
real platform can run on. The production path below exists to replace
it, not to describe it.

**One honest note on approval.** PayPal never lets code capture a wallet
payment on its own. The account holder has to approve the order first,
and Pact keeps that checkpoint instead of working around it. The agents
negotiate the deal and prepare both PayPal orders, the price and the
bond. The app then shows one approval link per order. The buyer approves
the price, the seller approves the bond, each in PayPal's own sandbox
checkout, and only then does Pact capture. Settlement after that point
(release payout, bond return payout, refund, and the slashed bond
payout) is fully programmatic, because PayPal designed payouts and
refunds to run server side. Agents propose and prepare; people approve
money movement. That is PayPal's own model for agentic commerce, and
the audit ledger records both approvals as events.

## The production path: PayPal Commerce Platform

The demo plumbing works and is honest about what it is. The production
design fixes its two problems: custody, and who eats the fees. It runs
on PayPal Commerce Platform with delayed disbursement, and the full
writeup lives in `research/paypal-business-case.md` section 6.

Pact registers as a Commerce Platform partner: a partner business
account, a BN code sent as the PayPal-Partner-Attribution-Id header, and
multiparty scopes arranged with the PayPal account team. Every seller
onboards through Partner Referrals before any deal, and Pact stores the
seller's payer_id. The PARTNER_FEE feature has to be enabled at
onboarding, or the platform_fees array is rejected.

The price order is created as the seller's transaction: partner
credentials, a PayPal-Auth-Assertion naming the seller,
purchase_units[0].payee set to the seller, and
payment_instruction.disbursement_mode set to DELAYED at creation. The
platform's own cut goes in the same instruction as platform_fees. The
deal id goes in reference_id and custom_id. The buyer approval step
stays exactly where it is.

Capture happens after approval. PayPal holds the funds. Auto
disbursement fires after 28 days, which is a hard limit: verification,
revision, and any dispute must finish within 28 days of capture. The
single revision round fits easily, but a long human dispute has a real
clock.

On a pass, Pact releases the price with
POST /v1/payments/referenced-payouts-items, reference_id set to the
capture id and reference_type set to TRANSACTION_ID. PayPal deducts its
fee and the platform fee at disbursement. The price leg never touches
the Payouts API, so the two $0.25 payout fees disappear. On a fail, Pact
refunds the price capture while the funds are still held.

The bond gets its own treatment, because the beneficiary on a slash is
the buyer, not the seller. The clean approach is intent AUTHORIZE on the
bond order. On a pass the app voids the authorization. No money moves,
and no capture fee is burned. On a fail the app captures the
authorization and pays the bond out to the buyer with Payouts.

On the same $250 price and $50 bond, production earns $9.22 on a
completed deal (price capture fee only, bond authorization voided) and
$11.70 on a refunded deal (price capture fee kept, bond captured and
slashed). That is an effective take of about 3.1 percent on a pass and
about 3.9 percent on a fail, using the same definition as the demo
numbers: total gross fees over captured volume. The platform finally
has its own revenue line, the platform fee in the disbursement
instruction, which the demo plumbing does not have. The largest single
change is seller identity: today there is no seller identity beyond two
hardcoded sandbox emails, and everything in this section depends on
that existing first.

**The contract travels with the money.** When the agents freeze the
spec, Pact computes its SHA-256 and writes the deal id plus that hash
onto both PayPal orders. The REST path puts it in the purchase unit
custom_id. The Agent Toolkit path puts it in the line item name,
because the toolkit's create_order exposes no custom_id. The ledger
records honestly which field carried the hash on each order. The
verification summary records the same hash. A judge can compare the
hash on PayPal's own order record against the hash of the frozen spec
and know the contract that judged the delivery is the contract the
money moved under. Change any single check value and the hash changes.
The deal view shows the hash for every deal.

## Demo mode honesty

With no PayPal credentials set, the app runs in DEMO MODE. A local payment
simulator mirrors the same states and IDs, every result is stamped demo,
and the UI badge, the API health response, and the ledger all say so. The
code path is genuinely different. Nothing in demo mode pretends a PayPal
call happened.

Each deal gets two random role tokens at creation, one for the buyer side
and one for the seller side. State-changing calls (negotiate, pay,
pay/confirm, deliver, verify) must carry the right token in the
X-Deal-Token header, and the demo UI sends them automatically. Deal ids
are random too, so guessing a neighbor's id gets a 404. This is demo-grade
role separation, not real user auth. There are no accounts, no passwords,
and no sessions. A production build would put real identity in front of
these endpoints.

## AI tools, stated plainly

Two separate things. At runtime, an optional language model layer (any
OpenAI compatible endpoint, gpt-4o-mini by default) can rewrite the
wording of negotiation rationales and verdict reasons so they read
naturally. It never decides anything: prices, check values, verdicts, and
every money movement come from the deterministic engine, and the app runs
fully offline with no key set. During development, I used an AI assistant
(Claude) for drafting support and help with parts of the code. The design,
the experiments, and the results are mine. I ran every test myself and
read the outputs, and the places where the tools were wrong are recorded
in the test suite rather than hidden.

## Setup

### 1. Create a PayPal sandbox app and accounts

Follow the official PayPal sandbox getting started flow.

1. Sign in to the PayPal Developer Dashboard at developer.paypal.com.
2. Create a sandbox app and select the REST API option. PayPal gives you a
   client ID and a secret for the app.
3. Under Sandbox Accounts, make sure you have two personal sandbox
   accounts. One plays the buyer and one plays the seller. Note the email
   address of each account.
4. Fund the buyer account in the sandbox if you plan to watch balances
   move. Sandbox money is test money.

### 2. Configure the environment

Copy `.env.example` to `.env` and fill in your values.

| Variable | Meaning |
| --- | --- |
| PAYPAL_CLIENT_ID | Client ID of your sandbox app |
| PAYPAL_CLIENT_SECRET | Secret of your sandbox app |
| PAYPAL_BASE_URL | API base. Default https://api-m.sandbox.paypal.com |
| PAYPAL_WEBHOOK_ID | Optional. The ID of a webhook registered for this app. When set, webhook signatures are verified with PayPal |
| SELLER_SANDBOX_EMAIL | Seller sandbox account email. Receives the payment payout and the bond return |
| BUYER_SANDBOX_EMAIL | Buyer sandbox account email. Receives the bond payout when a bond is slashed |
| LLM_API_KEY | Optional. Any OpenAI compatible chat endpoint key |
| LLM_BASE_URL | Optional. Default https://api.openai.com/v1 |
| LLM_MODEL | Optional. Default gpt-4o-mini |
| BOND_PERCENT | Bond size as a percent of the price. Default 20 |
| PACT_MAX_DEALS_PER_MINUTE_PER_IP | Deals created per minute from one client address. Default 30 |
| PACT_MAX_DEALS_PER_MINUTE_GLOBAL | Deals created per minute across all clients. Default 120 |
| PACT_RATE_WINDOW_SECONDS | Length of the rate window in seconds. Default 60 |
| PACT_MAX_REQUEST_BYTES | Request body size cap in bytes on the negotiation and delivery endpoints. Default 65536 |
| TURSO_DATABASE_URL | Optional. A Turso cloud database URL (libsql://...). When set with TURSO_AUTH_TOKEN, deals persist in Turso instead of the local SQLite file |
| TURSO_AUTH_TOKEN | Optional. Auth token for the Turso database above |

Leave the PayPal values empty to run in demo mode. Set any abuse
limit variable to 0 to turn that cap off. With Turso set, deals live in
Turso and survive the host restarting. The hosted demo has Turso set:
a deal created on one instance was still there, unchanged, after the
instance spun down and a new one woke up, so a deal is not lost when
the host restarts. Without Turso set, deals live in a local SQLite
file and a host restart wipes them.

### 3. Run the app

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn pact.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000 and run a deal from the setup card.

The language model layer is optional. With a key set, the model rewrites
negotiation rationales and reason text in a natural voice. Outcomes are
never decided by the model. Negotiation math and verification verdicts come
from the deterministic engine, so the app works fully offline with no key.

## Tests and experiments

```bash
.venv/bin/python tests/smoke_test.py
.venv/bin/python tests/accuracy_test.py
.venv/bin/python tests/webhook_test.py
.venv/bin/python experiments/run_experiments.py
.venv/bin/python experiments/adversarial.py
```

The smoke test boots the app in demo mode and runs the happy path, the
total fail path, and the cheat scenario end to end, asserting final states,
bond outcomes, negotiated check values, and reputation changes. The
accuracy battery holds the verifier and the negotiation math against
hand labeled cases, generated cases whose counts are true by
construction, and integration paths. `tests/money_test.py` pins the
money layer: every amount inside Pact is an integer number of cents,
parsed once at the boundary with round half even, and all money math
is exact integer arithmetic. No float ever holds money, so no float
can drift a settlement by a cent. The experiments folder holds the
measured studies behind the claims: verifier accuracy on constructed
deliveries, a 196 run negotiation sweep, a 196 run multi-issue sweep
that trades delivery window, revision rounds, and bond percent on
best-trade-ratio moves, settlement outcomes against a
rules oracle, an adversarial battery that attacks the system from
both sides, and a measurement study of text degeneracy. Three families
of attack found real holes during development, a hashtag counting
flaw, an item counting flaw, and a length padding flaw, and all three
were fixed and are covered by tests. The results live in `experiments/results.json`,
`experiments/results_multi_issue.json`, and
`experiments/adversarial_results.json`.

## Webhooks

`POST /webhooks/paypal` accepts PayPal webhook events and records them
on the matching deal ledger. When `PAYPAL_WEBHOOK_ID` is set and the app
runs with live sandbox credentials, each event's signature is verified
with PayPal before the event is accepted, and a failed verification is
rejected with a 400 and logged as a rejection. Without a webhook ID the
event is recorded and labeled unverified. A verified event can advance
reconciliation: a payout event triggers the same payout status read-back
the settlement flow uses (the read-back asks PayPal, so the event's own
content is never trusted for a money decision), and each outcome is
recorded as a ledger event naming the webhook event id. Settlement is
never authorized from a webhook: the deal leaves "verifying" only
through the verify endpoint, so a forged webhook cannot move money.

## Abuse limits

Deal creation is rate limited: 30 deals per minute per client address
and 120 per minute across all clients, by default. Over the cap the
API answers 429 with a Retry-After header and the standard clean
error shape. The negotiation and delivery endpoints reject request
bodies over 64KB with a 413. All four caps come from env vars
(PACT_MAX_DEALS_PER_MINUTE_PER_IP, PACT_MAX_DEALS_PER_MINUTE_GLOBAL,
PACT_RATE_WINDOW_SECONDS, PACT_MAX_REQUEST_BYTES), and a value of 0
turns a cap off. The counters live in memory, so a restart resets
them. This is demo-grade protection against accidental floods, not a
distributed rate limiter.

## Agent SDK (APIMatic)

Pact's API is built for other agents to call, so it ships a generated
Python SDK. APIMatic generated it from the OpenAPI spec the app serves
at /openapi.json. The SDK lives in sdk/pact-python-sdk.zip (61 files).
sdk/agent_example.py drives a full deal through it: create, negotiate,
pay, deliver, verify, then download the dispute packet. Run it with
sdk/.venv/bin/python sdk/agent_example.py. It boots its own demo-mode
server on 127.0.0.1:8123 with a throwaway database, so no PayPal
account is touched. The example run settles a logo brand kit deal to
released and downloads a 34,804 byte dispute packet.

Two honest limits. The generated client assumes https, so the example
patches the base URI to http for the local run; against the hosted
demo no patch is needed. The spec does not declare the per-deal role
token header, so the generated methods take no token argument; the
example carries the tokens on one requests session per role, buyer and
seller. The hosted APIMatic developer portal is not published yet. The
SDK here is the generated artifact. The portal needs a Docs-as-Code
build that runs on a developer machine.

## Layout

- `pact/main.py` FastAPI app and the deal flow endpoints
- `pact/negotiation.py` Price negotiation and agent written contract checks
- `pact/verifier.py` Rule based checks against the settled contract
- `pact/paypal_agents.py` Agent Toolkit rail, the primary PayPal path
- `pact/payments.py` Direct REST client and the demo simulator
- `pact/scenarios.py` Scenarios, candidate checks, deliverable builders
- `pact/store.py` Deals, ledger, agent reputation
- `pact/static/` The single page UI with the AG Grid audit ledger
- `mcp/` Example configuration for the official PayPal MCP server
- `sdk/pact-openapi.json` Exported OpenAPI spec for the app
- `sdk/pact-python-sdk.zip` APIMatic generated Python SDK (61 files)
- `sdk/agent_example.py` An agent drives a full deal through the SDK
- `tests/` Smoke test, accuracy battery, webhook tests
- `experiments/` Measured studies: accuracy, negotiation sweep, settlement oracle, adversarial battery

## License

MIT. Copyright Ashish Rathnakar Shetty.
