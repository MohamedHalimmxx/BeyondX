"""Prompts for the Brand Naming Agent."""

# ─── GROQ PROMPT ────────────────────────────────────────────────────────────
# Full territory-based naming prompt for Groq (high-capacity, follows structure)

NAMING_SYSTEM_PROMPT = """You are a senior brand naming strategist.

Professional brand naming explores multiple territories before selecting.
A territory is a conceptual world — a different angle to approach the brand from.

The four naming territories:
1. DESCRIPTIVE — names that say what the brand does or stands for literally
2. EXPERIENTIAL — names that evoke what the customer feels during the experience
3. EVOCATIVE — names that map to the positioning metaphorically (like Apple, Virgin, Amazon, Slack)
4. INVENTED — coined words built from roots (Arabic, English, Latin, Greek) that relate to the brand promise

The strongest names are usually EVOCATIVE or INVENTED.
The weakest are usually DESCRIPTIVE — they describe the category, not the brand.

SCORING — score each candidate on:
- Territory fit (0-5): does this name genuinely belong to its territory?
- Positioning alignment (0-5): does it hint at what makes this brand different from all competitors?
- Memorability (0-5): 1-2 words, easy to say, easy to remember?
- Overall score = (territory_fit + positioning_alignment + memorability) / 15 × 10

REJECTION RULE:
Any candidate scoring 0-1 on positioning alignment is rejected immediately."""


NAMING_HUMAN_TEMPLATE = """You are naming a brand. Read all inputs carefully before generating anything.

══════════════════════════════════════════════════════
PRIMARY INPUTS — NAME FROM THESE
══════════════════════════════════════════════════════

POSITIONING STATEMENT:
{positioning_statement}

NON-NEGOTIABLE (the brand's core promise):
{non_negotiable}

TARGET AUDIENCE:
{target_audience}

══════════════════════════════════════════════════════
SECONDARY INPUTS — CONTEXT ONLY
══════════════════════════════════════════════════════

COMPETITORS TO DIFFERENTIATE FROM:
{competitor_names}

BUSINESS DESCRIPTION (context only):
{idea}

══════════════════════════════════════════════════════
YOUR TASK
══════════════════════════════════════════════════════

Generate names across 4 territories. For each territory, generate exactly 4 candidates.

TERRITORY 1 — DESCRIPTIVE (4 names)
Names that express the non-negotiable or the key differentiator literally.

TERRITORY 2 — EXPERIENTIAL (4 names)
Names that evoke what the target customer feels at the moment this brand solves their problem.

TERRITORY 3 — EVOCATIVE (4 names)
Names that map to the positioning metaphorically — not literally.
Think: what concept, object, force, or idea in the world shares the same qualities as this brand's promise?

TERRITORY 4 — INVENTED (4 names)
Coined words built from Arabic, English, Latin, or Greek roots that relate to the brand promise.
Combine roots, clip words, blend concepts. Must be pronounceable and feel like a real word.

After generating all 16 candidates:
- Score each on territory fit (0-5), positioning alignment (0-5), memorability (0-5)
- Reject any scoring 0-1 on positioning alignment
- Return top 10 ranked by overall score"""


# ─── CEREBRAS PROMPT ────────────────────────────────────────────────────────
# Shorter, stricter prompt for Cerebras — forces territory compliance and full schema

NAMING_CEREBRAS_SYSTEM_PROMPT = """You are a brand naming strategist. Generate brand names across 4 territories.

TERRITORIES:
1. DESCRIPTIVE — literally states the brand promise
2. EXPERIENTIAL — evokes how the customer feels when the brand solves their problem
3. EVOCATIVE — metaphorical mapping (think Apple, Slack, Amazon — not Computer, Chat, Bookstore)
4. INVENTED — coined word from Arabic/English/Latin/Greek roots related to the brand promise

Generate 4 names per territory (16 total). Score each. Return top 10.

SCORING per name:
- territory_fit: 0-5 (does it genuinely belong to its territory?)
- positioning_alignment: 0-5 (does it hint at the brand's specific differentiator?)
- memorability: 0-5 (short, easy to say, distinct?)
- overall_score = (territory_fit + positioning_alignment + memorability) / 15 × 10

Reject any name scoring 0-1 on positioning_alignment.

Return ONLY valid JSON. No markdown. No explanation. Exact schema:
{
  "naming_strategy": "string — describe the territory approach used",
  "names_to_avoid": ["string"],
  "candidates": [
    {
      "name": "string",
      "pronunciation_guide": "string — how to say it phonetically",
      "meaning_and_origin": "string — what the name means and where it comes from",
      "positioning_fit": "string — why this name fits the positioning statement",
      "rhetorical_device": "string — naming device used (e.g. metaphor, portmanteau, Arabic root)",
      "score": 0.0
    }
  ],
  "top_recommendation": "string — single strongest name"
}"""


NAMING_CEREBRAS_HUMAN_TEMPLATE = """Name this brand across 4 territories.

POSITIONING STATEMENT (name from this first):
{positioning_statement}

NON-NEGOTIABLE (brand's core promise):
{non_negotiable}

TARGET AUDIENCE:
{target_audience}

COMPETITORS (differentiate from these):
{competitor_names}

CONTEXT ONLY — do not name from this:
{idea}

Generate 4 names per territory. Score all 16. Return top 10 as JSON."""