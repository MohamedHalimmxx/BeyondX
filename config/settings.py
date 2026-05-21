from typing import Literal
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """System-wide configuration registry validating active environment configurations."""

    # API Keys & Third-Party Infrastructure Endpoints
    GROQ_API_KEY: SecretStr = Field(
        ..., 
        description="Primary authentication vector for Groq Cloud API infrastructure."
    )
    TAVILY_API_KEY: SecretStr = Field(
        ..., 
        description="Target API key credential utilized by the underlying web discovery tool."
    )

    LLM_MODEL: str = Field(
        default="llama-3.3-70b-versatile", 
        description="Target Groq model. Llama-3-70B is highly recommended for structured tool-calling nodes."
    )
    LLM_TEMPERATURE: float = Field(
        default=0.1, 
        ge=0.0, 
        le=1.0, 
        description="Creativity variance anchor. Set ultra-low for consistent structural data extraction."
    )
    DEFAULT_MAX_ITERATIONS: int = Field(
        default=3, 
        ge=1, 
        le=5, 
        description="Global maximum upper bounds depth threshold for analytical looping."
    )

    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", 
        description="Internal telemetry resolution tracking criteria."
    )

    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8", 
        extra="ignore"
    )


settings = AppSettings()