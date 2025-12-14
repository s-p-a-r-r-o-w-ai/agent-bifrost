import os
from langchain_aws import ChatBedrock
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr, Field

class Settings(BaseSettings):
    """Application configuration settings."""
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # AWS Bedrock Credentials
    AWS_ACCESS_KEY_ID: str = Field(default="")
    AWS_SECRET_ACCESS_KEY: SecretStr = Field(default="")
    AWS_REGION: str = "us-east-1"
    AWS_MODEL_ID: str = "anthropic.claude-3-5-sonnet-20240620-v1:0"

    # Other API Keys
    OPENAI_API_KEY: SecretStr | None = None
    ANTHROPIC_API_KEY: SecretStr | None = None

    # MCP Servers
    MCP_SERVER_ES_URL: str | None = None
    MCP_SERVER_ES_API_KEY: SecretStr | None = None
    
    MCP_SERVER_KIBANA_URL: str | None = None
    MCP_SERVER_KIBANA_TOKEN: SecretStr | None = None

    @property
    def mcp_servers_config(self) -> dict:
        """
        Returns a dictionary configuration for MultiServerMCPClient.
        """
        servers = {}
        
        if self.MCP_SERVER_ES_URL:
            headers = {"Content-Type": "application/json"}
            if self.MCP_SERVER_ES_API_KEY:
                headers["Authorization"] = f"ApiKey {self.MCP_SERVER_ES_API_KEY.get_secret_value()}"
            
            servers["elasticsearch"] = {
                "transport": "http",
                "url": self.MCP_SERVER_ES_URL,
                "headers": headers
            }

        if self.MCP_SERVER_KIBANA_URL:
            headers = {"Content-Type": "application/json"}
            if self.MCP_SERVER_KIBANA_TOKEN:
                headers["Authorization"] = f"Bearer {self.MCP_SERVER_KIBANA_TOKEN.get_secret_value()}"
            
            servers["kibana"] = {
                "transport": "http",
                "url": self.MCP_SERVER_KIBANA_URL,
                "headers": headers
            }
            
        return servers

settings = Settings()

# Set environment variables for AWS (only if they have values)
if settings.AWS_ACCESS_KEY_ID:
    os.environ["AWS_ACCESS_KEY_ID"] = settings.AWS_ACCESS_KEY_ID
if settings.AWS_SECRET_ACCESS_KEY:
    os.environ["AWS_SECRET_ACCESS_KEY"] = settings.AWS_SECRET_ACCESS_KEY.get_secret_value()
os.environ["AWS_DEFAULT_REGION"] = settings.AWS_REGION

# Global LLM instance - handle ARN vs model ID
model_id = settings.AWS_MODEL_ID
if model_id.startswith("arn:aws:bedrock"):
    # For ARN, use model_id parameter
    llm = ChatBedrock(model_id=model_id, region_name=settings.AWS_REGION)
else:
    # For standard model names
    llm = ChatBedrock(model=model_id, region_name=settings.AWS_REGION)