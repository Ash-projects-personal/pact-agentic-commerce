# PayPal platform expert review (2026-10-22)

Expert panel subagent c5e741e9, completed 2026-10-22 21:26 UTC. Scope: pact/payments.py, paypal_agents.py, payment/settlement/webhook code in main.py, config.py, README PayPal sections, research/paypal-business-case.md. Fees checked against PayPal official US merchant fee page and delayed disbursement guide.

## Headline: right API families, right approval model, wrong custody topology
Orders, capture refunds, Payouts are correct products; Agent Toolkit is a reasonable primary rail; account holder approval before capture is exactly PayPal's model. But both orders are created with platform credentials and no payee, so price and bond captures land in ONE platform owned account and Pact re-pays via Payouts. In production that is taking custody of other people's money (money transmission licensing exposure); PayPal Commerce Platform + delayed disbursement exist to replace exactly this. Seller never becomes merchant of record. README is honest that the hold is modeled in the app ledger, but ledger text says funds are "HELD" by PayPal, and any engineer inspecting a capture will see the platform as payee.

True delayed disbursement path (for README/paper production section):
1. Commerce Platform partner: partner business account, BN code as PayPal-Partner-Attribution-Id header, multiparty scopes added with PayPal account team (401 until done). Sandbox multiparty accounts exist.
2. Onboard every seller via Partner Referrals before any deal; store seller payer_id; platform fee needs PARTNER_FEE feature at onboarding or platform_fees array is rejected; track payments_receivable and email_confirmed. Today there is NO seller identity beyond two hardcoded sandbox emails. Largest single change.
3. Price order created as the SELLER's transaction: partner credentials + PayPal-Auth-Assertion naming seller, purchase_units[0].payee = seller, payment_instruction.disbursement_mode = DELAYED at create, platform_fees in same instruction, deal id in reference_id and custom_id. Buyer approval step stays, ideally with application_context return/cancel URLs into Pact.
4. Capture after approval; funds held by PayPal. HARD LIMIT: auto disbursement after 28 days, so verification + revision + disputes must finish within 28 days of capture.
5. Pass: disburse via POST /v1/payments/referenced-payouts-items with reference_id = capture id, reference_type = TRANSACTION_ID. PayPal deducts its fee and platform fee at disbursement. Price leg never touches Payouts; the two $0.25 payout fees disappear.
6. Fail: refund the capture while funds still held (call Pact already has). Strictly safer than refunding out of a pooled platform account.
7. Bond needs its own treatment (beneficiary on slash is buyer, not seller). Option A: bond as normal order with platform merchant as payee; pass = refund bond capture to seller, fail = Payouts to buyer. Option B (cleaner, what PayPal engineers would suggest): bond order intent AUTHORIZE; pass = void authorization, no money moves, no capture fee burned; fail = capture authorization, then Payouts to buyer.
8. Reconcile from webhooks (see gaps).
9. Rework fee story for production model.

