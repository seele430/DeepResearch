# 技术决策记录

## 决策 001：多轮对话——选择"简单 REPL"而非"共享上下文"

**日期**：2026-09-26

### 背景
Agent 每次运行只处理一个问题，用完后程序退出。
每次测试都要重新运行 `python agent.py` 并重新输入，体验差。

### 方案对比

**方案 A：简单 REPL（已采用）**
- 程序持续运行，输入问题后处理，处理完回到提示符
- 每次问答独立，不共享 messages 历史
- 优点：实现简单、无额外 token 成本、不引入新问题
- 缺点：无法进行"追问式"对话

**方案 B：REPL + 共享 messages**
- 整个会话共用一个 messages 列表，支持上下文延续
- 优点：可以追问，如"它和 LangChain 有什么区别？"
- 缺点：
  - 历史中的工具调用结果（网页正文、搜索结果）会持续累积
  - 多轮后 token 数爆炸，成本上升、响应变慢
  - 需要额外实现"历史压缩/摘要"机制才能长期可用

### 决策
采用**方案 A**。

### 理由
1. 当前阶段的核心目标是验证"Agent 循环"能否稳定工作，而不是多轮交互
2. 方案 B 会引入"上下文管理"这个新问题，偏离当前学习重点
3. 遵循"避免过早优化（YAGNI）"原则——等真实需求出现再迭代
4. 方案 A 的实现为未来引入方案 B 留好了接口（`run_agent` 只需改签名即可）

### 后续计划
- 等阶段二引入"记忆系统"时，再统一处理多轮上下文
- 届时会配合实现"滑动窗口 + 摘要压缩"，解决 token 膨胀问题




## 决策 002：工具调用去重

**日期**：2026-09-26

### 问题

Agent 在多步执行中会重复搜索相似关键词、重复读取相同 URL：

- 搜索结果几乎完全一样，纯浪费
- 网页正文（数千 token）重复进入上下文，推高成本
- 重复信息干扰 LLM 判断，可能误判"多来源证实"

### 方案

在 Agent 循环中引入两级去重：

**搜索去重（拒绝式）**

- 对 query 做标准化（小写、去标点、合并空格）
- 已搜过的关键词直接返回"请换词"提示，不实际发起搜索

**阅读去重（缓存式）**

- 对 URL 做标准化（去末尾斜杠、去 fragment）
- 已读内容直接返回缓存，不重复发请求

### 为什么处理方式不同

- 重复搜索 → 拒绝：返回结果大概率相同，没有新信息
- 重复阅读 → 缓存：Agent 可能只是忘了读过，直接把内容给它即可

### 效果

- 避免无效的重复工具调用
- 上下文 token 减少（重复内容不再进入 messages）
- Agent 决策不受重复信息干扰

### 核心代码

```python
# 去重记录
seen_queries = set()   # 已搜过的关键词
read_cache = {}        # url -> 已读到的正文

# 搜索分支
if name == "web_search":
    key = _norm_query(args.get("query", ""))
    if key in seen_queries:
        result = "[已搜索过相似关键词] 请换一个更具体的词"
        continue
    seen_queries.add(key)

# 阅读分支
elif name == "read_url":
    key = _norm_url(args.get("url", ""))
    if key in read_cache:
        result = f"[已读取过该网页] {read_cache[key]}"
        continue
    # 读完后：read_cache[key] = str(result)






## 决策 003：工具调用次数上限

**日期**：2026-09-26

### 问题

在上一轮测试中，Agent 面对复杂问题时会反复搜索，导致：

- 步数不可控（可能跑到 `max_steps=10` 才停）
- 每轮搜索的结果都进上下文，token 迅速膨胀
- 单次会话可能超过 2 分钟

### 方案

为每类工具设置硬性调用上限：

```python
search_count = 0
read_count = 0
MAX_SEARCH = 5
MAX_READ = 8





## 决策 004：搜索上限 5 次的实测效果与反思

**日期**：2026-09-26

### 实测场景
调研"2025 年 AI Agent 框架现状"，Agent 连续搜索 5 次触发上限，切换到 `read_url`。

### 好的一面
- 上限触发后 Agent **自动换策略**，没有卡死
- 报告质量超出预期：有选型建议、有自我反思、有抽象分类

