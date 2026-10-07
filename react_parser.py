"""文本 ReAct（范式 A）输出解析器。

**纯标准库实现，零依赖，可独立单测** —— 这是刻意的设计：
解析器是范式 A 唯一的失败面，必须能脱离 API 单独做回归测试。

真实模型输出里，`Action Input` 的形态远比提示词要求的多样。
本模块把那些"畸形但可救"的形态全部救回来，救不回来的如实报错。
"""

import json
import re

# ---------------------------------------------------------------------------
# 正则：容忍常见的格式漂移
#   - 中文全角冒号 ：       Action：web_search
#   - 全角/半角空格、Tab
#   - markdown 加粗        **Action**: web_search
#   - 列表符号             - Action: web_search / > Action: ...
#   - 行首缩进             "  Action: web_search"
# 注意：一律用 [ \t] 而不是 \s，避免跨越换行把下一个 section 误吞。
# ---------------------------------------------------------------------------
_ACTION_RE = re.compile(
    r"^[ \t>*\-]*(?:\*\*)?Action(?:\*\*)?[ \t]*[:：][ \t]*(?:\*\*)?[ \t]*"
    r"([A-Za-z_][A-Za-z0-9_]*)",
    re.I | re.M,
)

_ACTION_INPUT_RE = re.compile(
    r"^[ \t>*\-]*(?:\*\*)?Action[ \t]*Input(?:\*\*)?[ \t]*[:：][ \t]*(.*?)"
    r"(?=^[ \t>*\-]*(?:\*\*)?(?:Observation|Action|Thought|Final[ \t]*Answer)(?:\*\*)?[ \t]*[:：]|\Z)",
    re.I | re.M | re.S,
)

_THOUGHT_RE = re.compile(
    r"^[ \t>*\-]*(?:\*\*)?Thought(?:\*\*)?[ \t]*[:：][ \t]*(.*?)"
    r"(?=^[ \t>*\-]*(?:\*\*)?(?:Action|Final[ \t]*Answer|Observation)(?:\*\*)?[ \t]*[:：]|\Z)",
    re.I | re.M | re.S,
)

_FINAL_RE = re.compile(
    r"^[ \t>*\-]*(?:\*\*)?Final[ \t]*Answer(?:\*\*)?[ \t]*[:：][ \t]*(.*)",
    re.I | re.M | re.S,
)

_FENCE_RE = re.compile(r"```(?:json|JSON)?[ \t]*\r?\n?(.*?)```", re.S)

# 部分模型会用 "Action Input = {...}" 而不是冒号
_EQUALS_RE = re.compile(
    r"^[ \t>*\-]*(?:\*\*)?Action[ \t]*Input(?:\*\*)?[ \t]*=[ \t]*(.*?)"
    r"(?=^[ \t>*\-]*(?:\*\*)?(?:Observation|Action|Thought|Final[ \t]*Answer)(?:\*\*)?[ \t]*[:：=]|\Z)",
    re.I | re.M | re.S,
)

# 输出被 stop 序列或长度限制截断的痕迹
_TRUNCATED_TAIL_RE = re.compile(r"\{\s*\"?[^}]*$")


class ParseResult:
    """一次解析的结果。

    kind:
        "action" —— 解析成功，可执行
        "final"  —— 模型给出了最终答案，循环应结束
        "error"  —— 解析失败（范式 A 的真实失败面）
    """

    __slots__ = ("kind", "thought", "action", "action_input", "final", "error", "raw")

    def __init__(self, kind, thought=None, action=None, action_input=None,
                 final=None, error=None, raw=None):
        self.kind = kind
        self.thought = thought
        self.action = action
        self.action_input = action_input
        self.final = final
        self.error = error
        self.raw = raw

    def __repr__(self):
        return f"<ParseResult {self.kind} action={self.action!r} error={self.error!r}>"


def _strip_fences(text):
    """剥掉 markdown 代码块围栏；没有围栏时原样返回。"""
    m = _FENCE_RE.search(text)
    return m.group(1).strip() if m else text.strip()


def parse_action_input(raw):
    """把 Action Input 的原始文本解析为 (dict, error)。

    按"由严到宽"的顺序尝试，真实模型输出中这些形态都出现过：
        1. 标准 JSON            {"query": "x"}
        2. markdown 代码块       ```json\\n{"query": "x"}\\n```
        3. 带尾随解释文字        {"query": "x"}  （x 是关键词）
        4. 单引号 JSON           {'query': 'x'}
        5. 被截断的 JSON         {"query": "x"     -> 报错，不猜
        6. 裸值                  x                 -> {"input": "x"}
    """
    if raw is None:
        return None, "Action Input 缺失"
    text = _strip_fences(raw)
    if not text:
        return None, "Action Input 为空"

    # 1) 标准 JSON（裸值也走这里）
    try:
        val = json.loads(text)
        return (val if isinstance(val, dict) else {"input": val}), None
    except json.JSONDecodeError:
        pass

    # 2) 从最外层 "{" 起用 raw_decode，天然容忍尾随解释文字
    start = text.find("{")
    if start != -1:
        try:
            val, _ = json.JSONDecoder().raw_decode(text[start:])
            if isinstance(val, dict):
                return val, None
            return {"input": val}, None
        except json.JSONDecodeError:
            pass

        # 3) 单引号 JSON
        end = text.rfind("}")
        if end > start:
            candidate = text[start:end + 1]
            try:
                return json.loads(candidate.replace("'", '"')), None
            except json.JSONDecodeError:
                pass

    # 4) 截断痕迹：宁可报错，也不要凭空补一个参数去打真实的 API
    if _TRUNCATED_TAIL_RE.search(text):
        return None, f"Action Input 疑似被截断: {text[:60]!r}"

    # 5) 裸值
    bare = text.strip().strip('"').strip("'").strip()
    if bare:
        return {"input": bare}, None

    return None, "Action Input 无法解析"


def parse(text):
    """解析一次模型输出，返回 ParseResult。"""
    if not text or not text.strip():
        return ParseResult("error", error="模型输出为空", raw=text)

    thought_m = _THOUGHT_RE.search(text)
    thought = thought_m.group(1).strip() if thought_m else None

    action_m = _ACTION_RE.search(text)
    final_m = _FINAL_RE.search(text)

    # Final Answer 优先：只要它出现在 Action 之前（或压根没有 Action），就是收尾。
    # 注意不能简单写成 "有 Final Answer 就收尾" —— 报告正文里很可能出现
    # "Action:" 字样，反之也不能写成 "有 Action 就当工具调用"。
    if final_m and (action_m is None or final_m.start() < action_m.start()):
        return ParseResult("final", thought=thought, final=final_m.group(1).strip(), raw=text)

    if not action_m:
        return ParseResult("error", thought=thought,
                           error="未找到 Action 或 Final Answer", raw=text)

    # Action Input 优先按冒号形态取，取不到再试等号形态
    input_m = _ACTION_INPUT_RE.search(text) or _EQUALS_RE.search(text)
    raw_input = input_m.group(1) if input_m else None
    action_input, err = parse_action_input(raw_input)
    action = action_m.group(1)

    if err:
        return ParseResult("error", thought=thought, action=action, error=err, raw=text)

    # 工具名大小写漂移（Web_Search / WEB_SEARCH）统一为小写
    return ParseResult("action", thought=thought, action=action.lower(),
                       action_input=action_input, raw=text)
