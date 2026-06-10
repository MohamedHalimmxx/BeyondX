from typing import Literal, Optional
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """System-wide configuration registry validating active environment configurations."""

    # ── Original Groq keys (kept for backward compatibility) ──────────────
    GROQ_API_KEY: SecretStr = Field(...)
    GROQ_API_KEY_2: Optional[SecretStr] = Field(default=None)
    GROQ_API_KEY_3: Optional[SecretStr] = Field(default=None)

    # ── Dedicated Groq keys — one per BrandGenius node ────────────────────
    GROQ_RESEARCH_PRIMARY_KEY: Optional[SecretStr] = Field(default=None)
    GROQ_RESEARCH_FALLBACK_KEY: Optional[SecretStr] = Field(default=None)
    GROQ_RESEARCH_NODE_KEY: Optional[SecretStr] = Field(default=None)
    GROQ_PLANNER_KEY: Optional[SecretStr] = Field(default=None)
    GROQ_REFLECTION_KEY: Optional[SecretStr] = Field(default=None)
    GROQ_REPORT_KEY: Optional[SecretStr] = Field(default=None)
    GROQ_ANALYST_KEY: Optional[SecretStr] = Field(default=None)
    GROQ_STRATEGY_KEY: Optional[SecretStr] = Field(default=None)
    GROQ_NAMING_KEY: Optional[SecretStr] = Field(default=None)
    GROQ_BRAND_IDENTITY_KEY: Optional[SecretStr] = Field(default=None)

    # ── Gemini keys — Stage 6 visual brief (Flash text) ──────────────────
    GEMINI_VISUAL_KEY_1: Optional[SecretStr] = Field(default=None)
    GEMINI_VISUAL_KEY_2: Optional[SecretStr] = Field(default=None)
    GEMINI_VISUAL_KEY_3: Optional[SecretStr] = Field(default=None)

    # ── Gemini keys — Stage 6 logo generation (Flash image) ──────────────
    GEMINI_LOGO_KEY_1: Optional[SecretStr] = Field(default=None)
    GEMINI_LOGO_KEY_2: Optional[SecretStr] = Field(default=None)
    GEMINI_LOGO_KEY_3: Optional[SecretStr] = Field(default=None)

    # ── Gemini keys — Stage 7 brand book (Pro → Flash fallback) ──────────
    GEMINI_BRAND_BOOK_KEY_1: Optional[SecretStr] = Field(default=None)
    GEMINI_BRAND_BOOK_KEY_2: Optional[SecretStr] = Field(default=None)
    GEMINI_BRAND_BOOK_KEY_3: Optional[SecretStr] = Field(default=None)
    GEMINI_BRAND_BOOK_KEY_4: Optional[SecretStr] = Field(default=None)

    # ── Legacy Gemini keys (kept for backward compat) ─────────────────────
    GEMINI_API_KEY: Optional[SecretStr] = Field(default=None)
    GEMINI_API_KEY_2: Optional[SecretStr] = Field(default=None)
    GEMINI_API_KEY_3: Optional[SecretStr] = Field(default=None)
    GEMINI_API_KEY_4: Optional[SecretStr] = Field(default=None)
    GEMINI_API_KEY_5: Optional[SecretStr] = Field(default=None)
    GEMINI_API_KEY_6: Optional[SecretStr] = Field(default=None)
    GEMINI_API_KEY_7: Optional[SecretStr] = Field(default=None)
    GEMINI_API_KEY_8: Optional[SecretStr] = Field(default=None)

    # ── Other keys ────────────────────────────────────────────────────────
    CEREBRAS_API_KEY: Optional[SecretStr] = Field(default=None)
    TAVILY_API_KEY: SecretStr = Field(...)
    GOOGLE_PLACES_API_KEY: SecretStr = Field(...)
    HF_API_KEY: Optional[SecretStr] = Field(default=None)

    # ── Model config ──────────────────────────────────────────────────────
    FAST_LLM_MODEL: str = Field(default="llama-3.1-8b-instant")
    LLM_MODEL: str = Field(default="llama-3.3-70b-versatile")
    GEMINI_MODEL: str = Field(default="gemini-2.5-flash")
    GEMINI_MODEL_PRO: str = Field(default="gemini-2.5-pro")
    GEMINI_IMAGE_MODEL: str = Field(default="gemini-2.5-flash-image")
    LLM_TEMPERATURE: float = Field(default=0.1, ge=0.0, le=1.0)
    DEFAULT_MAX_ITERATIONS: int = Field(default=2, ge=1, le=10)
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(default="INFO")

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


settings = AppSettings()