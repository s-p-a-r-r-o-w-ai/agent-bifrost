"""Node functions for the LangGraph workflow."""

from typing import List, Literal, Dict, Any
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

from src.utils.logger import get_logger
from src.utils.csv_handler import save_query_result_to_csv, generate_download_url, get_csv_summary
from src.utils.mapping_flattener import deduplicate_fields_across_indices

logger = get_logger("es_agent")

from src.graph.state import AgentState
from src.llm.chat_model import llm
from src.mcp_wrapper.tools import load_mcp_tools, get_tool_by_name
from src.mcp_wrapper.response_parser import (
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


class ESQLPlan(BaseModel):
    """Structured output for ES|QL generation."""
    query: str = Field(description="The ES|QL query")
    expected_fields: List[str] = Field(description="Expected result fields")





# ============================================================================
# LANGGRAPH NODES
# ============================================================================

async def list_indices_node(state: AgentState) -> AgentState:
    """Discover available indices using MCP tool."""
    logger.info("Starting list_indices_node")
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
        logger.error("platform_core_list_indices tool not available")
        return {
            "all_indices": [], 
            "execution_error": "platform_core_list_indices tool not available",
            "user_query": user_query
        }
    
    try:
        result = await list_tool.ainvoke({})
        
        # Add ToolMessage for MCP tool execution
        tool_message = ToolMessage(
            content=f"Listed indices using {list_tool.name}",
            tool_call_id="list_indices_call"
        )
        
        # Check for errors first
        error = extract_error_from_response(result)
        if error:
            return {
                "all_indices": [], 
                "execution_error": f"List indices failed: {error}",
                "user_query": user_query,
                "messages": [tool_message, AIMessage(content=f"Failed to list indices: {error}")]
            }
        
        # Extract indices and data streams
        indices, data_streams = extract_indices_from_response(result)
        all_indices = indices + data_streams
        
        logger.info(f"Found {len(all_indices)} indices and data streams")
        return {
            "all_indices": all_indices,
            "user_query": user_query,
            "messages": [tool_message, AIMessage(content=f"Found {len(all_indices)} indices and data streams")]
        }
        
    except Exception as e:
        logger.error(f"Failed to list indices: {str(e)}", exc_info=True)
        return {
            "all_indices": [], 
            "execution_error": f"Failed to list indices: {str(e)}",
            "user_query": user_query,
            "messages": [AIMessage(content=f"Error listing indices: {str(e)}")]
        }


def _create_index_selection_prompt(user_query: str, available_indices: list[str]) -> str:
    return f"""
You are an expert Elasticsearch index-selection agent.

TASK
----
From the provided list ONLY, select the MOST relevant index names or wildcard
patterns needed to answer the user query. Choose the smallest accurate set.

INPUTS
------
User query:
{user_query}

Available indices:
{available_indices}

SELECTION LOGIC
---------------
1. Infer intent and business domain from the query
   (orders, order items, fulfillments, inventory, returns, errors, logs, etc.).
   - Distinguish aggregate vs item-level entities.
   - If both are implied, include both.

2. Match inferred concepts to index names by semantic meaning,
   not hardcoded keyword rules.
   - Prefer clearly aligned indices.
   - Use wildcards for versioned or date-suffixed indices (e.g., orders-*).

3. Time awareness:
   - If a time range/month/year is mentioned, narrow the pattern accordingly
     (YYYY, YYYY.MM, YYYY.MM.DD).
   - If no time is mentioned, use a relevant broad wildcard.

4. Precision rules:
   - Do not select weakly related indices.
   - Do not invent indices.
   - Prefer fewer, higher-confidence indices.

OUTPUT (STRICT)
---------------
Return ONLY valid JSON:

{{"selected_indices": ["index1", "index2"]}}

No extra text.

"""


async def select_indices_node(state: AgentState) -> AgentState:
    """Select relevant indices using structured LLM output."""
    logger.info("Starting select_indices_node")
    if not state.get("all_indices"):
        return {
            "selected_indices": [], 
            "execution_error": "No indices available",
            "user_query": state.get("user_query")
        }
    
    user_query = state.get("user_query", "")
    prompt = _create_index_selection_prompt(user_query, state["all_indices"])
    
    structured_llm = llm.with_structured_output(IndexSelection)
    
    try:
        result = await structured_llm.ainvoke([HumanMessage(content=prompt)])
        return {
            "selected_indices": result.selected_indices,
            "user_query": state.get("user_query"),  # Preserve user query
            "messages": [AIMessage(content=f"Selected indices: {result.selected_indices}.")]
        }
    except Exception as e:
        return {
            "selected_indices": [], 
            "execution_error": f"Index selection failed: {str(e)}",
            "user_query": state.get("user_query")
        }


async def get_mappings_node(state: AgentState) -> AgentState:
    """Fetch and flatten index mappings using MCP tool."""
    if not state.get("selected_indices"):
        return {"flattened_fields": {}, "execution_error": "No indices selected"}
    
    tools = await load_mcp_tools()
    mapping_tool = get_tool_by_name(tools, "platform_core_get_index_mapping")
    
    if not mapping_tool:
        return {"flattened_fields": {}, "execution_error": "platform_core_get_index_mapping tool not available"}
    
    try:
        result = await mapping_tool.ainvoke({"indices": state["selected_indices"]})
        
        tool_message = ToolMessage(
            content=f"Retrieved mappings using {mapping_tool.name}",
            tool_call_id="get_mappings_call"
        )
        
        # Check for errors
        error = extract_error_from_response(result)
        if error:
            return {"flattened_fields": {}, "execution_error": f"Get mappings failed: {error}"}
        
        # Extract and flatten mappings
        mappings = extract_mappings_from_response(result)
        logger.info(f"Raw mappings extracted: {mappings}")
        
        flattened_fields = deduplicate_fields_across_indices(mappings)
        logger.info(f"Flattened fields: {flattened_fields}")
        
        return {
            "flattened_fields": flattened_fields,
            "user_query": state.get("user_query"),
            "selected_indices": state.get("selected_indices"),
            "messages": [tool_message, AIMessage(content=f"Flattened {len(flattened_fields)} unique fields from {len(state['selected_indices'])} indices")]
        }
        
    except Exception as e:
        return {"flattened_fields": {}, "execution_error": f"Failed to get mappings: {str(e)}"}


async def generate_esql_node(state: AgentState) -> AgentState:
    """Generate ES|QL query using LLM."""
    logger.info("Starting generate_esql_node")
    flattened_fields = state.get("flattened_fields", {})
    
    prompt = f"""
    Generate ES|QL for: {state.get("user_query", "")}
    Indices: {state.get("selected_indices", [])}
    Available fields: {flattened_fields}
    
    GENERATE ES|QL QUERY following this structure:
    FROM index-pattern | WHERE filters | KEEP/DROP columns | EVAL computations | STATS aggregations | SORT | LIMIT
    
    CRITICAL RULES:
    • Use index patterns with wildcards exactly as provided (e.g., fluent-*, kibana_sample_data_logs)
    • Field names MUST match mappings exactly (case-sensitive)
    • Filter early with WHERE for performance
    • Use STATS for aggregations: COUNT(*), SUM(), AVG(), MAX(), MIN()
    • Group with BY: STATS metric BY field or BUCKET(field, size)
    • Sort before LIMIT: SORT field DESC | LIMIT n
    • Handle nulls: COALESCE(field, default) or WHERE field IS NOT NULL
    • Escape special chars: `field.name` for dots/spaces
    • Time ranges: @timestamp >= NOW() - 1 DAY
    
    COMMON PATTERNS:
    • Top N: STATS total=COUNT(*) BY group | SORT total DESC | LIMIT 10
    • Time series: STATS count=COUNT(*) BY bucket=BUCKET(@timestamp, 1 HOUR)
    • Filtering: WHERE field IN ("val1", "val2") AND numeric_field > 100
    • String ops: WHERE field LIKE "*pattern*" or REGEX field "regex"
    
    IMPORTANT: Use the selected indices directly in FROM clause, including wildcards.
               Create query with LIMIT 10.
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
            "flattened_fields": state.get("flattened_fields"),
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
            "flattened_fields": state.get("flattened_fields")
        }


async def execute_esql_node(state: AgentState) -> AgentState:
    """Execute ES|QL query using MCP tool with dual execution strategy."""
    query = state.get("revised_esql_query") or state.get("esql_query")
    logger.info(f"Executing ES|QL query: {query[:100]}...")
    if not query:
        return {"execution_error": "No ES|QL query to execute"}
    
    tools = await load_mcp_tools()
    execute_tool = get_tool_by_name(tools, "platform_core_execute_esql")
    
    if not execute_tool:
        return {"execution_error": "platform_core_execute_esql tool not available"}
    
    try:
        # First execute with LIMIT 10 for LLM analysis
        limited_query = query
        if "LIMIT" not in query.upper():
            limited_query = f"{query} | LIMIT 10"
        elif "LIMIT" in query.upper():
            # Replace existing limit with 10
            import re
            limited_query = re.sub(r'LIMIT\s+\d+', 'LIMIT 10', query, flags=re.IGNORECASE)
        
        result = await execute_tool.ainvoke({"query": limited_query})
        
        tool_message = ToolMessage(
            content=f"Executed ES|QL query using {execute_tool.name}",
            tool_call_id="execute_esql_call"
        )
        
        # Check for errors
        error = extract_error_from_response(result)
        if error:
            return {
                "query_result": None,
                "execution_error": error,
                "retry_count": state.get("retry_count", 0) + 1,
                "user_query": state.get("user_query"),
                "selected_indices": state.get("selected_indices"),
                "flattened_fields": state.get("flattened_fields"),
                "all_indices": state.get("all_indices"),
                "esql_query": state.get("esql_query"),
                "revised_esql_query": state.get("revised_esql_query"),
                "messages": [tool_message]
            }
        
        # Extract tabular data
        tabular_data = extract_tabular_data_from_response(result)
        
        if not tabular_data.get("columns"):
            return {
                "query_result": None,
                "execution_error": "No data returned from query",
                "retry_count": state.get("retry_count", 0) + 1,
                "user_query": state.get("user_query"),
                "selected_indices": state.get("selected_indices"),
                "flattened_fields": state.get("flattened_fields"),
                "all_indices": state.get("all_indices"),
                "esql_query": state.get("esql_query"),
                "revised_esql_query": state.get("revised_esql_query"),
                "messages": [tool_message]
            }
        
        # Execute full query with 100K limit for CSV - don't store in state to avoid memory issues
        full_query = query
        if "LIMIT" not in query.upper():
            full_query = f"{query} | LIMIT 100000"
        else:
            import re
            full_query = re.sub(r'LIMIT\s+\d+', 'LIMIT 100000', query, flags=re.IGNORECASE)
        
        # Execute and directly save to CSV without storing in state
        csv_file_path = None
        csv_download_url = None
        
        try:
            full_result = await execute_tool.ainvoke({"query": full_query})
            full_tabular_data = extract_tabular_data_from_response(full_result)
            
            if full_tabular_data and full_tabular_data.get("values"):
                logger.info(f"Generating CSV for {len(full_tabular_data['values'])} rows")
                csv_file_path = await save_query_result_to_csv(full_tabular_data, state.get("user_query", ""))
                if csv_file_path:
                    csv_download_url = generate_download_url(csv_file_path)
                    logger.info(f"CSV generated: {csv_file_path}")
        except Exception as e:
            logger.error(f"Failed to generate CSV: {e}")
        
        return {
            "query_result": tabular_data,
            "execution_error": None,
            "user_query": state.get("user_query"),
            "selected_indices": state.get("selected_indices"),
            "flattened_fields": state.get("flattened_fields"),
            "all_indices": state.get("all_indices"),
            "esql_query": state.get("esql_query"),
            "revised_esql_query": state.get("revised_esql_query"),
            "csv_file_path": csv_file_path,
            "csv_download_url": csv_download_url,
            "messages": [tool_message, AIMessage(content=f"Query executed successfully, returned {len(tabular_data.get('values', []))} rows for analysis")]
        }
        
    except Exception as e:
        return {
            "query_result": None,
            "execution_error": str(e),
            "retry_count": state.get("retry_count", 0) + 1,
            "user_query": state.get("user_query"),
            "selected_indices": state.get("selected_indices"),
            "flattened_fields": state.get("flattened_fields"),
            "all_indices": state.get("all_indices"),
            "esql_query": state.get("esql_query"),
            "revised_esql_query": state.get("revised_esql_query")
        }


async def esql_evaluator_node(state: AgentState) -> AgentState:
    """Evaluate and revise failed ES|QL query."""
    error = state.get("execution_error", "")
    current_query = state.get("revised_esql_query") or state.get("esql_query", "")
    
    prompt = f"""
    ES|QL query failed with error: {error}
    Current query: {current_query}
    Available fields: {state.get("flattened_fields", {})}
    
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
            "execution_error": None,  # Clear error for retry
            "user_query": state.get("user_query"),
            "selected_indices": state.get("selected_indices"),
            "flattened_fields": state.get("flattened_fields"),
            "all_indices": state.get("all_indices"),
            "esql_query": state.get("esql_query"),  # Keep original
            "retry_count": state.get("retry_count", 0),
            "messages": [AIMessage(content=f"Revised ES|QL query: {result.query}")]
        }
    except Exception as e:
        return {
            "execution_error": f"ES|QL revision failed: {str(e)}",
            "user_query": state.get("user_query"),
            "esql_query": state.get("esql_query"),
            "retry_count": state.get("retry_count", 0)
        }


