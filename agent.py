"""DeepResearch Agent 主循环 —— 双 ReAct 后端。

两种后端并存，用同一套工具约束（ToolRuntime），便于对比：
  * function_call —— 原生 Function Calling（决策 006 采纳，默认）
  * text          —— 文本 ReAct（ReAct 论文原始形态，需正则解析）

切换方式：
  * 环境变量  REACT_MODE=text
  * 运行时命令 /mode text 、 /mode function_call
"""

import os
import json
from dotenv import load_dotenv
from openai import OpenAI
from rich.console import Console
from rich.panel import Panel

from tools import TOOLS_SCHEMA
from tool_runtime import ToolRuntime
from react_parser import parse as parse_text_action

load_dotenv()

client = OpenAI(
    api_key=os.getenv("LLM_API_KEY"),
    base_url=os.getenv("LLM_BASE_URL"),
)
MODEL = os.getenv("LLM_MODEL")
console = Console()

# 默认后端：function_call | text
REACT_MODE = os.getenv("REACT_MODE", "function_call").strip().lower()

SYSTEM_PROMPT = """你是一个专业的研究助手 Agent。你的目标是帮用户完成**有深度、有依据**的调研任务。

你可以使用以下工具：
- web_search: 搜索网页，返回链接和摘要
- read_url: 读取网页正文，获取详细信息
- save_note: 保存重要信息

工作原则：
1. **多角度搜索**：至少进行 2-3 次不同角度的搜索（不同关键词、不同侧面），不要一次搜索就下结论
2. **深入阅读**：对搜索结果中看起来最有价值的链接，用 read_url 读取正文，不要只看摘要
3. **交叉验证**：关键信息要在多个来源中验证，避免单一来源偏差
4. **识别矛盾**：如果不同来源信息冲突，要在报告中指出
5. **只有收集到足够信息后**，才输出最终答案（带来源链接）
6. 最终报告要结构清晰：概况、细节、趋势、来源

研究流程参考：
先搜 1-2 次获取全局 → 阅读 2-3 个关键网页 → 如发现信息不足，再补充搜索 → 综合分析 → 输出报告
"""


# ---------------------------------------------------------------------------
# 文本 ReAct（范式 A）的提示词
# 工具手册从 TOOLS_SCHEMA 自动渲染，避免 prompt 与 schema 两处维护后漂移
# ---------------------------------------------------------------------------
_TEXT_REACT_TEMPLATE = """你是一个专业的研究助手 Agent，通过"思考 → 行动 → 观察"的循环完成调研任务。

可用工具：
{{TOOL_MANUAL}}

## 输出格式（必须严格遵守）

每一步只输出一个 Thought 和一个 Action，格式如下：

Thought: <你的推理：当前缺什么信息、下一步该做什么>
Action: <工具名>
Action Input: <单行 JSON 参数对象>

系统执行工具后，会以一行 "Observation: ..." 的形式把结果给你，然后你继续输出下一轮。

当你已经收集到足够信息、可以回答用户问题时，用下面的格式收尾：

Thought: 我已掌握足够信息
Final Answer: <完整的研究报告，含来源链接>

## 硬性要求

1. Action Input 必须是**单行合法 JSON**，例如 {"query": "AI Agent 框架对比"}
2. 不要自己编造 Observation —— 它由系统填写，你只负责 Thought 和 Action
3. 一次输出里只能有一个 Action
4. 至少进行 2-3 次不同角度的搜索；对最有价值的链接用 read_url 读正文，不要只看摘要
5. 关键信息要在多个来源中交叉验证；来源冲突时在报告中明确指出
6. Final Answer 要结构清晰：概况、细节、趋势、来源
"""


def _render_tool_manual():
    """从 TOOLS_SCHEMA 渲染文本模式的工具手册。

    这样工具清单只有一个真实来源（tools.py），
    文本模式与 function calling 模式不会因为各自维护而漂移。
    """
    lines = []
    for tool in TOOLS_SCHEMA:
        fn = tool["function"]
        spec = fn.get("parameters", {})
        props = spec.get("properties", {})
        required = set(spec.get("required", []))
        params = ", ".join(
            f"{name}: {meta.get('type', 'any')}" + ("" if name in required else "（可选）")
            for name, meta in props.items()
        )
        lines.append(f"- {fn['name']}({params})：{fn['description']}")
    return "\n".join(lines)


