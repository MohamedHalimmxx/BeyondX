"""
Brand brief enrichment — asks the client 3 targeted questions
before brand analysis runs. Answers feed into the analyst and
strategy writer for client-specific output.
"""

from pydantic import BaseModel, Field


class ClientBrandBrief(BaseModel):
    """Structured client input collected before brand analysis."""
    idea: str
    differentiator: str = Field(..., description="What makes this concept different")
    ideal_customer: str = Field(..., description="One specific person who is the ideal customer")
    non_negotiable: str = Field(..., description="The one thing the brand refuses to compromise on")


def collect_brand_brief(idea: str) -> ClientBrandBrief:
    """
    Asks the client 3 focused questions to enrich the brand brief.
    Returns a structured ClientBrandBrief.
    """
    print("\n" + "=" * 70)
    print("BRAND BRIEF — 3 Quick Questions")
    print("(Your answers make the brand strategy specific to you)")
    print("=" * 70)

    print("\n[1] What makes your concept different from what already exists?")
    print("    (Don't say 'quality' or 'service' — be specific)")
    differentiator = input("    > ").strip()
    if not differentiator:
        differentiator = "Not specified"

    print("\n[2] Describe your ideal customer in one sentence.")
    print("    (e.g. 'A 25-year-old Cairo student who orders delivery late at night')")
    ideal_customer = input("    > ").strip()
    if not ideal_customer:
        ideal_customer = "Not specified"

    print("\n[3] What is the ONE thing you refuse to compromise on?")
    print("    (e.g. ingredient quality, speed, price, authenticity)")
    non_negotiable = input("    > ").strip()
    if not non_negotiable:
        non_negotiable = "Not specified"

    return ClientBrandBrief(
        idea=idea,
        differentiator=differentiator,
        ideal_customer=ideal_customer,
        non_negotiable=non_negotiable
    )
