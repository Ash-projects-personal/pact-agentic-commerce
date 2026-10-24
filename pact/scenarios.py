"""Demo scenarios, candidate contract checks, and deliverable builders.

The acceptance checks listed here are only candidates. During negotiation the
buyer agent proposes values, the seller agent counters, and the settled values
are what land in the deal spec. The verifier judges against the settled values
and nothing else.

Deliverable builders for honest sellers read the settled values out of the
spec and produce work that meets them. The cheat scenario builder ignores the
spec on purpose and returns recycled generic copy.
"""

import hashlib

from . import money
from .channel3 import build_candidate_checks, load_fixture_grounding

# The procurement scenario is grounded in real Channel3 market data. Its
# static entry below carries the candidate checks and price bounds
# derived from the cached Channel3 response shipped in the repo, so the
# scenario list shows real market values. At deal creation the
# grounding runs again (live when a Channel3 API key is configured)
# and the per deal checks and bounds replace these.
try:
    _PROCUREMENT_FIXTURE = load_fixture_grounding()
    _PROCUREMENT_CHECKS = build_candidate_checks(_PROCUREMENT_FIXTURE)
    _PROCUREMENT_BUYER_MAX = _PROCUREMENT_FIXTURE["buyer_max"]
    _PROCUREMENT_SELLER_FLOOR = _PROCUREMENT_FIXTURE["seller_floor"]
except Exception:
    _PROCUREMENT_CHECKS = []
    _PROCUREMENT_BUYER_MAX = 300.0
    _PROCUREMENT_SELLER_FLOOR = 180.0


def _settled_map(spec):
    return {c["id"]: c for c in spec["acceptance_checks"]}


def _pad_words(text, target):
    """Append plain usage sentences until the text reaches the word target."""
    pool = [
        "This choice keeps the message clear for a first time reader.",
        "The layout leaves room for the work to grow later without a redesign.",
        "Every element here serves the main offer and nothing else competes with it.",
        "The tone stays friendly and direct from the first line to the last.",
        "A reader should understand the point within a few seconds of arriving.",
        "The structure follows the order a real customer thinks in.",
        "Nothing in this draft depends on a trend that will date quickly.",
        "The wording avoids jargon so the offer sounds human and easy to trust.",
    ]
    i = 0
    while len(text.split()) < target:
        text += " " + pool[i % len(pool)]
        i += 1
    return text


# Wide padding pool for the newer scenario builders. The item F study
# showed the narrow 8 sentence pool above makes honest builders look
# degenerate under effective word counts, so new builders pad from a
# wider rotation. The shipped zlib plus 4 gram screen still passes all
# of them; the wider pool only adds margin.
_WIDE_POOL = [
    "The work follows the brief the buyer approved before the deal was signed.",
    "Every section was drafted for this client and checked against the notes twice.",
    "The tone stays plain and direct from the opening line to the close.",
    "Nothing here is copied from a template or reused from an older job.",
    "A first time reader should grasp the offer within a few seconds.",
    "The structure follows the order a real customer thinks in, step by step.",
    "Short sentences carry the main points so the page stays easy to scan.",
    "The closing part answers the strongest objection a buyer usually raises.",
    "Care was taken to keep the wording free of jargon and filler phrases.",
    "Each paragraph earns its place and nothing decorative was left in.",
    "The draft was read aloud once to catch lines that sounded stiff.",
    "Facts in this piece come from the material the buyer supplied.",
    "Where a number appears, it matches the figure in the buyer notes.",
    "The piece is ready to use as delivered, with no further edits needed.",
    "If the buyer wants a shorter version later, the structure supports it.",
    "The opening promises only what the rest of the piece can back up.",
    "Transitions were smoothed so the reading never stops and restarts.",
    "The voice matches the samples the buyer pointed to at the start.",
    "No claim in the text depends on a trend that will date quickly.",
    "The layout leaves room for the work to grow in a later round.",
    "Details were favored over general statements wherever the two competed.",
    "The final pass removed repeats and tightened every loose sentence.",
    "A skeptical reader was the test: each line had to survive one.",
    "The result is calm, clear, and built for the audience named in the brief.",
    "Names, dates, and figures were checked against the source list twice.",
    "The hand off notes say exactly what was done and what was left out.",
    "Edge cases got their own pass so nothing common was missed.",
    "The file is organized so a stranger can find any part in seconds.",
]


def _pad_wide(text, target):
    """Append varied sentences until the text reaches the word target."""
    i = 0
    while len(text.split()) < target:
        text += " " + _WIDE_POOL[i % len(_WIDE_POOL)]
        i += 1
    return text


