import os
from pathlib import Path

from dotenv import load_dotenv

_project_root = Path(__file__).resolve().parent.parent
load_dotenv(_project_root / ".env")

# 项目默认配置信息
class DefaultSettings:
    glm_default_settings = {  # 默认模型配置
        "model": "glm-5.1",
        "api_key": os.getenv("GLM_API_KEY", ""),
        "base_url": os.getenv("GLM_BASE_URL", ""),
        "model_provider": "anthropic",
    }
