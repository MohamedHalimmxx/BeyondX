import operator
from typing import Annotated, Any, TypedDict
from pydantic import BaseModel, Field


class ResearchState(TypedDict):
    """LangGraph state representation for the market research workflow."""

    idea: str
    research_plan: list[str]
    gathered_data: Annotated[list[str], operator.add]
    insights: Annotated[list[str], operator.add]
    iteration: int
    max_iterations: int
    reflection_verdict: dict[str, Any]  
    final_report: str


class ResearchStateInput(BaseModel):
    """Pydantic model used to strictly validate incoming user payloads."""
    idea: str = Field(..., description="The startup or business concept requiring market analysis.")
    max_iterations: int = Field(default=3, ge=1, le=5, description="Maximum execution depth allowed.")


class ReflectionVerdict(BaseModel):
    """Structured model used by the reflection node to govern graph routing."""
    is_complete: bool = Field(..., description="True if research plan is fully addressed.")
    reasoning: str = Field(..., description="Justification for continuing or terminating loops.")
    next_question: str | None = Field(default=None, description="Next priority question if continuing.")