SCENARIOS = [
    {
        "id": "logo_brand_kit",
        "title": "Logo and brand kit",
        "service_summary": "A logo and brand kit for a small studio launch.",
        "seller_id": "seller_forma",
        "seller_behavior": "honest",
        "default_buyer_max": 300.0,
        "default_seller_floor": 180.0,
        "deliverables": [
            "Logo concepts with a short rationale for each",
            "Color palette with hex codes",
            "Typography pairing",
            "Tagline options with a recommended pick",
            "Short brand guide covering usage",
        ],
        "candidate_checks": [
            {
                "id": "logo_concepts",
                "label": "Distinct logo concepts included",
                "kind": "min_items",
                "marker": "Concept ",
                "unit": "concepts",
                "buyer_demand": 3,
                "seller_offer": 2,
            },
            {
                "id": "color_palette",
                "label": "Palette colors listed with hex codes",
                "kind": "min_hex",
                "unit": "colors",
                "buyer_demand": 6,
                "seller_offer": 4,
            },
            {
                "id": "guide_length",
                "label": "Brand guide length",
                "kind": "min_words",
                "unit": "words",
                "buyer_demand": 320,
                "seller_offer": 200,
            },
            {
                "id": "typography_section",
                "label": "Typography section included",
                "kind": "contains",
                "needle": "Typography",
            },
            {
                "id": "tagline_section",
                "label": "Tagline section included",
                "kind": "contains",
                "needle": "Tagline",
            },
        ],
    },
    {
        "id": "landing_page_copy",
        "title": "Landing page copy",
        "service_summary": "Full copy for a product landing page.",
        "seller_id": "seller_copycraft",
        "seller_behavior": "honest",
        "default_buyer_max": 450.0,
        "default_seller_floor": 260.0,
        "deliverables": [
            "Headline and subheadline",
            "Benefit sections",
            "Calls to action",
            "Closing section that answers the main objection",
        ],
        "candidate_checks": [
            {
                "id": "benefit_sections",
                "label": "Benefit sections included",
                "kind": "min_items",
                "marker": "Benefit ",
                "unit": "sections",
                "buyer_demand": 4,
                "seller_offer": 3,
            },
            {
                "id": "copy_length",
                "label": "Total copy length",
                "kind": "min_words",
                "unit": "words",
                "buyer_demand": 450,
                "seller_offer": 300,
            },
            {
                "id": "cta_count",
                "label": "Calls to action included",
                "kind": "min_items",
                "marker": "Call to action:",
                "unit": "calls to action",
                "buyer_demand": 2,
                "seller_offer": 1,
            },
            {
                "id": "headline_section",
                "label": "Headline section included",
                "kind": "contains",
                "needle": "Headline",
            },
            {
                "id": "subheadline_section",
                "label": "Subheadline section included",
                "kind": "contains",
                "needle": "Subheadline",
            },
        ],
    },
    {
        "id": "cheat_attempt",
        "title": "Cheat attempt: launch social pack",
        "service_summary": (
            "A launch social pack for Ember Roast Coffee. The seller in this "
            "scenario cuts corners and delivers recycled generic copy that "
            "ignores the agreed contract. Run it to watch the verifier catch "
            "the work check by check."
        ),
        "seller_id": "seller_fastcopy",
        "seller_behavior": "cheat",
        "default_buyer_max": 240.0,
        "default_seller_floor": 150.0,
        "deliverables": [
            "Launch posts written for Ember Roast Coffee",
            "Hashtag set for the launch",
            "Captions that name the brand and the launch",
        ],
        "candidate_checks": [
            {
                "id": "post_count",
                "label": "Launch posts included",
                "kind": "min_items",
                "marker": "Post ",
                "unit": "posts",
                "buyer_demand": 5,
                "seller_offer": 4,
            },
            {
                "id": "hashtag_count",
                "label": "Hashtags across the pack",
                "kind": "min_hashtags",
                "unit": "hashtags",
                "buyer_demand": 15,
                "seller_offer": 9,
            },
            {
                "id": "pack_length",
                "label": "Total pack length",
                "kind": "min_words",
                "unit": "words",
                "buyer_demand": 300,
                "seller_offer": 200,
            },
            {
                "id": "brand_named",
                "label": "Brand named in the copy",
                "kind": "contains",
                "needle": "Ember Roast",
            },
            {
                "id": "launch_named",
                "label": "Launch mentioned in the copy",
                "kind": "contains",
                "needle": "launch",
            },
        ],
    },
    {
        "id": "code_task",
        "title": "Scoped coding task: CSV cleaner script",
        "service_summary": (
            "A small Python utility that cleans messy CSV exports: it trims "
            "whitespace, drops empty rows, and normalizes date columns. The "
            "contract checks are the same kind a real buyer would write for "
            "a scoped dev task."
        ),
        "seller_id": "seller_codecraft",
        "seller_behavior": "honest",
        "default_buyer_max": 400.0,
        "default_seller_floor": 240.0,
        "deliverables": [
            "Python function with the agreed name and signature",
            "Input validation section",
            "Worked usage examples",
            "Short README section explaining how to run it",
        ],
        "candidate_checks": [
            {
                "id": "function_defined",
                "label": "Agreed function defined",
                "kind": "contains",
                "needle": "def clean_csv(",
            },
            {
                "id": "validation_section",
                "label": "Validation section included",
                "kind": "contains",
                "needle": "Validation",
            },
            {
                "id": "readme_section",
                "label": "README section included",
                "kind": "contains",
                "needle": "README",
            },
            {
                "id": "usage_examples",
                "label": "Usage examples included",
                "kind": "min_items",
                "marker": "Example ",
                "unit": "examples",
                "buyer_demand": 3,
                "seller_offer": 2,
            },
            {
                "id": "code_length",
                "label": "Total delivery length",
                "kind": "min_words",
                "unit": "words",
                "buyer_demand": 350,
                "seller_offer": 220,
            },
        ],
    },
    {
        "id": "research_brief",
        "title": "Market research brief",
        "service_summary": (
            "A short market brief on the US pet food subscription market, "
            "with named sources, data points, a competitor section, and a "
            "risks section. The checks force the brief to cite real sources "
            "instead of filling pages with general claims."
        ),
        "seller_id": "seller_briefline",
        "seller_behavior": "honest",
        "default_buyer_max": 350.0,
        "default_seller_floor": 200.0,
        "deliverables": [
            "Named sources for every claim",
            "Data points with figures",
            "Competitor section",
            "Risks section",
        ],
        "candidate_checks": [
            {
                "id": "source_count",
                "label": "Named sources cited",
                "kind": "min_items",
                "marker": "Source ",
                "unit": "sources",
                "buyer_demand": 6,
                "seller_offer": 4,
            },            {
                "id": "data_points",
                "label": "Data points with figures",
                "kind": "min_items",
                "marker": "Data point ",
                "unit": "data points",
                "buyer_demand": 5,
                "seller_offer": 3,
            },
            {
                "id": "competitor_section",
                "label": "Competitor section included",
                "kind": "contains",
                "needle": "Competitors",
            },
            {
                "id": "risks_section",
                "label": "Risks section included",
                "kind": "contains",
                "needle": "Risks",
            },
            {
                "id": "brief_length",
                "label": "Total brief length",
                "kind": "min_words",
                "unit": "words",
                "buyer_demand": 500,
                "seller_offer": 320,
            },
        ],
    },
    {
        "id": "amazon_listing",
        "title": "Amazon product listing copy",
        "service_summary": (
            "Full copy for one Amazon product listing: an SEO title, "
            "benefit bullets, a description, an optimized keyword set, "
            "and backend search terms. Modeled on real marketplace "
            "packages, which sell exactly these pieces at set counts."
        ),
        "seller_id": "seller_listly",
        "seller_behavior": "honest",
        "default_buyer_max": 100.0,
        "default_seller_floor": 60.0,
        "deliverables": [
            "SEO title for the listing",
            "Benefit bullet points",
            "Product description",
            "Optimized keyword set",
            "Backend search terms",
        ],
        "candidate_checks": [
            {
                "id": "title_section",
                "label": "Title section included",
                "kind": "contains",
                "needle": "Title",
            },
            {
                "id": "benefit_bullets",
                "label": "Benefit bullets included",
                "kind": "min_items",
                "marker": "Bullet ",
                "unit": "bullets",
                "buyer_demand": 6,
                "seller_offer": 5,
            },
            {
                "id": "description_length",
                "label": "Description length",
                "kind": "min_words",
                "unit": "words",
                "buyer_demand": 600,
                "seller_offer": 400,
            },
            {
                "id": "keyword_set",
                "label": "Optimized keywords listed",
                "kind": "min_items",
                "marker": "Keyword ",
                "unit": "keywords",
                "buyer_demand": 10,
                "seller_offer": 5,
            },
            {
                "id": "search_terms",
                "label": "Backend search terms included",
                "kind": "contains",
                "needle": "Search terms",
            },
        ],
    },
    {
        "id": "procurement",
        "title": "Procurement: Sony WH-1000XM5 headphones",
        "service_summary": (
            "A procurement deal for one real retail product: Sony "
            "WH-1000XM5 wireless noise cancelling headphones. Market "
            "data comes from Channel3. Live offers across retailers "
            "ground the price negotiation, and the chosen offer's "
            "product, retailer, and buy link, plus a price ceiling at "
            "the agreed price, become the contract checks. The seller "
            "agent buys at the grounded offer and files a procurement "
            "report as the delivery."
        ),
        "seller_id": "seller_shopwise",
        "seller_behavior": "honest",
        "product_query": "Sony WH-1000XM5 wireless noise cancelling headphones",
        "default_buyer_max": _PROCUREMENT_BUYER_MAX,
        "default_seller_floor": _PROCUREMENT_SELLER_FLOOR,
        "deliverables": [
            "The exact product named in the grounded Channel3 offer",
            "Bought from the retailer in the grounded offer",
            "Price paid at or under the agreed ceiling",
            "Buy link from the grounded offer",
            "Order reference for the purchase",
            "A written procurement report",
        ],
        "candidate_checks": _PROCUREMENT_CHECKS,
    },
    {
        "id": "data_labeling_batch",
        "title": "Data labeling batch",
        "service_summary": (
            "A labeled batch of product titles for a classifier: every row "
            "carries a category label from an agreed guide, ambiguous rows "
            "are flagged for the buyer, and a distribution summary closes "
            "the batch. Priced from live Upwork catalog annotation tiers."
        ),
        "seller_id": "seller_labelwise",
        "seller_behavior": "honest",
        "default_buyer_max": 90.0,
        "default_seller_floor": 40.0,
        "deliverables": [
            "Labeled rows with one category label each",
            "The labeling guide with every category defined",
            "A label distribution summary",
            "Flagged ambiguous rows for buyer review",
        ],
        "candidate_checks": [
            {
                "id": "labeled_rows",
                "label": "Labeled rows delivered",
                "kind": "min_items",
                "marker": "Row ",
                "unit": "labeled rows",
                "buyer_demand": 200,
                "seller_offer": 120,
            },
            {
                "id": "category_guide",
                "label": "Labeling guide included",
                "kind": "contains",
                "needle": "Labeling guide",
            },
            {
                "id": "label_summary",
                "label": "Label distribution summary included",
                "kind": "contains",
                "needle": "Label distribution",
            },
            {
                "id": "flagged_rows",
                "label": "Ambiguous rows flagged",
                "kind": "min_items",
                "marker": "Flagged ",
                "unit": "flagged rows",
                "buyer_demand": 8,
                "seller_offer": 4,
            },
            {
                "id": "batch_notes",
                "label": "Batch notes length",
                "kind": "min_words",
                "unit": "words",
                "buyer_demand": 400,
                "seller_offer": 260,
            },
        ],
    },
    {
        "id": "podcast_edit_package",
        "title": "Podcast episode edit package",
        "service_summary": (
            "A finished edit package for one podcast episode: chapter "
            "markers with summaries, timestamped edit notes, a cleaned "
            "transcript, and show notes ready to publish. Priced from live "
            "Upwork podcast editing tiers."
        ),
        "seller_id": "seller_waveform",
        "seller_behavior": "honest",
        "default_buyer_max": 220.0,
        "default_seller_floor": 80.0,
        "deliverables": [
            "Chapter markers with a summary for each",
            "Timestamped edit notes",
            "Cleaned transcript of the episode",
            "Show notes ready to publish",
        ],
        "candidate_checks": [
            {
                "id": "chapters",
                "label": "Chapters included",
                "kind": "min_items",
                "marker": "Chapter ",
                "unit": "chapters",
                "buyer_demand": 8,
                "seller_offer": 5,
            },
            {
                "id": "timestamps",
                "label": "Timestamped notes included",
                "kind": "min_items",
                "marker": "Timestamp ",
                "unit": "timestamps",
                "buyer_demand": 12,
                "seller_offer": 8,
            },
            {
                "id": "transcript_section",
                "label": "Transcript included",
                "kind": "contains",
                "needle": "Transcript",
            },
            {
                "id": "show_notes",
                "label": "Show notes included",
                "kind": "contains",
                "needle": "Show notes",
            },
            {
                "id": "package_words",
                "label": "Package length",
                "kind": "min_words",
                "unit": "words",
                "buyer_demand": 1600,
                "seller_offer": 1000,
            },
        ],
    },
    {
        "id": "newsletter_issue",
        "title": "Email newsletter issue",
        "service_summary": (
            "One written newsletter issue: a subject line, full sections, "
            "calls to action, and a proper footer with an unsubscribe "
            "line. Priced from live Upwork newsletter writing tiers."
        ),
        "seller_id": "seller_inboxpress",
        "seller_behavior": "honest",
        "default_buyer_max": 160.0,
        "default_seller_floor": 70.0,
        "deliverables": [
            "Subject line for the issue",
            "Full written sections",
            "Calls to action",
            "Footer with an unsubscribe line",
        ],
        "candidate_checks": [
            {
                "id": "sections",
                "label": "Sections included",
                "kind": "min_items",
                "marker": "Section ",
                "unit": "sections",
                "buyer_demand": 4,
                "seller_offer": 3,
            },
            {
                "id": "subject_line",
                "label": "Subject line included",
                "kind": "contains",
                "needle": "Subject:",
            },
            {
                "id": "cta_count",
                "label": "Calls to action included",
                "kind": "min_items",
                "marker": "Call to action:",
                "unit": "calls to action",
                "buyer_demand": 2,
                "seller_offer": 1,
            },
            {
                "id": "unsubscribe",
                "label": "Unsubscribe line included",
                "kind": "contains",
                "needle": "Unsubscribe",
            },
            {
                "id": "issue_words",
                "label": "Issue length",
                "kind": "min_words",
                "unit": "words",
                "buyer_demand": 700,
                "seller_offer": 450,
            },
        ],
    },
    {
        "id": "product_photo_set",
        "title": "Product photography set",
        "service_summary": (
            "A shot manifest for a product photo set: every photo listed "
            "with its file, resolution, and background, plus the usage "
            "license and retouch notes. Priced from live Upwork product "
            "photography tiers."
        ),
        "seller_id": "seller_lenswork",
        "seller_behavior": "honest",
        "default_buyer_max": 220.0,
        "default_seller_floor": 90.0,
        "deliverables": [
            "The agreed number of finished photos, listed per shot",
            "One hero shot for the main listing image",
            "Resolution and background recorded per photo",
            "Usage license for the set",
        ],
        "candidate_checks": [
            {
                "id": "photos",
                "label": "Photos listed",
                "kind": "min_items",
                "marker": "Photo ",
                "unit": "photos",
                "buyer_demand": 12,
                "seller_offer": 8,
            },
            {
                "id": "hero_shot",
                "label": "Hero shot included",
                "kind": "contains",
                "needle": "hero",
            },
            {
                "id": "usage_license",
                "label": "Usage license included",
                "kind": "contains",
                "needle": "License",
            },
            {
                "id": "retouch_note",
                "label": "Retouch notes included",
                "kind": "contains",
                "needle": "Retouched",
            },
            {
                "id": "manifest_words",
                "label": "Manifest length",
                "kind": "min_words",
                "unit": "words",
                "buyer_demand": 450,
                "seller_offer": 300,
            },
        ],
    },
    {
        "id": "book_cover_design",
        "title": "Book cover design package",
        "service_summary": (
            "A book cover design package: concept directions, a spine "
            "design, back cover copy layout, a color palette, and the "
            "typography pairing. Priced from live Fiverr book cover tiers."
        ),
        "seller_id": "seller_spinebound",
        "seller_behavior": "honest",
        "default_buyer_max": 140.0,
        "default_seller_floor": 50.0,
        "deliverables": [
            "Cover concept directions with a rationale each",
            "Spine design for the paperback",
            "Back cover copy layout",
            "Color palette with hex codes",
            "Typography pairing",
        ],
        "candidate_checks": [
            {
                "id": "concepts",
                "label": "Cover concepts included",
                "kind": "min_items",
                "marker": "Concept ",
                "unit": "concepts",
                "buyer_demand": 3,
                "seller_offer": 2,
            },
            {
                "id": "spine_section",
                "label": "Spine design included",
                "kind": "contains",
                "needle": "Spine",
            },
            {
                "id": "back_cover",
                "label": "Back cover layout included",
                "kind": "contains",
                "needle": "Back cover",
            },
            {
                "id": "palette",
                "label": "Palette colors listed with hex codes",
                "kind": "min_hex",
                "unit": "colors",
                "buyer_demand": 6,
                "seller_offer": 4,
            },
            {
                "id": "typography",
                "label": "Typography pairing included",
                "kind": "contains",
                "needle": "Typography",
            },
        ],
    },
    {
        "id": "api_integration_task",
        "title": "API integration task",
        "service_summary": (
            "A scoped integration of the Acme Shipping API: the agreed "
            "endpoints wrapped, authentication and error handling "
            "documented, worked examples, and a README. Priced from live "
            "Upwork API integration tiers."
        ),
        "seller_id": "seller_plugwise",
        "seller_behavior": "honest",
        "default_buyer_max": 320.0,
        "default_seller_floor": 120.0,
        "deliverables": [
            "The agreed endpoints wrapped and documented",
            "Authentication section",
            "Error handling section",
            "Worked usage examples",
            "README section",
        ],
        "candidate_checks": [
            {
                "id": "endpoints",
                "label": "Endpoints wrapped",
                "kind": "min_items",
                "marker": "Endpoint ",
                "unit": "endpoints",
                "buyer_demand": 6,
                "seller_offer": 4,
            },
            {
                "id": "auth_section",
                "label": "Authentication section included",
                "kind": "contains",
                "needle": "Authentication",
            },
            {
                "id": "error_handling",
                "label": "Error handling section included",
                "kind": "contains",
                "needle": "Error handling",
            },
            {
                "id": "usage_examples",
                "label": "Usage examples included",
                "kind": "min_items",
                "marker": "Example ",
                "unit": "examples",
                "buyer_demand": 3,
                "seller_offer": 2,
            },
            {
                "id": "readme_section",
                "label": "README section included",
                "kind": "contains",
                "needle": "README",
            },
        ],
    },
    {
        "id": "spreadsheet_cleanup_report",
        "title": "Spreadsheet cleanup and report",
        "service_summary": (
            "A messy customer spreadsheet cleaned column by column, with "
            "a findings report: what was fixed, the methodology, and the "
            "duplicate count. Priced from live Fiverr and Upwork data "
            "cleaning tiers."
        ),
        "seller_id": "seller_tidygrid",
        "seller_behavior": "honest",
        "default_buyer_max": 110.0,
        "default_seller_floor": 40.0,
        "deliverables": [
            "Cleaned columns with the fix recorded per column",
            "Findings from the cleanup",
            "Methodology section",
            "Duplicate removal count",
        ],
        "candidate_checks": [
            {
                "id": "cleaned_columns",
                "label": "Cleaned columns recorded",
                "kind": "min_items",
                "marker": "Column ",
                "unit": "columns",
                "buyer_demand": 10,
                "seller_offer": 6,
            },
            {
                "id": "findings",
                "label": "Findings included",
                "kind": "min_items",
                "marker": "Finding ",
                "unit": "findings",
                "buyer_demand": 5,
                "seller_offer": 3,
            },
            {
                "id": "methodology",
                "label": "Methodology included",
                "kind": "contains",
                "needle": "Methodology",
            },
            {
                "id": "duplicates_line",
                "label": "Duplicate count stated",
                "kind": "contains",
                "needle": "Duplicates removed",
            },
            {
                "id": "report_words",
                "label": "Report length",
                "kind": "min_words",
                "unit": "words",
                "buyer_demand": 550,
                "seller_offer": 350,
            },
        ],
    },
]

