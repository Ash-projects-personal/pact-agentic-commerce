# The business case for PayPal in Pact

Researched 22 October 2026. All fees are from PayPal's official US merchant fee page unless marked otherwise. All market figures are sourced. Forecasts are labeled as forecasts. Estimates are labeled as estimates.

## Bottom line

One Pact deal puts four paid money movements on PayPal rails instead of one. At published US rates, PayPal collects about $11.95 in gross fees on a completed $250 deal with a $50 bond, and about $11.70 on a refunded deal, because refund fees are not returned. PayPal earns nearly the same whether the deal succeeds or fails. At 1 million deals a month that is roughly $143 million a year in gross fee revenue on $3.6 billion a year of new transaction volume, at an effective take of about 4.0 percent on captured volume, roughly double PayPal's blended take rate.

## 1. The published fees that apply to each movement

Source for this whole section: PayPal, "Fees | Merchant and Business | PayPal US", paypal.com/us/business/paypal-business-fees, accessed 22 October 2026. A September 2026 check of the same page by Sellfy confirms these rates were current then too.

Receiving a commercial transaction (this covers both the payment capture and the bond capture, since both are PayPal orders the platform receives):

- PayPal Checkout: 3.49 percent plus a fixed fee of $0.49 USD
- Standard credit and debit card payments: 2.99 percent plus $0.49
- International commercial transactions: an extra 1.50 percent on top of the domestic rate

Sending money out (this covers the seller payout on a pass, the bond return on a pass, and the bond slash payout on a fail):

- PayPal Payouts, US domestic, standard: 2 percent of the amount, capped at a maximum fee of $1.00 USD per payout
- PayPal Payouts, US domestic, when using the Payouts API: a flat $0.25 USD per payout
- PayPal Payouts, international: 2 percent, capped at $20.00 USD per payout in USD

Refunds (the fail path for the main payment):

- Per the same official fee page: "If you refund a Commercial Transaction or an Invoicing Transaction payment, there are no fees to make the refund, but the fees you originally paid to receive the payment are not returned to you."
- PayPal's developer documentation says the same: no fee to make the refund, original seller fees not returned (developer.paypal.com, RefundTransaction API page, updated 17 August 2026)

Currency conversion, where a cross border deal converts currency:

- 4.00 percent spread when paying for goods or services, or sending a Payout, where the recipient receives a different currency
- 3.00 percent spread for all other transactions

Related fees worth knowing for the risk section:

- Chargeback fee: $20.00 USD. Standard dispute fee: $15.00 USD. High volume dispute fee: $30.00 USD (all from the same official fee page)
- Optional instant withdrawal to a bank or card: 1.50 percent of the amount, minimum $0.50 USD

## 2. What PayPal has shipped and said about agentic commerce

Shipped (source: PayPal press release carried by PR Newswire and Stockwatch, 29 April 2025, and FF News coverage of PayPal Dev Days):

- The Agent Toolkit, developer tools that let agents pay, track shipments, and manage invoices through PayPal
- What PayPal calls the industry's first remote MCP server, so AI agents can call PayPal functions directly
- Dev Days partnerships and demos with AWS, Anthropic, Google Cloud, and Microsoft. PayPal CEO Alex Chriss: "We are building with velocity and partnering with the biggest players in AI to empower our customers to access new opportunities in the AI economy."

Shipped since (sources: The Inference, 21 October 2026; a protocol survey at surfthewave.substack.com, October 2026):

- Agent Ready and Store Sync: a single merchant integration that syncs a catalog and takes payment across AI surfaces. PayPal supports both ACP (the OpenAI and Stripe protocol) and Google's UCP
- Checkout already runs inside ChatGPT, and inside Microsoft Copilot, Perplexity, and Google AI experiences
- On 15 October 2026 PayPal became the only native checkout inside Glance, an AI shopping agent on more than 60 million US devices. No financial terms disclosed
- On 22 September 2026 PayPal announced a deal with Meta so customers can shop and pay through Muse, Meta's personal agent (The Paypers, via Admiral Markets summary)

What PayPal has said about monetizing it:

