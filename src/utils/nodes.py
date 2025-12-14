"""Node functions for the LangGraph workflow."""

from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, AIMessage

from .state import AgentState
from .llm import llm
from .tools import load_mcp_tools, get_tool_by_name
from ..mcp_wrapper.response_parser import (
    extract_indices_from_response,
    extract_mappings_from_response,
    extract_tabular_data_from_response,
    format_tabular_data_for_display,
    extract_error_from_response
)


# ============================================================================
# PYDANTIC MODELS FOR STRUCTURED OUTPUT
# ============================================================================

class IndexSelection(BaseModel):
    """Structured output for index selection."""
    selected_indices: List[str] = Field(description="List of relevant index names")
    reasoning: str = Field(description="Why these indices were selected")


class ESQLPlan(BaseModel):
    """Structured output for ES|QL generation."""
    query: str = Field(description="The ES|QL query")
    explanation: str = Field(description="What the query does")
    expected_fields: List[str] = Field(description="Expected result fields")


class CriticOutput(BaseModel):
    """Structured output for critic feedback."""
    improved_answer: str = Field(description="Enhanced final answer")
    improvements_made: List[str] = Field(description="List of improvements", default_factory=list)


# ============================================================================
# LANGGRAPH NODES
# ============================================================================

async def list_indices_node(state: AgentState) -> AgentState:
    """Discover available indices using MCP tool."""
    # Extract user query from the first HumanMessage
    user_query = state.get("user_query")
    if not user_query and state.get("messages"):
        for message in state["messages"]:
            if isinstance(message, HumanMessage):
                user_query = message.content
                break
    
    tools = await load_mcp_tools()
    list_tool = get_tool_by_name(tools, "platform_core_list_indices")
    
    if not list_tool:
        return {
            "all_indices": [], 
            "execution_error": "platform_core_list_indices tool not available",
            "user_query": user_query
        }
    
    try:
        result = await list_tool.ainvoke({})
        
        # Check for errors first
        error = extract_error_from_response(result)
        if error:
            return {
                "all_indices": [], 
                "execution_error": f"List indices failed: {error}",
                "user_query": user_query
            }
        
        # Extract indices and data streams
        indices, data_streams = extract_indices_from_response(result)
        all_indices = indices + data_streams
        
        return {
            "all_indices": all_indices,
            "user_query": user_query,  # Set extracted user query
            "messages": [AIMessage(content=f"Found {len(all_indices)} indices and data streams")]
        }
        
    except Exception as e:
        return {
            "all_indices": [], 
            "execution_error": f"Failed to list indices: {str(e)}",
            "user_query": user_query
        }


async def select_indices_node(state: AgentState) -> AgentState:
    """Select relevant indices using structured LLM output."""
    if not state.get("all_indices"):
        return {
            "selected_indices": [], 
            "execution_error": "No indices available",
            "user_query": state.get("user_query")
        }
    
    user_query = state.get("user_query", "")
    prompt = f"""
    IMPORTANT: The user asked: "{user_query}"
    
    Available indices: {state["all_indices"]}
    
    Analyze the user query and select the most relevant indices:
    
    Query Analysis:
    - If query mentions "orders", "order", "purchase" → select fluent-order-* or fluent-item_order-* indices
    - If query mentions "fulfilment", "fulfillment", "shipping" → select fluent-fulfilment-* or fluent-item_fulfilment-* indices  
    - If query mentions "inventory", "stock", "position" → select fluent-inventory_position-* indices
    - If query mentions "exception", "error", "failed" → select fluent-exception-* indices
    - If query mentions "return", "refund" → select fluent-item_return_order-* indices
    - If query mentions "logs", "web", "access" → select kibana_sample_data_logs
    
    Time Period Matching:
    - "nov 2025" or "november 2025" → look for indices with "2025.11"
    - "dec 2024" or "december 2024" → look for indices with "2024.12"
    - Match the time period in the query to the index naming pattern
    """
    
    structured_llm = llm.with_structured_output(IndexSelection)
    
    try:
        result = await structured_llm.ainvoke([HumanMessage(content=prompt)])
        return {
            "selected_indices": result.selected_indices,
            "user_query": state.get("user_query"),  # Preserve user query
            "messages": [AIMessage(content=f"Selected indices: {result.selected_indices}. Reasoning: {result.reasoning}")]
        }
    except Exception as e:
        return {
            "selected_indices": [], 
            "execution_error": f"Index selection failed: {str(e)}",
            "user_query": state.get("user_query")
        }