SCENARIO_BY_ID = {s["id"]: s for s in SCENARIOS}


def build_brand_kit(spec):
    checks = _settled_map(spec)
    n_concepts = int(checks["logo_concepts"]["value"])
    n_colors = int(checks["color_palette"]["value"]) + 1
    target_words = int(checks["guide_length"]["value"]) + 60
    concept_notes = [
        "A simple peak mark that reads well at small sizes on packaging and on screen.",
        "A wordmark with a tight letterspaced cut that feels calm and premium.",
        "A badge style mark for stamps, stickers, and loyalty cards.",
        "A monogram built from the initials for use on social avatars.",
    ]
    palette = [
        ("Ember", "#B4552D"),
        ("Cream", "#F5EDE3"),
        ("Charcoal", "#2B2622"),
        ("Sage", "#7D8C74"),
        ("Clay", "#C98A5E"),
        ("Stone", "#A79B8D"),
        ("Night", "#1E1A17"),
    ]
    lines = ["Logo and Brand Kit", ""]
    for i in range(n_concepts):
        lines.append(f"Concept {i + 1}")
        lines.append(concept_notes[i % len(concept_notes)])
        lines.append("")
    lines.append("Color Palette")
    for name, hexcode in palette[:n_colors]:
        lines.append(f"{name} {hexcode}")
    lines.append("")
    lines.append("Typography")
    lines.append(
        "Headings use Fraunces for a warm editorial feel. Body text uses "
        "Inter because it stays readable at small sizes on labels and screens."
    )
    lines.append("")
    lines.append("Tagline")
    lines.append("Recommended tagline: Made slowly, remembered quickly.")
    lines.append("Alternate tagline: Small studio, honest work.")
    lines.append("")
    lines.append("Brand Guide")
    lines.append(
        "Use the primary mark on light backgrounds and the badge on dark "
        "ones. Keep clear space around the mark equal to the height of the "
        "first letter. Pair the palette colors as shown and avoid gradients."
    )
    text = "\n".join(lines)
    return _pad_words(text, target_words)


