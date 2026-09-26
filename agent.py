import os
import json
import hashlib
from dotenv import load_dotenv
from openai import OpenAI
from rich.console import Console
from rich.panel import Panel

from tools import TOOLS_SCHEMA, TOOL_MAP

load_dotenv()

client = OpenAI(
    api_key=os.getenv("LLM_API_KEY"),
    base_url=os.getenv("LLM_BASE_URL"),
)
MODEL = os.getenv("LLM_MODEL")
console = Console()

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

def _norm_query(q: str) -> str:
    """标准化搜索关键词：转小写、去空格、去标点"""
    q = q.lower().strip()
    q = "".join(c for c in q if c.isalnum() or c.isspace())
    return " ".join(q.split())


def _norm_url(url: str) -> str:
    """标准化 URL：去掉末尾斜杠、去掉 #fragment"""
    url = url.strip().rstrip("/")
    if "#" in url:
        url = url.split("#")[0]
    return url
    
    
def run_agent(user_query: str, max_steps: int = 10) -> str:
    """Agent 主循环（含工具调用去重 + 次数限制）"""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_query},
    ]

    # 去重记录
    seen_queries = set()
    read_cache = {}

    # 工具调用计数
    search_count = 0
    read_count = 0
    MAX_SEARCH = 5
    MAX_READ = 8

    for step in range(max_steps):
        console.print(f"\n[bold cyan]--- Step {step + 1} ---[/bold cyan]")

        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOLS_SCHEMA,
            tool_choice="auto",
        )
        msg = response.choices[0].message

        # 没有工具调用 → 输出最终答案
        if not msg.tool_calls:
            console.print(Panel(msg.content, title="最终答案", border_style="green"))
            return msg.content

        messages.append(msg)

        # 逐个执行工具
        for tool_call in msg.tool_calls:
            name = tool_call.function.name
            try:
                args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                args = {}

            console.print(f"[yellow]🔧 调用工具:[/yellow] {name}({args})")

            # ---------- 搜索工具 ----------
            if name == "web_search":
                if search_count >= MAX_SEARCH:
                    console.print(f"[red]⛔ 已达搜索上限 {MAX_SEARCH} 次[/red]")
                    result = f"[已达搜索上限 {MAX_SEARCH} 次] 请基于已有信息作答，或调用 read_url 深入阅读已搜到的链接。"
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result,
                    })
                    continue

                key = _norm_query(args.get("query", ""))
                if key in seen_queries:
                    console.print(f"[magenta]⏭️  跳过重复搜索:[/magenta] {key}")
                    result = f"[已搜索过相似关键词] {args.get('query')}，请换一个更具体的词，或直接使用已有信息。"
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result,
                    })
                    continue

                seen_queries.add(key)
                search_count += 1

            # ---------- 阅读工具 ----------
            elif name == "read_url":
                if read_count >= MAX_READ:
                    console.print(f"[red]⛔ 已达阅读上限 {MAX_READ} 次[/red]")
                    result = f"[已达阅读上限 {MAX_READ} 次] 请基于已有信息作答。"
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result,
                    })
                    continue

                key = _norm_url(args.get("url", ""))
                if key in read_cache:
                    console.print(f"[magenta]⏭️  跳过重复阅读:[/magenta] {key}")
                    result = f"[已读取过该网页] 内容如下：\n{read_cache[key]}"
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result,
                    })
                    continue

                read_count += 1

            # ---------- 执行工具 ----------
            func = TOOL_MAP.get(name)
            if func is None:
                result = f"未知工具: {name}"
            else:
                try:
                    result = func(**args)
                except Exception as e:
                    result = f"工具执行失败: {e}"

            # 缓存 read_url 的结果
            if name == "read_url":
                key = _norm_url(args.get("url", ""))
                read_cache[key] = str(result)

            console.print(f"[dim]结果预览: {str(result)[:200]}...[/dim]")

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": str(result),
            })

    console.print("[red]达到最大步数，强制结束[/red]")
    return "任务未完成"

if __name__ == "__main__":
    console.print("[bold green]🤖 研究助手 Agent 已启动（输入 exit 退出）[/bold green]")
    while True:
        try:
            query = input("\n你的问题 > ").strip()
        except (KeyboardInterrupt, EOFError):
            break

        if not query:
            continue
        if query.lower() in ("exit", "quit", "q"):
            break

        run_agent(query)

    console.print("\n[dim]再见 👋[/dim]")