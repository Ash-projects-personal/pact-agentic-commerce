# Pact: Prior Art and Novelty Scan

Researched October 22, 2026. Scope: agent to agent commerce platforms, AI agent escrow, verified agent settlement, agent bonds and staking, agent reputation systems, PayPal's own agentic commerce products, and Devpost projects including the PayPal AI Hackathon.

Bottom line up front: no single product or project found does the full Pact combination. But almost every individual piece of Pact already exists somewhere, most of it in the crypto agent economy. Two pieces look genuinely uncommon: acceptance checks that are negotiated by the two agents instead of written by the buyer, and a per deal seller bond that is slashed to the buyer when verification fails. The pitch must lean on the combination and those two pieces, and must never claim to be the first agent marketplace, the first agent escrow, or the first verified agent settlement. Those claims are taken.

## Method note

Web searches covered agent to agent commerce, AI agent escrow, verified delivery, agent staking and slashing, ERC-8004 and ERC-8183, PayPal Agent Toolkit and MCP, PayPal delayed disbursement, and the named startups in this space (OKX, Fetch.ai, Skyfire, Nevermined, Catena Labs orbit). Devpost was checked two ways. The PayPal AI Hackathon page itself shows no public project gallery at research time, which is normal for Devpost before the November 12, 2026 deadline. Only one publicized submission to this hackathon surfaced in search (PatronAI, covered below). Devpost at large was searched for agent escrow and agent payment projects.

## Standards and protocols: the sharpest collisions

### ERC-8183 "Agentic Commerce" (draft Ethereum standard, proposed February 25, 2026)
What it does: defines a three role job lifecycle. A client opens and funds a job in escrow, a provider delivers the work, and a single evaluator attests PASS or FAIL. States are Open, Funded, Submitted, Terminal, with events for payment released and refunded.
Overlap with Pact: this is Pact's settlement core, written as a standard. Funded escrow, delivery, one evaluator verdict, release or refund. If a judge knows this standard, Pact's money flow will look familiar on sight.
What it does not have: no negotiation of terms or acceptance checks, no seller bond, no revision round, payments in ERC-20 tokens only.
Source: https://www.onchainagentintel.io/blog/erc-8183-vs-erc-8004

### ERC-8004 "Trustless Agents" (draft Ethereum standard, August 2025, authors from MetaMask, Ethereum Foundation, Google, Coinbase)
What it does: three on chain registries. Identity Registry gives each agent a persistent ID. Reputation Registry holds structured feedback and scores. Validation Registry lets independent validators check agent work, including stake secured re-execution where a validator that validates wrongly can be slashed.
Overlap with Pact: agent identity, reputation scores fed by deal outcomes, independent verification, and the general idea that stake backs trustworthiness.
What it does not have: no escrow, no negotiation, no per deal seller bond that compensates a buyer. Its slashing targets validators, not sellers who fail a delivery.
Source: https://www.concordium.com/article/erc-8004-explained-what-it-solves-and-the-gap-it-leaves

### AP2, A2A, x402 (protocol layer, widely covered)
Google's A2A protocol covers agent to agent communication, AP2 adds signed mandates for authorized payments, and Coinbase's x402 covers instant stablecoin payment per request. PayPal is an AP2 partner. These are plumbing, not competitors, but they mean agent negotiation and agent payment messaging are standardized territory, not inventions.
Source: https://phemex.com/academy/what-is-agent-to-agent-commerce

## Products and platforms

### OKX.AI agent marketplace (OKX, live product)
What it does: a marketplace where AI agents discover each other, list services with pricing and performance history, hire each other, and settle in stablecoins. Complex multi step work uses escrow based contracts. Every completed transaction logs on chain and builds a portable reputation record.
Overlap with Pact: agent hiring agent, escrow for complex work, reputation from outcomes. This is the biggest commercial collision on the marketplace framing.
What it does not have: no negotiation over acceptance criteria, no independent verifier agent judging delivery against a spec, no seller bond or slashing, crypto rails only, no PayPal.
Source: https://blog.thirdweb.com/ai-agent-marketplace-okx-lets-agents-hire-and-pay-each-other/

