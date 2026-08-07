# 阶段二 · Prompt 管理 Prompt Management

> 把 Prompt 从「散落在代码里的字符串」升级成「有版本、能灰度、能回滚的配置」。
> 一句话价值：**运营/产品在 UI 改 Prompt 就能上线，工程师不介入；出问题一键回滚。**

## 0. 心智模型

```
代码里只写：get_prompt("名字", label="production")
                     ↓
        Langfuse 服务端存着这个名字的很多个版本
                     ↓
        production 标签当前指向哪一版，线上就用哪一版
```

- **版本(version)**：每次 `create_prompt` 或在 UI 保存 = 一个新版本（v1、v2、v3…），只增不改。
- **标签(label)**：像 Git 分支指针，`production` / `staging` 各指向某一个版本。改标签指向 = 改线上行为，**代码不动**。

## 1. 两种 Prompt 类型

| 类型 | 内容形态 | 适用 |
| --- | --- | --- |
| `text` | 一个字符串，含 `{{变量}}` | 单轮、补全式 |
| `chat` | 消息数组 `[{role, content}, ...]` | 多轮对话、带 system 设定 |

变量统一用 **双大括号** `{{variable}}`（mustache 风格）。

## 2. 核心 API

### 创建 / 新增版本
```python
langfuse.create_prompt(
    name="tutorial-周报助手",
    prompt="把工作流水整理成周报：\n{{content}}",   # text 是字符串；chat 是消息列表
    labels=["production"],      # 带上 production 即设为线上默认
    type="text",                # 或 "chat"
    commit_message="v1 初版",   # 变更说明，便于回溯
)
```

### 拉取（默认取 production）
```python
prompt = langfuse.get_prompt("tutorial-周报助手")                 # 默认 label=production
prompt = langfuse.get_prompt("tutorial-周报助手", label="staging")  # 指定标签
prompt = langfuse.get_prompt("tutorial-周报助手", version=2)        # 指定版本（一般用于调试）
```

### 填充变量
```python
text = prompt.compile(content="周一修 bug；周三写检索…")   # text → 返回字符串
messages = chat_prompt.compile(brand="Acme", question="…", history=[...])  # chat → 返回消息字典列表
```

### chat 的「消息占位符」——注入运行时历史
创建时放一条占位符消息：
```python
prompt=[
    {"role": "system", "content": "你是{{brand}}客服"},
    {"type": "placeholder", "name": "history"},   # ← 占位符
    {"role": "user", "content": "{{question}}"},
]
```
compile 时用同名参数注入一段消息列表：
```python
prompt.compile(brand="Acme", question="…", history=[
    {"role": "user", "content": "你好"},
    {"role": "assistant", "content": "您好～"},
])
```

### 客户端缓存（零额外延迟）
```python
prompt = langfuse.get_prompt("名字", cache_ttl_seconds=60)
```
拉取一次后本地缓存 60 秒，期间再取不走网络；缓存过期后后台刷新，**不阻塞**你的请求。生产环境强烈建议开缓存。

> 生产健壮性建议：`get_prompt(..., fallback="兜底文案", max_retries=2)`，网络异常时用兜底 Prompt，保证不因拉取失败而挂。

## 3. Prompt 关联 Trace（按版本看效果）

### 手工 generation（本阶段 s7 用法）
```python
prompt = langfuse.get_prompt("tutorial-周报助手")
with langfuse.start_as_current_observation(
    as_type="generation", name="glm-answer", model="glm-4",
    input=prompt.compile(content=raw), prompt=prompt,  # ★ 关联
) as gen:
    ...
```

### LangChain 场景的关联写法
把 Langfuse prompt 转成 LangChain 模板，并在 `metadata` 里带上原始 prompt 对象：
```python
from langchain_core.prompts import ChatPromptTemplate
lf_prompt = langfuse.get_prompt("名字", type="chat")
lc_prompt = ChatPromptTemplate.from_messages(
    lf_prompt.get_langchain_prompt(),
    metadata={"langfuse_prompt": lf_prompt},   # ← Langfuse 据此自动关联
)
```