def _format_table_display(tabular_data: Dict[str, Any]) -> str:
    """Format tabular data as markdown table."""
    if not tabular_data.get("columns") or not tabular_data.get("values"):
        return "No data available."
    
    columns = [col["name"] if isinstance(col, dict) else str(col) for col in tabular_data["columns"]]
    values = tabular_data["values"]
    
    # Create markdown table
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join(["---"] * len(columns)) + " |"
    
    rows = []
    for row in values:
        formatted_row = []
        for val in row:
            if val is None:
                formatted_row.append("null")
            elif isinstance(val, str) and len(val) > 30:
                formatted_row.append(val[:27] + "...")
            else:
                formatted_row.append(str(val))
        rows.append("| " + " | ".join(formatted_row) + " |")
    
    return "\n".join([header, separator] + rows)


async def finalize_answer_node(state: AgentState) -> AgentState:
    """Create comprehensive final answer with CSV export for large datasets."""
    result = state.get("query_result")
    query = state.get("revised_esql_query") or state.get("esql_query")
    user_query = state.get("user_query", "")
    
    if not result:
        return {"messages": [AIMessage(content="No data found.")]}
    
    # Extract only column headers for LLM (token optimization)
    columns = result.get("columns", [])
    column_names = [col["name"] if isinstance(col, dict) else str(col) for col in columns]
    row_count = len(result.get("values", []))
    
    # Get CSV info
    csv_info = ""
    csv_file_path = state.get("csv_file_path")
    if csv_file_path:
        csv_summary = get_csv_summary(csv_file_path)
        csv_info = f"\n\n📊 **Complete Dataset Available**\nTotal rows: {csv_summary.get('row_count', 'Unknown')}\nFile size: {csv_summary.get('file_size_mb', 'Unknown')} MB\nFile: `{csv_summary.get('filename', 'dataset.csv')}`"
    
    prompt = f"""
    User asked: {user_query}
    ES|QL query executed: {query}
    
    Result columns: {column_names}
    Sample rows returned: {row_count}
    
    Provide a direct answer to the user's question based on the query.
    """
    
    try:
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        
        # Format data as table for display
        table_display = _format_table_display(result)
        
        # Combine LLM response with table and CSV info
        final_content = (response.content if hasattr(response, 'content') else str(response)) + \
                       f"\n\n{table_display}" + csv_info
        
        return {
            "messages": [AIMessage(content=final_content)],
            "user_query": state.get("user_query"),
            "query_result": state.get("query_result"),
            "csv_file_path": state.get("csv_file_path"),
            "csv_download_url": state.get("csv_download_url")
        }
    except Exception as e:
        return {
            "messages": [AIMessage(content=f"Error: {str(e)}")],
            "user_query": state.get("user_query"),
            "query_result": state.get("query_result"),
            "execution_error": f"Finalize answer failed: {str(e)}"
        }





# ============================================================================
# CONDITIONAL ROUTING
# ============================================================================

# Configuration constants
MAX_RETRY_ATTEMPTS = 3

def should_retry(state: AgentState) -> Literal["esql_evaluator", "finalize_answer"]:
    """Determine if we should retry or finalize based on execution results."""
    has_error = bool(state.get("execution_error"))
    retry_count = state.get("retry_count", 0)
    
    if has_error and retry_count < MAX_RETRY_ATTEMPTS:
        return "esql_evaluator"
    return "finalize_answer"