### AgentPay (agentpay.studio, live product)
What it does: escrow payments for AI agents backed by Stripe Connect. Agent A deposits, Stripe holds, a component called Agent Monitor confirms delivery, funds release. Every agent has a trust score it cannot set itself. Low trust means longer escrow holds, up to 7 days or blocked. High trust means instant release.
Overlap with Pact: escrow, third party delivery verification, per agent trust score that changes with outcomes. This is the closest non crypto product to Pact's trust loop.
What it does not have: no price or terms negotiation, acceptance is AgentPay's monitor rather than checks the two agents agreed, no seller bond, and a bad delivery costs the seller time, not money. Stripe rails, not PayPal.
Source: https://www.agentpay.studio/

### Underwrite (indie protocol, live demo, built by an AI agent with its human)
What it does: escrow protocol for agent to agent work. Buyer deposits against a machine readable contract. Seller delivers an artifact. Verification runs in two layers: deterministic checks (schema, fields, ranges, formats) plus typed rubric verdicts from an evaluator seat, each with a confidence score. Payment releases only if every check and verdict passes with minimum confidence 0.85. Anything less escalates to a named human arbitrator with signed evidence. Every event is HMAC signed and appended to a hash chained, tamper evident ledger, and the ledger feeds a public reputation trail.
Overlap with Pact: this is the closest single match to Pact's verification and ledger design. Verified delivery against a written spec, signed audit ledger, reputation derived from the ledger.
What it does not have: the contract is supplied by the buyer, not negotiated, and its acceptance checks are not haggled over by the seller. No seller bond. Failure ends in human arbitration, not an automatic slash. No PayPal; it sits on AP2 and x402 style rails.
Source: https://dev.to/workflowbuilderai/im-an-ai-agent-and-i-built-an-escrow-protocol-for-agent-to-agent-work-1dhm

### Kustodia (startup, launched 2026)
What it does: an escrow layer for AI agents exposed as MCP tools. An agent can create an escrow contract, lock buyer funds, monitor for delivery confirmation, and release payment to the seller once it verifies the deliverable meets the agreed specification. Built for multi step, time bound service contracts, positioned as the complement to x402 instant payments.
Overlap with Pact: escrow plus release on verification of a spec, agent native via MCP.
What it does not have: smart contract custody on crypto rails, no negotiation, no seller bond, no public rationale ledger, no PayPal.
Source: https://cointelegraph.com/press-releases/kustodia-launches-the-missing-escrow-layer-for-ai-agents-and-x402-payments

### Assay (indie build on Base)
What it does: bills itself as the trust layer for AI agents, combining stake, escrow, reputation, and discovery. Its StakeRegistry contract handles registration, staking, slashing, and earnings. Its Escrow contract runs the full escrow lifecycle and, after each settlement, writes the agent's score into the ERC-8004 Reputation Registry.
Overlap with Pact: this is the closest match to Pact's bond idea. Staking with slashing, escrow, and outcome based reputation in one system.
What it does not have: the stake is a general registration stake, not a per deal performance bond sized to one job and paid to the wronged buyer. No negotiation, no agent authored acceptance checks, no independent verifier agent flow described, crypto only.
Source: https://dev.to/grandionn/i-built-the-missing-trust-layer-for-ai-agents-on-base-stake-escrow-reputation-discovery-1mom

### AgentStake Protocol (whitepaper stage)
What it does: agents stake tokens to earn trust. A Trust Score combines stake amount, stake age, and track record. Misbehavior claims go through tiered dispute resolution, from automated checks to staked juror pools. Upheld claims compensate victims from the slashed stake and expel bad actors.
Overlap with Pact: bond, slashing, compensation to the wronged party, trust score. It proves the bond and slash idea is already circulating as a general trust mechanism.
What it does not have: it is about agent statements and behavior in general, not settlement of a specific negotiated service deal. No escrow of a buyer's payment, no delivery verification against deal specific checks, no PayPal.
Source: https://www.agentstake.dev/whitepaper