关联后，在 UI 的 **Prompts → 某 prompt → Metrics** 里能看到「该版本的调用量 / 延迟 / 关联评分」，
这就是「用数据决定 v2 要不要全量」的依据。

## 4. Playground（UI 内调试）

任意 generation 右上角 **Open in Playground** → 直接改 Prompt / 换模型 / 调参数试跑
→ 满意后 **Save as new prompt version**。适合非工程同学快速迭代。

---

## 5. 本阶段脚本与动手清单

| 脚本 | 学到的东西 |
| --- | --- |
| `s5_prompt版本与label灰度.py` | 创建多版本、用 label 控制线上版本、UI 里灰度切换 + 回滚 |
| `s6_prompt变量与缓存.py` | chat 模板、`{{变量}}`、历史占位符、客户端缓存 |
| `s7_prompt关联trace.py` | 把 Prompt 版本关联到 generation，按版本分析效果 + Playground |

### 运行
```bash
python "Langfuse实战/02_Prompt管理/s5_prompt版本与label灰度.py"
python "Langfuse实战/02_Prompt管理/s6_prompt变量与缓存.py"
python "Langfuse实战/02_Prompt管理/s7_prompt关联trace.py"   # 依赖 s5 播种的 prompt
```

> 注：`s5`/`s6` 内置了「已存在则跳过播种」，可安全重复运行，不会疯狂造版本。

## 6. 自检清单

- [ ] 在 UI Prompts 看到 `tutorial-周报助手`（≥2 版）和 `tutorial-客服助手`
- [ ] 在 UI 把 production 从 v1 挪到 v2，重跑 `s5`，production 结果随之改变（代码没动）
- [ ] 再把 production 挪回 v1，验证「一键回滚」
- [ ] `s6` 打印出的 compile 结果里，history 两条历史消息被正确注入
- [ ] `s7` 的 trace 里 generation 显示了关联的 Prompt 版本

---

## 附录 · API 速查表（完整签名 + 逐参数说明）

> 签名取自已安装的 **Langfuse SDK `4.14.3`** 源码。✅ 必填 · ⚪ 可选。

### A. `create_prompt(...)` —— 创建 Prompt / 新增一个版本
```python
langfuse.create_prompt(
    *,
    name: str,                                                 # ✅ Prompt 名（同名即同一条，新增版本）
    prompt: str | list,                                        # ✅ text→字符串；chat→消息列表
    labels: list[str] = [],                                    # 标签，含 "production" 即线上默认
    tags: list[str] | None = None,                             # 作用于该 Prompt 所有版本
    type: "text" | "chat" = "text",
    config: Any | None = None,                                 # 额外结构化数据（任意 JSON）
    commit_message: str | None = None,                         # 变更说明
) -> PromptClient
```
| 参数 | 说明 |
| --- | --- |
| `name` | ✅ Prompt 唯一名；再次 `create_prompt` 同名 = 新增一个版本（v1→v2…） |
| `prompt` | ✅ `type="text"` 时是含 `{{变量}}` 的字符串；`type="chat"` 时是消息列表 `[{role,content}, ...]`，历史占位符写成 `{"type":"placeholder","name":"history"}` |
| `labels` | 标签列表，`["production"]` = 线上默认；`["staging"]` = 灰度 |
| `tags` | 标签（区别于 label：tag 贴在整条 Prompt 上、跨版本） |
| `type` | `"text"` 或 `"chat"` |
| `config` | 额外结构化配置（如模型参数、温度），任意可序列化对象 |
| `commit_message` | 该版本的变更说明，便于回溯 |

---

