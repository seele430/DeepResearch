from dotenv import load_dotenv
load_dotenv()

from tools import read_url

urls = [
    # CSDN（间歇性限流）
    "https://blog.csdn.net/mingzaizai_123/article/details/161568742",
    # 掘金真实文章（不是首页）
    "https://juejin.cn/post/743751135157780532",
    # 阮一峰真实周报
    "https://www.ruanyifeng.com/blog/2024/01/weekly-issue-284.html",
    # 知乎（反爬严重）
    "https://www.zhihu.com/question/19550224",
]

for url in urls:
    print(f"\n=== {url} ===")
    result = read_url(url)
    print(result[:300])
    print(f"[长度: {len(result)}]")