### CrediClaw (protocol, Medium writeup, January 2026)
What it does: agents stake on the truth of what they communicate. If the information proves false, part or all of the stake is slashed or burned and the agent's Credibility Score falls. Integrates ERC-8004 identity.
Overlap with Pact: stake at risk plus a score that falls on failure.
What it does not have: it covers claims and information, not hired work, delivery, escrow, or buyers. No PayPal.
Source: https://medium.com/@crediclaw/crediclaw-the-trust-layer-for-ai-agents-9378e7895641

### AGIRAILS (protocol project)
What it does: payment and settlement rails for the agent economy. An agent requests a service, another quotes a price, funds go into escrow, delivery is verified, payment settles, reputation updates. Their own walkthrough uses a translation job: quote, escrow, delivery, requester confirmation, release, reputation update.
Overlap with Pact: quote, escrow, verified delivery, reputation, in one flow. Very close to Pact's sequence.
What it does not have: the requester confirms delivery rather than an independent verifier judging against negotiated checks. No seller bond. Blockchain rails on Base testnet.
Source: https://paragraph.com/@agenteconomy/from-ai-agents-to-an-agent-economy

### Synmerco (live agent work platform)
What it does: a requester funds an intent, agents bid on it, the lowest credible bid usually wins, and payment releases when the delivery passes acceptance checks. A published field report describes five real escrows released for data and writing jobs totaling 73 dollars, with acceptance hinging on provenance of the delivered work.
Overlap with Pact: funded escrow, price competition between agents, acceptance checks gating release.
What it does not have: bidding is not negotiation over terms and checks, checks belong to the requester, no verifier agent described as a separate party, no bond, USDC rails.
Source: http://dev.to/innerozma/how-my-ai-agent-earned-usdc-on-synmerco-5-released-escrows-73-gross-no-human-in-the-loop-mpn

### Fetch.ai and Agentverse (established platform)
What it does: a long running agent platform with a registry of millions of hosted agents, agent ratings, agents that negotiate deals (their personal agent negotiates with hotel, flight, and car agents), and AI to AI payments in USDC and FET since December 2025. A 2026 spin off, Agent Launch, gives agents tradeable tokens whose market value reflects reputation, explicitly framed as giving an agent something to lose.
Overlap with Pact: agent negotiation and agent payment at real scale, reputation, economic skin in the game via tokens.
What it does not have: no escrow with verified delivery against a spec, no per deal bond slashed to a buyer, no PayPal.
Source: https://cryptobriefing.com/fetch-ai-agentic-infrastructure-agentverse/

### Purple Flea Escrow (live niche service)
What it does: trustless escrow for agent to agent payments in Monero, exposed over MCP. Payer creates escrow and deposits, worker delivers and marks complete, payer verifies and releases, minus a 1 percent fee.
Overlap with Pact: escrow with a verify then release step, agent native.
What it does not have: the payer is the verifier, no third party checks, no negotiation, no bond, no reputation system described.
Source: https://dev.to/purpleflea/paying-ai-agents-like-employees-the-purple-flea-escrow-protocol-n92

### RustChain RIP-302 agent job marketplace (open source build)
What it does: agents post jobs with crypto locked in escrow, claim, deliver, and get paid on acceptance, with disputes, expiry refunds, and reputation across jobs, in 868 lines of Python.
Overlap with Pact: job escrow lifecycle plus reputation.
What it does not have: acceptance by the poster, no verifier agent, no negotiation, no bond.
Source: https://dev.to/scottcjn/we-built-an-agent-to-agent-job-marketplace-with-crypto-escrow-in-868-lines-3lmd

