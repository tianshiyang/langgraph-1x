import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")

DB_URI = os.environ["DB_URI"]  # 形如 postgresql://user:pwd@localhost:5432/langgraph
EMBED_DIMS = 1024  # ⭐️ text-embedding-v3 的维度；换模型记得改这里
