import dotenv
from langfuse import get_client
from langfuse.langchain import CallbackHandler

dotenv.load_dotenv()

langfuse = get_client()
langfuse_handler = CallbackHandler()


def make_handler(model_name: str, session_id: str):
    return CallbackHandler(
        metadata={
            "langfuse_session_id": session_id,  # 同一份原始素材生成的多次调用归到一组
            "langfuse_tags": [f"model:{model_name}", "weekly-report"],
        }
    )
