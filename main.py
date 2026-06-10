from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from provider import glm_model

if __name__ == "__main__":
    callback = UsageMetadataCallbackHandler()

    result = glm_model.invoke(
        [HumanMessage("你是GLM吗，你是GLM的那个版本")],
        config=RunnableConfig(callbacks=[callback]),
    )

    print(result)
    print("Token usage:", callback.usage_metadata)