async def get_mappings_node(state: AgentState) -> AgentState:
    """Fetch index mappings using MCP tool."""
    if not state.get("selected_indices"):
        return {"mappings": {}, "execution_error": "No indices selected"}
    
    tools = await load_mcp_tools()
    mapping_tool = get_tool_by_name(tools, "platform_core_get_index_mapping")
    
    if not mapping_tool:
        return {"mappings": {}, "execution_error": "platform_core_get_index_mapping tool not available"}
    
    try:
        result = await mapping_tool.ainvoke({"indices": state["selected_indices"]})
        
        # Check for errors
        error = extract_error_from_response(result)
        if error:
            return {"mappings": {}, "execution_error": f"Get mappings failed: {error}"}
        
        # Extract mappings
        mappings = extract_mappings_from_response(result)
        
        return {
            "mappings": mappings,
            "user_query": state.get("user_query"),
            "selected_indices": state.get("selected_indices"),
            "all_indices": state.get("all_indices"),
            "messages": [AIMessage(content=f"Retrieved mappings for {len(state['selected_indices'])} indices")]
        }
        
    except Exception as e:
        return {"mappings": {}, "execution_error": f"Failed to get mappings: {str(e)}"}


async def generate_esql_node(state: AgentState) -> AgentState:
    """Generate ES|QL query using LLM."""
    prompt = f"""
    You are an expert ES|QL generator. Create an optimized, production-ready query.
    
    USER REQUEST: {state.get("user_query", "")}
    INDICES: {state.get("selected_indices", [])}
    MAPPINGS: {state.get("mappings", {})}
    
    GENERATE ES|QL QUERY following this structure:
    FROM index | WHERE filters | KEEP/DROP columns | EVAL computations | STATS aggregations | SORT | LIMIT
    
    CRITICAL RULES:
    • Field names MUST match mappings exactly (case-sensitive)
    • Filter early with WHERE for performance
    • Use STATS for aggregations: COUNT(*), SUM(), AVG(), MAX(), MIN()
    • Group with BY: STATS metric BY field or BUCKET(field, size)
    • Sort before LIMIT: SORT field DESC | LIMIT n
    • Handle nulls: COALESCE(field, default) or WHERE field IS NOT NULL
    • Escape special chars: `field.name` for dots/spaces
    • Time ranges: @timestamp >= NOW() - 1 DAY
    
    COMMON PATTERNS:
    • Top N: STATS total=SUM(field) BY group | SORT total DESC | LIMIT 10
    • Time series: STATS count=COUNT(*) BY bucket=BUCKET(@timestamp, 1 HOUR)
    • Filtering: WHERE field IN ("val1", "val2") AND numeric_field > 100
    • String ops: WHERE field LIKE "*pattern*" or REGEX field "regex"
    
    Return executable ES|QL ready for /_query endpoint.
    """
    
    structured_llm = llm.with_structured_output(ESQLPlan)
    
    try:
        result = await structured_llm.ainvoke([HumanMessage(content=prompt)])
        return {
            "esql_plan": result.model_dump(),
            "esql_query": result.query,
            "generation_success": True,
            "user_query": state.get("user_query"),
            "selected_indices": state.get("selected_indices"),
            "mappings": state.get("mappings"),
            "messages": [AIMessage(content=f"Generated ES|QL query: {result.query}")]
        }
    except Exception as e:
        return {
            "esql_plan": {},
            "esql_query": "",
            "generation_success": False,
            "execution_error": f"ES|QL generation failed: {str(e)}",
            "user_query": state.get("user_query"),
            "selected_indices": state.get("selected_indices"),
            "mappings": state.get("mappings")
        }


async def execute_esql_node(state: AgentState) -> AgentState:
    """Execute ES|QL query using MCP tool."""
    query = state.get("revised_esql_query") or state.get("esql_query")
    if not query:
        return {"execution_error": "No ES|QL query to execute"}
    
    tools = await load_mcp_tools()
    execute_tool = get_tool_by_name(tools, "platform_core_execute_esql")
    
    if not execute_tool:
        return {"execution_error": "platform_core_execute_esql tool not available"}
    
    try:
        result = await execute_tool.ainvoke({"query": query})
        
        # Check for errors
        error = extract_error_from_response(result)
        if error:
            return {
                "query_result": None,
                "execution_error": error,
                "retry_count": state.get("retry_count", 0) + 1,
                "user_query": state.get("user_query"),
                "esql_query": state.get("esql_query")
            }
        
        # Extract tabular data
        tabular_data = extract_tabular_data_from_response(result)
        
        if not tabular_data.get("columns"):
            return {
                "query_result": None,
                "execution_error": "No data returned from query",
                "retry_count": state.get("retry_count", 0) + 1,
                "user_query": state.get("user_query"),
                "esql_query": state.get("esql_query")
            }
        
        return {
            "query_result": tabular_data,
            "execution_error": None,
            "user_query": state.get("user_query"),
            "esql_query": state.get("esql_query"),
            "messages": [AIMessage(content=f"Query executed successfully, returned {len(tabular_data.get('values', []))} rows")]
        }
        
    except Exception as e:
        return {
            "query_result": None,
            "execution_error": str(e),
            "retry_count": state.get("retry_count", 0) + 1,
            "user_query": state.get("user_query"),
            "esql_query": state.get("esql_query")
        }