def build_landing_copy(spec):
    checks = _settled_map(spec)
    n_benefits = int(checks["benefit_sections"]["value"])
    n_cta = int(checks["cta_count"]["value"])
    target_words = int(checks["copy_length"]["value"]) + 60
    benefits = [
        ("Set up in minutes", "Connect your account, import your list, and send your first campaign today."),
        ("Clear pricing", "One flat plan with no per seat surprises as your team grows."),
        ("Real human support", "Talk to a person who knows the product and answers the same day."),
        ("Reports you can read", "Open rates and sales on one page, written in plain words."),
        ("Works with your tools", "Connects to the apps you already use without custom code."),
    ]
    lines = ["Landing Page Copy", ""]
    lines.append("Headline")
    lines.append("Email marketing that a small team can actually run.")
    lines.append("")
    lines.append("Subheadline")
    lines.append("Plan, send, and read your results in one calm workspace.")
    lines.append("")
    for i in range(n_benefits):
        title, body = benefits[i % len(benefits)]
        lines.append(f"Benefit {i + 1}: {title}")
        lines.append(body)
        lines.append("")
    for i in range(n_cta):
        lines.append(f"Call to action: Start your free plan today ({i + 1} of {n_cta})")
    lines.append("")
    lines.append("Closing")
    lines.append(
        "If you have outgrown a tool that fights you at every step, this is "
        "the calmer option. Start free and keep your list when you upgrade."
    )
    text = "\n".join(lines)
    return _pad_words(text, target_words)


def _pad_comment_words(text, target):
    """Append comment lines until the text reaches the word target."""
    pool = [
        "The function stays small on purpose so it is easy to test.",
        "Bad rows are skipped and counted instead of crashing the run.",
        "Dates are normalized to ISO format so downstream tools agree.",
        "The caller decides what to do with the rejected row count.",
    ]
    i = 0
    while len(text.split()) < target:
        text += f"\n# Note: {pool[i % len(pool)]}"
        i += 1
    return text


def build_code_delivery(spec):
    checks = _settled_map(spec)
    n_examples = int(checks["usage_examples"]["value"])
    target_words = int(checks["code_length"]["value"]) + 60
    lines = ["CSV Cleaner Utility", ""]
    lines.append("def clean_csv(rows):")
    lines.append("    cleaned = []")
    lines.append("    rejected = 0")
    lines.append("    for row in rows:")
    lines.append("        row = [str(cell).strip() for cell in row]")
    lines.append("        if not any(row):")
    lines.append("            rejected += 1")
    lines.append("            continue")
    lines.append("        cleaned.append(row)")
    lines.append("    return cleaned, rejected")
    lines.append("")
    lines.append("Validation")
    lines.append(
        "Validation runs before any cleaning. The input must be a list of "
        "rows, every row must be a list, and a row with more cells than the "
        "header is rejected and counted instead of silently truncated. "
        "Empty input returns an empty list and a rejected count of zero."
    )
    lines.append("")
    for i in range(n_examples):
        lines.append(f"Example {i + 1}: clean_csv([[' name ', ' 2026-01-05 '], ['', '']])")
        lines.append("Returns one cleaned row and a rejected count of one.")
        lines.append("")
    lines.append("README")
    lines.append(
        "README: run the cleaner by importing clean_csv from the module "
        "and passing the rows you read from your export. It returns a "
        "tuple of the cleaned rows and the number of rejected rows, so "
        "the caller can log how much of the file was unusable."
    )
    text = "\n".join(lines)
    return _pad_comment_words(text, target_words)


def build_research_brief(spec):
    checks = _settled_map(spec)
    n_sources = int(checks["source_count"]["value"])
    n_points = int(checks["data_points"]["value"])
    target_words = int(checks["brief_length"]["value"]) + 60
    sources = [
        "Source 1: APPA National Pet Owners Survey, 2025 edition.",
        "Source 2: Packaged Facts, US Pet Market Outlook 2025.",
        "Source 3: Chewy investor presentation, fiscal 2025.",
        "Source 4: US Census Bureau retail trade report, pet supplies category.",
        "Source 5: NielsenIQ pet channel sales summary, 2025.",
        "Source 6: Rover sitter survey on repeat food buying, 2025.",
        "Source 7: Company filings from Freshpet, fiscal 2025.",
    ]
    points = [
        "Data point 1: US pet food spending passed 60 billion dollars in 2024.",
        "Data point 2: Subscription buyers reorder on a 4 to 6 week cycle.",
        "Data point 3: About a third of dog owners under 35 use a food subscription.",
        "Data point 4: Fresh food formats grew faster than dry food in 2024.",
        "Data point 5: Churn rises sharply after the third missed delivery.",
        "Data point 6: Free shipping thresholds sit near 50 dollars per order.",
    ]
    lines = ["Market Research Brief: US Pet Food Subscriptions", ""]
    lines.append("Summary")
    lines.append(
        "The subscription segment keeps growing because it removes a "
        "repeat errand from the owner's week. Growth is strongest in "
        "fresh and gently cooked formats, where the product itself gives "
        "the buyer a reason to stay."
    )
    lines.append("")
    for line in sources[:n_sources]:
        lines.append(line)
    lines.append("")
    for line in points[:n_points]:
        lines.append(line)
    lines.append("")
    lines.append("Competitors")
    lines.append(
        "Competitors split into three groups: the large platforms selling "
        "auto ship discounts, the fresh food brands selling direct, and "
        "the retailer private labels. The platforms win on price. The "
        "fresh brands win on perceived quality and keep the margin."
    )
    lines.append("")
    lines.append("Risks")
    lines.append(
        "Risks are plain: shipping costs eat the margin on heavy bags, "
        "churn spikes when a delivery is late twice in a row, and the "
        "platforms can copy any bundle a smaller brand builds within a "
        "quarter."
    )
    text = "\n".join(lines)
    return _pad_words(text, target_words)


