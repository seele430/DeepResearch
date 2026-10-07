"""双后端控制流 smoke test —— 不需要 API Key。

跑法：  python test_backend_loop.py

做法：把 openai / rich / dotenv / tools 全部 stub 掉，用一个"按脚本出牌"的
假客户端驱动 agent.run_agent()，断言两个 ReAct 后端的**循环控制流**正确：

  * text   模式：解析失败 -> 回喂纠错 -> 恢复 -> 调工具 -> 收尾
  * function_call 模式：tool_calls -> 执行 -> 回填 -> 收尾

这一步补上了唯一无法靠单测覆盖的部分：主循环的胶水逻辑。
"""

import sys
import types

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

FAILED = []


def check(desc, got, want):
    ok = got == want
    print(("  OK  " if ok else " FAIL ") + desc + ("" if ok else f"\n         got={got!r}\n         want={want!r}"))
    if not ok:
        FAILED.append(desc)


# ---------------------------------------------------------------------------
# 1) stub: dotenv
# ---------------------------------------------------------------------------
_dotenv = types.ModuleType("dotenv")
_dotenv.load_dotenv = lambda *a, **k: None
sys.modules["dotenv"] = _dotenv

# ---------------------------------------------------------------------------
# 2) stub: rich（只吞掉打印）
# ---------------------------------------------------------------------------
class _Console:
    def print(self, *a, **k):
        pass


_rich = types.ModuleType("rich")
_rich_console = types.ModuleType("rich.console")
_rich_console.Console = _Console
_rich_panel = types.ModuleType("rich.panel")
_rich_panel.Panel = lambda *a, **k: ""
_rich.console = _rich_console
_rich.panel = _rich_panel
sys.modules["rich"] = _rich
sys.modules["rich.console"] = _rich_console
sys.modules["rich.panel"] = _rich_panel

# ---------------------------------------------------------------------------
# 3) stub: tools（记录被调用的工具）
# ---------------------------------------------------------------------------
TOOL_CALLS = []


def _web_search(query, max_results=3):
    TOOL_CALLS.append(("web_search", query))
    return f"SEARCH_RESULT for {query}"


def _read_url(url):
    TOOL_CALLS.append(("read_url", url))
    return f"PAGE_BODY of {url}"


def _save_note(filename, content):
    TOOL_CALLS.append(("save_note", filename))
    return "saved"


TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "搜索网页",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_url",
            "description": "读取网页正文",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
    },
]
_tools = types.ModuleType("tools")
_tools.TOOLS_SCHEMA = TOOLS_SCHEMA
_tools.TOOL_MAP = {"web_search": _web_search, "read_url": _read_url, "save_note": _save_note}
sys.modules["tools"] = _tools

# ---------------------------------------------------------------------------
# 4) stub: openai（按脚本出牌的假客户端）
# ---------------------------------------------------------------------------
class _Fn:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class _TC:
    def __init__(self, id_, name, arguments):
        self.id = id_
        self.function = _Fn(name, arguments)


class _Msg:
    """模仿 openai 的 message 对象：既有属性访问，也带 role。"""

    def __init__(self, content=None, tool_calls=None, role="assistant"):
        self.content = content
        self.tool_calls = tool_calls
        self.role = role


class _Resp:
    def __init__(self, msg):
        self.choices = [types.SimpleNamespace(message=msg)]


class _Completions:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.script:
            raise AssertionError("假客户端脚本用完了 —— 循环没有按预期结束")
        return _Resp(self.script.pop(0))


class _FakeClient:
    def __init__(self, script):
        self.chat = types.SimpleNamespace(completions=_Completions(script))


CLIENT = {"instance": None}


class _ClientProxy:
    """agent.py 在 import 阶段就构造了 client，而假脚本是之后才注入的。
    所以这里返回一个转发代理，等真正发起请求时才解析到假客户端。"""

    @property
    def chat(self):
        inst = CLIENT["instance"]
        if inst is None:
            raise AssertionError("假客户端还没注入")
        return inst.chat


def _OpenAI(**kwargs):
    return _ClientProxy()


_openai = types.ModuleType("openai")
_openai.OpenAI = _OpenAI
sys.modules["openai"] = _openai

import agent  # noqa: E402


def _texts(call_kwargs):
    """把一次请求里的 messages 压成纯文本，便于断言。"""
    out = []
    for m in call_kwargs["messages"]:
        out.append(m["content"] if isinstance(m, dict) else str(m))
    return "\n".join(out)