TEXT_REACT_SYSTEM = _TEXT_REACT_TEMPLATE.replace("{{TOOL_MANUAL}}", _render_tool_manual())


def _print_block_notice(runtime):
    """把被去重/上限拦下的情况打印出来（两种后端共用）。"""
    if runtime.last_status == "blocked_limit":
        console.print(f"[red]⛔ {runtime.last_detail}[/red]")
    elif runtime.last_status == "blocked_dup":
        console.print(f"[magenta]⏭️  {runtime.last_detail}[/magenta]")


def _new_stats(mode):
    """一轮 run 的统计骨架（供基准脚本采集，见 bench_react_backends.py）。"""
    return {
        "mode": mode,
        "steps": 0,            # 实际走了几轮
        "finished": False,     # 是否拿到最终答案
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "parse_attempts": 0,   # 仅 text 模式：模型输出轮数
        "parse_failures": 0,   # 仅 text 模式：解析失败轮数
    }


def _record_usage(stats, response):
    """累加 token 用量。stub / 假客户端没有 usage 时静默跳过。"""
    usage = getattr(response, "usage", None)
    if usage is None:
        return
    stats["prompt_tokens"] += getattr(usage, "prompt_tokens", 0) or 0
    stats["completion_tokens"] += getattr(usage, "completion_tokens", 0) or 0


# ---------------------------------------------------------------------------
# 后端 1：原生 Function Calling（范式 B，默认）
# ---------------------------------------------------------------------------
def _run_function_call(user_query, max_steps, runtime, stats):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_query},
    ]

    for step in range(max_steps):
        console.print(f"\n[bold cyan]--- Step {step + 1} (function_call) ---[/bold cyan]")

        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOLS_SCHEMA,
            tool_choice="auto",
        )
        _record_usage(stats, response)
        stats["steps"] = step + 1
        msg = response.choices[0].message

        # 没有工具调用 → 输出最终答案
        if not msg.tool_calls:
            console.print(Panel(msg.content, title="最终答案", border_style="green"))
            stats["finished"] = True
            return msg.content

        messages.append(msg)

        for tool_call in msg.tool_calls:
            name = tool_call.function.name
            try:
                args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                args = {}

            console.print(f"[yellow]🔧 调用工具:[/yellow] {name}({args})")
            result = runtime.execute(name, args)
            _print_block_notice(runtime)
            console.print(f"[dim]结果预览: {str(result)[:200]}...[/dim]")

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": str(result),
            })

    console.print("[red]达到最大步数，强制结束[/red]")
    return "任务未完成"


