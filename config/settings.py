import os
from pathlib import Path

from dotenv import load_dotenv

# Step 1: 先加载 .env
_project_root = Path(__file__).resolve().parent.parent
load_dotenv(_project_root / ".env")

# Step 2: 导出常用配置常量
GLM_API_KEY = os.getenv("GLM_API_KEY", "")
GLM_BASE_URL = os.getenv("GLM_BASE_URL", "")

# Step 3: env 加载后再导入模型
from llms import glm_model  # noqa: E402

default_model = glm_model
