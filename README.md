# 📜 蛊箓 · 蛊真人维基百科

> **v1.0.0 · 第一版**｜本地部署、数据自管。

基于《蛊真人》全文（2334 章 + 序）+ 书友设定合集（约 40 万字）的**本地知识库 + 百科 + 游戏**网页应用。
**自带预建向量库（标准/中文增强两套模型可选），clone 即用；问答支持任意 OpenAI 兼容服务（不配 Key 也能用百科/阅读/游戏/检索测试）。**

## 特性

- 🔍 **混合检索**：稠密向量 + BM25 关键词，RRF 融合（人名/蛊名专名命中率高），四子库并行：正文（2335 块）+ 设定（1334 块）+ 章节摘要 + 百科词条（2968 条）
- 🧠 **多检索模型可选**：标准（bge-small-zh-v1.5，最快）/ jina-v2-base-zh（中文增强，更准）已预建随仓库分发；BGE-M3(ONNX) 可自行重建；网页一键切换，附实测准确率
- 🌐 **联网搜索兜底**：资料库答不了时自动联网搜索（DeepSeek Responses API web_search + chat 兼容双路径），网络回答标注参考来源、网址自动转链接；设置页可开关
- 🎯 **检索增强**：问题中的百科词条名**强制召回** + 回答要点**反哺二次检索**（命中过相似度门槛的章节再整合回答）+ 摘要库补位；检索范围过滤（全部库/仅正文）+ 多轮追问上下文
- 📝 **章节摘要增强**（可选）：剧情类问题先用章节摘要定位再回原文，检索命中大幅提升（试点：第1卷前13章已生效；生成全量摘要见 scripts/generate_summaries.py）
- 📖 **内置阅读器**：原版小说（卷→章目录 + 全文 + 上/下章）、插图版 PDF（本地 PDF.js 渲染）、人祖传、资料合集 docx 在线看（自动转 HTML）
- 🔗 **出处可定位**：答案的来源卡片可「阅读原文」（全文 + 高亮命中位置）、「打开本地文件」（直接打开对应 txt）
- 📚 **维基百科**：结构化词条——人物 178 / 蛊虫 769 / 仙蛊屋 481 / 人祖传 296 / 杀招 38 / 势力 21 / 灾劫 58 / 境界流派 50 / 天地秘境 31 / 五域地理 17（另「其他」1019 条自动归类）；分类浏览 + 搜索 + 详情 + 一键「问 AI」；词条可**在线编辑**（新增/改名/改分类），删除进**回收站**可恢复或彻底删除
- 🎮 **小游戏**：知识选择题 693 题（蛊虫 646 / 人物 27 / 蛊虫类型 20）+ 猜蛊虫/猜人物/猜物品谜题 491 道，本地计分，支持自定义题库批量导入
- 👤 **角色速查**：常用角色一键提问
- 🔌 **连接配置**：设置页可填写任意 OpenAI 兼容服务的 Base URL、API Key 和模型名，并在保存前测试连接
- 💰 **省钱**：向量库预建好（免费）；每次问答约 1~2 分钱；未配 Key 时自动进入“检索测试模式”

## 🎁 便携版：免安装，解压即用

> **不想装任何东西？用便携版。** 一个压缩包，解压后双击就能用——
> **不用装 Python、不用装环境、不用联网下载模型**，全部内置。

- **内置内容**：运行环境（Python + 依赖）、两套向量库、检索模型、小说全文 2335 章、插图 PDF、设定合集——**完全离线可用**
- **使用方式**：解压 → 双击 `gu-zhen-ren-rag\一键启动.bat` → 浏览器自动打开
- **压缩包内有说明**：解压后先看根目录的 `00-先看这里.txt`
- **哪里拿**：便携包体积约 360MB，放不进本仓库（GitHub 单文件限 100MB），由发布者另行提供（网盘 / 直接拷贝）；下方「快速开始」的一键启动脚本适用于任何电脑（只需装一次 Python）
- **注意**：便携包基于本机 Python 打包，适合直接拷贝使用；换电脑建议用仓库版

## 快速开始（新手 3 分钟）

> 不用懂任何命令：**装一次 Python，之后每次双击一个文件就能用。**

### 第 1 步：安装 Python（只装一次）

1. 打开 <https://www.python.org/downloads/> ，点黄色大按钮下载；
2. 双击安装包，**务必勾选** “Add Python to PATH”（加入系统路径），再一路点 Next；
3. 装完即可，以后不用再管它。

> 不确定装没装过？直接做第 2 步，脚本会帮你检查并提示。

### 第 2 步：双击启动