async def esql_evaluator_node(state: AgentState) -> AgentState:
    """Evaluate and revise failed ES|QL query."""
    error = state.get("execution_error", "")
    original_query = state.get("esql_query", "")
    
    prompt = f"""
    Original ES|QL query failed with error: {error}
    Original query: {original_query}
    Available mappings: {state.get("mappings", {})}
    
    Analyze the error and generate a corrected ES|QL query. Common fixes:
    - Fix field name typos
    - Correct syntax errors
    - Adjust data type handling
    - Fix aggregation syntax
    """
    
    structured_llm = llm.with_structured_output(ESQLPlan)
    
    try:
        result = await structured_llm.ainvoke([HumanMessage(content=prompt)])
        return {
            "revised_esql_plan": result.model_dump(),
            "revised_esql_query": result.query,
            "user_query": state.get("user_query"),
            "esql_query": state.get("esql_query"),
            "mappings": state.get("mappings"),
            "messages": [AIMessage(content=f"Revised ES|QL query: {result.query}")]
        }
    except Exception as e:
        return {
            "execution_error": f"ES|QL revision failed: {str(e)}",
            "user_query": state.get("user_query"),
            "esql_query": state.get("esql_query")
        }


async def finalize_answer_node(state: AgentState) -> AgentState:
    """Create final answer from query results."""
    result = state.get("query_result")
    query = state.get("revised_esql_query") or state.get("esql_query")
    user_query = state.get("user_query", "")
    
    if not result:
        return {"messages": [AIMessage(content="No results available to answer your question.")]}
    
    # Format the tabular data for better readability
    formatted_data = format_tabular_data_for_display(result)
    
    prompt = f"""
    User asked: {user_query}
    ES|QL query executed: {query}
    
    Query results:
    {formatted_data}
    
    Provide a clear, business-focused answer to the user's question based on these results.
    Include relevant data points and insights. Summarize key findings from the data.
    """
    
    try:
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        return {
            "messages": [response],
            "user_query": state.get("user_query"),
            "query_result": state.get("query_result")
        }
    except Exception as e:
        return {
            "messages": [AIMessage(content=f"Failed to generate final answer: {str(e)}")],
            "user_query": state.get("user_query")
        }


async def critic_node(state: AgentState) -> AgentState:
    """Improve the final answer using structured output."""
    if not state.get("messages"):
        return {"critique": {}, "improved_answer": "No answer to critique"}
    
    last_message = state["messages"][-1]
    current_answer = last_message.content if hasattr(last_message, 'content') else str(last_message)
    
    prompt = f"""
    Original user query: {state.get("user_query", "")}
    Current answer: {current_answer}
    Query results: {state.get("query_result")}
    
    Improve this answer by:
    - Adding more context and insights
    - Improving clarity and structure
    - Highlighting key findings
    - Making it more actionable
    """
    
    structured_llm = llm.with_structured_output(CriticOutput)
    
    try:
        result = await structured_llm.ainvoke([HumanMessage(content=prompt)])
        return {
            "critique": result.model_dump(),
            "improved_answer": result.improved_answer,
            "user_query": state.get("user_query"),
            "query_result": state.get("query_result"),
            "messages": [AIMessage(content=result.improved_answer)]
        }
    except Exception as e:
        return {
            "critique": {},
            "improved_answer": current_answer,
            "execution_error": f"Critic failed: {str(e)}",
            "user_query": state.get("user_query")
        }


# ============================================================================
# CONDITIONAL ROUTING
# ============================================================================

def should_retry(state: AgentState) -> Literal["esql_evaluator", "finalize_answer"]:
    """Determine if we should retry or finalize based on execution results."""
    has_error = bool(state.get("execution_error"))
    retry_count = state.get("retry_count", 0)
    max_retries = 3
    
    if has_error and retry_count < max_retries:
        return "esql_evaluator"
    return "finalize_answer"


def should_get_mappings(state: AgentState) -> Literal["get_mappings", "generate_esql"]:
    """Determine if we need to fetch mappings."""
    if state.get("selected_indices") and not state.get("mappings"):
        return "get_mappings"
    return "generate_esql"