- PayPal has not published a separate take rate or price list for agentic commerce. The monetization on the public record is the standard transaction take rate applied to new volume, plus the strategic value of staying the default wallet. Treat any claim of a special agentic fee as unconfirmed.
- CEO Enrique Lores, at Money 20/20 in Las Vegas, 19 October 2026 (Payments Dive, 20 October 2026): commerce done through agents in 2026 and 2027 "is going to be relatively small," and PayPal does not expect meaningful sales volumes from agentic commerce until 2028. He also said management expects agentic payments to become meaningful contributors from 2028 onward (Q2 2026 earnings call, via Admiral Markets)
- Lores on the strategic asset (Payments Dive): "Trust was very important when e-commerce started. It's going to be even more important in an agentic world, and that's the position that we need to occupy."
- The honest read: PayPal is spending now on rails and partnerships, expects the money from 2028, and has named trust as the ground it wants to hold. A verified settlement product like Pact is exactly a trust product.

## 3. Market size

Freelance and services marketplaces (the segment Pact serves first, agents hiring agents and freelancers):

- Mordor Intelligence, freelance platforms market: USD 7.64 billion in 2025, an estimated USD 8.91 billion in 2026, forecast to reach USD 18.97 billion by 2031 at a 16.32 percent CAGR (mordorintelligence.com, accessed October 2026). Forecast.
- Dataintelo, freelance marketplace gross services volume: $12.20 billion transacted in 2025, forecast to reach $20.34 billion by 2033 at a 6.6 percent CAGR. This one measures client spend flowing through marketplaces, which is the closest published analog to Pact style payment volume. Forecast beyond 2025.
- TechSci Research puts the wider online freelance market at USD 9.32 billion in 2025, growing to USD 24.68 billion by 2031. Forecast. The three firms define the market differently, so the figures are a range, not a single number.

Agentic commerce overall:

- McKinsey: by 2030, agentic commerce could orchestrate $3 trillion to $5 trillion globally (McKinsey, "The agentic commerce opportunity", October 2025, restated in McKinsey articles through 2026). Forecast. Note this counts revenue orchestrated by agents, a wide definition.
- Morgan Stanley, as summarized by Stellagent's forecast roundup: US purchases autonomously executed by agents of $190 billion to $385 billion by 2030. Forecast.
- Gartner, same roundup: $15 trillion of B2B purchases mediated by AI agents by 2028. Forecast, and the widest definition of all. Treat it as an upper bound, not a plan number.

Machine to machine payments today, for calibration:

- Chainalysis, 2026 Geography of Cryptocurrency Report (via Blockhead, 15 October 2026): agents have made more than 138 million payments over Coinbase's x402 protocol, but more than 87 percent were worth between $0.0001 and $0.10, and total activity in July 2026 was roughly 75 million payments worth only about $24 million. Machine payments are real and growing, but the dollars are still tiny and concentrated in micropayments.

## 4. The pitch math

Assumptions, stated plainly:

- Representative deal: $250 price, 20 percent bond of $50, both parties in the US, paid in USD, no currency conversion
- The buyer pays with PayPal at the published PayPal Checkout rate of 3.49 percent plus $0.49. This is an assumption about funding mix, not a quote
- Both captures (payment and bond) are commercial transactions received by the platform, so both pay the receiving rate
- Payouts go through the Payouts API at the flat $0.25 per payout
- Published rack rates throughout. A platform at real scale would negotiate volume pricing, which would lower these numbers. This is gross fee revenue to PayPal, before PayPal's own costs such as interchange on card funded payments
- On a fail, the $250 payment is refunded (refund itself is free, original fee kept) and the $50 bond is paid out to the buyer as the slash (one $0.25 payout fee)

Per completed deal (pass):

- Payment capture on $250: 250 × 3.49% = $8.73, plus $0.49 = $9.22 (exact $9.215)
- Bond capture on $50: 50 × 3.49% = $1.75, plus $0.49 = $2.24 (exact $2.235)
- Payout of $250 to the seller: $0.25
- Bond return payout of $50 to the seller: $0.25
- Total: $9.215 + $2.235 + $0.25 + $0.25 = $11.95 per completed deal

Per refunded deal (fail):

- Payment capture fee, kept after the refund: $9.22
- Bond capture fee: $2.24
- Refund of the $250: $0.00, and the capture fee above is not returned
- Bond slash payout of $50 to the buyer: $0.25
- Total: $9.215 + $2.235 + $0.25 = $11.70 per refunded deal

The point for the pitch: failure costs PayPal almost nothing in revenue. A failed deal earns 98 percent of what a completed deal earns, because the two capture fees are collected up front and never returned.

Scale, completed deals at $11.95 each:

- 10,000 deals a month: $119,500 a month, $1,434,000 a year
- 100,000 deals a month: $1,195,000 a month, $14,340,000 a year
- 1,000,000 deals a month: $11,950,000 a month, $143,400,000 a year

Scale, refunded deals at $11.70 each:

- 10,000 deals a month: $117,000 a month, $1,404,000 a year
- 100,000 deals a month: $1,170,000 a month, $14,040,000 a year
- 1,000,000 deals a month: $11,700,000 a month, $140,400,000 a year

Blended estimate (label: estimate). At an assumed 85 percent completion and 15 percent refund mix, PayPal earns about $11.91 per deal either way, so the blended scale numbers sit within 1 percent of the completed deal table above.

Volume and take rate view:

- Each deal captures $300 of volume ($250 payment plus $50 bond). At 1 million deals a month that is $300 million a month, $3.6 billion a year, of new total payment volume
- All in fees are $11.95 per completed deal on $300 captured, an effective take of about 4.0 percent on that volume. This report uses one definition of effective take everywhere: total gross fees per deal over captured volume. For comparison, one analyst breakdown of PayPal's filings puts its blended take rate at 1.62 percent in Q1 2026 (cheapsoftwarestocks.substack.com, from PayPal SEC filings). Pact style volume carries roughly double the blended rate because every deal is two full price wallet captures plus two payouts, with none of the low margin unbranded processing mix that drags PayPal's average down

Sensitivity (label: estimate). Pact's Orders wallet flow prices a card funded payment through PayPal Guest Checkout at the same 3.49 percent plus $0.49 as a wallet balance payment. A funding mix shift within this integration does not move the numbers. The older version of this paragraph used 2.99 percent plus $0.49, which is PayPal's Standard Card Payments rate, a different integration Pact does not use. If a deal is international, add 1.50 percent on both captures, another $4.50 per deal, plus the 4 percent conversion spread on any amount converted.

Float (label: estimate, yield not modeled). Delayed disbursement means PayPal holds $300 per open deal during the verification window. At 1 million deals a month and an assumed average cycle of 3 days, average held balances are about $30 million (300 × 1,000,000 × 3/30). At 100,000 deals a month, about $3 million. Longer or disputed deals hold more.

## 5. Why PayPal would care strategically

The rivals, sourced:

- Coinbase x402: an open protocol, whitepaper published 6 May 2025, that lets agents pay in stablecoins inside an HTTP request with no account and no card (Coinbase Developer Platform, via news.dropstab.com research summary). Chainalysis counts 138 million plus payments, but almost all under 10 cents and only about $24 million of value in July 2026. x402 owns the micropayment end. It has no buyer protection, no dispute process, no escrow, and no fiat payout network for a freelancer who needs rent money. That is exactly the gap a $250 verified services deal falls into.
- Stripe: co developed ACP with OpenAI, runs Instant Checkout in ChatGPT, and its Link wallet for agents lets consumers connect payment methods and approve agent spending. Stripe reported agentic purchases through Link rose 38 fold in September 2026 with an average cart of about $100, and about 200 agents now use Link (Stripe Link update, 29 September 2026, via goldenera.si and Upstarts Media). Stripe's standard online rate is 2.9 percent plus $0.30 (stripe.com/pricing, verified August 2026). Stripe is winning the consumer shopping agent today.
- Visa and Mastercard: Visa's Trusted Agent Protocol and Intelligent Commerce, and Mastercard Agent Pay with agentic tokens, extend card rails into agent initiated payments (surfthewave.substack.com protocol survey, October 2026). If agents default to network tokens, PayPal's wallet gets bypassed at the exact moment checkout disappears into an agent.

What Pact style volume does for PayPal against that field:

1. It defends the wallet. Every Pact deal needs a funded PayPal account on both sides and pays out into PayPal accounts through Payouts. Agents and freelancers who get paid into PayPal tend to keep balances and spend from them, and recipients cashing out instantly pay the 1.50 percent instant transfer fee. None of that happens if the same deal settles in USDC over x402.
2. It sells the one thing the crypto rails do not have: recourse. Escrow style holding, delivery verification, refunds, and a slashed bond are Purchase Protection rebuilt for agent to agent services. That is the trust position Lores publicly said PayPal needs to occupy in an agentic world.
3. It is high take volume in a business worried about take rate. About 4.0 percent effective take on captured volume versus a blended rate near 1.6 to 2 percent, and the revenue survives refunds.
4. It reduces PayPal's own dispute costs. Verified delivery evidence should cut claims on these deals, and each avoided dispute avoids the $15 standard dispute fee fight and the support cost behind it (fee sourced above; the savings size is an estimate, not a published figure).
5. It is cheap to win now and valuable later. PayPal's own CEO says the volume arrives in 2028. The rails Pact needs already exist (Orders, delayed disbursement, Payouts, Hyperwallet). Owning the verified settlement pattern for agent services before 2028 costs PayPal little and is hard to copy later, because the asset is the reputation and verification data that accumulates deal by deal.