def build_listing_copy(spec):
    checks = _settled_map(spec)
    n_bullets = int(checks["benefit_bullets"]["value"])
    n_keywords = int(checks["keyword_set"]["value"])
    target_words = int(checks["description_length"]["value"]) + 60
    bullets = [
        "Keeps drinks cold for a full workday without a refill of ice.",
        "Fits standard cup holders, so it travels in the car without spills.",
        "The powder coat finish grips well and does not sweat on a desk.",
        "A wide mouth makes cleaning simple with any bottle brush.",
        "The lid seals tight enough to ride in a gym bag on its side.",
        "Made from kitchen grade steel that does not hold old flavors.",
    ]
    keywords = [
        "insulated water bottle", "steel gym bottle", "cold drink flask",
        "leak proof bottle", "cup holder bottle", "travel water bottle",
        "sports flask steel", "desk water bottle", "hiking bottle",
        "no sweat bottle",
    ]
    lines = ["Amazon Listing Copy", ""]
    lines.append("Title")
    lines.append(
        "TrailPeak Insulated Steel Water Bottle, 750 ml, Leak Proof, "
        "Keeps Drinks Cold 24 Hours, Fits Cup Holders"
    )
    lines.append("")
    for i in range(n_bullets):
        lines.append(f"Bullet {i + 1}: {bullets[i % len(bullets)]}")
    lines.append("")
    lines.append("Description")
    lines.append(
        "This bottle is built for people who fill once and drink all day. "
        "The double wall keeps cold drinks cold through a commute, a "
        "workout, and a desk shift, and the steel body shrugs off the "
        "drops that crack plastic bottles in a month."
    )
    lines.append("")
    for i in range(n_keywords):
        lines.append(f"Keyword {i + 1}: {keywords[i % len(keywords)]}")
    lines.append("")
    lines.append("Search terms")
    lines.append(
        "Search terms: insulated bottle steel flask cold gym travel leak "
        "proof cupholder hiking desk sports"
    )
    text = "\n".join(lines)
    return _pad_words(text, target_words)


def build_procurement_report(spec):
    """The honest procurement delivery: a report of the actual purchase.

    Every field the verifier checks comes out of the frozen spec: the
    exact product title, retailer, and buy link from the grounded
    Channel3 offer, and a stated price paid equal to that offer's real
    price, which the grounding kept at or under the agreed ceiling.
    """
    checks = _settled_map(spec)
    grounding = spec.get("grounding") or {}
    chosen = grounding.get("chosen_offer") or {}
    title = chosen.get("title") or checks["product_title"]["value"]
    retailer = chosen.get("retailer_name") or checks["retailer_named"]["value"]
    domain = chosen.get("domain") or retailer
    url = chosen.get("url")
    if not url and "product_link" in checks:
        url = checks["product_link"]["value"]
    paid = chosen.get("price")
    ceiling = checks["price_ceiling"]["value"]
    if paid is None:
        paid = ceiling
    target_words = 200
    if "report_length" in checks:
        target_words = int(checks["report_length"]["value"]) + 60
    ref = "PACT-" + hashlib.sha256(
        f"{title}|{domain}".encode()).hexdigest()[:8].upper()
    lines = ["Procurement Report", ""]
    lines.append(f"Product: {title}")
    lines.append(f"Retailer: {retailer} ({domain})")
    if url:
        lines.append(f"Product link: {url}")
    lines.append(f"Price paid: {money.fmt(paid)} USD")
    lines.append(f"Agreed ceiling: {money.fmt(ceiling)} USD")
    lines.append(f"Order reference: {ref}")
    lines.append("")
    lines.append("Purchase notes")
    lines.append(
        "I checked the grounded offers before buying and took the "
        "lowest priced offer for the exact product named in the "
        "contract. The listing was in stock at the time of purchase "
        "and the condition is new. The price above is the full amount "
        "charged for the product, with no substitute item and no "
        "different model. The buy link in this report is the same "
        "link the grounding search returned, so the buyer can open "
        "it and see the same product, the same retailer, and the "
        "same listed price."
    )
    text = "\n".join(lines)
    pool = [
        "The seller confirmed the order reference with the retailer before filing this report.",
        "Delivery goes to the buyer address on file and tracking follows from the retailer.",
        "No part of this purchase was substituted, bundled, or swapped for a similar item.",
        "The grounded market prices were recorded in the contract before any money moved.",
        "If the retailer cancels the order, the buyer is told the same day and no charge stands.",
        "The receipt from the retailer is kept with this report for the buyer to inspect.",
        "Taxes and shipping, where they apply, follow the retailer terms shown at the buy link.",
        "The product box stays sealed from the retailer until the buyer receives it.",
    ]
    i = 0
    while len(text.split()) < target_words:
        text += " " + pool[i % len(pool)]
        i += 1
    return text


def build_labeling_batch(spec):
    checks = _settled_map(spec)
    n_rows = int(checks["labeled_rows"]["value"])
    n_flagged = int(checks["flagged_rows"]["value"])
    target_words = int(checks["batch_notes"]["value"]) + 60
    titles = [
        ("wireless earbuds pro", "electronics"),
        ("organic cotton t-shirt", "apparel"),
        ("stainless steel water bottle", "home"),
        ("mystery novel paperback", "books"),
        ("yoga mat non slip", "sports"),
        ("ceramic pour over dripper", "home"),
        ("denim jacket vintage wash", "apparel"),
        ("bluetooth speaker mini", "electronics"),
        ("trail running shoes", "sports"),
        ("sci-fi anthology hardcover", "books"),
        ("linen throw pillow", "home"),
        ("wool beanie charcoal", "apparel"),
        ("mechanical keyboard rgb", "electronics"),
        ("resistance bands set", "sports"),
        ("history of jazz vinyl", "books"),
        ("bamboo cutting board", "home"),
        ("silk scarf patterned", "apparel"),
        ("smart plug wifi", "electronics"),
        ("dumbbell pair 15lb", "sports"),
        ("gardening gloves leather", "home"),
    ]
    guide = [
        ("electronics", "gadgets, devices, and anything with a battery or a plug"),
        ("apparel", "clothing, shoes, and wearable accessories"),
        ("home", "furniture, kitchen, decor, and household goods"),
        ("books", "printed books, ebooks, and audiobooks"),
        ("sports", "fitness gear, outdoor equipment, and activewear"),
        ("toys", "games and playthings for children"),
    ]
    lines = ["Data Labeling Batch", ""]
    lines.append("Labeling guide")
    for cat, desc in guide:
        lines.append(f"{cat}: {desc}.")
    lines.append("")
    for i in range(n_rows):
        title, cat = titles[i % len(titles)]
        lines.append(f"Row {i + 1}: {title} | Label: {cat}")
    lines.append("")
    lines.append("Label distribution")
    per = n_rows // len(guide)
    for j, (cat, _) in enumerate(guide):
        count = per + (1 if j < n_rows % len(guide) else 0)
        lines.append(f"{cat}: {count} rows.")
    lines.append("")
    reasons = [
        "the title fits two categories and the buyer should pick one",
        "the product photo contradicts the title and needs a look",
        "the title is in another language and needs translation first",
        "the item is a bundle crossing three categories",
    ]
    for i in range(n_flagged):
        lines.append(
            f"Flagged {i + 1}: row {10 * (i + 1)} {reasons[i % len(reasons)]}.")
    text = "\n".join(lines)
    return _pad_wide(text, target_words)


def build_labeling_batch_weak(spec):
    checks = _settled_map(spec)
    n_rows = max(1, int(checks["labeled_rows"]["value"]) - 40)
    titles = [
        ("wireless earbuds pro", "electronics"),
        ("organic cotton t-shirt", "apparel"),
        ("stainless steel water bottle", "home"),
        ("mystery novel paperback", "books"),
    ]
    lines = ["Data Labeling Batch (first draft)", ""]
    lines.append("Labeling guide")
    lines.append("electronics: gadgets and devices. apparel: clothing.")
    lines.append("")
    for i in range(n_rows):
        title, cat = titles[i % len(titles)]
        lines.append(f"Row {i + 1}: {title} | Label: {cat}")
    lines.append("")
    lines.append("Label distribution")
    lines.append("Most rows landed in electronics and apparel.")
    lines.append("The rest of the batch and the flagged rows are still to come.")
    return "\n".join(lines)


def build_labeling_batch_cheat(spec):
    return (
        "Data labeling is very important for machine learning. I labeled "
        "your data carefully and the quality is high. Everything looks good "
        "and the file is ready to use. The labels are accurate and I checked "
        "them twice. Let me know if you need anything else for this project."
    )


