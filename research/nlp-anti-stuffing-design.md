# NLP expert: anti stuffing design for min_words (2026-10-22)

Expert panel subagent 582a3990, completed 2026-10-22 21:25 UTC.

## Recommendation
Replace raw word count with EFFECTIVE word count:
- Tokenize by whitespace split, exactly as current min_words (no case folding, no punctuation stripping).
- Form 5-token shingles. A shingle occurring c times has c-1 duplicate instances. Mark every token position covered by a duplicate instance (first instance never marked). dup = marked positions. Effective words = W - dup. Pass iff effective words >= required value. Report raw, dup, effective in verdict reason.
- Why n=5: 2-3 token shingles repeat in honest prose/code; 8+ lets short loops through. Padded attack (~320 copies of one word after honest front): ~315 tail tokens marked, effective ~125 vs requirement 260-320, fails wide.

Rank 2 hard fail backstop: longest repeated substring share. Find longest contiguous token run occurring at least twice (suffix automaton/array, overlapping counts). share = length / W. Hard fail if share >= calibrated ceiling (starting point 0.15). Catches dilution attack (half honest, half one repeated block).

Rank 3 log only: zlib compression ratio. Diagnostic only, NOT a gate. Reasons: code honestly compresses into stuffed prose range; ratio swings with text length at delivery sizes; compressor bytes can shift across library versions, breaking reproducibility.

Rejected: distinct word floors / raw type token ratio (falls with length, punishes code; McCarthy and Jarvis 2010), MTLD/HD-D (measure vocabulary spread not duplication; salad scores diverse, code scores undiverse), unigram entropy (mixture average, honest part dominates; code low entropy), perplexity under small model (model artifact, drift, breaks reproducibility), per segment worst window (attackers interleave; honest repetitive segments exist).

## Calibration method (empirical, frozen, regression tested)
- Honest corpus: every builder output across all scenarios over settled value grid, plus human deliveries. Split by kind from the start: prose vs code bearing get separate bands.
- Attack corpus: parameterized stuffing family sized to cheapest version passing old raw count: one repeated token; one repeated sentence; rotated cycles 5/20/100 tokens; own vocabulary shuffled salad; mutated cycles changing one token every m tokens (m=5,10,20); honest interleaved with stuffed block at 25/50/75 percent.
- Margins demanded in writing before looking: worst honest delivery clears requirement by >=10% of required value in effective words (if builders fail, fix builders with wider pool, do not loosen statistic); strongest attack falls >=15% short; longest repeat ceiling set only if honest max and attack min shares are at least 3x apart, else that kind gets logged value only.
- If effective count bands overlap for a kind, statistic does not gate for that kind. Report overlap, do not ship a coin flip.
- Short text rule: below ~150 tokens, gate off, raw count stands (settled requirements run well above 150 anyway).

## Attacker ladder, honest limits
1. One repeated word: dead. 2. One repeated sentence: dead. 3. Rotated cycle small K: dead; escapes only when K approaches delivery length, at which point padding is mostly unique and attack has become writing. 4. Mutated cycle: real fight. Mutation poisons the 5 shingles containing it; at m~20 caught, at m~5 coverage collapses. Defense does not fully win; it sets attacker price: roughly every 5-token window must be novel. 5. Vocabulary salad: passes coverage, longest repeat, entropy, diversity. No surface statistic separates salad from prose. 6. Generated filler prose on topic: passes everything; out of scope for deterministic surface checks.
Boundary to state in paper: statistics raise price of padding from free to approx price of producing fresh text. Semantic emptiness is bounded by rest of system (item checks, required sections, bond), not this check.

Other failure modes: legitimately repetitive honest content (disclaimers, chorus, table labels, generated code blocks) handled by headroom + per kind bands; contract could quote length in effective words from the start. Threshold hugging: 15% shortfall demand + bands stay in test fixtures unpublished. Tokenization splitting: both measures use same whitespace split, keep consistent.

## Published practice cited
Broder 1997 shingling/containment; Lee et al ACL 2022 dedup training data (repeated substrings mark degenerate text, suffix arrays); Welleck et al ICLR 2020 (repeated n-gram ~0.5% human vs ~43% degenerate); Holtzman et al ICLR 2020 text degeneration; Bratko et al JMLR 2006 compression vs adaptive spam adversary; Jiang et al ACL 2023 gzip classification; Cebrian et al 2005 NCD pitfalls (why compression stays diagnostic); McCarthy and Jarvis 2010 MTLD validation (why diversity floors rejected).

## RECONCILIATION NOTE (Max, 2026-10-22)
Shipped screen today is different: text >=100 words fails only if BOTH zlib ratio < 0.27 AND 4-gram uniqueness < 0.50, thresholds measured (honest >=0.280 / >=0.531, attacks <=0.254 / <=0.441). All three stuffing variants currently caught at 4/5 and full regression is green; paper section 4.5 reports the shipped screen and its measured numbers.
This expert design is a candidate upgrade, arguably more principled (prices repeated filler at zero, deterministic, no compressor dependence). Do NOT swap it in without: building the two frozen corpora, running the calibration with the stated margins, re-running E1 + E5 + real cases, and updating the paper numbers. Decision belongs in the expert panel reconciliation pass.

## CALIBRATION OUTCOME (2026-10-22, item F)
The calibration this design demanded was run as experiments/effective_words_study.py, results in experiments/effective_words_study.json. Frozen honest corpus: every builder output across scenarios over the settled value grid, split prose vs code. Parameterized attack family: repeated token, repeated sentence, rotated cycles 5/20/100, vocabulary salad, mutated cycles m=5/10/20, honest interleaved with stuffed block at 25/50/75 percent, 240 attack texts total.
Result: the margins did not hold for either kind. Prose: worst honest effective 0.608x of required, strongest attack 1.52x. Code: worst honest 0.69x, strongest attack 1.21x. Longest repeat separation was far under 3x, so it stays log only. The effective words gate was REJECTED for both kinds. The shipped zlib plus 4 gram screen stays. The honest failure comes from the narrow builder padding pools, not from the statistic alone, but fixing builders is out of this item's scope, and the attack failure (mutated cycle every 5 tokens) is a documented limit of surface statistics, not a tuning problem. Paper section 4.5 records this outcome with its numbers.
