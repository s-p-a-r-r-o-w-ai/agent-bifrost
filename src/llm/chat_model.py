import os
from langchain_aws import ChatBedrock
from src.config import settings

# Set environment variables for AWS (only if they have values and not already set)
if settings.AWS_ACCESS_KEY_ID and "AWS_ACCESS_KEY_ID" not in os.environ:
    os.environ["AWS_ACCESS_KEY_ID"] = settings.AWS_ACCESS_KEY_ID
if settings.AWS_SECRET_ACCESS_KEY and "AWS_SECRET_ACCESS_KEY" not in os.environ:
    os.environ["AWS_SECRET_ACCESS_KEY"] = settings.AWS_SECRET_ACCESS_KEY.get_secret_value()

if "AWS_DEFAULT_REGION" not in os.environ:
    os.environ["AWS_DEFAULT_REGION"] = settings.AWS_REGION

# Global LLM instance - handle ARN vs model ID
model_id = settings.AWS_MODEL_ID
if model_id.startswith("arn:aws:bedrock"):
    # For ARN, use model_id parameter
    llm = ChatBedrock(model_id=model_id, region_name=settings.AWS_REGION)
else:
    # For standard model names
    llm = ChatBedrock(model=model_id, region_name=settings.AWS_REGION)