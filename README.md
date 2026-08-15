# 📜 蛊箓 · 蛊真人维基百科

基于《蛊真人》全文（2334 章）+ 书友设定合集（约 40 万字）的**本地知识库 + 百科 + 游戏**网页应用。
**自带预建向量库，clone 即用；问答支持任意 OpenAI 兼容服务（不配 Key 也能用百科/阅读/游戏/检索测试）。**

## 特性

- 🔍 **混合检索**：稠密向量 + BM25 关键词，RRF 融合（人名/蛊名专名命中率高）
- 📚 **双知识库**：正文库（2334 章）+ 设定库（蛊虫百科/人物图鉴/势力/仙蛊屋等）
- 📖 **内置阅读器**：原版小说（章节目录+全文）、插图版 PDF、人祖传、资料合集 docx 在线看
- 🔗 **出处可定位**：答案的来源卡片可「阅读原文」（全文+高亮命中位置）、「打开本地文件」（直接打开对应 txt）
- 🔌 **连接配置**：设置页可填写任意 OpenAI 兼容服务的 Base URL、API Key 和模型名，并在保存前测试连接
- 🧠 **多检索模型可选**：标准（bge-small-zh-v1.5，快）/ BGE-M3（更准）/ jina-v2-base-zh（中文增强），网页一键切换，附实测准确率与速度
- 🎯 **检索范围过滤**：全部库 / 仅正文 / 仅设定；支持多轮追问上下文
- 📝 **章节摘要增强**（可选）：剧情类问题先用章节摘要定位再回原文，检索命中大幅提升（试点：第1卷前10章摘要已生效；生成全量摘要见 scripts/generate_summaries.py）
- 📚 **维基百科**：设定合集结构化整理——人物图鉴 181 条、蛊虫百科 1011 条、势力 95 条、仙蛊屋/灾劫/杀招/境界流派，分类浏览 + 搜索 + 详情，一键「问 AI」
- 🎮 **小游戏**：蛊真人知识选择题（蛊虫/人物/类型题库 440 题）+ 猜蛊虫/猜人物/猜物品谜题（764 道），本地计分
- 👤 **角色速查**：常用角色一键提问
- 💰 **省钱**：向量库预建好（免费）；每次问答约 1~2 分钱；未配 Key 时自动进入“检索测试模式”

## 快速开始（3 分钟）

```bash
# 1. 安装依赖（Python 3.10+）
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt

# 2. 启动（数据目录已随仓库提供）
uvicorn app.main:app --port 8000

# 3. 浏览器打开
#    http://localhost:8000

# 4. 连接 AI（两种方式任选）
#    ① 网页「设置」页 → 填写 Base URL、API Key、模型名 → 测试并保存（推荐，免重启）
#    ② 手动：copy .env.example .env → 编辑 AI_API_KEY / AI_BASE_URL / AI_MODEL → 重启服务
```

> 不填 Key 也能启动：页面显示“检索测试模式”，可看到每个问题检索到了哪些章节。

## 项目结构

```
gu-zhen-ren-rag/
├── data/                    # ★ 预建向量库（已随仓库提供，无需重建）
│   ├── info.json            #   模型/维度信息
│   ├── novel/               #   正文库：vectors.npy + meta.json（2335 条）
│   └── lore/                #   设定库：vectors.npy + meta.json
├── app/
│   ├── main.py              # FastAPI 服务（问答/设置/阅读库/文件定位接口）
│   ├── rag.py               # 检索（RRF 融合）+ prompt 拼装 + DeepSeek 调用
│   ├── library.py           # 阅读库：小说目录/章节全文/PDF/资料合集 HTML
│   ├── embed.py             # BGE-M3(ONNX) 嵌入器（可选升级）
│   ├── config.py            # .env 配置（支持网页里保存 Key）
│   └── static/index.html    # 前端（问答/阅读/设置 三栏，单文件）
├── scripts/
│   ├── build_db.py          # 从原文重建向量库（可选）
│   ├── build_db_m3.py       # 用 BGE-M3(ONNX) 重建（需先下载模型）
│   └── eval_retrieval.py    # 检索评估（hit@k）
├── .env.example
└── requirements.txt
```

## 配置项（.env）

