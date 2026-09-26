# 2025年国产大模型发展现状调研——DeepSeek vs 通义千问

## 一、行业概况
- 截至2025年11月，611款生成式AI服务完成备案，306款应用/功能完成登记（国家网信办）
- 《国家信息化发展报告(2024)》显示：DeepSeek、通义千问等产品性能位于全球前列
- LMArena榜单多款国产大模型名列前茅
- 2025年初DeepSeek爆火，掀起千行百业"AI+"热潮
- 竞争格局：文心一言(百度)、通义千问(阿里)、ChatGLM/智谱、Kimi(月之暗面)、豆包(字节)、DeepSeek(幻方/深度求索)

## 二、DeepSeek
- DeepSeek-V3(2024.12)：6710亿参数(MoE)，激活370亿，14.8万亿tokens预训练
- 性能接近GPT-4o/Claude-3.5-Sonnet；训练成本仅约557.6万美元，2788K H800 GPU小时
- 生成速度TPS从20提升到60(3倍)
- DeepSeek-R1(2025.1)：复杂推理模型，性能对标OpenAI o1；开源蒸馏小模型
- V3-0324(2025.3.24)：6850亿参数(激活约370亿)，升级MIT许可证，前端代码接近Claude 3.7，上下文128K
- 2026.2更新：上下文从128K提升到1M，知识截止2025.5
- App爆火：1月26日登顶苹果App Store，18天下载1600万次(约ChatGPT发布时2倍)
- 全球生态：英伟达NIM、微软Azure、AWS等接入；国产芯片适配(中科曙光+海光DCU)
- 开源多模态Janus-Pro击败DALL-E 3和Stable Diffusion

## 三、通义千问 Qwen
- 全球最大开源模型族群：已开源200多款模型，衍生模型超10万，超越Meta Llama
- HuggingFace下载量达1.8亿，衍生模型9万+
- Qwen2.5(2024.9)：0.5B-72B，128K上下文，18万亿tokens，Apache 2.0
- Qwen2.5-Max(2025.1)：超大规模MoE，20万亿+ tokens，性能超越DeepSeek-V3
- Qwen3(2025.4.29)：8款模型；旗舰Qwen3-235B-A22B(MoE，总参235B仅为R1的1/3，激活22B)，36万亿tokens，119种语言
  - 国内首款"快思考+慢思考"混合推理模型，支持enable_thinking切换
  - AIME25得81.5分(刷新开源纪录)，LiveCodeBench超70分(超Grok3)，ArenaHard 95.6分
  - 30B-A3B模型激活3B即媲美上代Qwen2.5-32B；32B跨级超越Qwen2.5-72B
- 全系列：Qwen-Coder/Qwen-VL/Qwen-Audio/Qwen-Math/QwQ/Qwen-Omni/Qwen-Embedding
- 2025.6开源Qwen3全系列32款MLX量化模型(苹果芯片优化)
- 服务超9万企业，覆盖金融、医疗、教育、游戏等

## 四、对比要点
- 架构：两者均采用MoE。DeepSeek-V3 6710亿(激活370亿)；Qwen3-235B(激活22B)，Qwen更强调"以小博大"
- 训练方法：DeepSeek R1用GRPO(结果奖励优化)；Qwen3用基于规则的奖励+多阶段训练，不完全依赖GRPO
- 数据：Qwen3 36万亿tokens(119语言)，自蒸馏；DeepSeek成本更低(557.6万美元)
- 战略定位：DeepSeek偏性能突破+极致低成本；Qwen偏全尺寸全模态开源生态

## 矛盾点/注意
- 网络上有内容称DeepSeek新模型参数量"1.8万亿"、与事实不符(简书来源可信度低，未证实)
- 部分搜索结果时间标注混乱(如2026年新闻出现)，需谨慎
