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

    # Logging Configuration
    LOG_LEVEL: str = "INFO"
    LOG_DIR: str = "logs"
    LOG_MAX_BYTES: int = 10485760  # 10MB
    LOG_BACKUP_COUNT: int = 5

    def _create_headers(self, auth_token: SecretStr | None = None, auth_type: str = "Bearer") -> dict:
        """Create headers with optional authorization."""
        headers = {"Content-Type": "application/json"}
        if auth_token:
            headers["Authorization"] = f"{auth_type} {auth_token.get_secret_value()}"
        return headers

    @property
    def mcp_servers_config(self) -> dict:
        """
        Returns a dictionary configuration for MultiServerMCPClient.
        """
        servers = {}
        
        if self.MCP_SERVER_ES_URL:
            servers["elasticsearch"] = {
                "transport": "http",
                "url": self.MCP_SERVER_ES_URL,
                "headers": self._create_headers(self.MCP_SERVER_ES_API_KEY, "ApiKey")
            }

        if self.MCP_SERVER_KIBANA_URL:
            servers["kibana"] = {
                "transport": "http",
                "url": self.MCP_SERVER_KIBANA_URL,
                "headers": self._create_headers(self.MCP_SERVER_KIBANA_TOKEN)
            }
            
        return servers

settings = Settings()