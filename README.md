# 🛋 你的短时生活搭子

### Plan-then-Execute 双引擎本地短时活动规划 Agent

> 输入一句"今天下午带孩子出去玩，别太远"，  
> 几分钟内自动完成 **POI 搜索 → 排队查询 → 餐厅预订 → 时间轴方案 → 一键分享**。  
> 无论是否接入 LLM，都能稳定输出可用方案 — 这得益于 **Plan-then-Execute 策略 + 规则模板兜底** 的双引擎设计。

---

## 📖 目录

- [这是什么](#-这是什么)
- [为什么要做这个](#-为什么要做这个)
- [它是怎么工作的](#-它是怎么工作的)
- [核心亮点](#-核心亮点)
- [快速启动](#-快速启动)
- [项目结构](#-项目结构)
- [核心模块详解](#-核心模块详解)
- [API 端点](#-api-端点)
- [配置指南](#-配置指南)
- [技术栈](#-技术栈)
- [安全说明](#-安全说明)

---

## 🎯 这是什么

一个**本地短时活动规划 Agent**。周末下午、下班傍晚、临时起意 — 你只需要用自然语言说一句话，Agent 自动帮你搞定剩下的事：

| 你说的 | Agent 做的 |
|--------|-----------|
| "带老婆去一个有夜景的地方吃顿好的" | 识别情侣场景 → 筛选夜景拍照 POI → 查位预订 → 生成 17:00 出发的时间轴 |
| "孩子考完试了想带他放松" | 触发亲子模式 → 过滤刺激项目 → 安排景点+休息+晚餐三段式 |
| "下班了想一个人静静，然后吃个饭" | 独行模式 → 推荐安静咖啡厅/书店 → 匹配评分最高的一人食餐厅 |
| "周末和四五个朋友聚一下" | 识别人数=5 → 按评分推荐热门景点 → 预订大桌 → 发送到群 |

**适用场景**：2-6 小时的短时出行，本地城市范围内，需要快速决策和预订。

---

## ❓ 为什么要做这个

周末想出趟门，你会经历什么？

> 打开大众点评 → 翻几十条评论 → 切换高德看距离 → 纠结要不要排队 → 回到点评看其他餐厅 → 再次切换高德……  
> **决策成本极高，信息分布在多个 App 里，没有一条线串起来。**

这个 Agent 的解决思路是：**把所有决策链路收拢到一次对话里**，用 LLM 做语义理解和方案编排，用确定性工具做数据查询和执行，最后输出一个可以直接照着走的时间表。

---

## 🧠 它是怎么工作的

### 整体流程

```
用户自然语言输入
       │
       ▼
┌──────────────────────────────────────────────────┐
│  阶段一 · Plan（规划）                            │
│  意图识别 → POI 搜索 → 场景模板匹配               │
│  耗时: ~500ms（LLM） 或 ~20ms（规则引擎）          │
└──────────────────────┬───────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────┐
│  阶段二 · Execute（执行）                         │
│  排队查询 → 餐厅预订 → 方案发送（并行 Tool 调用）  │
│  耗时: ~150ms（Mock API）                         │
└──────────────────────┬───────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────┐
│  阶段三 · Generate（生成）                        │
│  时间轴编排 → Markdown 方案 → 地图路线渲染        │
│  耗时: ~300ms（LLM） 或 ~5ms（模板填充）           │
└──────────────────────────────────────────────────┘
```

### 为什么是 Plan-then-Execute 而不是 ReAct？

| 策略 | 特点 | 问题 |
|------|------|------|
| ReAct（Think→Act→Observe→循环） | 灵活，支持多轮纠错 | LLM 调用次数不可控，串行慢，成本高 |
| **Plan-then-Execute（本方案）** | 先全局规划再批量执行 | 调用次数固定为 2-3 轮，确定性高，成本低 |

短时活动规划的场景**高度结构化**（搜 POI → 查排队 → 预订 → 排时间），知识需求封闭，不需要开放域推理，所以 Plan-then-Execute 更合适。

### 三级降级保障

当 LLM 不可用或 Tool 调用失败时，系统会自动降级：

| 层级 | 触发条件 | 降级为 | 用户体验 |
|------|----------|--------|----------|
| **L1** | LLM 正常 | 语义理解 + 智能生成 | 完全个性化方案 |
| **L2** | LLM 不可用 / 超时 | 规则引擎（关键词匹配 + 场景模板） | 按预设模板生成，标签"通用推荐" |
| **L3** | Tool 调用失败 | Observation 最小方案 | 至少 1 景点 + 1 餐，标注"部分操作为估算" |

**任何情况下，用户都能拿到一个可用的出行方案。**

---

## ✨ 核心亮点

### 4 个 Mock Tool，可替换真实 API

代码中 4 个 Tool 均以 Mock 实现，接口设计与真实 API 对齐，替换时只需修改 Tool 内部实现：

| Tool | 功能 | 模拟数据 | 替换目标 |
|------|------|----------|----------|
| `search_pois` | POI 搜索与排序 | 郑州 22 个 POI | 大众点评/美团搜索 API |
| `check_queue` | 排队查询 | 10 家餐厅容量 | 美团排队 API |
| `book_table` | 预订确认 | 生成 MT-{id}-{code} | 美团预订 API |
| `send_plan` | 方案分享 | 模拟 SMS 送达 | 微信分享/短信接口 |

### 场景化一键预设

前端内置 4 种场景快捷入口，一键填充参数：

- 👨‍👩‍👧 **亲子**：过滤刺激项目，三段式节奏（玩→歇→吃）
- 💑 **情侣**：优先夜景/拍照/浪漫标签
- 👫 **朋友**：热门+高评分，自动识别人数
- 🧘 **独行**：安静/小众，灵活时间

### 白盒可视化

每一步 Agent 操作都实时展示在前端：
- 调用了哪个 Tool、传了什么参数、耗时多少
- 每个 Tool 的返回结果摘要
- 异常时标记降级路径

### 零构建前端

单文件 `index.html`，无 npm/webpack/Vite 依赖，开箱即用。地图基于 Leaflet.js CDN 加载，数据通过 Fetch API 与后端交互。

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
│   ├── agent/                      # 🔥 Agent 核心（Plan-then-Execute）
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
├── start.bat                       # Windows 一键启动
├── requirements.txt                # 根目录依赖（指向 backend）
├── .env.example                    # 环境变量模板
├── .gitignore
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

- ✅ **无硬编码 API Key**：所有密钥通过 `.env` 环境变量或前端运行时输入设置
- ✅ **`.env` 已加入 `.gitignore`**：不会被提交到 Git 仓库
- ✅ **API Key 掩码返回**：`GET /api/ai-config` 返回 `sk-xxxx****abcd` 形式
- ⚠️ **本地开发用**：CORS 开放 `*`，生产部署需限制域名
- ⚠️ **无认证**：`/api/ai-config` 无身份校验，仅适合本地/内网使用

### 提交到 GitHub 前确认

```bash
git status                           # 确认无 .env 或 __pycache__/
git diff --staged                    # 检查暂存区内容
```

---

## 📝 许可与致谢

- POI 数据为郑州地区模拟数据，仅供演示
- 项目基于 FastAPI + Leaflet.js 开源生态构建