### Skyfire and Nevermined (funded agent payment startups)
What they do: Skyfire is an identity and payments trust layer for agents (Know Your Agent protocol, tokenized cards, programmatic checkout), backed by a16z CSX and Coinbase Ventures. Nevermined, funded to build agent to agent payment infrastructure and often described as a PayPal for AI, handles agent payments with protocol level A2A, MCP, and x402 support and tamper proof metering.
Overlap with Pact: agent identity, agent payment rails, trust positioning. Useful context that well funded teams own the generic agent payments pitch.
What they do not have: neither does negotiated service contracts, escrow with verified delivery, or seller bonds. They are rails and identity, not settlement of hired work.
Sources: https://www.businesswire.com/news/home/20261019685711/en/Skyfire-and-Forter-Enrich-Trusted-Agentic-Commerce-Decisions-at-Checkout and https://parsers.vc/news/250110-the-dawn-of-ai-commerce--nevermined-s-4/

## Hackathon projects

### AgentBazaar (Chainlink Convergence hackathon)
What it does: an on chain marketplace where AI agents post jobs, get matched by AI, negotiate, and transact. USDC sits in escrow. One workflow matches the job to an agent, one triggers execution, and one scores the delivered output with AI and releases payment only if it passes a quality threshold. Agents are gated by World ID.
Overlap with Pact: negotiate, escrow, AI scored delivery gating release. A judge who follows hackathons may have seen this shape before.
What it does not have: the score is a quality threshold, not checks negotiated into the deal. No seller bond. No PayPal.
Source: https://chain.link/hack-26/projects/agentbazaar

### Chainlink Agent (Chainlink Convergence hackathon)
What it does: a marketplace where agents buy data from merchants using x402 plus on chain escrow. A Settlement Verifier workflow verifies delivery and finalizes payment. A Dispute Resolver workflow runs dual LLM analysis on disputes and files a verdict on chain. An Expiry Watchdog auto refunds stalled escrows.
Overlap with Pact: verifier driven settlement and automatic refunds, in a hackathon project.
What it does not have: it sells data through a gateway, with no negotiated spec, no acceptance checks authored by the parties, no seller bond.
Source: https://chain.link/hack-26/projects/chainlink-agent

### AgentCred (The Synthesis hackathon)
What it does: an on chain reputation and escrow layer for AI agents backed by verifiable execution receipts. Jobs run in a verifiable runtime, settle through escrow, and each job's cryptographic receipt and evidence feed the agent's reputation.
Overlap with Pact: escrow plus receipts plus reputation.
What it does not have: no negotiation, no acceptance checks from the parties, no bond, verification is about execution proofs rather than a spec verdict.
Source: https://medium.com/@web3devzz/agentcred-verifiable-execution-escrow-for-ai-agents-e6ada383e413

### Agent Auction Protocol (Chainlink hackathon winner)
What it does: on chain auctions where agents participate with a bonded identity, place bids, and settle through a verifiable flow, using ERC-8004 identity.
Overlap with Pact: the word bond attached to agent participation in commerce. Worth knowing so the pitch does not claim bonded agents are new.
What it does not have: the bond backs auction participation and identity, not delivery quality on a specific job, and there is no verified delivery or slash to a buyer.
Source: https://chain.link/hackathon/winners/agent-auction-protocol

### AI Smart Escrow for Digital Commerce (Devpost project)
What it does: smart contract escrow for ordinary digital commerce where an ML risk model scores each transaction and classifies it as auto release, hold in escrow, or reject.
Overlap with Pact: AI plus escrow on Devpost, nothing more.
What it does not have: no agents, no negotiation, no delivery verification, no bond.
Source: https://devpost.com/software/ai-smart-escrow-for-digital-commerce

### Sigil (Devpost project)
What it does: an approval and audit layer for agent payments. Every payment decision sits in a hash chained log, reputation points can be revoked when abuse is found later, and tests show small scams blocked by instruction provenance checks. Escrow and a deposit contract are listed as future work, not built.
Overlap with Pact: hash chained audit log and reputation with consequences.
What it does not have: escrow and deposits are explicitly unbuilt roadmap items, and it guards a human owner's payments rather than settling deals between two agents.
Source: https://devpost.com/software/sigil-0t86j1

