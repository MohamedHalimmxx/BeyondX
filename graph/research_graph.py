import logging
from typing import Any, Literal
from langgraph.graph import StateGraph, START, END
from state.research_state import ResearchState
from nodes.planner_node import planner_node
from nodes.research_node import research_node
from nodes.reflection_node import reflection_node
from nodes.report_node import report_node

logger = logging.getLogger("research_agent.graph.research_graph")


def route_research_loop(state: ResearchState) -> Literal["research_node", "report_node"]:
    """Evaluates the latest reflection analysis to determine the next graph edge.
    
    Args:
        state: Comprehensive current operational execution scope.
        
    Returns:
        The target node identity string to guide state progression.
    """
    verdict = state.get("reflection_verdict")
    current_iteration = state.get("iteration", 0)
    max_iterations = state.get("max_iterations", 3)

    if not verdict:
        logger.warning("No reflection verdict metadata discovered. Defaulting immediately to report phase.")
        return "report_node"

    # Extract boolean decision metrics
    is_complete = verdict.get("is_complete", True)
    reasoning = verdict.get("reasoning", "")

    if is_complete:
        logger.info(f"Routing Decision -> Proceeding to Report Synthesis. Reason: {reasoning}")
        return "report_node"
        
    if current_iteration >= max_iterations:
        logger.warning(f"Routing Decision -> Forcing Report Synthesis. Loop limit encountered ({current_iteration}/{max_iterations}).")
        return "report_node"

    logger.info(f"Routing Decision -> Continuing Exploration Loop. Turn index: {current_iteration}. Target vector: {verdict.get('next_question')}")
    return "research_node"


def compile_research_graph() -> StateGraph:
    """Constructs, connects, and compiles the autonomous execution state graph.
    
    Returns:
        A compiled, executable instance of StateGraph.
    """
    logger.info("Initializing LangGraph workflow builder blueprint configuration.")
    
    workflow = StateGraph(ResearchState)

    workflow.add_node("planner_node", planner_node)
    workflow.add_node("research_node", research_node)
    workflow.add_node("reflection_node", reflection_node)
    workflow.add_node("report_node", report_node)

    workflow.add_edge(START, "planner_node")
    workflow.add_edge("planner_node", "research_node")
    workflow.add_edge("research_node", "reflection_node")

    workflow.add_conditional_edges(
        source="reflection_node",
        path=route_research_loop,
        path_map={
            "research_node": "research_node",
            "report_node": "report_node"
        }
    )

    workflow.add_edge("report_node", END)
    logger.info("Compiling compiled execution graph infrastructure.")
    return workflow.compile()