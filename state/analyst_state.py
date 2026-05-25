from typing import Optional
from pydantic import BaseModel, Field


class PositioningAxes(BaseModel):
    """
    The two most strategically relevant axes for this specific industry.
    Derived by the LLM from the business context — never hardcoded.
    """
    axis_1_label: str = Field(..., description="Name of the first axis, e.g. 'Price Point'")
    axis_1_low: str = Field(..., description="Low end label, e.g. 'Budget'")
    axis_1_high: str = Field(..., description="High end label, e.g. 'Premium'")
    axis_2_label: str = Field(..., description="Name of the second axis, e.g. 'Experience Type'")
    axis_2_low: str = Field(..., description="Low end label, e.g. 'Traditional'")
    axis_2_high: str = Field(..., description="High end label, e.g. 'Innovative'")
    reasoning: str = Field(..., description="Why these two axes are most relevant for this industry and market")


class CompetitorProfile(BaseModel):
    """
    A fully enriched competitor profile scored from real evidence.
    Works for any business type — restaurant, gym, SaaS, skincare, clinic, etc.
    """
    name: str
    rating: float = Field(..., description="Google rating out of 5")
    review_count: int

    # Positioning scores — must be derived from evidence, never guessed
    axis_1_score: float = Field(..., ge=0, le=10, description="Score on axis 1 based on evidence")
    axis_2_score: float = Field(..., ge=0, le=10, description="Score on axis 2 based on evidence")

    # Evidence-based signals extracted from reviews and online data
    pricing_tier: str = Field(..., description="budget / mid-range / premium / luxury — from pricing signals in data")
    service_style: str = Field(..., description="How they deliver their core offering — from menu/product data")
    brand_personality: str = Field(..., description="Their voice and identity — from marketing language and reviews")
    target_audience: str = Field(..., description="Who actually buys from them — from review demographics and context")
    distribution_channels: str = Field(..., description="How customers access them — delivery, physical, app, online")

    # Direct from customer language
    top_strengths: list[str] = Field(default_factory=list, description="What customers consistently praise — quoted from reviews. Empty list if no data available.")
    top_weaknesses: list[str] = Field(default_factory=list, description="What customers consistently complain about — from reviews. Empty list if no data available.")

    # Transparency
    evidence_summary: str = Field(..., description="Brief summary of what data was used to score this competitor")
    data_confidence: str = Field(..., description="high / medium / low — based on how much real data was available")


class PainPoint(BaseModel):
    """A strategic customer pain point derived from competitor weakness patterns."""
    theme: str = Field(..., description="Short label for the pain point")
    description: str = Field(..., description="What customers are frustrated about across competitors")
    affected_competitors: list[str] = Field(..., description="Which competitors show this weakness")
    opportunity: str = Field(..., description="How a new brand could solve this better than anyone currently does")
    evidence: str = Field(..., description="Specific quotes or signals from the data that support this pain point")


class MarketWhiteSpace(BaseModel):
    """A specific positioning opportunity no current competitor owns."""
    description: str = Field(..., description="What the white space is — be specific")
    axis_1_position: str = Field(..., description="Where on axis 1 this white space sits")
    axis_2_position: str = Field(..., description="Where on axis 2 this white space sits")
    why_it_exists: str = Field(..., description="Why no current competitor owns this space")
    evidence: str = Field(..., description="Which competitor gaps create this opportunity")


class BrandAnalystOutput(BaseModel):
    """
    Complete brand positioning analysis output.
    Every field is grounded in real data — no invented insights.
    """
    # Dynamic axes derived from industry context
    positioning_axes: PositioningAxes

    # Enriched competitor profiles
    competitors: list[CompetitorProfile]

    # Strategic opportunities
    white_spaces: list[MarketWhiteSpace] = Field(..., description="One or more positioning gaps identified")
    pain_points: list[PainPoint]

    # Final output
    positioning_recommendation: str = Field(
        ...,
        description="The single strongest positioning a new brand could own. Must reference specific white space and pain points."
    )
    target_audience_summary: str = Field(
        ...,
        description="Who the new brand should target and why — based on underserved segments identified in competitor analysis"
    )
    competitive_advantage: str = Field(
        ...,
        description="The specific advantage the new brand has if it takes the recommended position"
    )


class PositioningStatement(BaseModel):
    """
    A structured brand positioning statement derived from white space analysis.
    Bridges the brand analyst output to the strategy writer input.
    """
    for_audience: str = Field(..., description="The specific target audience")
    who_need: str = Field(..., description="The specific need or frustration they have")
    brand_name_placeholder: str = Field(default="[Brand Name]", description="Placeholder until strategy writer names the brand")
    is_the: str = Field(..., description="The category the brand competes in")
    that: str = Field(..., description="The single key differentiator")
    unlike: str = Field(..., description="The main competitor being differentiated from")
    we: str = Field(..., description="The proof point — why this is believable")
    full_statement: str = Field(..., description="The complete formatted positioning statement")


class PositioningStatement(BaseModel):
    """
    A structured brand positioning statement derived from white space analysis.
    Bridges the brand analyst output to the strategy writer input.
    """
    for_audience: str = Field(..., description="The specific target audience")
    who_need: str = Field(..., description="The specific need or frustration they have")
    brand_name_placeholder: str = Field(default="[Brand Name]", description="Placeholder until strategy writer names the brand")
    is_the: str = Field(..., description="The category the brand competes in")
    that: str = Field(..., description="The single key differentiator")
    unlike: str = Field(..., description="The main competitor being differentiated from")
    we: str = Field(..., description="The proof point — why this is believable")
    full_statement: str = Field(..., description="The complete formatted positioning statement")