### 暴露的问题
- Agent 狂搜 5 次的**根本原因是 `read_url` 大量失败**
- 想深入读原文时 CSDN/360doc/ZOL 抓取失败，只能靠摘要
- 信息颗粒度受限于搜索结果，无法交叉验证

### 反思
**次数上限只是"症状缓解"，不是"病根治疗"。**
真正的解法是修好 `read_url`，让"搜一次 + 读一次"就能拿到高质量信息，
而不是"搜五次 + 读失败"。

### 后续计划
优化 `read_url`：
- 加 User-Agent 伪装
- 增加 requests + BeautifulSoup 作为 trafilatura 的降级方案
- 针对 CSDN 等站点做专门适配




## 决策 005：read_url 添加 UA 伪装

**日期**：2026-09-26

### 问题
决策 004 暴露 read_url 对 CSDN、360doc、ZOL 等站点抓取失败。
经排查，主要是：
- trafilatura 默认 User-Agent 被反爬识别
- 部分中文站点使用非 UTF-8 编码，导致乱码

### 方案
1. 用 `requests` 替代 `trafilatura.fetch_url`（后者不支持自定义 headers）
2. 加浏览器 User-Agent + Accept + Accept-Language 伪装
3. 用 `resp.apparent_encoding` 自动修正中文编码
4. 保留 `trafilatura.extract` 做正文提取

### 效果
- CSDN 抓取从失败变为成功
- 中文不再乱码
- 正文完整可读

### 后续可优化
- 加 requests + BeautifulSoup 作为 trafilatura.extract 失败时的降级方案（优化 2）
- 针对已知反爬站点做专门适配（优化 3）

## 决策 006：ReAct 的实现范式——文本模板 vs 原生 Function Calling

**日期**：2026-10-06（回顾性补记；循环实现定稿于 2026-09-26）

**性质**：本文档为事后补记。补记原因：README 与简历中"基于 ReAct 模式 / 手写 ReAct 循环"的表述存在歧义——ReAct 有两种互不相同的工程落地范式，本项目实际只用了其中一种，而原始 5 份决策日志没有记录这次选型，容易被误读为另一种。

### 背景

ReAct（Reasoning + Acting）在工程上有两条路线，二者在**代码形态上差异极大**：

**范式 A：文本 ReAct**（ReAct 论文原始形式，LangChain `hwchase17/react` 提示词模板的形态）

模型被要求在提示词约束下输出固定格式的自由文本，程序用正则/字符串切分解析：

```
Thought: 我需要先了解 X 的基本情况
Action: web_search
Action Input: {"query": "X"}
Observation: （由程序填入工具返回）
```

**范式 B：原生 Function Calling**（OpenAI tools API 及其兼容实现）

工具以 JSON Schema 声明，模型返回结构化 `tool_calls`，程序无需解析任何自由文本：

```json
{"name": "web_search", "arguments": "{\"query\": \"X\"}"}
```

**本项目采用范式 B。** 代码中不含 `Thought`、`Action`、`Action Input`、`Observation` 任何一个字符串——这四个词是范式 A 的产物，不是本项目的实现细节。

### 方案对比

| 维度 | 范式 A：文本 ReAct | 范式 B：Function Calling（已采用） |
|---|---|---|
| Action 的产出形式 | 自由文本，需正则解析 | API 返回结构化 JSON |
| 典型解析失败模式 | 参数带 markdown 代码块、中文全角冒号、漏写字段、Thought 与 Action 粘连、一次输出多个 Action、幻觉工具名 | 参数不符合 schema 时由 API 层直接暴露 |
| 推理过程（Thought） | 明文可见，可审计、可用 few-shot 引导 | 模型内部隐式完成，不落文本 |
| 模型兼容性 | 任何能对话的模型 | 需模型支持 `tools` |
| 需要额外实现 | 提示词模板 + 解析器 + 容错重试 | 仅 JSON Schema 声明 |
| 可观测性 | 高（推理链可直接读） | 低（需靠日志补偿） |
| 主循环复杂度 | 高 | 低 |

### 决策

采用**范式 B（原生 Function Calling）**。

### 理由

