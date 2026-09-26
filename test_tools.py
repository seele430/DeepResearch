from dotenv import load_dotenv
load_dotenv()

from tools import read_url

print("=== 测试 read_url ===")
result = read_url("https://blog.csdn.net/mingzaizai_123/article/details/161568742")
print(result[:500])