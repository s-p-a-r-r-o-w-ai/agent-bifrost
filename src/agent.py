"""Agent Bifrost - Main graph construction."""

from typing import Dict, Any
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage

from .utils import (
    AgentState,
    list_indices_node,
    select_indices_node,
    get_mappings_node,
    generate_esql_node,
    execute_esql_node,
    esql_evaluator_node,
    finalize_answer_node,
    critic_node,
    should_retry,
    should_get_mappings
)


def create_workflow() -> StateGraph:
    """Create the complete LangGraph workflow."""
    workflow = StateGraph(AgentState)
    
    # Add all nodes
    workflow.add_node("list_indices", list_indices_node)
    workflow.add_node("select_indices", select_indices_node)
    workflow.add_node("get_mappings", get_mappings_node)
    workflow.add_node("generate_esql", generate_esql_node)
    workflow.add_node("execute_esql", execute_esql_node)
    workflow.add_node("esql_evaluator", esql_evaluator_node)
    workflow.add_node("finalize_answer", finalize_answer_node)
    workflow.add_node("critic", critic_node)
    
    # Define the flow
    workflow.add_edge(START, "list_indices")
    workflow.add_edge("list_indices", "select_indices")
    workflow.add_conditional_edges("select_indices", should_get_mappings)
    workflow.add_edge("get_mappings", "generate_esql")
    workflow.add_edge("generate_esql", "execute_esql")
    workflow.add_conditional_edges("execute_esql", should_retry)
    workflow.add_edge("esql_evaluator", "execute_esql")  # Retry loop
    workflow.add_edge("finalize_answer", "critic")
    workflow.add_edge("critic", END)
    
    return workflow


async def run_workflow(user_query: str) -> Dict[str, Any]:
    """Execute the complete workflow for a user query."""
    workflow = create_workflow()
    memory = MemorySaver()
    app = workflow.compile(checkpointer=memory)
    
    # Initial state
    initial_state = {
        "user_query": user_query,
        "messages": [HumanMessage(content=user_query)],
        "retry_count": 0,
        "generation_success": False
    }
    
    # Execute workflow
    config = {"configurable": {"thread_id": "main"}}
    final_state = await app.ainvoke(initial_state, config)
    
    return final_state


# Export for LangGraph dev server
compile_graph = create_workflow().compile()