### PatronAI (PayPal AI Hackathon submission, publicized by its author)
What it does: a sponsorship platform for youth sports clubs. An agent matches businesses to clubs, an AI valuator prices in kind services and drafts agreements, PayPal REST API v2 handles payments, and a multimodal audit checks expenses with Gemini plus SHA-256 hashing.
Overlap with Pact: it is in the same hackathon and uses PayPal plus an expense audit. That is where the similarity ends. No agent to agent deal, no escrow, no bond.
Source: https://www.youtube.com/watch?v=hYZpIEeT7xw

### Unnamed agent work platform, field report (dev.to)
What it does: a working loop where a publisher commits budget into on chain escrow before work starts, an agent delivers, the delivery is reviewed against task criteria, and a rejected delivery goes back for rework while funds stay locked. The author ran both the accept branch and the reject and rework branch for real.
Overlap with Pact: the revision round before refund already exists in practice, so it should be presented as table stakes, not a feature.
Source: http://dev.to/sanye/an-ai-agent-did-real-work-last-week-this-is-a-0-mechanism-demo-not-a-paid-receipt-114c

## What PayPal itself ships (collision check inside the sponsor)

PayPal's own agentic commerce stack is about letting agents pay and letting merchants be found by agents. It does not include negotiated agent contracts, escrow for agent services, verifier agents, seller bonds, or agent reputation.

- PayPal Agent Toolkit and MCP server: tools that let agents create orders, pay orders, create refunds, manage invoices, subscriptions, disputes, and shipment tracking through function calling. This is the rail Pact builds on, not a competing product. Source: https://developer.paypal.com/community/blog/accelerating-agentic-payments/
- Agent Ready and Store Sync: one merchant integration that syncs a product catalog and takes PayPal payment inside AI shopping surfaces such as Copilot, Perplexity, and Glance. Consumer checkout, not agent to agent service settlement. Source: https://theinference.org/article/paypal-s-checkout-is-inside-glance-an-ai-shopping-agent-on-60-million-devices-but-volume-waits-until-2028
- Delayed disbursement: PayPal's existing marketplace primitive that holds a buyer's funds before disbursing to a seller, with vetting time in between. It is built for human marketplaces, but it is the legitimate PayPal native basis for Pact's hold step, and citing it makes the build look grounded rather than improvised. Source: https://developer.paypal.com/platforms/checkout/delayed-disbursement
- Google Cloud Conversational Commerce agent with PayPal over A2A and AP2: a shopping assistant story, again consumer side.

## Verdict

### Element by element

Already common, worth zero novelty claims:
- Agents negotiating price with offers and counteroffers. Described step by step in A2A commerce guides, live at Fetch.ai, and present in AgentBazaar. Common.
- Buyer funds held in escrow until delivery. Everywhere: OKX, Kustodia, AgentPay, AGIRAILS, ERC-8183, and a dozen hackathon builds. Common.
- A verifier or evaluator deciding pass or fail before release. AgentPay's Agent Monitor, Underwrite's evaluator seat, ERC-8183's evaluator role, Chainlink Agent's Settlement Verifier. Common, close to standard practice now.
- Reputation scores updated by deal outcomes. OKX, AgentPay trust scores, ERC-8004, Assay, Fetch.ai ratings. Common.
- An audit ledger of deal events. Underwrite and Sigil both ship signed or hash chained logs. Common in serious builds.
- A revision round before refund. Present in live agent work platforms. Table stakes.
- Staking and slashing as a general agent trust idea. AgentStake, CrediClaw, Assay, ERC-8004 validation. The concept exists.

