from typing import Literal, Optional
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """System-wide configuration registry validating active environment configurations."""

    # Groq keys
    GROQ_API_KEY: SecretStr = Field(
        ...,
        description="Primary Groq API key."
    )
    GROQ_API_KEY_2: Optional[SecretStr] = Field(
        default=None,
        description="Fallback Groq key if primary hits rate limit."
    )

    # Gemini key
    GEMINI_API_KEY: Optional[SecretStr] = Field(
        default=None,
        description="Google Gemini API key. Used as final fallback when both Groq keys are exhausted."
    )

    # Search + Places
    TAVILY_API_KEY: SecretStr = Field(
        ...,
        description="Tavily API key for web search."
    )
    GOOGLE_PLACES_API_KEY: SecretStr = Field(
        ...,
        description="Google Places API key for local competitor discovery."
    )

    # Model config
    LLM_MODEL: str = Field(
        default="llama-3.3-70b-versatile",
        description="Primary Groq model."
    )
    GEMINI_MODEL: str = Field(
        default="gemini-2.0-flash",
        description="Gemini model used as fallback."
    )
    LLM_TEMPERATURE: float = Field(
        default=0.1,
        ge=0.0,
        le=1.0,
        description="Temperature for all LLM calls."
    )
    DEFAULT_MAX_ITERATIONS: int = Field(
        default=7,
        ge=1,
        le=10,
        description="Max research loop iterations."
    )
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        description="Logging level."
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = AppSettings()
