"""State and schema definitions for the Brand Identity Agent."""
from pydantic import BaseModel, Field


class BrandIdentityOutput(BaseModel):
    selected_name: str = Field(..., description="The chosen brand name")
    name_rationale: str = Field(..., description="Why this name was selected over others")
    mission: str = Field(..., description="What the brand does and for whom — one sentence")
    vision: str = Field(..., description="The world the brand is building toward — one sentence")
    origin_story: str = Field(..., description="2-3 paragraph narrative of why this brand exists")
    brand_promise: str = Field(..., description="The single sentence commitment to every customer")
    personality_traits: list[str] = Field(..., description="Exactly 4 single-word or two-word personality traits. No sentences, no examples.")
    brand_voice_is: list[str] = Field(..., description="Exactly 4 short descriptors of how the brand talks. Each item is 1-3 words only. No examples, no sentences.")
    brand_voice_never: list[str] = Field(..., description="Exactly 4 short descriptors of how the brand never talks. Each item is 1-3 words only. No examples, no sentences.")
    core_values: list[str] = Field(..., description="Exactly 4 core values. Each item is 1-5 words only. No explanations, no sentences.")
    tagline: str = Field(..., description="Final refined tagline — short, memorable, specific")