| 变量 | 默认 | 说明 |
|---|---|---|
| `AI_API_KEY` | 空 | OpenAI 兼容服务的 Key，留空时进入检索测试模式 |
| `AI_BASE_URL` | `https://api.deepseek.com` | OpenAI 兼容接口地址 |
| `AI_MODEL` | `deepseek-chat` | 服务商开放的模型 ID |
| `RAG_TOP_K` | `5` | 检索返回片段数（可调，见评估） |
| `RAG_EXCERPT_CHARS` | `600` | 每个片段送入模型的字数 |
| `RAG_DATA_DIR` | `data` | 向量库目录 |
| `RAG_MODEL_CACHE_DIR` | `model_cache` | 本地 embedding 模型缓存 |

旧版 `DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL` 仍可读取；同一项同时存在时优先使用 `AI_*`。

## 自己重建向量库（可选）

预建库已随仓库提供；如果你拿到的是自己的文本，或想换 embedding 模型：

```bash
# 需要：小说文本目录（默认 ../gu-zhen-ren，按卷/章分好的 txt）+ 设定 docx
python scripts/build_db.py
# 可选参数：--model BAAI/bge-small-zh-v1.5（更小更快） --text-free（不保存原文）
```

首次运行会下载 embedding 模型（BGE-M3 约 2GB，之后离线使用）。
国内网络可先设置 `set HF_ENDPOINT=https://hf-mirror.com`。

## 章节摘要（可选，提升剧情类问题检索）

1. 生成摘要：`python scripts/generate_summaries.py --vol 第1卷：魔性不改 --start 1 --end 199`（需要 .env 配置 DeepSeek key，会调用 deepseek-chat 给每章写 150 字左右摘要，可增量续跑）
2. 建立摘要索引：`python scripts/build_summaries.py`（向量化 summaries.json 到 data/novel_sum/）
3. 重启服务生效。试点数据（第1卷前10章）已随仓库提供。

## 评估检索质量

```bash
python scripts/eval_retrieval.py            # 原测试集（15题）
python scripts/eval_models.py --save       # 多模型对比（30题，只计正文命中），结果写入 eval_results.json 供网页展示
```

根据结果修改 `.env` 里的 `RAG_TOP_K`，或直接在网页「设置」里切换检索模型。

### 检索模型实测对比（2026-08-15，校准测试集 30 题、只计正文命中、全库检索）

| 模型 | rrf@3 | rrf@5 | rrf@8 | dense@5 | 查询耗时 | 说明 |
|---|---|---|---|---|---|---|
| **bge-small-zh-v1.5**（默认） | 80% | 83% | 83% | 50% | 0.018s | 最快、体积最小（90MB） |
| **jina-v2-base-zh**（推荐更准） | 77% | **87%** | 90% | 50% | 0.033s | 中文专用，rrf@5 高 4pp |
| BGE-M3(int8) | — | — | — | — | — | int8 量化 + CPU 全量建库不可行，未达预期，不推荐 |

- 参数结论：`k=5` 已足够（k=8 几乎无增益）；**RRF 混合检索比纯向量高 ~33pp**（dense@5=50% → rrf@5=83%）——关键词腿在小说专名场景下极其关键；标题 boost / 加大候选池 / 调 RRF 常数均无增益，当前参数即最优
- 摘要增强对剧情类问题 top-1 命中 2/8 → 7/8；测试集校准脚本：`python scripts/calib_testset.py`（用 BM25 专名定位真实章节，避免人工标注偏差）
- 切换方式：网页「设置」→「检索模型」，或 `RAG_DATA_DIR=data_jina2` 后重启
- 想自己用 GPU/更强机器重建 fp32 BGE-M3：`python scripts/build_db_m3.py`（需先下载官方 onnx 到 model_cache/bge-m3-onnx/）


## 成本参考（2026-08）

- 建库：¥0（本地向量化，已预建好随仓库分发；默认 bge-small-zh-v1.5，可换 BGE-M3）
- 每次问答：约 1~2 分钱（deepseek-chat，3K 输入 + 0.8K 输出；命中缓存更低）
- 开发调试（deepseek-v4-flash）：一个项目约 ¥5~15

## 版权与使用

- 文本来源：百度贴吧精校版（见原文目录 README）；设定合集为书友社区整理，版权归作者蛊真人所有。
- 本仓库仅作个人学习使用，**请勿公开传播小说全文**；向量库含原文，公开分发请考虑 `--text-free` 重建（仅向量+章节元数据，不存原文）。
