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