## 6. The production model (Commerce Platform plus delayed disbursement)

The fee math above prices the demo plumbing. A production build on PayPal Commerce Platform looks different and earns different fees. This section is the honest version, because a platform engineer judge will know it anyway.

The demo takes custody. Both orders are created with platform credentials and no payee, so both captures land in the platform's own account and Pact pays the seller out at full price with Payouts. That means the platform absorbs both capture fees on every deal, which is not a business model. It also means the platform is holding both sides' money, which is a money transmission question PayPal's Commerce Platform exists to answer.

The production path removes the platform from custody entirely.

1. Pact registers as a PayPal Commerce Platform partner: a partner business account, a BN code sent as the PayPal-Partner-Attribution-Id header, and multiparty scopes arranged with the PayPal account team.
2. Every seller onboards through Partner Referrals before any deal. Pact stores the seller's payer_id. The PARTNER_FEE feature has to be enabled at onboarding, or the platform_fees array is rejected.
3. The price order is created as the seller's transaction: partner credentials, a PayPal-Auth-Assertion naming the seller, purchase_units[0].payee set to the seller, and payment_instruction.disbursement_mode set to DELAYED at creation. The platform's own cut goes in the same instruction as platform_fees. The deal id goes in reference_id and custom_id. The buyer approval step stays.
4. Capture happens after approval. PayPal holds the funds. There is a hard limit: auto disbursement after 28 days. Verification, revision, and any dispute must finish within 28 days of capture. Pact's single revision round fits easily, but a long human dispute has a real clock.
5. On a pass, Pact releases the price with POST /v1/payments/referenced-payouts-items, reference_id set to the capture id and reference_type set to TRANSACTION_ID. PayPal deducts its fee and the platform fee at disbursement. The price leg never touches the Payouts API, so the two $0.25 payout fees disappear.
6. On a fail, Pact refunds the price capture while the funds are still held, which is strictly safer than refunding out of a pooled platform account.
7. The bond gets its own treatment, because the beneficiary on a slash is the buyer, not the seller. The clean approach is intent AUTHORIZE on the bond order. On a pass, the app voids the authorization: no money moves, and no capture fee is burned. On a fail, the app captures the authorization and pays the bond out to the buyer with Payouts.

Production fee math, same $250 price and $50 bond, same published 3.49 percent plus $0.49 rate. A completed deal earns the price capture fee only: $9.215. The bond authorization is voided, and the two $0.25 payout fees are gone. That is $9.215 on $300 captured, an effective take of about 3.1 percent. A refunded deal earns the price capture fee ($9.215, kept after the refund) plus the bond capture fee ($2.235) plus the $0.25 slash payout: $11.70, the same as the demo, an effective take of about 3.9 percent. At the assumed 85/15 mix the blended number is about $9.59 per deal, and a million deals a month gives roughly $115 million a year in gross fees on the same $3.6 billion of volume.

What changes and what stays. The per deal fee drops from $11.95 to $9.22 on a pass, because the platform is no longer routing payouts through itself. What stays is the point of the pitch: the fee is still well above PayPal's blended take rate, the platform finally has its own revenue line (the platform fee in the disbursement instruction, which the demo does not have), and failure still costs PayPal almost nothing in revenue. The largest single engineering change is seller identity: today there is no seller identity beyond two hardcoded sandbox emails, and everything in this section, onboarding, payee, assertions, platform fees, depends on that existing first.

## Caveats

- All fee figures are US published rates as of 22 October 2026 and change over time. Rates differ by country.
- The $250 deal, the funding mix, the completion mix, and the 3 day cycle are stated assumptions, not observed Pact data. Pact is a hackathon build running on the PayPal sandbox, so there is no live volume behind any of this yet.
- Gross fee revenue is not profit. On card funded captures PayPal pays interchange and network costs out of the 3.49 percent.
- Forecast figures in section 3 use each firm's own definition of agentic commerce, and the definitions differ by trillions of dollars.