Genuinely uncommon, based on everything found:
- Acceptance checks authored by the negotiation itself. In every close match, the spec and its checks come from the buyer, the requester, or a platform template. Underwrite is the nearest, and its contract is still buyer supplied. Nobody found has the seller proposing, resisting, and agreeing to the very checks it will later be judged against, as part of the haggle. This makes the verdict hard to dispute, because the seller signed its own test.
- A per deal seller performance bond slashed to the buyer. Staking systems slash for network misbehavior, false claims, or bad validation. Assay combines stake, escrow, and reputation but its stake is a standing registration stake. No product found takes a bond sized to one deal, holds it next to the buyer's payment, and pays it to the buyer automatically when that deal's own checks fail. On PayPal rails it appears to be unclaimed entirely.
- The full loop on fiat PayPal rails. Every close match settles in stablecoins or testnet crypto, except AgentPay, which uses Stripe and stops at hold duration as its only penalty. Nobody found runs negotiation, hold, verified delivery, payout, refund, and bond slash through PayPal Orders, Payouts, and refunds.

Does the whole combination exist somewhere? No. The combination is open. But the center of the combination, escrow plus verifier plus reputation, is close to a commodity pattern in the crypto agent world, and ERC-8183 has already standardized that center. Pact wins or loses on the edges: the negotiated checks, the bond, and the PayPal execution.

### Top three differentiators to lean on in the pitch

1. The agents negotiate the test, not just the price. Pact's haggle produces the acceptance checks themselves, frozen into the deal spec. The seller is later judged only on what it agreed to be judged on, in its own words. Lead the demo with the seller pushing back on a check and the check changing. No competitor demo found has that moment.
2. Both sides have money at risk. The buyer's payment is held, and the seller's bond sits next to it. A failed verification does not just refund the buyer, it pays the buyer the slashed bond, automatically, through PayPal. Frame it plainly: in every other system, a cheating seller loses nothing but time. In Pact, cheating costs money. This is also what makes the cheating seller demo land.
3. One verdict moves everything, in real money rails, with the reasoning public. The verifier's single pass or fail triggers payout or refund, bond return or slash, and a reputation change, and the ledger shows each agent's rationale next to each money movement. Competitors split these across systems or settle in testnet tokens. Pact does it in one place, in dollars, on the sponsor's own platform, which is exactly what a PayPal hackathon jury is positioned to reward.

### Claims to avoid

- Do not say first agent escrow, first agent marketplace, or first verified agent settlement. OKX, Kustodia, AgentPay, and ERC-8183 kill those claims.
- Do not present the audit ledger or reputation score as inventions. Present them as the public record that makes the bond and the negotiated checks enforceable and visible.
- Do not overclaim the bond as a new mechanism in general. AgentStake and Assay exist. The accurate claim is narrower and stronger: a per deal bond, posted through PayPal, slashed to the buyer on a failed check the seller itself agreed to.

## Refresh 2026-10-22: publicized entries in this hackathon

The Devpost gallery for this hackathon is not public yet (the /projects
path 404s and the homepage lists no submissions). It normally opens
after submissions close on Nov 12, 2026. Only self publicized entries
can be checked right now. Four were found:

- PatronAI: youth sports sponsorship matching with an expense audit.
  No agent to agent deal, no escrow, no bond. Already covered above.
- Sonar Desk (closest neighbor): an agent buys prediction market
  signal briefs through PayPal inside a user set mandate, and a wrong
  signal triggers an automatic refund through the Refunds API. No
  negotiation, nothing held, no verifier agent judging a delivery
  against negotiated checks, and the seller risks only the sale price.
  Runs real PayPal rails (Orders, Refunds, Agent Toolkit), so "on
  PayPal" alone is not a differentiator against it. Pitch line from
  this: a refund gives the buyer their money back; a slashed bond also
  makes the failure cost the seller something.
- BOLT PayFlow Guard: natural language payment request, a human
  approval gate, then a sandbox order. No dealing, no escrow, no
  verification, no bond.
- Dunly: turns client messages into PayPal invoices with late payment
  reminders. No overlap in mechanics.

Verdict after the refresh: no publicized entry matches any of Pact's
three uncommon pieces (negotiation authored acceptance checks, a per
deal seller bond slashed to the buyer, the full loop on PayPal). The
verdict must be re-run when the Devpost gallery opens after Nov 12.
