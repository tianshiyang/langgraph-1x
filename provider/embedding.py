import os

from dotenv import load_dotenv
from langchain_community.embeddings import DashScopeEmbeddings

load_dotenv()

# os.environ[...] 返回 str（非 str | None），变量必存在时用它即可，无需非空断言
embeddings = DashScopeEmbeddings(
    model=os.environ["ALI_EMBEDDINGS_MODEL"],
    dashscope_api_key=os.environ["ALI_DASHSCOPE_API_KEY"],
)

if __name__ == "__main__":
    print(embeddings.embed_query("你好"))
