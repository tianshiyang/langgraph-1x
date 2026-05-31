import os
from langchain.chat_models import init_chat_model

glm_model = init_chat_model(
    model="glm-5.1",
    api_key=os.getenv("GLM_API_KEY"),
    model_provider="anthropic",
    base_url=os.getenv("GLM_BASE_URL"),
)
