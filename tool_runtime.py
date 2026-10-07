"""工具执行运行时：承载去重与调用上限，与 ReAct 实现范式解耦。

重构动机：决策 002（去重）与决策 003（次数上限）原本内联在 function calling
分支里。要做范式对比，两种后端必须**共享同一套工程约束**，否则对比的是
"两个不同的策略"而不是"两种不同的范式"。

所以把约束下沉到这里：无论文本 ReAct 还是原生 Function Calling，
都通过 ToolRuntime.execute() 执行工具。
"""

from tools import TOOL_MAP


def norm_query(q):
    """标准化搜索关键词：转小写、去标点、合并空格（决策 002）。"""
    q = (q or "").lower().strip()
    q = "".join(c for c in q if c.isalnum() or c.isspace())
    return " ".join(q.split())


def norm_url(url):
    """标准化 URL：去末尾斜杠、去 #fragment（决策 002）。"""
    url = (url or "").strip().rstrip("/")
    if "#" in url:
        url = url.split("#")[0]
    return url


class ToolRuntime:
    """一次 Agent run 的工具执行上下文。

    用法::

        rt = ToolRuntime(max_search=5, max_read=8)
        observation = rt.execute("web_search", {"query": "..."})
        if rt.last_status == "blocked_dup":
            ...

    last_status 取值：
        ok / blocked_limit（撞上限）/ blocked_dup（被去重）
        failed（工具报错）/ unknown_tool
    """

    def __init__(self, max_search=5, max_read=8):
        self.max_search = max_search
        self.max_read = max_read
        self.seen_queries = set()
        self.read_cache = {}
        self.search_count = 0
        self.read_count = 0
        self.last_status = "ok"
        self.last_detail = ""
        # 统计：用于对比两种范式的行为差异
        self.stats = {
            "executed": 0,   # 真正打到外部 API 的工具调用
            "blocked": 0,    # 被去重/上限拦下的调用
            "failed": 0,     # 工具自身报错
        }

    def _set(self, status, detail=""):
        self.last_status = status
        self.last_detail = detail
        return detail

    def execute(self, name, args):
        """执行一次工具调用，返回给模型看的 observation 文本。"""
        args = args if isinstance(args, dict) else {}

        # ---------- 搜索：拒绝式去重 + 次数上限（决策 002 / 003） ----------
        if name == "web_search":
            if self.search_count >= self.max_search:
                self.stats["blocked"] += 1
                detail = f"已达搜索上限 {self.max_search} 次"
                self._set("blocked_limit", detail)
                return (f"[{detail}] 请基于已有信息作答，"
                        f"或调用 read_url 深入阅读已搜到的链接。")
            key = norm_query(args.get("query", ""))
            if key in self.seen_queries:
                self.stats["blocked"] += 1
                detail = f"跳过重复搜索: {key}"
                self._set("blocked_dup", detail)
                return (f"[已搜索过相似关键词] {args.get('query')}，"
                        f"请换一个更具体的词，或直接使用已有信息。")
            self.seen_queries.add(key)
            self.search_count += 1

        # ---------- 阅读：缓存式去重 + 次数上限（决策 002 / 003） ----------
        elif name == "read_url":
            if self.read_count >= self.max_read:
                self.stats["blocked"] += 1
                detail = f"已达阅读上限 {self.max_read} 次"
                self._set("blocked_limit", detail)
                return f"[{detail}] 请基于已有信息作答。"
            key = norm_url(args.get("url", ""))
            if key in self.read_cache:
                self.stats["blocked"] += 1
                detail = f"命中阅读缓存: {key}"
                self._set("blocked_dup", detail)
                return f"[已读取过该网页] 内容如下：\n{self.read_cache[key]}"
            self.read_count += 1

        # ---------- 实际执行 ----------
        func = TOOL_MAP.get(name)
        if func is None:
            self.stats["failed"] += 1
            self._set("unknown_tool")
            return f"未知工具: {name}"

        try:
            result = str(func(**args))
        except TypeError as e:
            # 参数名/参数个数不对（模型给了幻觉参数，或文本解析回了错误的键名）
            self.stats["failed"] += 1
            self._set("failed")
            return f"工具参数错误: {e}"
        except Exception as e:
            self.stats["failed"] += 1
            self._set("failed")
            return f"工具执行失败: {e}"

        if name == "read_url":
            self.read_cache[norm_url(args.get("url", ""))] = result

        self.stats["executed"] += 1
        self._set("ok")
        return result

    def summary(self):
        return (f"工具执行 {self.stats['executed']} 次 / "
                f"被拦下 {self.stats['blocked']} 次 / "
                f"失败 {self.stats['failed']} 次 | "
                f"搜索 {self.search_count}/{self.max_search} "
                f"阅读 {self.read_count}/{self.max_read}")