1. 把项目文件夹放到任意位置（路径里**不要有中文**，例如 `D:\gzr`）；
2. 双击文件夹里的 **`一键启动.bat`**；
3. 第一次运行会自动完成三件事（约 3 分钟，需要联网）：
   - 创建运行环境；
   - 安装依赖；
   - 下载约 90MB 的检索模型（只需一次）。
4. 以后每次使用，双击同一个文件，几秒就打开。

### 第 3 步：开始使用

- 浏览器会自动打开 **http://127.0.0.1:8000**（没自动打开就手动输入这个地址）；
- **不填任何 Key 也能用**：百科、阅读器、小游戏、检索测试（能看到每个问题命中了哪些章节）；
- 想让 AI 真正回答问题：页面右上角「设置」→ 填 Base URL / API Key / 模型名 → 「测试连接」→ 保存（任意 OpenAI 兼容服务都行，如 DeepSeek）；
- 用完直接**关掉黑色窗口**就是停止服务。

### 常见问题

| 现象 | 解决 |
|---|---|
| 提示找不到 Python | 做第 1 步；装完重新双击 |
| 提示依赖安装失败 | 网络问题，稍后再双击；还不行删掉 `.venv` 文件夹重试 |
| 端口 8000 被占用 | 右键编辑 `一键启动.bat`，把 `--port 8000` 改成 `--port 8001`，浏览器访问 8001 |
| 想更新代码后重装依赖 | 删掉 `.venv\.deps_ok` 再双击 |

### 高级用户：命令行方式（可选）

不习惯双击脚本，也可以在 PowerShell / CMD 里手动执行：

```bash
cd 项目目录
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --port 8000
```

已有环境则直接：

```bash
cd 项目目录
.venv\Scripts\uvicorn app.main:app --port 8000
```

浏览器打开 http://localhost:8000；端口被占用换 `--port 8001`。

## 项目结构

```
gu-zhen-ren-rag/
├── data/                    # ★ 预建向量库（已随仓库提供，无需重建）
│   ├── info.json            #   模型/维度/数量信息
│   ├── novel/               #   正文子库：vectors.npy + meta.json（2335 条）
│   ├── lore/                #   设定子库：vectors.npy + meta.json（1334 条）
│   ├── novel_sum/           #   章节摘要子库（13 条，检索增强用）
│   ├── wiki/                #   百科词条子库（2968 条，第4子库）
│   ├── wiki.json            #   百科权威数据（可在线编辑/回收站）
│   ├── quiz.json            #   题库：选择题 693 + 猜谜 491
│   ├── summaries.json       #   章节摘要原文（generate_summaries.py 产出）
│   └── testset.json         #   校准测试集（30 题，calib_testset.py 产出）
├── data_jina2/              # ★ jina-v2-base-zh 向量库（同结构，网页可切换）
├── app/
│   ├── main.py              # FastAPI 服务（问答/设置/百科/游戏/阅读/文件定位接口）
│   ├── rag.py               # 检索（RRF 融合）+ prompt 拼装 + LLM 调用（含联网兜底/反哺）
│   ├── library.py           # 阅读库：小说目录/章节全文/PDF 书签/资料合集 HTML
│   ├── embed.py             # BGE-M3(ONNX) 嵌入器（可选升级）
│   ├── config.py            # .env 配置（支持网页里保存 Key/切换模型）
│   └── static/              # 前端：index.html + app.js + app.css + refine.css + ink.css
│                            #       + wiki-browser.js/css + pdfjs/（本地 PDF.js）
├── scripts/
│   ├── build_db.py          # 从原文重建向量库（默认 bge-small，--text-free 可省原文）
│   ├── build_db_m3.py       # 用 BGE-M3(ONNX) 重建（--out data_m3，需先下载模型）
│   ├── quantize_m3.py       # BGE-M3 ONNX 动态 int8 量化（2.2GB → ~550MB）
│   ├── generate_summaries.py# 批量生成章节摘要（调 LLM，可增量）
│   ├── build_summaries.py   # 摘要向量化 → data/novel_sum/ 子库
│   ├── calib_testset.py     # 测试集校准（BM25 专名定位真实章节）
│   ├── eval_retrieval.py    # 检索评估（hit@k，内置 15 题 + 校准测试集）
│   ├── eval_models.py       # 多模型对比（30 题只计正文命中 → eval_results.json）
│   ├── eval_grid.py         # 检索参数网格实验（dense_k/bm25_k/RRF 常数等）
│   ├── build_wiki.py        # 设定库 → 百科 data/wiki.json
│   ├── build_wiki_store.py  # 百科词条 → 向量子库 wiki/
│   ├── build_quiz.py        # wiki.json → 题库 data/quiz.json（零 LLM 成本）
│   └── ai_toc.py            # AI 审核资料合集目录层级 → lore_toc.json
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
| `RAG_DATA_DIR` | `data` | 向量库目录（切到 `data_jina2` 用中文增强模型） |
| `RAG_MODEL_CACHE_DIR` | `model_cache` | 本地 embedding 模型缓存 |

旧版 `DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL` 仍可读取；同一项同时存在时优先使用 `AI_*`。

## 自己重建向量库（可选）

预建库已随仓库提供；如果你拿到的是自己的文本，或想换 embedding 模型：

```bash
# 需要：小说文本目录（默认 ../gu-zhen-ren，按卷/章分好的 txt）+ 设定 docx
python scripts/build_db.py
# 可选参数：--model BAAI/bge-small-zh-v1.5（更小更快） --text-free（不保存原文）
```

- 默认走 fastembed 的 BGE-M3（模型较大，失败自动回退 bge-small-zh-v1.5）；也可以直接用 `--model BAAI/bge-small-zh-v1.5` 或 `BAAI/bge-m3`
- 用官方 ONNX 版 BGE-M3（更快、免 torch）：先把模型放到 `model_cache/bge-m3-onnx/`，再跑 `python scripts/build_db_m3.py --out data_m3`；嫌大可先 `python scripts/quantize_m3.py` 转 int8
- 首次运行会下载 embedding 模型（BGE-M3 约 2GB，之后离线使用）。国内网络可先设置 `set HF_ENDPOINT=https://hf-mirror.com`

