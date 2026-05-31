from langchain.chat_models import init_chat_model
from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from config import DefaultSettings

glm_model = init_chat_model(
    model=DefaultSettings.glm_default_settings["model"],
    api_key=DefaultSettings.glm_default_settings["api_key"],
    model_provider=DefaultSettings.glm_default_settings["model_provider"],
    base_url=DefaultSettings.glm_default_settings["base_url"],
)

if __name__ == "__main__":
    callback = UsageMetadataCallbackHandler()
    result = glm_model.invoke([HumanMessage("你是哪个模型呢，你又是哪个版本呢")], config=RunnableConfig(
        callbacks=[callback]
    ))
    # token消耗情况
    print(callback.usage_metadata)
    print(result)