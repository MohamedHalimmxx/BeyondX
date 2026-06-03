"""State and schema definitions for the Brand Analyst Agent."""
from typing import Optional
from pydantic import BaseModel, Field


class PositioningAxes(BaseModel):
    axis_1_label: str
    axis_1_low: str
    axis_1_high: str
    axis_2_label: str
    axis_2_low: str
    axis_2_high: str
    reasoning: str


class CompetitorProfile(BaseModel):
    name: str
    rating: Optional[float] = Field(
        default=None,
        description="Google rating out of 5. None if no review data available."
    )
    review_count: int = Field(default=0)

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
    data_confidence: str


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
    for_audience: str
    who_need: str = Field(default="")
    brand_name_placeholder: str = Field(default="[Brand Name]")
    is_the: str
    that: str
    unlike: str
    we: str
    full_statement: str