def test_text_backend():
    print("=== text 后端（范式 A）：解析失败 -> 纠错 -> 恢复 -> 收尾 ===")
    TOOL_CALLS.clear()
    CLIENT["instance"] = _FakeClient([
        # 第 1 轮：自由文本，解析必然失败
        _Msg(content="我觉得应该先搜索一下 AI Agent 的现状。"),
        # 第 2 轮：模型被纠错后给出正确格式
        _Msg(content='Thought: 搜索基本情况\nAction: web_search\n'
                     'Action Input: {"query": "AI Agent 现状"}\n'),
        # 第 3 轮：收尾
        _Msg(content="Thought: 信息足够\nFinal Answer: 这是最终报告。"),
    ])

    answer = agent.run_agent("AI Agent 现状如何？", max_steps=5, mode="text")
    comp = CLIENT["instance"].chat.completions

    check("返回最终答案", answer, "这是最终报告。")
    check("共发生 3 次模型调用", len(comp.calls), 3)
    check("确实执行了 web_search", TOOL_CALLS, [("web_search", "AI Agent 现状")])
    check("text 模式不传 tools", "tools" in comp.calls[0], False)
    check("text 模式传了 stop 序列", "stop" in comp.calls[0], True)
    check("text 模式是自由对话（无 tool 角色消息）",
          any(m.get("role") == "tool" for m in comp.calls[2]["messages"]), False)
    check("解析失败后把错误回喂给模型（纠错）",
          "[格式错误]" in _texts(comp.calls[1]), True)
    check("工具结果以 Observation 形式回喂",
          "Observation: SEARCH_RESULT for AI Agent 现状" in _texts(comp.calls[2]), True)


def test_text_backend_consecutive_failure():
    print("\n=== text 后端：连续 3 次解析失败应主动终止（不烧空转步数） ===")
    TOOL_CALLS.clear()
    CLIENT["instance"] = _FakeClient([
        _Msg(content="嗯，我先想想。"),
        _Msg(content="还是不太确定该怎么做。"),
        _Msg(content="要不我们换个思路？"),
        _Msg(content="这轮不该被调用到"),  # 兜底：如果被调用，脚本会继续出牌
    ])
    answer = agent.run_agent("测试", max_steps=10, mode="text")
    comp = CLIENT["instance"].chat.completions
    check("提前终止并说明原因", "不符合 ReAct 格式" in answer, True)
    check("只调用 3 次就停", len(comp.calls), 3)
    check("未执行任何工具", TOOL_CALLS, [])


def test_function_call_backend():
    print("\n=== function_call 后端（范式 B）：结构化调用 -> 回填 -> 收尾 ===")
    TOOL_CALLS.clear()
    CLIENT["instance"] = _FakeClient([
        _Msg(content=None, tool_calls=[_TC("call_1", "web_search", '{"query": "AI Agent"}')]),
        _Msg(content="这是 function calling 的最终报告。"),
    ])
    answer = agent.run_agent("AI Agent 现状如何？", max_steps=5, mode="function_call")
    comp = CLIENT["instance"].chat.completions

    check("返回最终答案", answer, "这是 function calling 的最终报告。")
    check("共发生 2 次模型调用", len(comp.calls), 2)
    check("确实执行了 web_search", TOOL_CALLS, [("web_search", "AI Agent")])
    check("传了 tools schema", comp.calls[0].get("tools") is TOOLS_SCHEMA, True)
    check("tool_choice=auto", comp.calls[0].get("tool_choice"), "auto")
    # 第 2 次请求里应当有 assistant(tool_calls) + tool(结果) 两条消息
    # 注意：assistant 那条是 message 对象（不是 dict）——这正是代码要求的行为
    msgs = comp.calls[1]["messages"]
    roles = [m["role"] if isinstance(m, dict) else m.role for m in msgs]
    check("二次请求含 assistant + tool 两条消息", roles, ["system", "user", "assistant", "tool"])
    tool_msg = [m for m in msgs if isinstance(m, dict) and m["role"] == "tool"][0]
    check("tool 消息带对的 tool_call_id", tool_msg["tool_call_id"], "call_1")
    check("tool 消息带工具结果", tool_msg["content"], "SEARCH_RESULT for AI Agent")
    check("assistant 消息保留了 tool_calls 字段",
          hasattr([m for m in msgs if not isinstance(m, dict)][0], "tool_calls"), True)


def test_shared_constraints():
    print("\n=== 两种后端共享同一套工程约束（去重 / 上限） ===")
    TOOL_CALLS.clear()
    CLIENT["instance"] = _FakeClient([
        _Msg(content=None, tool_calls=[
            _TC("c1", "web_search", '{"query": "same"}'),
            _TC("c2", "web_search", '{"query": "same"}'),  # 同轮内重复
        ]),
        _Msg(content="done"),
    ])
    agent.run_agent("测试去重", max_steps=3, mode="function_call")
    check("同轮内重复搜索只打一次外部 API", TOOL_CALLS, [("web_search", "same")])
    tool_msgs = [m for m in CLIENT["instance"].chat.completions.calls[1]["messages"]
                 if isinstance(m, dict) and m["role"] == "tool"]
    check("第二个调用拿到的是被拦下的提示",
          "已搜索过相似关键词" in tool_msgs[1]["content"], True)


def main():
    test_text_backend()
    test_text_backend_consecutive_failure()
    test_function_call_backend()
    test_shared_constraints()
    print("\n" + "=" * 64)
    if FAILED:
        print(f"{len(FAILED)} 项失败：")
        for f in FAILED:
            print("  - " + f)
        return 1
    print("全部通过：两个后端的循环控制流均已验证")
    return 0


if __name__ == "__main__":
    sys.exit(main())