1. **格式可靠性是 Agent 循环的生命线。** 主循环每一轮都要消费一次 Action，解析失败即整轮失效。范式 A 把"格式正确"交给模型自觉遵守提示词，范式 B 把它交给 API 的结构化约束——后者是结构性保证，不依赖模型当天的输出稳定性。
2. **DeepSeek API 原生支持 `tools`，没有理由绕路。** 本项目的选型前提是"手写循环以理解 Agent 本质机制"，而不是"必须手写解析器"。手写解析器不增加对 Agent 的理解，只增加 bug 面。
3. **减少一个解析器 = 减少一个失败面。** 去掉正则、容错、格式重试分支后，`agent.py` 的主循环维持在约 100 行，可读性显著提升。
4. **代价被部分补偿。** 范式 B 牺牲了 Thought 的可观测性，但：
   - `SYSTEM_PROMPT` 中的"工作原则 / 研究流程参考"承担了**引导推理顺序**的职责（多角度搜索 → 深入阅读 → 交叉验证 → 输出报告）；
   - `rich` 打印的 `--- Step N ---`、工具名与参数、结果预览提供了**行为级**可观测性；
   - 决策 002 / 003 的去重与次数上限逻辑都发生在**工具执行层**，不依赖模型输出的文本形态，因此换范式不受影响。

### 核心代码：范式 A → 范式 B 的对应关系

| ReAct 文本范式 | 本项目实现 | 位置 |
|---|---|---|
| Thought | `SYSTEM_PROMPT` 的工作原则 + 模型隐式推理 | `agent.py` `SYSTEM_PROMPT` |
| Action | `msg.tool_calls[i].function.name` | `agent.py` 工具执行循环 |
| Action Input | `json.loads(msg.tool_calls[i].function.arguments)` | 同上 |
| Observation | `{"role": "tool", "tool_call_id": ..., "content": result}` | 工具结果回填处 |
| 工具清单声明 | `TOOLS_SCHEMA`（JSON Schema） | `tools.py` 末尾 |
| Final Answer | `if not msg.tool_calls: return msg.content` | 循环开头 |

```python
response = client.chat.completions.create(
    model=MODEL,
    messages=messages,
    tools=TOOLS_SCHEMA,          # 工具以 schema 声明，而非写进 prompt 正文
    tool_choice="auto",
)
msg = response.choices[0].message

if not msg.tool_calls:           # 对应范式 A 的 "Final Answer:" 分支
    console.print(Panel(msg.content, title="最终答案", border_style="green"))
    return msg.content

messages.append(msg)             # 必须回填原始 message 对象（含 tool_calls 字段）
for tool_call in msg.tool_calls:
    name = tool_call.function.name                          # 对应范式 A 的 Action
    args = json.loads(tool_call.function.arguments)         # 对应范式 A 的 Action Input
    ...
    messages.append({                                       # 对应范式 A 的 Observation
        "role": "tool",
        "tool_call_id": tool_call.id,
        "content": str(result),
    })
```

**一个易错点（实测）**：`messages.append(msg)` 必须追加**原始 message 对象**而不是手写的 dict。若把 `tool_calls` 字段丢掉，下一轮请求会因"tool 消息找不到对应的 tool_call_id"被 API 拒绝。

### 什么情况下会切回范式 A

- 目标模型不支持 `tools`（如部分本地小模型、旧版接口）；
- 需要把推理过程作为**审计产物**输出（合规、教学、人在环审批场景）；
- 需要用 few-shot 示例引导某种特殊推理格式——自由文本比 JSON Schema 更灵活。

### 后续计划

- [x] 修正对外表述：将"基于 ReAct 模式"明确为"**ReAct 控制流 + 原生 Function Calling 实现**"，避免与范式 A 混淆
- [x] 实现 `REACT_MODE=text|function_call` 双后端开关，用于对比两种范式的稳定性与格式崩坏率

---

**结论一句话**：本项目采用的是 ReAct 的**控制流**（推理 → 行动 → 观察循环），而不是 ReAct 的**文本格式**；Action / Action Input / Observation 由 API 的结构化工具调用承载，`Thought` 由系统提示词引导、不落文本。因此"手写 ReAct 循环"的准确含义是——**循环控制流是手写的，工具调用的序列化不是**。

## 决策 007：引入文本 ReAct 后端作为对照实现

**日期**：2026-10-07

### 背景