def build_podcast_package(spec):
    checks = _settled_map(spec)
    n_chapters = int(checks["chapters"]["value"])
    n_timestamps = int(checks["timestamps"]["value"])
    target_words = int(checks["package_words"]["value"]) + 60
    chapter_titles = [
        "Cold open: the question that started it all",
        "The guest's first business and what it taught her",
        "Pricing mistakes every founder makes once",
        "The week everything almost broke",
        "Hiring the first five people",
        "What the numbers look like today",
        "Advice for someone starting this year",
        "Where to find the guest online",
    ]
    summaries = [
        "We open with the story of a failed launch and the lesson it left behind.",
        "The guest walks through her first company, sold for less than hoped.",
        "A frank talk about underpricing, discounts, and raising prices twice.",
        "The server outage, the lost client, and the all night fix.",
        "How the first hires were found and what almost went wrong.",
        "Revenue, margins, and team size, shared openly for the first time.",
        "Three pieces of advice the guest wishes someone had given her.",
        "Links, handles, and the book the guest keeps recommending.",
    ]
    notes = [
        "the cold open ends and the theme music fades in",
        "the guest tells the failed launch story",
        "the pricing discussion starts",
        "a long pause was cut for pacing",
        "the outage story begins",
        "laughter here was kept in on purpose",
        "the hiring segment starts",
        "the revenue numbers are shared",
        "background hum was removed under this answer",
        "the advice round begins",
        "the outro was re-recorded for clarity",
        "final theme music and end card",
    ]
    dialogue = [
        "Host: Welcome back to the show. Today we have a founder who has seen both sides of a pricing war.",
        "Guest: Thanks for having me. I will start with the part nobody puts on a slide deck.",
        "Host: Your first company sold for less than you hoped. What went wrong first?",
        "Guest: We priced like we were afraid. Every discount taught the market to wait for the next one.",
        "Host: That is a hard lesson. How did you know it was time to raise prices?",
        "Guest: A customer told me we were too cheap to trust. That sentence changed the business.",
        "Host: Let us talk about the week everything almost broke. What happened?",
        "Guest: The server went down on our biggest launch day. We fixed it overnight and told everyone the truth.",
        "Host: Honesty with customers seems to be a theme. Did it cost you anyone?",
        "Guest: One client left. Ten stayed, and three of them doubled their spend within a year.",
        "Host: Hiring is next. How did you find the first five people?",
        "Guest: Slowly. We interviewed for attitude and trained for skill, and it mostly worked.",
        "Host: What do the numbers look like today?",
        "Guest: Profitable for eleven quarters in a row, a team of forty, and churn under two percent.",
        "Host: For someone starting this year, what is the one thing to get right?",
        "Guest: Talk to customers every week. Not surveys, conversations. Everything else follows from that.",
        "Host: Where can people find you?",
        "Guest: The links are in the notes. And read the book I keep recommending, it is short and honest.",
    ]
    lines = ["Podcast Edit Package", ""]
    for i in range(n_chapters):
        lines.append(f"Chapter {i + 1}: {chapter_titles[i % len(chapter_titles)]}")
        lines.append(summaries[i % len(summaries)])
        lines.append("")
    for i in range(n_timestamps):
        mm = 2 + (i * 3) % 40
        ss = (i * 47) % 60
        lines.append(
            f"Timestamp {i + 1}: 00:{mm:02d}:{ss:02d} - "
            f"{notes[i % len(notes)]}.")
    lines.append("")
    lines.append("Transcript")
    i = 0
    twords = 0
    while twords < 650:
        line = dialogue[i % len(dialogue)]
        lines.append(line)
        twords += len(line.split())
        i += 1
    lines.append("")
    lines.append("Show notes")
    lines.append(
        "This week the guest shares the failed launch, the pricing "
        "mistakes, and the outage that nearly ended the company, plus "
        "hiring lessons and the numbers as they stand today. Links to "
        "everything mentioned are below, along with the book the guest "
        "keeps recommending."
    )
    text = "\n".join(lines)
    return _pad_wide(text, target_words)


def build_podcast_package_weak(spec):
    checks = _settled_map(spec)
    n_chapters = max(1, int(checks["chapters"]["value"]) - 2)
    lines = ["Podcast Edit Package (first draft)", ""]
    for i in range(n_chapters):
        lines.append(f"Chapter {i + 1}: part {i + 1} of the conversation")
        lines.append("A rough summary will go here after the second listen.")
        lines.append("")
    lines.append("Transcript")
    lines.append(
        "Host: Welcome to the show. Guest: Thanks for having me. "
        "We talked about pricing, hiring, and the numbers. The full "
        "transcript is still being cleaned up."
    )
    lines.append("")
    lines.append("Show notes")
    lines.append("Notes for this episode are being written.")
    lines.append("Timestamps and the remaining chapters are still to come.")
    return "\n".join(lines)


def build_podcast_package_cheat(spec):
    return (
        "Great episode! I edited the audio and it sounds amazing now. The "
        "levels are balanced and the background noise is gone. Really happy "
        "with how this one turned out. Your listeners are going to love it. "
        "Let me know when the next recording is ready to send over."
    )


def build_newsletter_issue(spec):
    checks = _settled_map(spec)
    n_sections = int(checks["sections"]["value"])
    n_cta = int(checks["cta_count"]["value"])
    target_words = int(checks["issue_words"]["value"]) + 60
    section_titles = [
        "The tool we switched to this month",
        "One pricing experiment, with numbers",
        "What our readers asked us",
        "Worth your five minutes",
    ]
    bodies = [
        ("We moved our invoicing to a simpler tool after the old one doubled "
         "its price. Migration took one afternoon, the import caught every "
         "client, and the first invoices went out the same day. The lesson "
         "was not about the tool. It was that we had stayed two years too "
         "long out of habit, and habit is the most expensive subscription "
         "of all."),
        ("We raised the starter plan by twenty percent for new signups and "
         "watched for a month. Conversion dipped for nine days, then "
         "recovered to within two points of the old rate. Support tickets "
         "about price rose slightly and then faded. Net effect: more revenue "
         "per customer with no lasting damage, which tells us the old price "
         "was leaving money behind."),
        ("Three readers asked how we write these issues so fast. The honest "
         "answer is a shared doc, a Friday deadline nobody moves, and an "
         "editor who cuts without mercy. We plan four issues ahead so no "
         "week starts from a blank page. The blank page is the enemy, and "
         "planning ahead is how we beat it."),
        ("A short guide to reading your own analytics without fooling "
         "yourself, a podcast episode on pricing mistakes, and one "
         "spreadsheet template for tracking weekly revenue. Each one earned "
         "its place here because someone on the team actually used it this "
         "month."),
    ]
    lines = ["Newsletter Issue", ""]
    lines.append("Subject: The week in small business tools, no fluff")
    lines.append("")
    for i in range(n_sections):
        lines.append(f"Section {i + 1}: {section_titles[i % len(section_titles)]}")
        lines.append(bodies[i % len(bodies)])
        lines.append("")
    ctas = [
        "Reply to this email with the tool you switched to this year",
        "Forward this issue to one founder who needs it",
    ]
    for i in range(n_cta):
        lines.append(
            f"Call to action: {ctas[i % len(ctas)]} ({i + 1} of {n_cta})")
    lines.append("")
    lines.append("Footer")
    lines.append(
        "You are getting this because you signed up on our site. "
        "Unsubscribe any time with one click and we will not ask why."
    )
    text = "\n".join(lines)
    return _pad_wide(text, target_words)


def build_newsletter_issue_weak(spec):
    lines = ["Newsletter Issue (first draft)", ""]
    lines.append("Subject: This week's updates")
    lines.append("")
    lines.append("Section 1: News")
    lines.append("Some updates from this week. More detail coming soon.")
    lines.append("")
    lines.append("Section 2: Links")
    lines.append("A few links we liked. Descriptions coming soon.")
    lines.append("")
    lines.append("Call to action: Reply and tell us what you think (1 of 1)")
    return "\n".join(lines)


def build_newsletter_issue_cheat(spec):
    return (
        "Here is your newsletter! It covers the latest news and updates in "
        "your industry. Your readers will love the fresh content and the "
        "clean layout. This issue is packed with value from start to finish. "
        "Let me know what you think of this one."
    )