# ---------------------------------------------------------------------------
# 后端 2：文本 ReAct（范式 A）—— 需要解析器，且解析会失败
# ---------------------------------------------------------------------------
def _run_text_react(user_query, max_steps, runtime, stats):
    messages = [
        {"role": "system", "content": TEXT_REACT_SYSTEM},
        {"role": "user", "content": f"Question: {user_query}"},
    ]

    attempts = 0        # 模型输出总轮数
    failures = 0        # 其中解析失败的轮数
    consecutive = 0     # 连续失败数

    for step in range(max_steps):
        console.print(f"\n[bold cyan]--- Step {step + 1} (text_react) ---[/bold cyan]")

        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            # 让模型在"该收到 Observation"的位置停下，而不是自己往下编
            stop=["\nObservation:", "\nObservation："],
        )
        _record_usage(stats, response)
        stats["steps"] = step + 1
        raw = (response.choices[0].message.content or "").strip()
        messages.append({"role": "assistant", "content": raw})

        attempts += 1
        stats["parse_attempts"] = attempts
        parsed = parse_text_action(raw)

        # ---- 收尾 ----
        if parsed.kind == "final":
            console.print(Panel(parsed.final, title="最终答案", border_style="green"))
            stats["finished"] = True
            _report_text_stats(attempts, failures)
            return parsed.final

        # ---- 解析失败：范式 A 的固有失败面 ----
        if parsed.kind == "error":
            failures += 1
            consecutive += 1
            stats["parse_failures"] = failures
            console.print(f"[red]⚠️  解析失败（{parsed.error}）[/red]")
            console.print(f"[dim]原始输出: {raw[:200]}[/dim]")

            if consecutive >= 3:
                console.print("[red]连续 3 次格式解析失败，终止[/red]")
                _report_text_stats(attempts, failures)
                return "任务未完成：模型连续输出不符合 ReAct 格式"

            # 把错误当 Observation 回喂，给模型一次自我修复的机会
            messages.append({
                "role": "user",
                "content": (
                    f"Observation: [格式错误] {parsed.error}。\n"
                    "请严格按以下格式重新输出，不要输出任何多余内容：\n"
                    "Thought: ...\n"
                    "Action: 工具名\n"
                    'Action Input: {"参数名": "值"}'
                ),
            })
            continue

        # ---- 工具调用 ----
        consecutive = 0
        if parsed.thought:
            console.print(f"[dim]💭 Thought: {parsed.thought[:150]}[/dim]")
        console.print(f"[yellow]🔧 调用工具:[/yellow] {parsed.action}({parsed.action_input})")

        observation = runtime.execute(parsed.action, parsed.action_input)
        _print_block_notice(runtime)
        console.print(f"[dim]结果预览: {observation[:200]}...[/dim]")

        messages.append({"role": "user", "content": f"Observation: {observation}"})

    console.print("[red]达到最大步数，强制结束[/red]")
    _report_text_stats(attempts, failures)
    return "任务未完成"


def _report_text_stats(attempts, failures):
    if not attempts:
        return
    rate = failures / attempts * 100
    console.print(
        f"[bold]📊 文本模式格式解析：{attempts} 轮输出，{failures} 轮解析失败"
        f"（崩坏率 {rate:.1f}%）[/bold]"
    )


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------
def run_agent(user_query, max_steps=10, mode=None, stats=None):
    """Agent 主循环。mode: "function_call"（默认）或 "text"。

    stats: 传入一个 dict 会写入本轮统计（步数 / token / 解析失败数 / 工具调用），
           供基准脚本 bench_react_backends.py 采集；不传则内部自行丢弃。
    """
    mode = (mode or REACT_MODE).strip().lower()
    runtime = ToolRuntime()
    if stats is None:
        stats = _new_stats(mode)
    else:
        stats.update(_new_stats(mode))

    if mode in ("text", "text_react", "react"):
        answer = _run_text_react(user_query, max_steps, runtime, stats)
    else:
        answer = _run_function_call(user_query, max_steps, runtime, stats)

    stats["tool_executed"] = runtime.stats["executed"]
    stats["tool_blocked"] = runtime.stats["blocked"]
    stats["tool_failed"] = runtime.stats["failed"]
    stats["search_count"] = runtime.search_count
    stats["read_count"] = runtime.read_count
    stats["total_tokens"] = stats["prompt_tokens"] + stats["completion_tokens"]

    console.print(f"[dim]📈 {runtime.summary()}[/dim]")
    return answer


if __name__ == "__main__":
    console.print("[bold green]🤖 研究助手 Agent 已启动[/bold green]")
    console.print(
        f"[dim]ReAct 后端: {REACT_MODE}｜输入 /mode text 或 /mode function_call 切换，"
        f"exit 退出[/dim]"
    )

    while True:
        try:
            query = input("\n你的问题 > ").strip()
        except (KeyboardInterrupt, EOFError):
            break

        if not query:
            continue
        if query.lower() in ("exit", "quit", "q"):
            break

        if query.startswith("/mode"):
            parts = query.split()
            if len(parts) == 2 and parts[1] in ("text", "function_call"):
                REACT_MODE = parts[1]
                console.print(f"[green]已切换 ReAct 后端: {REACT_MODE}[/green]")
            else:
                console.print("[yellow]用法: /mode text  |  /mode function_call[/yellow]")
            continue

        run_agent(query)

    console.print("\n[dim]再见 👋[/dim]")