## 章节摘要（可选，提升剧情类问题检索）

1. 生成摘要：`python scripts/generate_summaries.py --vol 第1卷：魔性不改 --start 1 --end 199`（需要 .env 配置 key，会调 deepseek-chat 给每章写 150 字左右摘要，可增量续跑）
2. 建立摘要索引：`python scripts/build_summaries.py`（向量化 summaries.json 到 data/novel_sum/）
3. 重启服务生效。试点数据（第1卷前 13 章：第 1~10 章手工 + 第 11~13 章真实 API 生成）已随仓库提供，剧情类问题 top-1 命中率 2/8 → 7/8。

## 评估检索质量

```bash
python scripts/eval_retrieval.py            # 内置测试集（15 题，或优先用校准测试集 testset.json）
python scripts/calib_testset.py            # 校准测试集：BM25 专名定位真实章节（30 题）
python scripts/eval_models.py --save       # 多模型对比（30 题只计正文命中）→ eval_results.json 供网页展示
python scripts/eval_grid.py                # 参数网格实验（验证 k / RRF 常数 / 标题 boost 无增益）
```

根据结果修改 `.env` 里的 `RAG_TOP_K`，或直接在网页「设置」里切换检索模型。

### 检索模型实测对比（2026-08-15，校准测试集 30 题、只计正文命中、全库检索）

| 模型 | rrf@3 | rrf@5 | rrf@8 | dense@5 | 查询耗时 | 说明 |
|---|---|---|---|---|---|---|
| **bge-small-zh-v1.5**（默认，已随仓库） | 80% | 83% | 83% | 50% | 0.018s | 最快、体积最小（90MB） |
| **jina-v2-base-zh**（推荐更准，已随仓库 data_jina2） | 77% | **87%** | 90% | 50% | 0.033s | 中文专用，rrf@5 高 4pp |
| BGE-M3(int8) | — | — | — | — | — | int8 量化 + CPU 全量建库不可行，未达预期，不推荐 |

- 参数结论：`k=5` 已足够（k=8 几乎无增益）；**RRF 混合检索比纯向量高 ~33pp**（dense@5=50% → rrf@5=83%）——关键词腿在小说专名场景下极其关键；标题 boost / 加大候选池 / 调 RRF 常数均无增益，当前参数即最优
- 切换方式：网页「设置」→「检索模型」，或改 `.env` 的 `RAG_DATA_DIR=data_jina2` 后重启

## 成本参考（2026-08）

- 建库：¥0（本地向量化，已预建好随仓库分发；默认 bge-small-zh-v1.5，可换 jina / BGE-M3）
- 每次问答：约 1~2 分钱（deepseek-chat，3K 输入 + 0.8K 输出；命中缓存更低）
- 开发调试（deepseek-v4-flash）：一个项目约 ¥5~15

## 版权与使用

- 文本来源：百度贴吧精校版（见原文目录 README）；设定合集为书友社区整理，版权归作者蛊真人所有。
- 本仓库仅作个人学习使用，**请勿公开传播小说全文**；向量库含原文，公开分发请考虑 `--text-free` 重建（仅向量+章节元数据，不存原文）。
