from typing import Literal, Optional
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """System-wide configuration registry validating active environment configurations."""

    # Groq keys
    GROQ_API_KEY: SecretStr = Field(..., description="Primary Groq API key.")
    GROQ_API_KEY_2: Optional[SecretStr] = Field(
        default=None, description="Fallback Groq key if primary hits rate limit."
    )

    # Gemini keys
    GEMINI_API_KEY: Optional[SecretStr] = Field(
        default=None, description="Primary Gemini API key."
    )
    GEMINI_API_KEY_2: Optional[SecretStr] = Field(
        default=None, description="Fallback Gemini API key."
    )
    GEMINI_API_KEY_3: Optional[SecretStr] = Field(default=None)
    GEMINI_MODEL_PRO: str = Field(
    default="gemini-2.5-pro", description="Gemini Pro model for brand book generation."
    )
    GEMINI_API_KEY_4: Optional[SecretStr] = Field(default=None)
    GEMINI_API_KEY_5: Optional[SecretStr] = Field(default=None)
    GEMINI_API_KEY_6: Optional[SecretStr] = Field(default=None)
    GEMINI_API_KEY_7: Optional[SecretStr] = Field(default=None)
    GEMINI_API_KEY_8: Optional[SecretStr] = Field(default=None)

    # Other keys
    CEREBRAS_API_KEY: Optional[SecretStr] = Field(
        default=None,
        description="Cerebras API key. Used as fallback when Groq keys are exhausted.",
    )

    # Search + Places
    TAVILY_API_KEY: SecretStr = Field(..., description="Tavily API key for web search.")
    GOOGLE_PLACES_API_KEY: SecretStr = Field(
        ..., description="Google Places API key for local competitor discovery."
    )

    HF_API_KEY: Optional[SecretStr] = Field(
        default=None,
        description="Hugging Face API key for logo image generation fallback.",
    )
    GROQ_API_KEY_3: Optional[SecretStr] = Field(
        default=None,
        description="Third Groq key for additional fallback capacity."
        )

    # Model config
    FAST_LLM_MODEL: str = Field(
        default="llama-3.1-8b-instant",
        description="Lightweight model for simple classification tasks.",
    )
    LLM_MODEL: str = Field(
        default="llama-3.3-70b-versatile", description="Primary Groq model."
    )
    GEMINI_MODEL: str = Field(
        default="gemini-2.5-flash", description="Gemini model for text generation."
    )
    GEMINI_IMAGE_MODEL: str = Field(
        default="gemini-2.5-flash-image",
        description="Gemini model for image generation (logo concepts).",
    )
    LLM_TEMPERATURE: float = Field(
        default=0.1, ge=0.0, le=1.0, description="Temperature for all LLM calls."
    )
    DEFAULT_MAX_ITERATIONS: int = Field(
        default=2, ge=1, le=10, description="Max research loop iterations."
    )
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", description="Logging level."
    )

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


settings = AppSettings()
