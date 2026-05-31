"""State and schema definitions for the Strategy Writer Agent."""

from pydantic import BaseModel, Field


class MessagingPillars(BaseModel):
    """Core copy hooks and brand messaging rules."""
    primary_tagline: str = Field(
        ..., 
        description="The main, high-impact brand slogan or hook that sums up the unique positioning."
    )
    value_prop_hooks: list[str] = Field(
        ..., 
        description="Exactly 3 distinct copywriting hooks designed to directly address the key customer pain points found in your research."
    )
    brand_voice_guidelines: list[str] = Field(
        ..., 
        description="3-4 explicit rules defining the tone, vocabulary style, and emotional resonance of the brand."
    )


class CampaignPhase(BaseModel):
    """A structured chronological phase within the launch framework."""
    phase_name: str = Field(..., description="e.g., 'Phase 1: Local Awareness and Trust Building (Days 1-30)'")
    strategic_objective: str = Field(..., description="The main, overriding goal of this specific 30-day window.")
    tactical_actions: list[str] = Field(..., description="Concrete, actionable steps, community events, or launch tactics to execute.")
    kpis_to_track: list[str] = Field(..., description="Specific, measurable key performance indicators to track success.")


class MarketingChannel(BaseModel):
    """A target customer acquisition vector."""
    channel_name: str = Field(..., description="e.g., 'Instagram Hyper-local Ads', 'Community Event Partnerships'")
    allocation_weight: str = Field(..., description="Strategic priority weight: High (Top focus), Medium, or Low")
    execution_strategy: str = Field(..., description="Dynamic tactical strategy explaining how to weaponize this channel against competitors.")


class StrategicGoToMarketPlan(BaseModel):
    """The master container schema parsed and validated by the Strategy Node."""
    messaging_framework: MessagingPillars = Field(..., description="The brand voice foundations and copywriting pillars.")
    ninety_day_launch_roadmap: list[CampaignPhase] = Field(..., description="A step-by-step 3-phase execution timeline.")
    channel_matrix: list[MarketingChannel] = Field(..., description="The specific channels leveraged to intercept market share.")
    creative_content_pillars: list[str] = Field(..., description="4 distinct thematic pillars for continuous content creation.")
    defensive_moat_strategy: str = Field(..., description="Actionable advice on how to operationally or legally protect this positioning space.")


class StrategyState(BaseModel):
    """The localized Graph Dictionary layer tracking the data across execution runs."""
    idea: str
    research_report: str
    positioning_statement: str
    positioning_map_ascii: str
    final_strategic_brief: str = ""