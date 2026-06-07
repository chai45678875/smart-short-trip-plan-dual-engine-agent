# 本地场景短时活动规划与执行 Agent — 设计文档

## 1. Planning 策略

### 1.1 整体架构

```
用户自然语言输入
       │
       ▼
┌──────────────────┐
│ 意图识别 (intent) │  ← 复用已有 LLM 解析 + 关键词兜底
└──────┬───────────┘
       │ 用户画像 (亲子/情侣/朋友) + 偏好标签 + 预算
       ▼
┌──────────────────┐
│ POI 检索 (Tool)   │  ← search_pois(Mock API)：预算过滤 + 标签偏好排序
└──────┬───────────┘
       │ 候选 POI 列表 (景点 + 美食)
       ▼
┌──────────────────┐
│ 可行性校验 (Tool) │  ← check_queue(Mock API)：查排队/空位
└──────┬───────────┘
       │ 排队状态 + 可预订时段
       ▼
┌──────────────────┐
│ 时间轴编排        │  ← 场景模板 × 时间计算
└──────┬───────────┘
       │ 按时间顺序的活动节点 + 预订信息
       ▼
┌──────────────────┐
│ 预订执行 (Tool)   │  ← book_table(Mock API)：生成预订号
│ 计划发送 (Tool)   │  ← send_plan(Mock API)：分享给家人/朋友
└──────────────────┘
```

### 1.2 场景模板策略

| 场景 | 模板 | 约束逻辑 |
|------|------|----------|
| 亲子 | 景点(90min) → 休息饮品(30min) → 晚餐(90min) | 排除「刺激/过山车」标签；默认3人 |
| 情侣 | 打卡(60min) → 下午茶(40min) → 晚餐(90min) | 优先「夜景/拍照/浪漫」标签；默认2人 |
| 朋友/游客 | 景点(120min) → 晚餐(90min) | 从输入检测人数(4个/2个等) |

### 1.3 异常处理机制

| 异常类型 | 检测条件 | 处理策略 |
|----------|----------|----------|
| 排队过长 | check_queue 返回 wait_minutes ≥ 60 | 自动预订并推荐备选餐厅 |
| 时间紧张 | 检测输入中仅 2-3h | 精简至 1 景点 + 1 餐 |
| 预算极低 | budget_level=1 | 筛掉人均>50 POI |
| Tool 调用失败 | any Tool 返回 success=false | 记录降级，使用通用推荐 |
| 标签无匹配 | 偏好标签匹配不到 POI | 回退全部 POI 池，按评分排序 |
| 儿童安全 | 亲子场景 | 过滤「过山车」「刺激」「惊险」标签 |

---

## 2. 工具调用链路

### 2.1 完整调用时序

```
POST /api/agent/plan
  │
  ├─ [1] recognize_intent()     ← 意图识别（LLM解析自然语言）
  │     耗时: ~300-800ms (取决于LLM响应)
  │
  ├─ [2] tool_search_pois()     ← 检索POI候选集
  │     参数: query, user_type, budget_level, prefer_tags
  │     返回: 10个景点 + 10个美食 (按标签偏好+评分排序)
  │     耗时: ~50ms (Mock)
  │
  ├─ [3] tool_check_queue()     ← 查询餐厅排队状态
  │     参数: restaurant_id, party_size, preferred_time
  │     返回: 排队长度, 预计等待, 可预订时段
  │     Mock数据: MOCK_RESTAURANT_CAPACITY (10家餐厅容量)
  │     耗时: ~80ms (Mock)
  │
  ├─ [4] tool_book_table()      ← 预订餐厅桌位
  │     参数: restaurant_id, party_size, time
  │     返回: booking_id, confirm_code, status
  │     耗时: ~120ms (Mock)
  │
  └─ [返回] 时间轴方案 + 发送预览文本

POST /api/agent/execute  (用户确认后调用)
  │
  ├─ [5] tool_book_table()      ← 二次确认预订
  ├─ [6] tool_send_plan()       ← 发送计划给收件人
  │     参数: recipient ("老婆"/"小张"), plan_text, channel ("sms")
  │     返回: message_id, sent_at, status
  │     耗时: ~60ms (Mock)
  │
  └─ [返回] 执行结果日志
```

### 2.2 Tool 注册表

| Tool | 描述 | 参数 | Mock 数据源 |
|------|------|------|------------|
| search_pois | POI搜索 | query, user_type, budget_level, prefer_tags, category | ZHENGZHOU_POIS (22条) |
| check_queue | 排队查询 | restaurant_id, restaurant_name, party_size, preferred_time | MOCK_RESTAURANT_CAPACITY (10家) |
| book_table | 预订桌位 | restaurant_id, restaurant_name, party_size, time, special_requests | 随机生成预订号 MT-{id}-{code} |
| send_plan | 发送计划 | recipient, plan_text, channel | 模拟返回 delivered 状态 |

### 2.3 白盒日志

每次 Tool 调用记录以下字段供前端展示：
- `tool_name`: 工具名
- `params`: 传入参数
- `success`: 是否成功
- `duration_ms`: 耗时
- `summary`: 人类可读结果摘要
- 完整 `data`: 返回数据

---

## 3. 异常处理机制

### 3.1 逐层降级策略

```
Layer 1: LLM 不可用
  → 降级到关键词匹配 (intent.py 的 _match_type)
  → 使用默认权重和画像模板

Layer 2: POI 检索无结果
  → 放宽预算和标签限制
  → 返回全部 POI 按评分排序
  → 前端展示"通用推荐"标记

Layer 3: Tool 调用失败
  → 记录错误日志 (success=false)
  → 预订失败 → 降级为"直接前往"建议
  → 发送失败 → 方案仍可用，仅丢失分享功能

Layer 4: 时间轴编排异常
  → 最少保证 1 景点 + 1 餐
  → 忽略无法满足的约束
```

### 3.2 错误隔离

- 每个 Tool 独立 try-catch，单个失败不影响其他 Tool
- 所有异常写入 ToolLogger，通过 API 返回前端白盒展示
- 关键路径 (预订) 失败时，前端标记"部分操作失败"

---

## 4. 与现有老接口的隔离

新增 Agent 相关代码全部在独立路径：
- 后端: `backend/agent/` (planner.py, tools.py, executor.py)
- API: `/api/agent/*` 三个新端点
- 前端: Agent 模式 Tab + 独立面板

**原有接口完全不受影响**: `/api/plan`, `/api/chat`, `/api/chat/with-context`, `/api/rag/*`, `/api/pois` 等全部保持不变。