决策 006 选了范式 B（原生 Function Calling），理由是"格式可靠性更高"。
但这是**论断，不是实测**：没有可运行的对照片，就无法证明文本 ReAct 的解析
失败率真的更高，更回答不了"高多少"。面试时只能说"我觉得"。

### 方案对比

**方案 A：只保留 Function Calling**

- 优点：代码最少，没有第二条需要长期维护的循环
- 缺点：决策 006 的理由停留在口头，无法验证

**方案 B：双后端并存（已采用）**

- 优点：可运行、可切换、可测量，两种范式的差异变成可复现的工程数据
- 缺点：多一个解析器和一条循环路径需要维护

### 决策

采用**方案 B**：新增 `REACT_MODE=text|function_call` 开关，
文本 ReAct 作为**对照实现**长期保留在仓库里。

### 实现要点

1. **约束下沉到 `ToolRuntime`。** 决策 002（去重）与决策 003（次数上限）原本
   内联在 function calling 分支里。若不做这一步，两个后端跑的是**两套不同的
   工程策略**，对比出的差异无法归因到范式本身。抽到 `tool_runtime.py` 后，
   两种范式共享完全一致的约束。
2. **解析器独立成 `react_parser.py`，零依赖、可单测。** 解析器是范式 A 相对
   范式 B 多出来的**唯一**失败面，必须能脱离 API 单独回归 —— 否则每次验证
   都要花钱调模型。
3. **工具手册从 `TOOLS_SCHEMA` 自动渲染。** 文本模式的提示词里要写工具清单，
   手工维护必然与 `tools.py` 的 schema 漂移；改为运行时生成，保证两者一致。
4. **连续 3 次解析失败主动终止。** 范式 A 解析不了时继续循环只是白烧 token
   和步数，设阈值并如实报告失败原因。
5. **解析失败时把错误回喂给模型**，给它一次自我修复机会 —— 这是范式 A 唯一
   能降低崩坏率的手段。

### 实测数据（`test_react_parser.py`，17 例）

> **口径说明**：以下 17 例是**人工构造**的真实畸形格式样本（取自模型输出中
> 常见的漂移形态），用于回归测试，**不是对真实模型输出的采样统计**。
> 真实崩坏率需要真实 API 采样，见"后续计划"。

| 分类 | 数量 | 说明 |
|---|---|---|
| 解析成功 · 语义正确 | 11 | 全角冒号、markdown 加粗、代码块包裹、单引号 JSON、尾随解释、行首缩进、大写工具名、等号写法等 |
| 解析成功 · **语义陷阱** | 2 | 解析"成功"但不报错，危害最大 |
| 无法解析 | 4 | 本轮 Agent 步骤直接作废 |

两个语义陷阱尤其值得记录：

- **裸值参数**：`Action Input: https://example.com` 被解析成 `{"input": "..."}`，
  参数名不对，要等到工具层抛 `TypeError` 才暴露 —— 错误延迟很晚才出现。
- **一次输出两个 Action**：解析器只能取第一个，**第二个被静默丢弃**，
  而模型以为自己已经做过这件事。

这两类失败在范式 B 下都不存在：API 层会拒绝不符合 JSON Schema 的参数。

### 结论

决策 006 的"格式可靠性更高"得到了**可复现证据**的支持，而不只是主观判断。
同时明确了范式 A 的两个固有代价：失败时作废整轮步骤，且存在不报错的语义陷阱。

### 文件

| 文件 | 作用 |
|---|---|
| `agent.py` | 双后端 dispatch + `/mode` 运行时切换 |
| `tool_runtime.py` | 两种范式共享的工具约束（去重 / 上限 / 统计） |
| `react_parser.py` | 文本 ReAct 解析器（纯标准库） |
| `test_react_parser.py` | 解析器鲁棒性回归（17 例） |
| `test_tool_runtime.py` | 约束行为回归（25 项，证明重构未改变决策 002/003） |
| `test_backend_loop.py` | 双后端循环控制流 smoke test（22 项） |

### 后续计划

- [x] 修正 `requirements.txt`：补上 `tools.py` 直接 import 却未声明的
      `requests` / `beautifulsoup4` / `lxml`，移除无人使用的 `tavily-python`
- [ ] 用真实 API 采样 N 个问题，统计两种范式的**真实**崩坏率、token 消耗与耗时
