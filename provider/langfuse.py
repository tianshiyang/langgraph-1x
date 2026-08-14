import dotenv
from langfuse import get_client
from langfuse.langchain import CallbackHandler

dotenv.load_dotenv()

langfuse = get_client()
langfuse_handler = CallbackHandler()


def make_handler(model_name: str, session_id: str):
    # v4：CallbackHandler 构造器不再接受 metadata/session/tags。
    # 需要归会话/打标签时，在 invoke 外层用 propagate_attributes(session_id=..., tags=[...]) 包裹，
    # 这里只返回一个干净的 handler。
    return CallbackHandler()
