"""
MCP Response Parser - Handles parsing of complex MCP tool responses.
All MCP tools return responses in a nested structure that needs careful parsing.
"""

import json
from typing import Dict, List, Any, Optional, Tuple


def parse_mcp_response(response: Any) -> Dict[str, Any]:
    """
    Parse the standard MCP response structure.
    
    MCP responses follow this pattern:
    {
        "content": [
            {
                "type": "text",
                "text": "{\"results\":[{\"type\":\"...\", \"data\":{...}, \"tool_result_id\":\"...\"}]}"
            }
        ]
    }
    """
    try:
        # Handle direct response format
        if isinstance(response, dict) and "content" in response:
            content = response["content"]
            if isinstance(content, list) and content:
                text_content = content[0].get("text", "")
                if text_content:
                    return json.loads(text_content)
        
        # Handle legacy format (list with dict containing text)
        elif isinstance(response, list) and response:
            first_item = response[0]
            if isinstance(first_item, dict) and "text" in first_item:
                return json.loads(first_item["text"])
        
        return {"results": []}
        
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        print(f"Failed to parse MCP response: {e}")
        return {"results": []}


def extract_indices_from_response(response: Any) -> Tuple[List[str], List[str]]:
    """
    Extract index names and data stream names from list_indices response.
    
    Returns:
        Tuple of (indices, data_streams)
    """
    parsed = parse_mcp_response(response)
    indices = []
    data_streams = []
    
    try:
        results = parsed.get("results", [])
        if results:
            data = results[0].get("data", {})
            
            # Extract regular indices
            indices_data = data.get("indices", [])
            indices = [idx["name"] for idx in indices_data if idx.get("name")]
            
            # Extract data streams
            streams_data = data.get("data_streams", [])
            data_streams = [stream["name"] for stream in streams_data if stream.get("name")]
            
    except (KeyError, IndexError, TypeError) as e:
        print(f"Failed to extract indices: {e}")
    
    return indices, data_streams


def extract_mappings_from_response(response: Any) -> Dict[str, Any]:
    """
    Extract index mappings from get_index_mapping response.
    
    Returns:
        Dictionary of index mappings
    """
    parsed = parse_mcp_response(response)
    mappings = {}
    
    try:
        results = parsed.get("results", [])
        if results:
            data = results[0].get("data", {})
            mappings = data.get("mappings", {})
            
    except (KeyError, IndexError, TypeError) as e:
        print(f"Failed to extract mappings: {e}")
    
    return mappings


def extract_esql_from_response(response: Any) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract ES|QL query and explanation from generate_esql response.
    
    Returns:
        Tuple of (query, explanation)
    """
    parsed = parse_mcp_response(response)
    query = None
    explanation = None
    
    try:
        results = parsed.get("results", [])
        
        for result in results:
            result_type = result.get("type")
            data = result.get("data", {})
            
            if result_type == "query":
                query = data.get("esql")
            elif result_type == "other":
                explanation = data.get("answer")
                
    except (KeyError, IndexError, TypeError) as e:
        print(f"Failed to extract ES|QL: {e}")
    
    return query, explanation


def extract_tabular_data_from_response(response: Any) -> Dict[str, Any]:
    """
    Extract tabular data from execute_esql response.
    
    Returns:
        Dictionary containing columns, values, and metadata
    """
    parsed = parse_mcp_response(response)
    result_data = {
        "columns": [],
        "values": [],
        "query": None,
        "source": None
    }
    
    try:
        results = parsed.get("results", [])
        
        for result in results:
            result_type = result.get("type")
            data = result.get("data", {})
            
            if result_type == "tabular_data":
                result_data.update({
                    "columns": data.get("columns", []),
                    "values": data.get("values", []),
                    "query": data.get("query"),
                    "source": data.get("source")
                })
                break
            elif result_type == "query":
                result_data["query"] = data.get("esql")
                
    except (KeyError, IndexError, TypeError) as e:
        print(f"Failed to extract tabular data: {e}")
    
    return result_data


def format_tabular_data_for_display(tabular_data: Dict[str, Any]) -> str:
    """
    Format tabular data into a readable string representation.
    """
    if not tabular_data.get("columns") or not tabular_data.get("values"):
        return "No data returned from query."
    
    columns = tabular_data["columns"]
    values = tabular_data["values"]
    
    # Create header
    header = " | ".join([col["name"] for col in columns])
    separator = "-" * len(header)
    
    # Format rows
    rows = []
    for row in values[:10]:  # Limit to first 10 rows for display
        formatted_row = []
        for i, value in enumerate(row):
            # Handle different data types
            if value is None:
                formatted_row.append("null")
            elif isinstance(value, str) and len(value) > 50:
                formatted_row.append(value[:47] + "...")
            else:
                formatted_row.append(str(value))
        rows.append(" | ".join(formatted_row))
    
    result = f"{header}\n{separator}\n" + "\n".join(rows)
    
    if len(values) > 10:
        result += f"\n... and {len(values) - 10} more rows"
    
    return result


def extract_error_from_response(response: Any) -> Optional[str]:
    """
    Extract error message from MCP response if present.
    """
    try:
        parsed = parse_mcp_response(response)
        results = parsed.get("results", [])
        
        for result in results:
            if result.get("type") == "error":
                return result.get("data", {}).get("message", "Unknown error")
                
        return None
        
    except Exception:
        return None