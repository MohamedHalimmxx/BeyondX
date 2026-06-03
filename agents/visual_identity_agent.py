"""Visual Identity Agent — wraps the visual identity node."""

import logging
from pathlib import Path
from nodes.visual_identity_node import visual_identity_node, VisualIdentityOutput

logger = logging.getLogger("research_agent.agents.visual_identity_agent")


class VisualIdentityAgent:
    """Generates color palette, typography, and logo concepts for a brand."""

    async def generate_visual_identity(
        self,
        brand_name: str,
        identity,
        analysis,
        output_dir: Path = None,
    ) -> VisualIdentityOutput:
        logger.info("Initializing Visual Identity Agent.")
        return await visual_identity_node(
            brand_name=brand_name,
            identity=identity,
            analysis=analysis,
            output_dir=output_dir,
        )