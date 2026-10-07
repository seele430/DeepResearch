"""双 ReAct 后端基准采样 —— ⚠️ 需要真实 API Key（.env），会真实消耗额度。

跑法::

    python bench_react_backends.py                 # 默认 5 个问题 × 2 个后端
    python bench_react_backends.py --questions 10  # 加大样本
    python bench_react_backends.py --modes text    # 只跑文本 ReAct
    python bench_react_backends.py --max-steps 6   # 限制每问的步数上限

产出::

    bench_report.md   —— 可直接粘贴进 README 的对比表
    bench_raw.json    —— 逐条原始记录（含每问的答案长度，可复算）

设计说明
--------
* 两种后端通过同一个 `run_agent(..., stats=...)` 采集指标，**口径完全一致**；
  若两边各写一套统计，出来的差异就无法归因到范式本身。
* 每个问题对两个后端各跑一次，是**单次采样**，不含方差 —— 表格里会如实标注。
* 控制台输出被静音（rich Console(quiet=True)），否则表格会被 Agent 的调试
  日志淹没。
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# 采样问题：覆盖"多步搜索 + 阅读正文"的典型场景，便于观察步数与工具调用差异
# ---------------------------------------------------------------------------
QUESTIONS = [
    "2025 年国内 AI Agent 框架的现状与主要选型对比",
    "RAG 与长上下文方案在工程落地上的取舍",
    "MCP（Model Context Protocol）是什么，解决了什么问题",
    "向量数据库的主流选型与各自适用场景",
    "大模型 Function Calling 与文本 ReAct 在实现上的差异",
]

MODES = ["function_call", "text"]


def parse_args():
    p = argparse.ArgumentParser(description="双 ReAct 后端基准采样")
    p.add_argument("--questions", type=int, default=5,
                   help=f"取前 N 个问题（题库共 {len(QUESTIONS)} 个，默认 5）")
    p.add_argument("--modes", default=",".join(MODES),
                   help="要跑的后端，逗号分隔（function_call,text）")
    p.add_argument("--max-steps", type=int, default=8, help="每问的最大步数（默认 8）")
    p.add_argument("--out", default=".", help="产出目录（默认当前目录）")
    return p.parse_args()


def main():
    args = parse_args()

    if not os.getenv("LLM_API_KEY"):
        print("✗ 未找到 LLM_API_KEY。请先把 .env 放好（参考 .env.example）。")
        return 2

    import agent
    from rich.console import Console

    # 静音 Agent 的控制台输出，否则表格会被调试日志淹没
    agent.console = Console(quiet=True)
    quiet = Console(quiet=True)

    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    questions = QUESTIONS[: max(1, min(args.questions, len(QUESTIONS)))]

    total_runs = len(modes) * len(questions)
    print(f"计划：{len(questions)} 个问题 × {len(modes)} 个后端 = {total_runs} 次 Agent run"
          f"（max_steps={args.max_steps}，模型={os.getenv('LLM_MODEL')}）")
    print("⚠️  这会真实消耗 API 额度。开始采样...\n")

    records = []
    for mode in modes:
        for i, q in enumerate(questions, 1):
            stats = {}
            t0 = time.perf_counter()
            error = None
            answer = ""
            try:
                answer = agent.run_agent(q, max_steps=args.max_steps, mode=mode, stats=stats)
            except Exception as e:                     # 单条失败不中断整轮采样
                error = f"{type(e).__name__}: {e}"
            elapsed = time.perf_counter() - t0

            rec = {
                "mode": mode,
                "question": q,
                "elapsed_s": round(elapsed, 2),
                "answer_chars": len(answer or ""),
                "error": error,
            }
            rec.update(stats)
            records.append(rec)

            status = "ERR " if error else ("OK  " if stats.get("finished") else "MAX ")
            print(f"[{mode:>13}] {i}/{len(questions)} {status} "
                  f"{elapsed:5.1f}s  steps={stats.get('steps', 0):<2} "
                  f"tools={stats.get('tool_executed', 0):<2} "
                  f"tokens={stats.get('total_tokens', 0):<6} "
                  f"parse_fail={stats.get('parse_failures', 0)}  {q[:26]}")

    # ---------------- 汇总 ----------------
    def agg(mode):
        rs = [r for r in records if r["mode"] == mode]
        n = len(rs) or 1
        att = sum(r.get("parse_attempts", 0) for r in rs)
        fail = sum(r.get("parse_failures", 0) for r in rs)
        return {
            "runs": len(rs),
            "finished": sum(1 for r in rs if r.get("finished")),
            "errors": sum(1 for r in rs if r.get("error")),
            "avg_steps": round(sum(r.get("steps", 0) for r in rs) / n, 2),
            "avg_tools": round(sum(r.get("tool_executed", 0) for r in rs) / n, 2),
            "avg_tokens": round(sum(r.get("total_tokens", 0) for r in rs) / n),
            "avg_secs": round(sum(r["elapsed_s"] for r in rs) / n, 1),
            "parse_attempts": att,
            "parse_failures": fail,
            "parse_fail_rate": round(fail / att * 100, 1) if att else None,
        }

    summary = {m: agg(m) for m in modes}

    # ---------------- Markdown ----------------
    lines = []
    lines.append("# 双 ReAct 后端基准采样报告")
    lines.append("")
    lines.append(f"- 采样时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- 模型：`{os.getenv('LLM_MODEL')}`")
    lines.append(f"- 样本：{len(questions)} 个问题 × {len(modes)} 个后端，"
                 f"每问 **单次采样**（不含方差），max_steps={args.max_steps}")
    lines.append("- 两种后端共享同一套工具约束（`ToolRuntime` 去重 / 次数上限），"
                 "指标口径一致")
    lines.append("")
    lines.append("## 汇总对比")
    lines.append("")
    header = "| 指标 | " + " | ".join(f"`{m}`" for m in modes) + " |"
    lines.append(header)
    lines.append("|---" * (len(modes) + 1) + "|")

    def row(label, key, fmt="{}"):
        cells = []
        for m in modes:
            v = summary[m][key]
            cells.append("—" if v is None else fmt.format(v))
        lines.append(f"| {label} | " + " | ".join(cells) + " |")

    row("完成率", "finished", "{}")
    lines.append("| ↑ 分母（总 run 数） | " + " | ".join(str(summary[m]["runs"]) for m in modes) + " |")
    row("异常数", "errors")
    row("平均步数", "avg_steps")
    row("平均工具调用（真实打到 API）", "avg_tools")
    row("平均 token / 问", "avg_tokens")
    row("平均耗时 / 问（秒）", "avg_secs")
    row("格式解析失败率", "parse_fail_rate", "{}%")
    lines.append("| ↑ （失败轮数 / 输出轮数） | " + " | ".join(
        f"{summary[m]['parse_failures']}/{summary[m]['parse_attempts']}" for m in modes) + " |")
    lines.append("")
    lines.append("> `function_call` 没有解析器，因此解析失败率一栏为「—」"
                 "—— 这正是范式 B 被选中的结构性原因。")
    lines.append("")
    lines.append("## 逐条记录")
    lines.append("")
    lines.append("| 后端 | 问题 | 结果 | 步数 | 工具 | token | 耗时(s) | 解析失败 | 答案字数 |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for r in records:
        if r.get("error"):
            res = "异常"
        elif r.get("finished"):
            res = "完成"
        else:
            res = "未完成"
        lines.append(
            f"| `{r['mode']}` | {r['question'][:22]} | {res} | {r.get('steps', 0)} "
            f"| {r.get('tool_executed', 0)} | {r.get('total_tokens', 0)} "
            f"| {r['elapsed_s']} | {r.get('parse_failures', 0)} | {r['answer_chars']} |")
    lines.append("")

    os.makedirs(args.out, exist_ok=True)
    md_path = os.path.join(args.out, "bench_report.md")
    json_path = os.path.join(args.out, "bench_raw.json")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "records": records},
                  f, ensure_ascii=False, indent=2)

    print(f"\n✓ 报告已写入 {md_path}")
    print(f"✓ 原始记录已写入 {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
