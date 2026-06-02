"""State and schema definitions for the Brand Identity Agent."""
from pydantic import BaseModel, Field


class BrandIdentityOutput(BaseModel):
    selected_name: str = Field(..., description="The chosen brand name with rationale")
    name_rationale: str = Field(..., description="Why this name was selected over others")
    mission: str = Field(..., description="What the brand does and for whom — one sentence")
    vision: str = Field(..., description="The world the brand is building toward — one sentence")
    origin_story: str = Field(..., description="2-3 paragraph narrative of why this brand exists")
    brand_promise: str = Field(..., description="The single sentence commitment to every customer")
    personality_traits: list[str] = Field(..., description="3-5 specific personality traits")
    brand_voice_is: list[str] = Field(..., description="How the brand talks — 3-4 descriptors")
    brand_voice_never: list[str] = Field(..., description="How the brand never talks — 3-4 descriptors")
    core_values: list[str] = Field(..., description="3-4 core beliefs that drive every decision")
    tagline: str = Field(..., description="Final refined tagline — short, memorable, specific")