from pydantic import BaseModel, Field


class CompetitorPosition(BaseModel):
    """A single competitor scored on two strategic axes."""
    name: str
    premium_score: float = Field(..., ge=0, le=10, description="0=budget, 10=premium")
    innovation_score: float = Field(..., ge=0, le=10, description="0=traditional, 10=innovative")
    strength: str
    weakness: str


class PainPoint(BaseModel):
    """A recurring customer pain point derived from competitor weaknesses."""
    theme: str
    description: str
    opportunity: str


class BrandAnalystOutput(BaseModel):
    """Complete structured output of the brand analyst agent."""
    competitors: list[CompetitorPosition]
    white_space: str
    pain_points: list[PainPoint]
    positioning_recommendation: str
