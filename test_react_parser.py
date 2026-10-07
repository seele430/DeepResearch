"""文本 ReAct 解析器鲁棒性测试 —— 零依赖，不需要 API Key。

跑法：  python test_react_parser.py

设计意图
--------
范式 A（文本 ReAct）相对范式 B（Function Calling）多出来的**唯一**失败面
就是解析器。这里用真实模型输出中常见的畸形形态做回归测试，得出
"哪些能救、哪些救不回、哪些救回来反而是坑"的可复现数据 ——
这是决策 006 中"格式可靠性"论断的实测依据，而不是主观判断。

用例分三类：
  * 可救回     —— 解析成功，语义正确
  * 语义陷阱   —— 解析"成功"，但会导致错误调用（最危险的一类）
  * 无法救回   —— 解析失败，该轮 Agent 步骤作废
"""

import sys

try:  # Windows 控制台默认可能是 GBK，强制 UTF-8 输出
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from react_parser import parse

# ---------------------------------------------------------------------------
# 用例：(名称, 模型原始输出, 期望 kind, 期望 action, 备注)
# ---------------------------------------------------------------------------
CASES = [
    # ---------- 正常形态 ----------
    (
        "标准三行格式",
        'Thought: 先了解基本情况\n'
        'Action: web_search\n'
        'Action Input: {"query": "AI Agent 框架对比"}\n',
        "action", "web_search", "",
    ),
    (
        "正常收尾 Final Answer",
        'Thought: 信息已经足够\n'
        'Final Answer: 这是最终报告内容。\n',
        "final", None, "",
    ),

    # ---------- 可救回：格式漂移 ----------
    (
        "中文全角冒号",
        'Thought：先搜索\n'
        'Action：web_search\n'
        'Action Input：{"query": "AI Agent"}\n',
        "action", "web_search", "中文输入法残留，极常见",
    ),
    (
        "markdown 加粗",
        '**Thought**: 需要搜索\n'
        '**Action**: web_search\n'
        '**Action Input**: {"query": "test"}\n',
        "action", "web_search", "模型爱用 markdown 强调",
    ),
    (
        "Action Input 被代码块包裹",
        'Thought: 搜索一下\n'
        'Action: web_search\n'
        'Action Input: ```json\n'
        '{"query": "test"}\n'
        '```\n',
        "action", "web_search", "训练数据里 ReAct 都长这样",
    ),
    (
        "单引号 JSON",
        'Action: web_search\n'
        "Action Input: {'query': 'test'}\n",
        "action", "web_search", "Python 习惯污染",
    ),
    (
        "JSON 后带尾随解释",
        'Action: web_search\n'
        'Action Input: {"query": "test"} （test 是关键词）\n',
        "action", "web_search", "raw_decode 容忍尾随文本",
    ),
    (
        "行首缩进 + 列表符号",
        '  Thought: 搜索\n'
        '  Action: web_search\n'
        '  Action Input: {"query": "test"}\n',
        "action", "web_search", "",
    ),
    (
        "工具名大写",
        'Action: WEB_SEARCH\n'
        'Action Input: {"query": "test"}\n',
        "action", "web_search", "统一 lower 归一化",
    ),
    (
        "Action Input 用等号",
        'Action: web_search\n'
        'Action Input = {"query": "test"}\n',
        "action", "web_search", "非标准但出现过",
    ),
    (
        "Final Answer 正文内含 Action 字样",
        'Thought: 信息足够\n'
        'Final Answer: 调研结论如下。\n'
        '本次调研使用 Action: web_search 共 3 次。\n',
        "final", None, "靠出现顺序判定，不能被正文里的 Action 骗到",
    ),

    # ---------- 语义陷阱：解析成功但会出错 ----------
    (
        "Action Input 是裸值",
        'Action: read_url\n'
        'Action Input: https://example.com/article\n',
        "action", "read_url",
        "陷阱：解析成 {'input': ...}，参数名不对，工具层抛 TypeError",
    ),
    (
        "一次输出两个 Action",
        'Thought: 同时做两件事\n'
        'Action: web_search\n'
        'Action Input: {"query": "a"}\n'
        'Action: read_url\n'
        'Action Input: {"url": "https://example.com"}\n',
        "action", "web_search",
        "陷阱：第二个动作被静默丢弃，模型以为自己做过",
    ),

    # ---------- 无法救回 ----------
    (
        "JSON 被截断",
        'Thought: 搜索\n'
        'Action: web_search\n'
        'Action Input: {"query": "AI Agent\n',
        "error", None, "宁可报错也不猜参数，否则会拿错词去打真实搜索",
    ),
    (
        "自由文本（完全没格式）",
        '我需要先了解一下 AI Agent 的现状，让我搜索一下相关信息。\n',
        "error", None, "本轮步骤作废",
    ),
    (
        "只有 Thought 没有 Action",
        'Thought: 我应该先搜索一下\n',
        "error", None, "本轮步骤作废",
    ),
    (
        "空输出",
        '',
        "error", None, "本轮步骤作废",
    ),
]

TRAPS = {"Action Input 是裸值", "一次输出两个 Action"}


def main():
    width = 34
    print("=" * 104)
    print(f"{'结果':<7}{'用例':<{width}}{'解析结果':<12}{'action':<14}备注")
    print("=" * 104)

    passed = 0
    errors = []
    traps = []

    for name, raw, want_kind, want_action, note in CASES:
        r = parse(raw)
        ok = (r.kind == want_kind) and (want_action is None or r.action == want_action)
        passed += ok
        if r.kind == "error":
            errors.append(name)
        if name in TRAPS:
            traps.append(name)

        got = f"{r.kind}" + (f"({r.action})" if r.action else "")
        flag = "  OK  " if ok else " FAIL "
        pad = width - sum(2 if ord(c) > 127 else 1 for c in name)
        print(f"{flag:<7}{name}{' ' * max(pad, 1)}{got:<12}"
              f"{(r.action or '-'):<14}{note}")
        if not ok:
            print(f"         ^ 期望 kind={want_kind} action={want_action}，"
                  f"实际 kind={r.kind} action={r.action} error={r.error}")

    total = len(CASES)
    print("=" * 104)
    print(f"解析器行为断言：{passed}/{total} 通过")
    print(f"无法救回（本轮步骤作废）：{len(errors)}/{total}  ->  {', '.join(errors)}")
    print(f"语义陷阱（解析成功但调用会错）：{len(traps)}/{total}  ->  {', '.join(traps)}")
    print()
    print("结论（对应决策 006）：")
    print(f"  * 文本 ReAct 的格式失败率不是 0：{len(errors)}/{total} 的畸形输出直接作废一轮，")
    print(f"    另有 {len(traps)}/{total} 属于'解析成功但语义错'——这类不会报错，更难发现。")
    print("  * Function Calling 由 API 层做 schema 校验，这两类失败面都不存在。")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
