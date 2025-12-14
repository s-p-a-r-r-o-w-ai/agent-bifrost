from typing import List, Dict, Any
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient as BaseMultiServerMCPClient
from core.config import settings

class MultiServerMCPClient:
    """
    Wrapper around langchain_mcp_adapters.client.MultiServerMCPClient.
    Acts as a plug-n-play client using configuration from settings.
    """
    
    def __init__(self, server_config: Dict[str, Any] = None):
        # Use provided config or fallback to settings
        config = server_config if server_config is not None else settings.mcp_servers_config
        
        if config:
            self.client = BaseMultiServerMCPClient(config)
        else:
            self.client = None

    async def get_all_tools(self) -> List[BaseTool]:
        """
        Returns tools from all configured servers.
        """
        if not self.client:
            return []
        
        try:
             return await self.client.get_tools()
        except Exception as e:
            print(f"Error loading tools: {e}")
            # Printing simple traceback for debugging if needed but keeping it cleaner
            import traceback
            traceback.print_exc()
            return []

    async def aclose(self):
        """Close connections if needed."""
        if self.client and hasattr(self.client, "aclose"):
            await self.client.aclose()
        elif self.client and hasattr(self.client, "close"):
            if hasattr(self.client.close, "__await__") or hasattr(self.client.close, "__code__") and "async" in str(self.client.close):
                 await self.client.close()
