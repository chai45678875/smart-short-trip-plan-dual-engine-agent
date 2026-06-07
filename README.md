# 🛋 你的短时生活搭子

### Plan-then-Execute 双引擎本地短时活动规划 Agent

> 输入一句"今天下午带孩子出去玩，别太远"，
> 几分钟内自动完成 **POI 搜索 → 排队查询 → 餐厅预订 → 时间轴方案 → 一键分享**。
> 无论是否接入 LLM，都能稳定输出可用方案 — 这得益于 **Plan-then-Execute 策略 + 规则模板兜底** 的双引擎设计。

---

## 📖 目录

- [效果预览](#-效果预览)
- [四维度评审视角](#-四维度评审视角)
  - [1. 创新性](#1-创新性)
  - [2. 完整性](#2-完整性)
  - [3. 应用效果](#3-应用效果)
  - [4. 商业价值](#4-商业价值)
- [快速启动](#-快速启动)
- [项目结构](#-项目结构)
- [核心模块详解](#-核心模块详解)
- [API 端点](#-api-端点)
- [配置指南](#-配置指南)
- [技术栈](#-技术栈)
- [安全说明](#-安全说明)

---

## 🖼️ 效果预览

### 首页 · 双模式切换

![首页界面]((https://raw.githubusercontent.com/chai45678875/smart-short-trip-plan-dual-engine-agent/main/smart-travel-planner/docs/screenshots/01-homepage.png))

左侧为 **快速模式**（规则引擎秒级生成）与 **Agent 模式**（Plan-then-Execute 流式规划）的双入口，右侧 Leaflet 地图实时渲染 POI 与路线。

### 场景预设 · 一键填充

![场景预设](https://raw.githubusercontent.com/chai45678875/smart-short-trip-plan-dual-engine-agent/main/smart-travel-planner/docs/screenshots/02-scene-preset.png)

内置 4 类用户画像快捷入口（亲子 / 情侣 / 学生 / 游客），点击后自动填充意图参数，降低输入成本。

### Agent 模式 · 白盒可视化

![Agent 规划过程](https://raw.githubusercontent.com/chai45678875/smart-short-trip-plan-dual-engine-agent/main/smart-travel-planner/docs/screenshots/03-agent-planning.png)

Agent 的每一步操作实时展示：调用了哪个 Tool、传了什么参数、耗时多少、是否触发降级。用户全程可见决策链路。

### Agent 结果 · 时间轴 + 地图

![Agent 结果](https://raw.githubusercontent.com/chai45678875/smart-short-trip-plan-dual-engine-agent/main/smart-travel-planner/docs/screenshots/04-agent-result.png)

规划完成后输出结构化时间轴，含每个节点的地点、时间、预订状态，并同步渲染到地图。

### 快速模式 · 秒级路线生成

![快速路线](https://raw.githubusercontent.com/chai45678875/smart-short-trip-plan-dual-engine-agent/main/smart-travel-planner/docs/screenshots/05-quick-route.png)

规则引擎在 20ms 内完成意图识别 + POI 筛选 + 多因子评分排序，输出可直接执行的路线方案。

---

## 📊 四维度评审视角

本作品从 **创新性、完整性、应用效果、商业价值** 四个维度进行设计与实现。

---

### 1. 创新性

#### 策略创新：Plan-then-Execute 替代 ReAct

传统 Agent 多采用 ReAct（Think→Act→Observe 循环），其 LLM 调用次数随任务复杂度不可控，串行执行慢、成本高。

本项目针对**短时活动规划**这一高度结构化场景，采用 **Plan-then-Execute** 策略：

```
用户输入 → 全局规划（Plan）→ 批量执行（Execute）→ 方案生成（Generate）
         └─ 固定 2-3 轮 LLM 调用 ─┘
```

| 维度 | ReAct | Plan-then-Execute（本方案） |
|------|-------|----------------------------|
| LLM 调用次数 | 不可控（6-10+ 轮） | **固定 2-3 轮** |
| 执行方式 | 串行试错 | **并行批量 Tool 调用** |
| 确定性 | 低，可能陷入循环 | **高，阶段边界清晰** |
| 成本 | 高 | **可控，可预估** |

短时出行场景的知识需求封闭（搜 POI → 查排队 → 预订 → 排时间），不需要开放域推理，Plan-then-Execute 是更优解。

#### 架构创新：LLM + 规则模板双引擎

系统不依赖单一 LLM，而是构建**双引擎**架构：

- **主引擎**：LLM 做语义理解、方案润色、异常解释
- **兜底引擎**：规则模板（关键词匹配 + 场景模板 + 多因子评分）在 LLM 不可用时无缝接管

#### 机制创新：三级降级保障

| 层级 | 触发条件 | 降级策略 | 输出质量 |
|------|----------|----------|----------|
| **L1** | LLM 正常 | 语义理解 + 智能生成 | 完全个性化 |
| **L2** | LLM 不可用 / 超时 | 规则引擎兜底 | 按场景模板生成，标注"通用推荐" |
| **L3** | Tool 调用失败 | Observation 最小方案 | 至少 1 景点 + 1 餐，标注"部分估算" |

**任何情况下，用户都能拿到一个可用的出行方案**，实现 100% 方案可用率。

#### 交互创新：白盒可视化

前端实时展示 Agent 的完整思考链：
- 每个 Tool 的调用时机、参数、耗时
- 每个 Tool 的返回结果摘要
- 异常时标记降级路径和原因

用户从"黑盒等待"变为"白盒旁观」，信任感显著提升。

---

### 2. 完整性

#### 功能完整性：双模式覆盖全场景

| 模式 | 技术路径 | 响应速度 | 适用场景 |
|------|----------|----------|----------|
| **快速模式** | 规则引擎 + 多因子评分 | ~20ms | 明确需求，追求效率 |
| **Agent 模式** | Plan-then-Execute + LLM | ~500ms-2s | 模糊需求，需要对话澄清 |

两种模式共享同一套 POI 数据和地图渲染层，用户可随时切换对比。

#### 链路完整性：端到端闭环

一条用户输入，系统完成完整链路：

```
意图识别 → POI 搜索 → 排队查询 → 餐厅预订 → 时间轴编排 → 地图渲染 → 一键分享
   ↑                                                              ↓
└──── 语义理解（LLM/规则）                            结果交付（Markdown + 地图 + 短信）
```

4 个 Mock Tool 接口已与真实 API 对齐，可无缝替换：

| Tool | 功能 | 替换目标 |
|------|------|----------|
| `search_pois` | POI 搜索与排序 | 大众点评/美团搜索 API |
| `check_queue` | 排队查询 | 美团排队 API |
| `book_table` | 预订确认 | 美团预订 API |
| `send_plan` | 方案分享 | 微信分享/短信接口 |

#### 用户覆盖完整性：4 类画像差异化策略

| 画像 | 标签偏好 | 节奏设计 | 预算策略 |
|------|----------|----------|----------|
| 👨‍👩‍👧 **亲子** | 教育、户外、安全 | 三段式（玩→歇→吃） | 中等，强调性价比 |
| 💑 **情侣** | 夜景、拍照、浪漫 | 两段式（景→餐） | 中高，氛围优先 |
| 👫 **朋友** | 热门、社交、娱乐 | 灵活，支持多人 | 分摊，人均可控 |
| 🧘 **独行** | 安静、小众、灵活 | 单点深度 | 自由，无约束 |

#### 文档完整性：全生命周期文档

- **[AGENT_DESIGN.md](./AGENT_DESIGN.md)** — 技术设计文档（Planning 策略、Tool 链路、异常处理）
- **[PORTFOLIO.md](./PORTFOLIO.md)** — 产品经理视角（需求分析、决策过程、迭代反思）
- **API 文档** — FastAPI 自动生成 OpenAPI/Swagger UI（`http://localhost:8000/docs`）
- **环境配置模板** — `.env.example` 含全部可配置项说明

---

### 3. 应用效果

#### 交互自然度

支持**自然语言输入**，用户无需学习结构化指令：

| 用户输入示例 | 系统理解 |
|-------------|----------|
| "带老婆去一个有夜景的地方吃顿好的" | 情侣场景 → 夜景/拍照标签 → 高评分餐厅 |
| "孩子考完试了想带他放松" | 亲子场景 → 过滤刺激项目 → 三段式节奏 |
| "下班了想一个人静静，然后吃个饭" | 独行场景 → 安静标签 → 灵活时间 |

#### 响应及时性

| 阶段 | 快速模式 | Agent 模式 |
|------|----------|-----------|
| 意图识别 | ~5ms（关键词） | ~200ms（LLM） |
| POI 搜索 | ~10ms | ~50ms |
| 方案生成 | ~5ms（模板填充） | ~300ms（LLM 润色） |
| **总耗时** | **~20ms** | **~500ms-2s** |

Agent 模式通过**流式 SSE 推送**实时展示进度，用户感知等待时间显著缩短。

#### 输出准确性

多因子评分模型综合 6 个维度对 POI 排序：

```
score = w1·rating + w2·popularity + w3·distance + w4·price_match + w5·tag_match + w6·time_fit
```

用户可通过前端滑块实时调整权重，系统即时重新排序，实现**可解释的个人化推荐**。

#### 稳定性

三级降级保障下，系统在以下场景仍可用：
- ❌ LLM API 欠费 / 超时 → L2 规则引擎接管
- ❌ 网络中断（Tool 调用失败）→ L3 最小方案
- ✅ 离线环境（无网络）→ 纯规则引擎运行

---

### 4. 商业价值

#### 痛点真实：本地生活决策成本高

用户规划一次 2-6 小时的短时出行，平均需要在 3-5 个 App 间切换（点评→高德→美团→微信），决策时间 15-30 分钟。Agent 将其压缩为**一次对话 + 几分钟执行**。

#### 落地路径清晰：Mock → 真实 API

当前 4 个 Tool 均为 Mock 实现，但接口已与真实 API 对齐：

```python
# 替换示例：将 search_pois 从 Mock 改为真实美团 API
# 只需修改 backend/agent/tools.py 中 search_pois 函数内部实现
# 输入输出数据结构保持不变
```

#### 商业化场景

| 场景 | 商业模式 |
|------|----------|
| **本地生活平台插件** | 作为美团/点评的"智能规划"功能模块，按调用量收费 |
| **酒店/景区增值服务** | 为住客提供"周边短时游"规划，提升入住体验 |
| **企业团建工具** | 基于人数、预算、偏好自动生成团建方案 |
| **数据服务** | 积累用户偏好数据，输出区域消费热力报告 |

#### 成本优势

相比纯 LLM 方案，Plan-then-Execute 将 LLM 调用次数从 6-10 轮压缩到 **固定 2-3 轮**，单次查询成本降低 **60%-70%**，在规模化场景下具备显著的成本优势。

---

## 🚀 快速启动

### 环境要求

- **Python** ≥ 3.10
- **pip**（Python 自带）
- LLM API Key **可选**（不配置也能用规则引擎）

### 三步启动

```bash
# 1. 进入项目目录
cd smart-travel-planner

# 2. 安装依赖（约 5 秒）
pip install -r requirements.txt

# 3. 启动服务
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

打开浏览器访问 → **http://localhost:8000**

### Windows 用户

直接双击 `start.bat`，自动完成依赖安装和启动。

### 验证启动成功

```bash
curl http://localhost:8000/api/health
# 返回: {"status": "ok", "timestamp": "..."}
```

---

## 📁 项目结构

```
smart-travel-planner/
│
├── backend/                        # Python 后端
│   ├── main.py                     # FastAPI 入口，13+ 个 API 端点
│   ├── config.py                   # LLM 配置、推荐策略参数、场景模板
│   ├── requirements.txt            # Python 依赖
│   │
│   ├── agent/                      # Agent 核心（Plan-then-Execute）
│   │   ├── planner.py              #   三阶段规划器：Plan→Execute→Generate
│   │   ├── tools.py                #   4 个 Tool 的 Mock API 实现
│   │   └── executor.py             #   Tool 调度与日志收集
│   │
│   ├── engine/                     # 推荐引擎
│   │   ├── intent.py               #   意图识别：LLM 语义 + 关键词兜底
│   │   ├── agent.py                #   AI 推荐：LLM 生成 + 规则兜底
│   │   ├── llm_client.py           #   多模型适配层（智谱/DeepSeek/本地）
│   │   ├── recommender.py          #   推荐模块对外统一接口
│   │   ├── rag_engine.py           #   轻量 RAG：字符 n-gram 相似度
│   │   └── rag_engine_standard.py  #   标准 RAG：jieba + TF-IDF
│   │
│   ├── data/
│   │   └── poi_data.py             #   郑州 22 个 POI（景点+餐厅标签+坐标）
│   │
│   └── llm/
│       └── __init__.py
│
├── frontend/
│   └── index.html                  # 单页 Web UI（Leaflet 地图 + 完整交互）
│
├── docs/
│   └── screenshots/                # 运行时截图（README 引用）
│
├── start.bat                       # Windows 一键启动
├── requirements.txt                # 根目录依赖（指向 backend）
├── .env.example                    # 环境变量模板
├── .gitignore
├── AGENT_DESIGN.md                 # Agent 技术设计文档
├── PORTFOLIO.md                    # 产品经理作品集
└── README.md
```

---

## 📐 核心模块详解

### 1. Planner（规划器）— `backend/agent/planner.py`

三阶段确定性流程：

- **Plan**：调用意图识别 → 分析用户画像（亲子/情侣/朋友/独行）→ 调用 `search_pois` 获取候选集
- **Execute**：对每个候选餐厅并行调用 `check_queue` + `book_table`
- **Generate**：按场景模板编排时间轴 → LLM 润色 → 组装完整方案

### 2. Tools（工具层）— `backend/agent/tools.py`

每个 Tool 返回统一结构：

```python
{
    "success": True,          # 是否成功
    "tool_name": "search_pois",
    "duration_ms": 45,        # 耗时
    "summary": "找到 10 个景点, 8 个美食",  # 人类可读摘要
    "data": { ... }           # 完整返回数据
}
```

- POI 数据源在 `backend/data/poi_data.py`，包含 22 条带标签、坐标、评分、人均消费的结构化数据
- 排队状态由 Mock 函数模拟，支持高峰期/低峰期差异化
- 预订返回唯一预订号格式 `MT-{restaurant_id}-{random_hex}`

### 3. Intent（意图识别）— `backend/engine/intent.py`

双路径设计：
- **LLM 路径**：将自然语言送入 LLM，提取 `user_type / budget_level / prefer_tags / party_size / duration_hours`
- **规则路径**（LLM 不可用时）：关键词匹配 + 正则提取 → 默认画像

### 4. 前端 UI — `frontend/index.html`

- 左侧 430-560px 侧边栏：场景预设、Agent 控制台、思考链可视化
- 右侧自适应地图：Leaflet.js 渲染 POI 标记和路线
- 三栏布局：经典 Agent Tab ↔ 场景画像 ↔ AI 对话
- 响应式地实时展示 Tool 调用日志和降级状态

---

## 📡 API 端点

### 核心端点

| Method | Path | 说明 |
|--------|------|------|
| `POST` | `/api/agent/plan` | **Agent 完整规划**：意图识别→POI搜索→排队查询→预订→时间轴 |
| `POST` | `/api/agent/execute` | **执行确认**：用户确认后二次预订+发送 |

### 辅助端点

| Method | Path | 说明 |
|--------|------|------|
| `GET` | `/api/health` | 健康检查 |
| `GET` | `/api/pois` | POI 列表查询 |
| `GET` | `/api/profiles` | 快捷场景画像 |
| `POST` | `/api/plan` | 传统推荐模式（规则引擎单路径） |
| `POST` | `/api/ai-config` | 运行时设置 LLM API Key |
| `GET` | `/api/ai-config` | 查看 LLM 配置状态（Key 已掩码） |

### 调用示例

```bash
# Agent 完整规划
curl -X POST http://localhost:8000/api/agent/plan \
  -H "Content-Type: application/json" \
  -d '{
    "goal": "周末下午带老婆去一个能看夕阳的地方，然后吃个浪漫晚餐",
    "execute": true
  }'

# 响应包含:
# - intent: 意图解析结果（user_type, budget_level, prefer_tags 等）
# - plan: 时间轴方案（含每个节点的地点、时间、预订信息）
# - tools_log: 每个 Tool 的调用详情（白盒日志）
# - share_preview: 一键分享的文本
```

---

## ⚙️ 配置指南

### LLM 配置（可选）

不配置 LLM 也能运行，系统自动使用规则引擎。

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑 .env，至少填一个 API Key
ZHIPU_API_KEY=你的智谱API密钥     # 智谱 GLM
DEEPSEEK_API_KEY=你的DeepSeek密钥  # DeepSeek
LOCAL_API_KEY=你的本地模型密钥      # 自定义模型
```

或在启动后通过前端 UI 的「AI 设置」面板输入 Key（不持久化，服务重启需重新设置）。

### 端口修改

```bash
# 方式一：命令行参数
python -m uvicorn backend.main:app --host 0.0.0.0 --port 3000 --reload

# 方式二：.env 中设置（需要在代码中读取，当前默认 8000）
```

### 场景模板定制

编辑 `backend/config.py` 中的 `SCENE_TEMPLATES` 字典，可以修改每个场景的活动数量、时长、标签权重。

---

## 🔧 技术栈

| 层 | 技术选型 | 说明 |
|----|----------|------|
| **后端框架** | FastAPI + Uvicorn | 异步、自动 OpenAPI 文档 |
| **LLM 适配** | 智谱 GLM / DeepSeek | 通过 `llm_client.py` 统一接口，可扩展 |
| **RAG** | jieba + TF-IDF / n-gram | 两套实现，数据量小用轻量版 |
| **前端** | 原生 HTML/CSS/JS | 零构建依赖，单文件部署 |
| **地图** | Leaflet.js | CDN 加载，OpenStreetMap 瓦片 |
| **Python 依赖** | fastapi, uvicorn, httpx, numpy, scikit-learn, jieba | 无重量级框架 |

---

## 🛡️ 安全说明

- **无硬编码 API Key**：所有密钥通过 `.env` 环境变量或前端运行时输入设置
- **`.env` 已加入 `.gitignore`**：不会被提交到 Git 仓库
- **API Key 掩码返回**：`GET /api/ai-config` 返回 `sk-xxxx****abcd` 形式
- **本地开发用**：CORS 开放 `*`，生产部署需限制域名
- **无认证**：`/api/ai-config` 无身份校验，仅适合本地/内网使用

### 提交到 GitHub 前确认

```bash
git status                           # 确认无 .env 或 __pycache__/
git diff --staged                    # 检查暂存区内容
```

---

## 📝 许可与致谢

- POI 数据为郑州地区模拟数据，仅供演示
- 项目基于 FastAPI + Leaflet.js 开源生态构建

---

## 📂 相关文档

- **[PORTFOLIO.md](./PORTFOLIO.md)** — 产品经理视角的项目作品集（简历描述 + 面试故事 + 追问应对）
- **[AGENT_DESIGN.md](./AGENT_DESIGN.md)** — Agent 技术设计文档（Planning 策略 + Tool 链路 + 异常处理）
