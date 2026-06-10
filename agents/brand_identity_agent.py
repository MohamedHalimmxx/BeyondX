"""Brand Identity Agent — orchestrates the brand identity generation."""
import logging
from langchain_core.language_models.chat_models import BaseChatModel
from nodes.brand_identity_node import brand_identity_node
from state.brand_identity_state import BrandIdentityOutput
from config.llm_factory import get_brand_identity_llm

logger = logging.getLogger("research_agent.agents.brand_identity_agent")

class BrandIdentityAgent:
    def __init__(self):
        self.llm: BaseChatModel = get_brand_identity_llm()
        logger.info("Initializing Brand Identity Agent.")

    async def generate_identity(
        self,
        idea: str,
        positioning_statement: str,
        naming_output,
        analysis,
        brand_brief,
    ) -> BrandIdentityOutput:
        logger.info("Starting brand identity generation.")
        async def run(active_llm):
            return await brand_identity_node(
                idea=idea,
                positioning_statement=positioning_statement,
                naming_output=naming_output,
                analysis=analysis,
                brand_brief=brand_brief,
                llm=active_llm,
            )
        try:
            return await run(self.llm)
        except Exception as err:
            logger.error(f"Brand Identity Agent failed: {err}", exc_info=True)
            raise