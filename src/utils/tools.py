from typing import List
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from src.utils.llm import settings

# Global reference to keep client alive
_mcp_client: MultiServerMCPClient | None = None
_all_tools: List[BaseTool] | None = None

async def load_mcp_tools() -> List[BaseTool]:
    """
    Load all MCP tools using MultiServerMCPClient as per langchain-mcp-adapters specification.
    """
    global _all_tools, _mcp_client
    
    if _all_tools is not None:
        return _all_tools
    
    # Build server configuration from settings
    server_config = settings.mcp_servers_config
    
    if not server_config:
        print("No MCP servers configured")
        _all_tools = []
        return _all_tools
    
    try:
        if _mcp_client is None:
            _mcp_client = MultiServerMCPClient(server_config)
        
        tools = await _mcp_client.get_tools()
        _all_tools = tools
        return tools
        
    except Exception as e:
        print(f"Failed to load MCP tools: {e}")
        _all_tools = []
        return _all_tools

def get_tool_by_name(tools: List[BaseTool], name: str) -> BaseTool | None:
    """Helper to find a tool by name."""
    return next((t for t in tools if t.name == name), None)