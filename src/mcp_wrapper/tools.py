from typing import List
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from src.llm.chat_model import settings

class MCPToolsManager:
    """Singleton manager for MCP tools to avoid global variable issues."""
    _instance = None
    _mcp_client: MultiServerMCPClient | None = None
    _all_tools: List[BaseTool] | None = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    async def get_tools(self) -> List[BaseTool]:
        if self._all_tools is not None:
            return self._all_tools
        
        server_config = settings.mcp_servers_config
        
        if not server_config:
            print("No MCP servers configured")
            self._all_tools = []
            return self._all_tools
        
        try:
            if self._mcp_client is None:
                self._mcp_client = MultiServerMCPClient(server_config)
            
            tools = await self._mcp_client.get_tools()
            self._all_tools = tools
            return tools
            
        except Exception as e:
            print(f"Failed to load MCP tools: {e}")
            self._all_tools = []
            return self._all_tools

async def load_mcp_tools() -> List[BaseTool]:
    """Load all MCP tools using singleton manager."""
    manager = MCPToolsManager()
    return await manager.get_tools()

def get_tool_by_name(tools: List[BaseTool], name: str) -> BaseTool | None:
    """Helper to find a tool by name."""
    return next((t for t in tools if t.name == name), None)