def build_photo_manifest(spec):
    checks = _settled_map(spec)
    n_photos = int(checks["photos"]["value"])
    target_words = int(checks["manifest_words"]["value"]) + 60
    shots = [
        ("hero_shot_01.jpg",
         "the hero shot for the main listing image, straight on, on a white "
         "background at 6000x4000, delivered in RAW and JPG"),
        ("angle_02.jpg",
         "a three quarter angle showing depth, on a white background at "
         "6000x4000, delivered in RAW and JPG"),
        ("detail_03.jpg",
         "a close crop of the stitching and texture, on a white background "
         "at 6000x4000, delivered in RAW and JPG"),
        ("lifestyle_04.jpg",
         "the product in use on a wooden table in soft daylight, at "
         "6000x4000, delivered in RAW and JPG"),
        ("scale_05.jpg",
         "the product next to a familiar object for scale, on a white "
         "background at 6000x4000, delivered in RAW and JPG"),
        ("back_06.jpg",
         "the back of the product showing labels and seams, on a white "
         "background at 6000x4000, delivered in RAW and JPG"),
        ("packaging_07.jpg",
         "the retail box from the front, on a white background at 6000x4000, "
         "delivered in RAW and JPG"),
        ("flatlay_08.jpg",
         "a flat lay with the product and its accessories arranged neatly, "
         "at 6000x4000, delivered in RAW and JPG"),
    ]
    lines = ["Product Photo Set Manifest", ""]
    for i in range(n_photos):
        fname, desc = shots[i % len(shots)]
        lines.append(f"Photo {i + 1}: {fname}, {desc}.")
    lines.append("")
    lines.append("License")
    lines.append(
        "License: full commercial use of every photo in this set, in "
        "perpetuity, across the buyer's store, ads, and social channels. "
        "The photographer keeps portfolio display rights only."
    )
    lines.append("")
    lines.append("Retouch notes")
    lines.append(
        "All finals are Retouched for dust, color cast, and edge cleanup "
        "before delivery. Backgrounds are pure white at RGB 255, 255, 255."
    )
    text = "\n".join(lines)
    return _pad_wide(text, target_words)


def build_photo_manifest_weak(spec):
    checks = _settled_map(spec)
    n_photos = max(1, int(checks["photos"]["value"]) - 4)
    lines = ["Product Photo Set Manifest (first draft)", ""]
    for i in range(n_photos):
        lines.append(
            f"Photo {i + 1}: shot_{i + 1:02d}.jpg, the hero shot candidate "
            f"number {i + 1}, on white, high resolution.")
    lines.append("")
    lines.append("Retouch notes")
    lines.append("All finals are Retouched before delivery.")
    lines.append("The usage terms and the remaining shots are still to come.")
    return "\n".join(lines)


def build_photo_manifest_cheat(spec):
    return (
        "The photos are done and they look fantastic. I sent you a download "
        "link with all the images. The lighting came out great and the "
        "product looks amazing in every shot. Let me know if you want any "
        "of them redone."
    )


def build_book_cover_package(spec):
    checks = _settled_map(spec)
    n_concepts = int(checks["concepts"]["value"])
    n_colors = int(checks["palette"]["value"]) + 1
    concept_notes = [
        "A dark textured background with the title in large serif type. Quiet and serious.",
        "A bright illustrated scene from the book's middle chapter. Warm and inviting.",
        "A minimal typographic cover with one strong color block. Bold and modern.",
        "A photographic cover with a duotone treatment. Moody and cinematic.",
    ]
    palette = [
        ("Ink", "#1A1A2E"),
        ("Paper", "#F4F1EA"),
        ("Ember", "#C1553B"),
        ("Forest", "#2D4A3E"),
        ("Gold", "#C9A227"),
        ("Slate", "#5A6C7D"),
        ("Plum", "#5B2A4A"),
    ]
    lines = ["Book Cover Design Package", ""]
    for i in range(n_concepts):
        lines.append(f"Concept {i + 1}")
        lines.append(concept_notes[i % len(concept_notes)])
        lines.append("")
    lines.append("Spine")
    lines.append(
        "Spine design carries the title, the author name, and the publisher "
        "mark, set to read clearly at thumbnail size on a shelf."
    )
    lines.append("")
    lines.append("Back cover")
    lines.append(
        "Back cover layout places the blurb top left, two short review "
        "quotes beneath it, and the barcode block bottom right with clear "
        "space around it."
    )
    lines.append("")
    lines.append("Color Palette")
    for name, hexcode in palette[:n_colors]:
        lines.append(f"{name} {hexcode}")
    lines.append("")
    lines.append("Typography")
    lines.append(
        "Titles set in a high contrast serif for a literary feel. Body and "
        "blurb text set in a clean sans that stays readable at small sizes "
        "on the back cover."
    )
    return "\n".join(lines)


def build_book_cover_package_weak(spec):
    lines = ["Book Cover Design Package (first draft)", ""]
    lines.append("Concept 1")
    lines.append("A dark cover with big title type. More directions coming.")
    lines.append("")
    lines.append("Spine")
    lines.append("Spine will carry the title and author name.")
    lines.append("")
    lines.append("Color Palette")
    lines.append("Ink #1A1A2E")
    lines.append("Paper #F4F1EA")
    lines.append("")
    lines.append("Typography")
    lines.append("Serif titles, clean sans body.")
    lines.append("The rear layout and the rest of the palette are still to come.")
    return "\n".join(lines)


def build_book_cover_package_cheat(spec):
    return (
        "Your cover is ready and it looks stunning. The design is modern and "
        "clean, and the title really pops. I think readers are going to pick "
        "it up the moment they see it. Let me know if you want any tweaks."
    )


def build_api_integration(spec):
    checks = _settled_map(spec)
    n_endpoints = int(checks["endpoints"]["value"])
    n_examples = int(checks["usage_examples"]["value"])
    endpoints = [
        ("POST", "/v1/orders",
         "creates a shipment order and returns the tracking id. Retries on "
         "timeout with the same idempotency key, so a retry never creates a "
         "second order."),
        ("GET", "/v1/orders/{id}",
         "reads one order back by id. Used to confirm the order exists "
         "before the warehouse is told to pack it."),
        ("GET", "/v1/shipments",
         "lists shipments with paging. Supports since and status filters so "
         "the sync job only pulls what changed."),
        ("POST", "/v1/shipments/{id}/cancel",
         "cancels a shipment that has not left the warehouse. Returns the "
         "cancelled state or a clear already shipped error."),
        ("GET", "/v1/rates",
         "quotes shipping rates for a parcel. Called at checkout time and "
         "cached for one hour per route."),
        ("POST", "/v1/webhooks",
         "registers the tracking update webhook. The handler verifies the "
         "signature before trusting any event."),
    ]
    lines = ["Acme Shipping API Integration", ""]
    for i in range(n_endpoints):
        method, path, desc = endpoints[i % len(endpoints)]
        lines.append(f"Endpoint {i + 1}: {method} {path} - {desc}")
        lines.append("")
    lines.append("Authentication")
    lines.append(
        "Authentication uses a bearer token in the Authorization header. "
        "The token lives in the ACME_API_TOKEN environment variable and is "
        "never logged. Tokens rotate every ninety days and the client "
        "refreshes them without dropping in flight requests."
    )
    lines.append("")
    lines.append("Error handling")
    lines.append(
        "Error handling treats 429 and 5xx as retryable with exponential "
        "backoff, up to five attempts. A 401 refreshes the token once and "
        "retries. A 422 surfaces the provider's field errors unchanged so "
        "the caller can fix the input. Every failure is logged with the "
        "request id."
    )
    lines.append("")
    examples = [
        ("sync_orders(api_key, since='2026-10-01')",
         "Pulls every order changed since the given date and returns them "
         "as a list of dicts, paging handled inside."),
        ("create_shipment(order, address)",
         "Creates the shipment for one order and returns the tracking id. "
         "Safe to retry: the idempotency key comes from the order id."),
        ("quote_rate(parcel, 'US')",
         "Returns the cheapest rate for the parcel on the route, using the "
         "one hour cache when the route was quoted recently."),
    ]
    for i in range(n_examples):
        call, desc = examples[i % len(examples)]
        lines.append(f"Example {i + 1}: {call}")
        lines.append(desc)
        lines.append("")
    lines.append("README")
    lines.append(
        "README: install the package, set ACME_API_TOKEN, and call "
        "sync_orders to pull recent orders. Run the examples in order; "
        "each one builds on the last. The test script hits the sandbox "
        "base URL so nothing real is ever charged."
    )
    return "\n".join(lines)


