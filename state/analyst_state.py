"""State and schema definitions for the Brand Analyst Agent."""
from typing import Optional
from pydantic import BaseModel, Field


class PositioningAxes(BaseModel):
    axis_1_label: str = Field(..., description="Name of the first axis, e.g. 'Price Point'")
    axis_1_low: str = Field(..., description="Low end label, e.g. 'Budget'")
    axis_1_high: str = Field(..., description="High end label, e.g. 'Premium'")
    axis_2_label: str = Field(..., description="Name of the second axis, e.g. 'Experience Type'")
    axis_2_low: str = Field(..., description="Low end label, e.g. 'Traditional'")
    axis_2_high: str = Field(..., description="High end label, e.g. 'Innovative'")
    reasoning: str = Field(..., description="Why these two axes are most relevant for this industry and market")


class CompetitorProfile(BaseModel):
    name: str
    rating: float = Field(..., description="Google rating out of 5")
    review_count: int

    axis_1_score: float = Field(..., ge=0, le=10)
    axis_2_score: float = Field(..., ge=0, le=10)

    pricing_tier: Optional[str] = None
    service_style: Optional[str] = None
    brand_personality: str
    target_audience: str
    distribution_channels: str

    top_strengths: list[str] = Field(default_factory=list)
    top_weaknesses: list[str] = Field(default_factory=list)

    evidence_summary: str
    data_confidence: str = Field(..., description="high / medium / low")


class PainPoint(BaseModel):
    theme: str
    description: str
    affected_competitors: list[str]
    opportunity: str
    evidence: str


class MarketWhiteSpace(BaseModel):
    description: str
    axis_1_position: str
    axis_2_position: str
    why_it_exists: str
    evidence: str


class BrandAnalystOutput(BaseModel):
    positioning_axes: PositioningAxes
    competitors: list[CompetitorProfile]
    white_spaces: list[MarketWhiteSpace]
    pain_points: list[PainPoint]
    positioning_recommendation: str
    target_audience_summary: str
    competitive_advantage: str


class PositioningStatement(BaseModel):
    """Structured positioning statement bridging analyst output to strategy writer."""
    for_audience: str
    who_need: str
    brand_name_placeholder: str = Field(default="[Brand Name]")
    is_the: str
    that: str
    unlike: str
    we: str
    full_statement: str