### B. `get_prompt(...)` —— 拉取 Prompt（默认取 production）
```python
prompt = langfuse.get_prompt(
    name: str,                                                 # ✅ Prompt 名
    *,
    version: int | None = None,
    label: str | None = None,
    type: "text" | "chat" = "text",
    cache_ttl_seconds: int | None = None,
    fallback: str | list | None = None,
    max_retries: int | None = None,
    fetch_timeout_seconds: int | None = None,
) -> PromptClient      # 实际返回 TextPromptClient 或 ChatPromptClient
```
| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `name` | str | ✅ | — | Prompt 名 |
| `version` | int | ⚪ | None | 按版本号拉取；与 `label` **二选一** |
| `label` | str | ⚪ | None | 按标签拉取；都不传则取 `production` |
| `type` | str | ⚪ | `"text"` | 决定返回 text/chat 两类客户端 |
| `cache_ttl_seconds` | int | ⚪ | `60` | 本地缓存秒数；设 `0` 关闭缓存 |
| `fallback` | str/list | ⚪ | None | 拉取失败时的兜底内容（首次无缓存时尤其重要） |
| `max_retries` | int | ⚪ | `2` | 网络/API 失败重试次数，**上限 4**，指数退避（最长 10s） |
| `fetch_timeout_seconds` | int | ⚪ | `5` | 拉取超时（秒） |

> 缓存语义：命中缓存零网络；过期后**后台异步刷新**不阻塞当前请求；刷新失败且有过期缓存则返回过期版（降级不中断）。

---

### C. PromptClient 对象 —— 属性与方法

`get_prompt` / `create_prompt` 返回的对象（`TextPromptClient` 或 `ChatPromptClient`）。

**属性**
| 属性 | 类型 | 说明 |
| --- | --- | --- |
| `.name` | str | Prompt 名 |
| `.version` | int | 版本号（v1=1, v2=2…；兜底返回时为 0） |
| `.labels` | list[str] | 该版本所带标签 |
| `.tags` | list[str] | 该 Prompt 的标签 |
| `.config` | dict | 结构化配置 |
| `.commit_message` | str \| None | 该版本变更说明 |
| `.variables` | list[str] | 模板里的变量名列表（自动解析 `{{xxx}}`，**只读 property**） |
| `.is_fallback` | bool | 是否为兜底返回的 Prompt |

**方法**
```python
# text → 返回字符串；chat → 返回消息字典列表（含注入的历史）
prompt.compile(**kwargs)

# 转成 LangChain 兼容的字符串/消息（{{var}}→{var}），用于 ChatPromptTemplate
prompt.get_langchain_prompt(**kwargs)
```
| 方法 | 返回 | 说明 |
| --- | --- | --- |
| `compile(**变量)` | `str`（text）/ `list[dict]`（chat） | 用关键字参数填充 `{{变量}}`；chat 的 `history=` 注入到同名 `placeholder` |
| `get_langchain_prompt(**变量)` | `str` | 把 mustache 双花括号转成 LangChain 单花括号；可先预填部分变量 |

---

### D. chat 消息的两种写法（创建时）

普通消息：
```python
{"role": "system", "content": "你是{{brand}}客服"}      # role: system/user/assistant/...
```
历史占位符消息（compile 时注入一段对话）：
```python
{"type": "placeholder", "name": "history"}              # compile(history=[{"role":..,"content":..}, ...])
```

---

### E. 把 Prompt 版本关联到 Trace（按版本看效果）

两种等价写法（任选其一）：

```python
# ① 创建 generation 时传入
with langfuse.start_as_current_observation(
    as_type="generation", name="glm-answer", model="glm-4",
    input=prompt.compile(content=raw),
    prompt=prompt,          # ★ 关联
) as gen: ...

# ② 在已有 generation 上下文里补关联
langfuse.update_current_generation(prompt=prompt)
```

关联后，UI 的 **Prompts → 某 Prompt → Metrics** 能看到「该版本的调用量 / 延迟 / 关联评分」。
> LangChain 场景的关联（用 `get_langchain_prompt()` + `metadata={"langfuse_prompt": lf_prompt}`）见正文第 3 节。
