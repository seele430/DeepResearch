"""ToolRuntime 行为回归测试 —— 零依赖（stub 掉 tools 模块），不需要 API Key。

跑法：  python test_tool_runtime.py

背景：双后端改造时，决策 002（去重）与决策 003（次数上限）的逻辑被从主循环
抽到了 ToolRuntime。本测试确保**抽取后行为不变**，并且两种 ReAct 后端
拿到的是完全相同的一套约束（否则范式对比就不公平）。
"""

import sys
import types

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ---------------------------------------------------------------------------
# stub 掉 tools 模块：跑测试不该被 requests / trafilatura / lxml 绑架
# ---------------------------------------------------------------------------
_calls = []


def _web_search(query, max_results=3):
    _calls.append(("web_search", query))
    return f"[call#{len(_calls)}] results for {query}"


def _read_url(url):
    _calls.append(("read_url", url))
    return f"BODY of {url}"


def _save_note(filename, content):
    _calls.append(("save_note", filename))
    return f"saved {filename}"


_fake = types.ModuleType("tools")
_fake.TOOL_MAP = {"web_search": _web_search, "read_url": _read_url, "save_note": _save_note}
_fake.TOOLS_SCHEMA = []
sys.modules["tools"] = _fake

from tool_runtime import ToolRuntime, norm_query, norm_url  # noqa: E402

FAILED = []


def check(desc, got, want):
    ok = got == want
    print(("  OK  " if ok else " FAIL ") + desc + ("" if ok else f"\n         got={got!r}\n         want={want!r}"))
    if not ok:
        FAILED.append(desc)


def main():
    print("=== 1. 关键词 / URL 归一化（决策 002） ===")
    check("大小写+标点归一化", norm_query("AI Agent，框架!!  对比"), "ai agent框架 对比")
    check("末尾斜杠去除", norm_url("https://a.com/x/"), "https://a.com/x")
    check("fragment 去除", norm_url("https://a.com/x#sec2"), "https://a.com/x")

    print("\n=== 2. 搜索：拒绝式去重 ===")
    rt = ToolRuntime()
    check("首次搜索被执行", rt.last_status, "ok")
    rt.execute("web_search", {"query": "AI Agent"})
    check("首次搜索后 status=ok", rt.last_status, "ok")
    check("计数 +1", rt.search_count, 1)

    before = len(_calls)
    rt.execute("web_search", {"query": "ai-agent!!"})  # 归一化后与 "AI Agent" 不同，见下
    check("归一化后不同关键词 -> 仍执行", len(_calls), before + 1)

    before = len(_calls)
    rt.execute("web_search", {"query": "AI Agent"})
    check("完全重复 -> blocked_dup", rt.last_status, "blocked_dup")
    check("完全重复 -> 不打外部 API", len(_calls), before)
    check("完全重复 -> 不消耗计数", rt.search_count, 2)

    print("\n=== 3. 阅读：缓存式去重 ===")
    rt2 = ToolRuntime()
    body = rt2.execute("read_url", {"url": "https://a.com/x"})
    check("首次阅读被执行", rt2.last_status, "ok")
    check("首次阅读返回正文", body, "BODY of https://a.com/x")

    before = len(_calls)
    cached = rt2.execute("read_url", {"url": "https://a.com/x#fragment"})
    check("同 URL(带 fragment) -> blocked_dup", rt2.last_status, "blocked_dup")
    check("命中缓存 -> 不打外部 API", len(_calls), before)
    check("命中缓存 -> 直接返回正文", "BODY of https://a.com/x" in cached, True)
    check("命中缓存 -> 不消耗计数", rt2.read_count, 1)

    print("\n=== 4. 次数上限（决策 003） ===")
    rt3 = ToolRuntime(max_search=2, max_read=1)
    rt3.execute("web_search", {"query": "q1"})
    rt3.execute("web_search", {"query": "q2"})
    rt3.execute("web_search", {"query": "q3"})
    check("超出搜索上限 -> blocked_limit", rt3.last_status, "blocked_limit")
    check("上限提示语包含次数", "已达搜索上限 2 次" in rt3.last_detail, True)
    check("超限不消耗计数", rt3.search_count, 2)

    rt3.execute("read_url", {"url": "https://a.com/1"})
    rt3.execute("read_url", {"url": "https://a.com/2"})
    check("超出阅读上限 -> blocked_limit", rt3.last_status, "blocked_limit")

    print("\n=== 5. 异常与未知工具 ===")
    rt4 = ToolRuntime()
    rt4.execute("no_such_tool", {})
    check("未知工具 -> unknown_tool", rt4.last_status, "unknown_tool")
    rt4.execute("read_url", {"wrong_param": "x"})   # 文本 ReAct 解析裸值的典型后果
    check("参数名错 -> failed（不是静默成功）", rt4.last_status, "failed")
    check("失败计入 stats", rt4.stats["failed"], 2)

    print("\n=== 6. 两种后端共用同一套约束 ===")
    a, b = ToolRuntime(), ToolRuntime()
    a.execute("web_search", {"query": "same"})
    check("runtime 之间状态隔离", (a.search_count, b.search_count), (1, 0))
    check("summary 可读", "搜索 1/5" in a.summary(), True)

    print("\n" + "=" * 60)
    if FAILED:
        print(f"{len(FAILED)} 项失败：")
        for f in FAILED:
            print("  - " + f)
        return 1
    print("全部通过：重构未改变决策 002 / 003 的行为")
    return 0


if __name__ == "__main__":
    sys.exit(main())
