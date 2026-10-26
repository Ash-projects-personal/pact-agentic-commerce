# Pact demo tour script

One take, under 3 minutes. The same captions the guided tour shows in the
live demo, in order, with the shot for each beat. The tour runs in demo
mode only. Press Play the tour in the demo UI and read along.

Scenario: logo and brand kit. Buyer max $300. Seller floor $180. The
deterministic engine settles every run the same way: price $222.17, bond
$44.43 at 20 percent, 5 checks, 330 word delivery, 5 of 5 checks passed.
Demo capture and payout ids change on every run. The ids below are from
the recorded run. Read the ones on screen when you record.

Total run time: about 2 minutes 30 seconds.

## Beat 1. Open. 0:00 to 0:10. 10 seconds.

Shot: the full demo page, cursor on Play the tour in the Guided tour card.

Caption: "Pact settles work between two AI agents. One deal, start to
finish, in under a minute."

## Beat 2. Negotiation. 0:10 to 0:35. 25 seconds.

Shot: the Deal setup card, then the negotiation thread filling in move
by move.

Caption: "Two agents open a deal. A buyer wants a logo and brand kit.
The buyer will pay up to $300. The seller will not work under $180."

Caption: "They agreed on $222.17. The bond is $44.43, 20 percent of the
price. The agents wrote 5 checks into the contract."

## Beat 3. The bond hold. 0:35 to 1:00. 25 seconds.

Shot: the payment timeline, then the audit ledger as the payment held
and bond posted rows land and light up.

Caption: "The buyer pays $222.17. The seller posts a $44.43 bond. PayPal
holds both until the work is judged."

Caption: "Money held. Payment capture DEMO-CAPTURE-5652F71838. Bond
capture DEMO-CAPTURE-535BEB6E18. Nothing moves until verification."

## Beat 4. Delivery. 1:00 to 1:20. 20 seconds.

Shot: the Deliverable card with the brand kit text.

Caption: "The seller delivers the brand kit: logo concepts, a color
palette, typography, taglines, and a short brand guide."

Caption: "Delivery in. 330 words. The verifier now reads it against the
contract, not against the seller's word."

## Beat 5. Verification. 1:20 to 1:50. 30 seconds.

Shot: the verification checklist, each check flipping to PASS with its
measured number next to its required number.

Caption: "The verifier runs the 5 checks the agents wrote. Each check
has a measured number and a required number."

Caption: "5 of 5 checks passed. 3 concepts against 3 required. 6 colors
against 5. 330 words against 260."

## Beat 6. Payout. 1:50 to 2:20. 30 seconds.

Shot: the audit ledger, the payment released and bond returned rows
highlighted, then the reputation bars.

Caption: "Done. The $222.17 price is released to the seller. The $44.43
bond goes back. Payout batch DEMO-PAYOUT-432D2929E4. Every step sits in
the ledger below."

## Beat 7. Close. 2:20 to 2:30. 10 seconds.

Shot: the reputation bars and the dispute packet download link.

Caption: "The seller's reputation rose from 82 to 88. The buyer's from
80 to 83. The whole deal fits in one evidence file."

## Notes for the recording

Numbers that stay the same on every run: price $222.17, bond $44.43,
5 checks, 330 words, 5 of 5 passed. Numbers that change with history:
reputation scores and demo ids. Record on a fresh demo database if you
want the reputation numbers in beat 7 to match this script. The tour
button stays off on the hosted sandbox demo. Record against a local run
with no PayPal credentials set, so the app runs in demo mode.