## Fee math: arithmetic verified correct
Checkout 3.49% + $0.49 correct. Standard card 2.99% + $0.49 correct. International +1.50% correct. Payouts 2% capped $1.00, flat $0.25 via Payouts API correct (the pitch's $0.25 is real). Refund rule verbatim correct. Conversion 4% goods/payouts, 3% other correct. Chargeback $20, dispute $15, high volume dispute $30 correct (omission: high volume tier = dispute ratio >=1.5% and >100 sales in prior 3 months). Instant transfer 1.50% min $0.50 correct for business (blogs saying 1.75% quote consumer). Per deal: $9.215 + $2.235 + $0.25 + $0.25 = $11.95 completed; $11.70 refunded; scale math, blended $11.91, card sensitivity $10.45, float all recompute cleanly.
Shaky framings:
1. Pitch prices the demo plumbing, not the production design. Under delayed disbursement the two $0.25 payout fees mostly vanish. Present BOTH models' numbers before a platform engineer judge points it out.
2. "Effective take about 3.8%" uses capture fees only ($11.45/$300). All in is $11.95/$300 = 3.98%. Pick one definition, use it in both places.
3. Card funded sensitivity mixes integrations: Pact's wallet Orders flow prices card as PayPal Guest Checkout 3.49% + $0.49, not 2.99% (that rate is Standard Card Payments, a different integration). $10.45 is arithmetically right for a checkout Pact does not have.
4. Blended take 1.62% rests on one analyst Substack from SEC filings, not a PayPal published figure; blended rate dragged down by unbranded mix. Labeled with source in doc (right), but never say it aloud as a PayPal number.
5. Both capture fees currently land on the platform's own account while seller is paid full price by payout: platform is eating both capture fees. Doc never says this; matters for Pact's own unit economics.

## Production gaps, ranked by judge impact
1. IDEMPOTENCY DEFEATED: PayPalClient._request generates a NEW random PayPal-Request-Id on every call; payout() generates a new sender_batch_id every call. Retried timeout = duplicate execution. Fix: derive ids deterministically from deal + leg (deal id + "price-capture"), store on deal.
2. SETTLEMENT CAN WEDGE: verify() sets state "verifying" then settles; if second payout in _settle_release fails, 502 leaves deal in "verifying", a state no endpoint accepts. No resume/retry/unwind. Refund path same shape (refund then slash, retry would double refund). Settlement legs need individual recording and resumability.
3. PAYOUTS TREATED AS SYNCHRONOUS/FINAL: payout() returns batch status (PENDING/PROCESSING) and _settle_release immediately records released/returned, sets state, moves reputation. Items can later be unclaimed/denied/returned/blocked. No show batch/item calls; webhook handler ignores PAYMENT.PAYOUTSBATCH / PAYOUTS-ITEM events.
4. WEBHOOK RECONCILIATION DECORATIVE, FAILS OPEN: matching by substring search of order/capture ids in str(payload), done BEFORE verification. Events never update state; ORDER.APPROVED, CAPTURE.COMPLETED/DENIED/REFUNDED, disputes ignored. No dedupe by event id. When verify signature call ERRORS, handler records event as received with "error" label instead of 5xx so PayPal retries. Security control fails open.
5. CAPTURE RESULTS NEVER VALIDATED: capture_order in both rails swallows missing capture id, returns None; main.py writes success ledger event, marks HELD, literal text "capture None". Status (COMPLETED vs DECLINED/PARTIALLY_REFUNDED), amount, currency never checked against spec. A declined or short capture books as a good hold.
6. Partial money movement unhandled: refunds always full (matches current rules) but refund status never read back (PENDING refund recorded completed). No partial capture/slash paths. Lower priority, production reviewer will ask.
7. TOKEN CACHING DEAD CODE: _access_token caches per instance, but get_agent_payment_service() builds a new AgentPaymentService/PayPalClient/ToolkitOrders on EVERY API call; webhook handler builds another. Nearly every action pays a fresh OAuth round trip. Rate limit risk at volume.
8. CURRENCY STUB: methods accept currency but every call site passes literal "USD"; _amt formats two decimals for all currencies (wrong for JPY, HUF, TWD zero decimal). Money runs on floats end to end; should be integer minor units or Decimal.
9. ERROR SURFACES LEAK, DO NOT CLASSIFY: PaymentError carries raw PayPal body, returned verbatim in 502 detail and written into user facing ledger (debug ids, field issues). No retryable (429, 5xx) vs business (422 ORDER_NOT_APPROVED, INSTRUMENT_DECLINED with documented restart flow) distinction.
10. ORDER HYGIENE: no application_context (return/cancel URLs, brand, NO_SHIPPING for digital service), no custom_id on REST orders, pay() creates price then bond order in sequence with no cleanup (bond create fail orphans price order; retry creates a second). Approved orders expire; nothing handles stale order at confirm beyond capture failure.

## Embarrassment list
- paypal_agents.py reads secret via getattr(settings, "paypal_client" + "_secret"). Split string reads as dodging secret scanning. No functional reason. FIX FIRST, cheap.
- Custody story vs ledger language: "HELD maps to delayed disbursement" overstates; funds captured into platform account. The delayed disbursement team will push on exactly this sentence.
- Success events for captures with no capture id ("capture None") undermines the audit ledger, otherwise a best feature.
- Two rails build different orders: REST puts deal reference in reference_id; toolkit stuffs reference into an item name and builds items array. Reconciliation/support inconsistency.
- Sandbox detection for toolkit context is substring test "sandbox" in base URL; a future URL without that word silently flips toolkit to live context. Mode should come from explicit config.
- Money as floats everywhere; first tell of demo payment code this audience notices.

## Fix priority (credibility per hour, per reviewer)
Deterministic idempotency keys; resumable settlement legs; payout status follow through; capture result validation; remove getattr secret access. None of the findings are fatal for a hackathon entry; real sandbox ids, honest demo mode, visible approval checkpoint, and rail recorded in ledger are already judge positives.