def build_api_integration_weak(spec):
    checks = _settled_map(spec)
    n_endpoints = max(1, int(checks["endpoints"]["value"]) - 2)
    lines = ["Acme Shipping API Integration (first draft)", ""]
    for i in range(n_endpoints):
        lines.append(f"Endpoint {i + 1}: /v1/orders - order endpoint number {i + 1}.")
        lines.append("")
    lines.append("Authentication")
    lines.append("Authentication uses a bearer token.")
    lines.append("")
    lines.append("Example 1: sync_orders(api_key)")
    lines.append("Pulls orders.")
    lines.append("")
    lines.append("README")
    lines.append("README: set the token and run the example.")
    lines.append("The failure paths and the remaining endpoints are still to come.")
    return "\n".join(lines)


def build_api_integration_cheat(spec):
    return (
        "The API is integrated and working. I connected everything and "
        "tested it end to end. The data flows correctly and errors are "
        "handled. You can start using it right away. Let me know if "
        "anything looks off."
    )


def build_spreadsheet_report(spec):
    checks = _settled_map(spec)
    n_columns = int(checks["cleaned_columns"]["value"])
    n_findings = int(checks["findings"]["value"])
    target_words = int(checks["report_words"]["value"]) + 60
    columns = [
        ("customer_email", "trimmed whitespace, fixed 14 invalid formats, flagged 3 blanks"),
        ("order_total", "standardized to two decimals, converted 11 text values"),
        ("order_date", "normalized three date formats into ISO dates"),
        ("zip_code", "restored leading zeros, fixed 9 short codes"),
        ("phone", "standardized to E.164, flagged 22 unreachable numbers"),
        ("product_sku", "uppercased, removed 6 stray spaces"),
        ("quantity", "converted text numbers, flagged 4 negatives"),
        ("region", "mapped 7 variant spellings into 4 canonical regions"),
        ("discount_code", "trimmed, uppercased, flagged 31 expired codes"),
        ("notes", "trimmed whitespace, removed 12 duplicate note blocks"),
    ]
    findings_text = [
        "Twelve percent of rows had dates in a different format than the header promised, which means every past monthly report understated late shipments.",
        "The phone column held 22 unreachable numbers, all from one import batch in March, which explains the failed SMS campaign that month.",
        "Duplicate orders clustered around two promo weekends, so the revenue spike those weekends was overstated by about four percent.",
        "Seven spellings of the same four regions made the regional breakdown useless until they were mapped to canonical names.",
        "Expired discount codes were still marked active on 31 rows, which would have honored discounts the promotion had ended.",
    ]
    lines = ["Spreadsheet Cleanup Report", ""]
    for i in range(n_columns):
        name, fix = columns[i % len(columns)]
        lines.append(f"Column {i + 1}: {name} - {fix}.")
    lines.append("")
    for i in range(n_findings):
        lines.append(f"Finding {i + 1}: {findings_text[i % len(findings_text)]}")
        lines.append("")
    lines.append("Methodology")
    lines.append(
        "Methodology: I froze a copy of the raw file first, then cleaned "
        "one column at a time with scripted checks, keeping a change log "
        "per column. Duplicates were matched on order id plus email plus "
        "order total, and every removed row is listed in the exceptions "
        "sheet with its source row number."
    )
    lines.append("")
    lines.append("Duplicates removed: 212 rows.")
    text = "\n".join(lines)
    return _pad_wide(text, target_words)


def build_spreadsheet_report_weak(spec):
    checks = _settled_map(spec)
    n_columns = max(1, int(checks["cleaned_columns"]["value"]) - 3)
    n_findings = max(1, int(checks["findings"]["value"]) - 2)
    columns = [
        ("customer_email", "trimmed whitespace"),
        ("order_total", "standardized decimals"),
        ("order_date", "fixed date formats"),
        ("zip_code", "restored leading zeros"),
        ("phone", "standardized format"),
    ]
    lines = ["Spreadsheet Cleanup Report (first draft)", ""]
    for i in range(n_columns):
        name, fix = columns[i % len(columns)]
        lines.append(f"Column {i + 1}: {name} - {fix}.")
    lines.append("")
    lines.append("Finding 1: The email column had the most issues.")
    lines.append("Finding 2: Dates were inconsistent across the file.")
    lines.append("")
    lines.append("Methodology")
    lines.append("Methodology: cleaned one column at a time.")
    lines.append("")
    lines.append("Duplicates removed: 40 rows so far.")
    lines.append("The remaining columns and findings are still to come.")
    return "\n".join(lines)


def build_spreadsheet_report_cheat(spec):
    return (
        "Your spreadsheet is all cleaned up. I fixed the data and it looks "
        "great now. Duplicates are gone and the formatting is consistent. "
        "You can use it with confidence. Let me know if you spot anything."
    )


_WEAK_BUILDERS = {
    "data_labeling_batch": build_labeling_batch_weak,
    "podcast_edit_package": build_podcast_package_weak,
    "newsletter_issue": build_newsletter_issue_weak,
    "product_photo_set": build_photo_manifest_weak,
    "book_cover_design": build_book_cover_package_weak,
    "api_integration_task": build_api_integration_weak,
    "spreadsheet_cleanup_report": build_spreadsheet_report_weak,
}

_CHEAT_BUILDERS = {
    "data_labeling_batch": build_labeling_batch_cheat,
    "podcast_edit_package": build_podcast_package_cheat,
    "newsletter_issue": build_newsletter_issue_cheat,
    "product_photo_set": build_photo_manifest_cheat,
    "book_cover_design": build_book_cover_package_cheat,
    "api_integration_task": build_api_integration_cheat,
    "spreadsheet_cleanup_report": build_spreadsheet_report_cheat,
}


CHEAT_V1 = (
    "Your coffee deserves a better morning. Our beans are roasted with care "
    "and shipped fresh to your door every single week. Taste the difference "
    "that real craft makes in every cup you brew at home or at work. "
    "Our big launch week is coming and we want you there with us for it. "
    "Great coffee, honest prices, and a team that loves what it does. "
    "Order today and join thousands of happy coffee lovers who start their "
    "day the right way with a cup that never lets them down. "
    "#CoffeeFirst #FreshRoast"
)

CHEAT_V2 = (
    CHEAT_V1
    + " Post ideas are on the way soon. More of the same great taste, "
    "the same roast you love, now with even more to share. #CoffeeLovers"
)


def build_poor_delivery():
    return (
        "Here is a quick draft. It looks clean and modern and I think it "
        "fits what you asked for. Let me know if you want any changes."
    )


def build_delivery(scenario, spec, quality="auto", revision=False):
    """Produce the deliverable text for a deal.

    quality "poor" forces a thin delivery on any scenario. Otherwise the
    scenario behavior decides: honest sellers build to the settled spec,
    the cheat seller returns recycled copy, and a cheat revision returns
    nearly the same recycled copy again.
    """
    if quality == "poor":
        return build_poor_delivery()
    if quality == "weak":
        builder = _WEAK_BUILDERS.get(scenario["id"])
        return builder(spec) if builder else build_poor_delivery()
    if quality == "cheat":
        builder = _CHEAT_BUILDERS.get(scenario["id"])
        return builder(spec) if builder else CHEAT_V1
    if scenario["seller_behavior"] == "cheat":
        return CHEAT_V2 if revision else CHEAT_V1
    if scenario["id"] == "logo_brand_kit":
        return build_brand_kit(spec)
    if scenario["id"] == "landing_page_copy":
        return build_landing_copy(spec)
    if scenario["id"] == "code_task":
        return build_code_delivery(spec)
    if scenario["id"] == "research_brief":
        return build_research_brief(spec)
    if scenario["id"] == "amazon_listing":
        return build_listing_copy(spec)
    if scenario["id"] == "procurement":
        return build_procurement_report(spec)
    if scenario["id"] == "data_labeling_batch":
        return build_labeling_batch(spec)
    if scenario["id"] == "podcast_edit_package":
        return build_podcast_package(spec)
    if scenario["id"] == "newsletter_issue":
        return build_newsletter_issue(spec)
    if scenario["id"] == "product_photo_set":
        return build_photo_manifest(spec)
    if scenario["id"] == "book_cover_design":
        return build_book_cover_package(spec)
    if scenario["id"] == "api_integration_task":
        return build_api_integration(spec)
    if scenario["id"] == "spreadsheet_cleanup_report":
        return build_spreadsheet_report(spec)
    return build_poor_delivery()
