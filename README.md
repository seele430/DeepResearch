# DeepResearch

> **一个基于 ReAct 模式的多步调研 Agent，能自主搜索、阅读、验证信息，并生成带引用来源的研究报告。**

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## ✨ Features / 特性

- **🤖 自主决策**：基于 ReAct（Reasoning + Acting）模式，LLM 自主决定何时搜索、何时阅读、何时收尾
- **🔍 多步调研**：不是"搜一次就答"，而是多角度搜索 + 深入阅读 + 交叉验证
- **📝 带引用报告**：输出结构化研究报告，每条结论附来源链接
- **🧠 自我反思**：主动识别信息矛盾，标注来源可信度，说明调研局限
- **⚡ 工程化优化**：
  - 工具调用去重（避免重复搜索/阅读）
  - 工具调用次数上限（防止失控）
  - 网页抓取 UA 伪装 + 降级方案

---

## 🏗️ Architecture / 架构
```
用户提问
   │
   ▼
┌─────────────────────────────────────┐
│         ReAct Agent Loop            │
│                                     │
│   ┌──────────────────────────┐      │
│   │  1. LLM 推理下一步做什么  │      │
│   └──────────┬───────────────┘      │
│              │                      │
│              ▼                      │
│   ┌──────────────────────────┐      │
│   │  2. 选择工具并执行        │      │
│   └──────────┬───────────────┘      │
│              │                      │
│              ▼                      │
│   ┌──────────────────────────┐      │
│   │  3. 观察结果，加入上下文  │      │
│   └──────────┬───────────────┘      │
│              │                      │
│              └──── 循环直到能回答 ──┐│
│                                     ││
└─────────────────────────────────────┘│
                                       │
                                       ▼
                              最终报告（带来源）
```

### 工具集

| 工具 | 功能 | 实现 |
|------|------|------|
| `web_search` | 搜索网页，返回链接和摘要 | 博查 Bocha API |
| `read_url` | 抓取网页正文 | requests + trafilatura + BeautifulSoup |
| `save_note` | 保存调研笔记到本地 | 文件写入 |

---
## 🚀 Quick Start / 快速开始

### 1. 环境要求

- Python 3.10+
- 一个 LLM API Key（推荐 [DeepSeek](https://platform.deepseek.com)，便宜且国内直连）
- 一个搜索 API Key（推荐 [博查 Bocha](https://open.bochaai.com)，国内直连）

### 2. 安装

```bash
git clone https://github.com/your-username/deepresearch.git
cd deepresearch

python -m venv venv
# Windows
venv\Scripts\activate
# Mac/Linux
source venv/bin/activate

pip install -r requirements.txt
```

## 📖 Usage / 使用示例

### 示例问题

### 输出示例

完整示例报告见 [examples/sample-report.md](examples/sample-report.md)。

节选：

> **## 二、DeepSeek**
> - DeepSeek-V3（2024.12）：6710 亿参数（MoE），激活 370 亿，14.8 万亿 tokens 预训练
> - 性能接近 GPT-4o/Claude-3.5-Sonnet；训练成本仅约 557.6 万美元
>
> **## ⚠️ 矛盾点/注意**
> - 网络上有内容称 DeepSeek 新模型参数量"1.8 万亿"，与事实不符（简书来源可信度低，未证实）

**注意 Agent 主动识别了信息矛盾并标注来源可信度。**

---
## 🧠 Design Decisions / 设计决策

本项目记录了完整的工程决策过程，见 [DECISIONS.md](DECISIONS.md)。核心决策包括：

| # | 决策 | 核心权衡 |
|---|------|---------|
| 001 | 多轮对话：简单 REPL vs 共享上下文 | 避免过早优化，先验证核心循环 |
| 002 | 工具调用去重 | 搜索拒绝式去重 + 阅读缓存式去重 |
| 003 | 工具调用次数上限 | 防止失控，提示而非报错 |
| 004 | 搜索上限的反思 | 次数上限只是症状缓解，病根在 read_url 失败率 |
| 005 | read_url 添加 UA 伪装 | 解决 CSDN 等站点的反爬问题 |

**为什么记录决策？** 因为"做了什么"容易看到，"为什么这么做"才是工程价值的核心。

---
## 🛠️ Tech Stack / 技术栈

| 类别 | 技术 |
|------|------|
| 语言 | Python 3.10+ |
| LLM | DeepSeek（兼容 OpenAI SDK） |
| 搜索 | 博查 Bocha API |
| 网页解析 | trafilatura + BeautifulSoup4 + lxml |
| HTTP | requests |
| CLI 展示 | rich |
| 配置 | python-dotenv |

**说明**：本项目**不依赖 LangChain / LangGraph**，Agent 循环是手写的。目的是理解 Agent 的本质机制。

---
## 📁 Project Structure / 项目结构
```
deepresearch/
├── agent.py                # Agent 主循环（ReAct 实现）
├── tools.py                # 工具定义（搜索、阅读、保存）
├── requirements.txt        # 依赖列表
├── .env                    # 环境变量（不提交）
├── .env.example            # 环境变量模板
├── .gitignore              # Git 忽略规则
├── DECISIONS.md            # 技术决策记录
├── README.md               # 本文件
├── examples/
│   └── sample-report.md    # 示例调研报告
├── test_tools.py           # 工具测试
└── test_read_url.py        # 网页抓取专项测试
```
---
## 🗺️ Roadmap / 后续计划

- [ ] **阶段二**：Plan-and-Execute 模式（先规划后执行）
- [ ] **阶段二**：长期记忆系统（向量数据库）
- [ ] **阶段三**：Multi-Agent 协作（Planner / Researcher / Analyst / Writer / Critic）
- [ ] Web UI（Streamlit / FastAPI）
- [ ] 打包为可执行文件（PyInstaller）

---
## 📄 License

MIT

---

## 🙏 致谢

- [DeepSeek](https://platform.deepseek.com) — LLM 服务
- [博查 Bocha](https://open.bochaai.com) — 搜索 API
- [trafilatura](https://github.com/adbar/trafilatura) — 网页正文提取

---

**如果这个项目对你有帮助，欢迎 Star ⭐**