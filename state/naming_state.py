"""State and schema definitions for the Brand Naming Agent."""

from pydantic import BaseModel, Field


class BrandNameCandidate(BaseModel):
    name: str = Field(..., description="The brand name candidate")
    pronunciation_guide: str = Field(..., description="How to say it")
    meaning_and_origin: str = Field(..., description="What the name means or where it comes from")
    positioning_fit: str = Field(..., description="Why this name fits the brand positioning")
    rhetorical_device: str = Field(..., description="The naming device used")
    score: float = Field(..., ge=0, le=10, description="Overall score 0-10")
    domain_com: str = Field(default="unknown", description=".com domain status")
    domain_io: str = Field(default="unknown", description=".io domain status")
    brand_conflict: str = Field(default="unknown", description="conflict, clear, or unknown")
    conflict_reason: str = Field(default="", description="Why this name conflicts if it does")


class BrandNamingOutput(BaseModel):
    candidates: list[BrandNameCandidate] = Field(..., description="Brand name candidates ranked by score")
    top_recommendation: str = Field(..., description="The single strongest name recommendation")
    naming_strategy: str = Field(..., description="The overall naming approach used")
    names_to_avoid: list[str] = Field(..., description="Names or patterns to avoid")
