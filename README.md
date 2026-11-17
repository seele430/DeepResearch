# DeepResearch

一个用 Python 写的多步调研工具。Agent 按 ReAct 循环决定搜索、阅读和收尾，最后生成带来源链接的报告。

这个项目主要用于拆开看 Agent 的运行过程：循环、工具调用、去重和次数上限都在仓库里，不依赖 LangChain 或 LangGraph。

## 两种 ReAct 后端

- `function_call`：默认后端，使用 DeepSeek 原生 Function Calling 传递工具调用。
- `text`：使用 Thought / Action / Action Input / Observation 文本模板和正则解析，作为对照实现保留。

两种后端共用 `ToolRuntime`，因此工具去重和调用上限一致。运行时可以切换，也可以用 `REACT_MODE` 指定默认值。

```text
用户问题
  → 模型选择下一步
  → 调用搜索、阅读或笔记工具
  → 把观察结果放回上下文
  → 继续循环或输出报告
```

工具只有三个：

| 工具 | 用途 |
|---|---|
| `web_search` | 通过博查 API 搜索网页 |
| `read_url` | 用 requests、trafilatura 和 BeautifulSoup 提取正文 |
| `save_note` | 把调研笔记保存到本地 |

搜索采用拒绝式去重，阅读采用缓存式去重；调用达到上限后，运行器会提示模型收尾，而不是继续无限制调用。

## 安装与运行

需要 Python 3.10+、一个兼容 OpenAI SDK 的模型 API Key，以及博查搜索 API Key。

```bash
git clone https://github.com/seele430/DeepResearch.git
cd DeepResearch

python -m venv venv
# Windows: venv\Scripts\activate
# macOS/Linux: source venv/bin/activate

pip install -r requirements.txt
```

复制 `.env.example` 为 `.env`，填写配置：

```env
LLM_API_KEY=your_llm_api_key_here
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
BOCHA_API_KEY=your_bocha_api_key_here
```

启动命令行界面：

```bash
python agent.py
```

输入问题后开始调研，输入 `exit` 退出。切换后端：

```text
你的问题 > /mode text
你的问题 > /mode function_call
```

示例报告见 [examples/sample-report.md](examples/sample-report.md)。报告中的事实和链接仍需要人工核对，模型标注的“可信度”不能代替来源验证。

## 测试

以下测试使用 stub，不联网，也不需要 API Key：

```bash
python test_react_parser.py
python test_tool_runtime.py
python test_backend_loop.py
```

分别覆盖文本解析、工具运行时约束，以及两种后端的循环控制流。

真实 API 基准测试会消耗模型和搜索额度：

```bash
python bench_react_backends.py --questions 5
```

结果写入 `bench_report.md` 和 `bench_raw.json`，包括完成率、步数、token、耗时和文本解析失败率。已有结果见 [bench_report.md](bench_report.md)；这些数字只对应记录中的模型、问题和测量时间，不代表固定的性能结论。

## 目录

```text
DeepResearch/
├── agent.py                 # 命令行入口与双后端 Agent 循环
├── tool_runtime.py          # 工具去重、次数上限与统计
├── react_parser.py          # 文本 ReAct 解析器
├── tools.py                 # 搜索、网页阅读和笔记工具
├── bench_react_backends.py  # 双后端基准测试
├── examples/                # 示例报告
├── DECISIONS.md             # 技术决策记录
└── test_*.py                # 解析、运行时与工具测试
```

## 已知限制

- 网页阅读和搜索质量受目标站点、搜索接口与网络状态影响。
- 文本后端一次只执行一个 Action，复杂问题可能达到步数上限仍未完成。
- 基准测试样本较小，只适合复现和比较当前实现，不适合外推为普遍结论。
- 当前主要是命令行工具；后续多 Agent 版本放在 [ResearchSwarm](https://github.com/seele430/ResearchSwarm)。

实现取舍和修改原因记录在 [DECISIONS.md](DECISIONS.md)。

## License

MIT
