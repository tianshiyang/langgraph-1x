import dotenv
from langchain_core.runnables import RunnableConfig
from langfuse import get_client
from langfuse.langchain import CallbackHandler

from provider import glm_model

dotenv.load_dotenv()

# v4 推荐：全程用 get_client() 返回的单例，不再另建 Langfuse() 实例
langfuse = get_client()
langfuse_handler = CallbackHandler()


if langfuse.auth_check():
    print("Langfuse连接成功")
else:
    print("认证失败，检查key和host是否填对")

prompt = langfuse.get_prompt("数学", version=2)
print(prompt.prompt)

# response = glm_model.invoke(
#     "帮我写一句周报总结", config=RunnableConfig(callbacks=[langfuse_handler])
# )
