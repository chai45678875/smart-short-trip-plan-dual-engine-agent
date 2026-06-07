"""
FastAPI 后端主服务 v3.0

新增：
  - 时段约束：departure_time / return_time
  - 自定义权重滑块：custom_weights
  - 异常检测：anomalies 返回
  - POI 详情查询
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from typing import Optional

from backend.data.poi_data import get_all_pois, filter_pois, get_poi_by_id
from backend.engine.recommender import generate_route
from backend.engine.intent import QUICK_PROFILES
from backend.engine.rag_engine import get_rag
from backend.engine.rag_engine_standard import get_standard_rag
from backend.engine.llm_client import (
    create_llm_client,
    set_llm_runtime_config,
    get_llm_runtime_config,
    LLMClient,
)
from backend.config import LLM_MODELS, PACKAGES, ACTIVE_LLM
from backend.agent.planner import get_planner
from backend.agent.executor import get_executor
from backend.engine.intent import recognize_intent, TimeConstraint

app = FastAPI(
    title="本地场景短时活动规划与执行 Agent",
    description="美团黑客松 - 一句话→完整方案→一键执行：搜索POI、查排队、预订、发送",
    version="3.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================
# 请求/响应模型
# ============================================
class PlanRequest(BaseModel):
    description: str = ""
    quick_profile: Optional[str] = None
    user_type: Optional[str] = None
    transport: Optional[str] = None
    budget: Optional[int] = None
    prefer_tags: Optional[list[str]] = None
    avoid_tags: Optional[list[str]] = None
    district: Optional[str] = None
    max_price: Optional[int] = None
    # v3.0 新增
    departure_time: Optional[str] = None  # "09:00"
    return_time: Optional[str] = None     # "18:00"
    custom_weights: Optional[dict] = None # {"economy":50,"time_efficiency":50,"distance":50}


class ChatRequest(BaseModel):
    messages: list[dict]
    temperature: float = 0.7
    max_tokens: int = 2048


class ChatWithContextRequest(BaseModel):
    """AI 对话模式请求：携带路线上下文"""
    messages: list[dict]
    route_context: Optional[dict] = None  # 路线数据 {plan_name, pois_detail, ...}
    user_profile: Optional[dict] = None   # 用户画像 {user_type, scene, ...}
    temperature: float = 0.7
    max_tokens: int = 2048


class RAGCompareRequest(BaseModel):
    """RAG 消融实验对比请求"""
    query: str
    temperature: float = 0.7
    max_tokens: int = 2048


class AIConfigRequest(BaseModel):
    provider: Optional[str] = None
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    model: Optional[str] = None
    package: Optional[str] = None


class TestConnectionRequest(BaseModel):
    provider: str
    api_key: str
    api_base: Optional[str] = None
    model: Optional[str] = None


class AgentPlanRequest(BaseModel):
    """Agent 规划请求 —— 一句自然语言目标"""
    goal: str                                      # "今天下午想带老婆孩子出去玩几个小时"
    scene_hint: Optional[str] = None               # "family" / "friends"
    party_size: Optional[int] = None               # 人数
    budget_hint: Optional[int] = None              # 预算档位
    departure_time: Optional[str] = "14:00"        # 出发时间


class AgentExecuteRequest(BaseModel):
    """Agent 执行请求 —— 确认方案后一键执行"""
    itinerary: list[dict]                          # 方案时间轴
    plan_text: str = ""                            # 分享文本
    execute_actions: list[str] = []                # 要执行的动作 ["book","send"]
    send_to: str = ""                              # 发送对象（前端根据场景推断）


# ============================================
# API 路由
# ============================================
@app.post("/api/plan")
async def plan_route(req: PlanRequest):
    """核心接口 v3.0：生成出行路线规划（含时段约束、自定义权重、异常提示）"""
    result = await generate_route(
        description=req.description,
        quick_profile=req.quick_profile,
        user_type=req.user_type,
        transport=req.transport,
        budget=req.budget,
        prefer_tags=req.prefer_tags,
        avoid_tags=req.avoid_tags,
        district=req.district,
        max_price=req.max_price,
        plan_count=3,
        use_llm=True,
        departure_time=req.departure_time or "",
        return_time=req.return_time or "",
        custom_weights=req.custom_weights,
    )

    anomalies_data = []
    for a in result.anomalies:
        anomalies_data.append({
            "type": a.type,
            "severity": a.severity,
            "message": a.message,
            "suggestion": a.suggestion,
        })

    return {
        "success": True,
        "intent": {
            "user_type": result.intent.profile.user_type,
            "scene": result.intent.profile.scene,
            "transport": result.intent.profile.transport,
            "budget_level": result.intent.profile.budget_level,
            "speed_prefer": result.intent.profile.speed_prefer,
            "prefer_tags": result.intent.profile.prefer_tags,
            "avoid_tags": result.intent.profile.avoid_tags,
            "reasoning": result.intent.reasoning,
            "parsed_by_llm": result.intent.parsed_by_llm,
            "weights": result.intent.preference_weights,
        },
        "plans": result.plans,
        "raw_poi_count": result.raw_poi_count,
        "anomalies": anomalies_data,
    }


@app.post("/api/chat")
async def chat(req: ChatRequest):
    """AI 自然语言对话"""
    client = create_llm_client()
    if not client.is_available():
        return {
            "success": False,
            "error": "LLM 未配置，请先在 AI 配置中设置 API Key",
            "reply": "我还没有接入 AI 大脑，请帮我配置一下模型和 API Key 吧~",
        }

    reply = await client.chat(req.messages, req.temperature, req.max_tokens)
    return {"success": True, "reply": reply}


@app.post("/api/chat/with-context")
async def chat_with_context(req: ChatWithContextRequest):
    """
    AI 对话模式（带路线上下文）
    将快速模式生成的路线数据注入 system prompt，LLM 可基于此追问优化
    """
    client = create_llm_client()
    if not client.is_available():
        return {
            "success": False,
            "error": "LLM 未配置",
            "reply": "我还没有接入 AI 大脑，请先在 AI 配置中设置 API Key 吧~",
        }

    # 构建增强版 system prompt（注入路线上下文）
    system_prompt = "你是智能出行路线规划系统的 AI 助手，用简洁温暖的中文帮助用户规划出行。\n\n"

    if req.route_context:
        ctx = req.route_context
        system_prompt += f"""当前已经有一条生成好的路线方案：
- 方案名：{ctx.get('plan_name', '未命名')}
- 描述：{ctx.get('description', '')}
- 共 {ctx.get('total_pois', 0)} 个点位
- 预估总花费：¥{ctx.get('total_cost', 0)}

路线详细 POI 列表：
"""
        for i, p in enumerate(ctx.get('pois_detail', []), 1):
            system_prompt += f"  {i}. [{p.get('category','')}] {p.get('name','')} | ⭐{p.get('rating',0)} | ¥{p.get('price',0)} | {p.get('district','')} | 标签:{','.join(p.get('tags',[]))}\n"

        system_prompt += "\n如果用户询问关于这条路线的问题，请基于以上真实数据回答。如果用户要求修改路线，给出你的建议即可，具体路由计算由系统其他模块完成。\n"

    if req.user_profile:
        up = req.user_profile
        system_prompt += f"\n用户画像：{up.get('user_type','')} | 预算Lv{up.get('budget_level',2)} | {up.get('speed_prefer','')}\n"

    # 将 system prompt 作为第一条消息注入
    enriched_messages = [{"role": "system", "content": system_prompt}] + req.messages

    reply = await client.chat(enriched_messages, req.temperature, req.max_tokens)
    return {"success": True, "reply": reply}


@app.post("/api/rag/compare")
async def rag_compare(req: RAGCompareRequest):
    """
    RAG 消融实验对比
    - without_rag: LLM 直接回答（可能出现幻觉，推荐不存在的餐厅）
    - with_rag: LLM + 检索到的真实 POI 上下文
    - retrieved_pois: RAG 检索到的 Top-K 真实 POI 列表
    """
    rag = get_rag()
    search_result = rag.search(req.query, top_k=5)
    retrieved = search_result["results"]
    degraded = search_result["degraded"]
    search_log = search_result["search_log"]
    context = rag.format_context(req.query, top_k=5)

    # 构造逐步检索日志（白盒展示）
    _step2 = f"字符 bigram 分词 → {search_log['token_count']} 个 token"
    if search_log['tokens']:
        _step2 += f"（截断显示：{' | '.join(search_log['tokens'][:10])}）"
    search_details = [
        {"step": "1. 查询输入", "content": f'用户查询：「{req.query}」'},
        {"step": "2. 分词处理", "content": _step2},
        {"step": "3. 向量化", "content": f"词表维度: {len(rag.vocab)}, 转为归一化向量"},
        {"step": "4. 相似度计算", "content": f"余弦相似度 × {len(rag.pois)} 条 POI → Top-{len(retrieved)}"},
    ]
    for i, r in enumerate(retrieved, 1):
        p = r["poi"]
        score_pct = r["score"] * 100
        score_bar = "█" * max(1, int(score_pct / 5))
        search_details.append({
            "step": f"4.{i} 匹配 #{i}",
            "content": f"{p['name']}（{p['category']}）→ 相似度 {score_pct:.0f}% {score_bar}",
        })
    if degraded:
        search_details.append({
            "step": "⚠️ 降级警告",
            "content": f"最高相似度 {search_result['max_score']*100:.0f}% < 阈值 {search_result['search_log']['threshold']*100:.0f}%，触发降级：展示地图通用推荐",
        })

    client = create_llm_client()

    prompt_prefix = "你是郑州旅游推荐助手。"
    no_rag_answer = ""
    rag_answer = ""

    if client.is_available():
        # 无 RAG: LLM 裸奔
        no_rag_prompt = prompt_prefix + f"\n\n用户问题：{req.query}\n\n请用简洁中文回答，列出3-5个推荐。"
        no_rag_answer = await client.chat(
            [{"role": "user", "content": no_rag_prompt}],
            req.temperature, req.max_tokens
        )

        # 有 RAG: 注入真实 POI 数据
        rag_prompt = prompt_prefix + (
            f"\n\n用户问题：{req.query}\n\n"
            f"以下是郑州真实存在的 POI 数据，请严格基于以下数据推荐，"
            f"不要推荐数据中没有的地点：\n\n{context}\n\n"
            f"请用简洁中文回答，列出3-5个推荐。如果数据中没有合适的，请如实说明。"
        )
        rag_answer = await client.chat(
            [{"role": "user", "content": rag_prompt}],
            req.temperature, req.max_tokens
        )
    else:
        # LLM 不可用时的模拟对比
        no_rag_answer = (
            "（⚠ LLM 未配置，这是模拟输出）\n\n"
            "推荐以下餐厅：\n"
            "1. 阿强烩面馆 - 老牌郑州烩面\n"
            "2. 辣天下火锅城 - 鸳鸯锅搭配\n"
            "3. 如意音乐餐吧 - 环境雅致适合约会\n"
            "\n这些推荐来自模型训练数据，可能不准确或不存在，仅供参考。"
        )
        rag_answer = f"（✅ 基于真实 POI 数据的推荐）\n\n{context}"

    return {
        "success": True,
        "without_rag": no_rag_answer,
        "with_rag": rag_answer,
        "retrieved_pois": retrieved,
        "poi_count": len(retrieved),
        "degraded": degraded,
        "max_score": search_result["max_score"],
        "search_log": search_log,
        "search_details": search_details,
    }


@app.post("/api/rag/compare-v2")
async def rag_compare_v2(req: RAGCompareRequest):
    """
    RAG 消融实验对比（标准版 TF-IDF + jieba 分词）
    - jieba 中文分词 → TF-IDF 向量 → 余弦相似度检索
    - 相比轻量版（字符 n-gram），分词更准确、统计权重更科学
    - without_rag: LLM 直接回答
    - with_rag: LLM + TF-IDF 检索到的真实 POI 上下文
    """
    rag = get_standard_rag()
    search_result = rag.search(req.query, top_k=5)
    retrieved = search_result["results"]
    degraded = search_result["degraded"]
    search_log = search_result["search_log"]
    context = rag.format_context(req.query, top_k=5)

    # 构造逐步检索日志（白盒展示）
    search_details = [
        {"step": "1. 查询输入", "content": f'用户查询：「{req.query}」'},
        {"step": "2. 中文分词", "content": f"jieba 分词 → {search_log['token_count']} 个词"
            + (f"：[{' | '.join(search_log['tokens'][:15])}]" if search_log['tokens'] else "")},
        {"step": "3. TF-IDF 向量化", "content": "sklearn TfidfVectorizer (max_features=200, ngram 1~2) → 归一化向量"},
        {"step": "4. 相似度计算", "content": f"余弦相似度 × {len(rag.pois)} 条 POI → Top-{len(retrieved)}"},
    ]
    for i, r in enumerate(retrieved, 1):
        p = r["poi"]
        score_pct = r["score"] * 100
        score_bar = "█" * max(1, int(score_pct / 5))
        search_details.append({
            "step": f"4.{i} 匹配 #{i}",
            "content": f"{p['name']}（{p['category']}）→ 相似度 {score_pct:.0f}% {score_bar}",
        })
    if degraded:
        search_details.append({
            "step": "⚠️ 降级警告",
            "content": f"最高相似度 {search_result['max_score']*100:.0f}% < 阈值 {rag.SIM_THRESHOLD*100:.0f}%，触发降级：展示地图通用推荐",
        })

    client = create_llm_client()
    prompt_prefix = "你是郑州旅游推荐助手。"

    no_rag_answer = ""
    rag_answer = ""

    if client.is_available():
        no_rag_prompt = prompt_prefix + f"\n\n用户问题：{req.query}\n\n请用简洁中文回答，列出3-5个推荐。"
        no_rag_answer = await client.chat(
            [{"role": "user", "content": no_rag_prompt}],
            req.temperature, req.max_tokens
        )

        rag_prompt = prompt_prefix + (
            f"\n\n用户问题：{req.query}\n\n"
            f"以下是郑州真实 POI 的 TF-IDF 检索结果（jieba 分词 + 统计加权），"
            f"请严格基于以下数据推荐，不要推荐数据中没有的地点：\n\n{context}\n\n"
            f"请用简洁中文回答，列出3-5个推荐。"
        )
        rag_answer = await client.chat(
            [{"role": "user", "content": rag_prompt}],
            req.temperature, req.max_tokens
        )
    else:
        no_rag_answer = (
            "（⚠ LLM 未配置，模拟输出）\n\n"
            "推荐：阿强烩面馆、辣天下火锅城、如意音乐餐吧\n"
            "这些来自模型训练数据，可能不存在，仅供参考。"
        )
        rag_answer = f"（✅ 标准版 TF-IDF 检索结果）\n\n{context}"

    return {
        "success": True,
        "without_rag": no_rag_answer,
        "with_rag": rag_answer,
        "retrieved_pois": retrieved,
        "poi_count": len(retrieved),
        "degraded": degraded,
        "max_score": search_result["max_score"],
        "search_log": search_log,
        "search_details": search_details,
        "embedding_method": "jieba 分词 + sklearn TF-IDF + cosine similarity",
        "vector_dim": 200,
    }


@app.get("/api/pois")
async def list_pois(
    category: Optional[str] = None,
    district: Optional[str] = None,
    max_price: Optional[int] = None,
    min_rating: float = 0.0,
):
    pois = filter_pois(category=category, district=district, max_price=max_price, min_rating=min_rating)
    return {"success": True, "count": len(pois), "pois": [p.to_dict() for p in pois]}


@app.get("/api/pois/{poi_id}")
async def get_poi_detail(poi_id: str):
    """POI 详情查询"""
    poi = get_poi_by_id(poi_id)
    if poi:
        return {"success": True, "poi": poi.to_dict()}
    return {"success": False, "error": "未找到该POI"}


@app.get("/api/profiles")
async def list_profiles():
    profiles = {}
    for key, p in QUICK_PROFILES.items():
        profiles[key] = {
            "user_type": p.user_type,
            "scene": p.scene,
            "transport": p.transport,
            "budget_level": p.budget_level,
            "speed_prefer": p.speed_prefer,
            "prefer_tags": p.prefer_tags,
        }
    return {"success": True, "profiles": profiles}


@app.get("/api/models")
async def list_models():
    return {"success": True, "models": LLM_MODELS}


@app.get("/api/packages")
async def list_packages():
    return {"success": True, "packages": PACKAGES}


@app.get("/api/ai-config")
async def get_ai_config():
    cfg = get_llm_runtime_config()
    if not cfg.get("provider"):
        cfg["provider"] = ACTIVE_LLM
    if not cfg.get("model"):
        cfg["model"] = ACTIVE_LLM
    key = cfg.get("api_key", "")
    masked = key[:6] + "****" + key[-4:] if len(key) > 10 else ("****" if key else "")
    return {
        "success": True,
        "config": {
            "provider": cfg.get("provider"),
            "model": cfg.get("model"),
            "api_base": cfg.get("api_base"),
            "api_key_masked": masked,
        },
    }


@app.post("/api/ai-config")
async def save_ai_config(req: AIConfigRequest):
    set_llm_runtime_config(
        provider=req.provider,
        api_key=req.api_key,
        api_base=req.api_base,
        model=req.model,
    )
    return {"success": True, "message": "配置已保存"}


@app.post("/api/ai-config/test")
async def test_ai_config(req: TestConnectionRequest):
    client = LLMClient(
        provider=req.provider,
        api_key=req.api_key,
        api_base=req.api_base,
        model=req.model,
    )
    result = await client.test_connection()
    return {"success": result.get("ok", False), **result}


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "service": "智能出行路线规划系统", "version": "4.0.0"}


# ============================================
# Agent API（v4.0 新增 —— 本地场景短时活动规划与执行）
# ============================================
@app.post("/api/agent/plan")
async def agent_plan(req: AgentPlanRequest):
    """
    Agent 规划接口
    
    接收一句自然语言目标，输出：
    1. 时间轴可执行方案
    2. Tool 调用白盒日志
    3. 可分享的自然语言计划

    Planning 策略：意图识别 → POI检索 → 查位 → 时间轴编排 → 预订
    工具调用链路：search_pois → check_queue → book_table
    """
    planner = get_planner()

    # Step 1: 意图识别（复用现有 intent.py）
    time_constraint = None
    if req.departure_time:
        time_constraint = TimeConstraint(
            departure=req.departure_time,
            return_time=f"{int(req.departure_time[:2])+5:02d}:00"  # 默认5小时
        )

    intent = await recognize_intent(
        user_input=req.goal,
        user_type_hint="亲子" if req.scene_hint == "family" else ("游客" if req.scene_hint == "friends" else None),
        transport_hint="自驾" if req.scene_hint == "family" else "公交",
        budget_hint=req.budget_hint,
        use_llm=True,
        time_constraint=time_constraint,
    )

    # Step 2: Agent 规划（LLM ReAct 异步推理）
    plan = await planner.plan(user_input=req.goal, intent=intent)

    # Step 3: 构造响应
    itinerary_data = plan.itinerary

    return {
        "success": True,
        "intent": {
            "user_type": intent.profile.user_type,
            "scene": intent.profile.scene,
            "transport": intent.profile.transport,
            "budget_level": intent.profile.budget_level,
            "prefer_tags": intent.profile.prefer_tags,
            "reasoning": intent.reasoning,
        },
        "plan": {
            "itinerary": itinerary_data,
            "total_cost_estimate": plan.total_cost_estimate,
            "total_duration": plan.total_duration,
            "bookings": plan.bookings,
            "plan_text_for_sharing": plan.plan_text_for_sharing,
        },
        "debug": {
            "reasoning": plan.reasoning,
            "tool_logs": plan.tool_logs,
            "tool_calls_count": len(plan.tool_logs),
        },
    }


@app.post("/api/agent/plan-stream")
async def agent_plan_stream(req: AgentPlanRequest):
    """
    Agent 规划 SSE 流式接口 v6.0
    
    实时推送思考链事件：
    - phase: analyzing | planning | plan_done | executing | generating | degraded
    - tool_call: executing | done | failed
    - final: 完整方案
    
    前端可用 EventSource 或 fetch + ReadableStream 读取
    """
    planner = get_planner()

    # Step 1: 意图识别
    time_constraint = None
    if req.departure_time:
        time_constraint = TimeConstraint(
            departure=req.departure_time,
            return_time=f"{int(req.departure_time[:2])+5:02d}:00"
        )

    intent = await recognize_intent(
        user_input=req.goal,
        user_type_hint="亲子" if req.scene_hint == "family" else ("游客" if req.scene_hint == "friends" else None),
        transport_hint="自驾" if req.scene_hint == "family" else "公交",
        budget_hint=req.budget_hint,
        use_llm=True,
        time_constraint=time_constraint,
    )

    async def event_generator():
        """SSE 事件生成器"""
        try:
            async for event_str in planner.plan_stream(user_input=req.goal, intent=intent):
                yield event_str
        except Exception as e:
            import json
            yield f"event: error\ndata: {json.dumps({'message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/agent/execute")
async def agent_execute(req: AgentExecuteRequest):
    """
    Agent 执行接口
    
    确认方案后一键执行：
    - 预订餐厅（book_table）
    - 发送计划给家人/朋友（send_plan）
    
    异常处理：
    - 预订失败 → 返回错误信息，前端提示降级
    - 发送失败 → 记录失败但方案仍可用
    """
    executor = get_executor()

    # 构建临时 plan 对象供 executor 使用
    class SimplePlan:
        def __init__(self, itinerary, plan_text, intent=None):
            self.itinerary = itinerary
            self.plan_text_for_sharing = plan_text
            self.intent = intent or SimpleIntent()

    class SimpleIntent:
        def __init__(self, user_type='游客'):
            self.profile = type('obj', (object,), {'user_type': user_type})

    # 从请求或itinerary推断场景类型
    user_type = '游客'
    if req.send_to == '老婆':
        user_type = '亲子'
    elif req.send_to == '女朋友':
        user_type = '情侣'
    elif req.send_to == '小张':
        user_type = '朋友'

    plan = SimplePlan(req.itinerary, req.plan_text, SimpleIntent(user_type))

    # 执行
    actions = req.execute_actions or ["book", "send"]
    result = executor.execute(plan, send_to=req.send_to or None)

    # 过滤只执行用户要求的动作
    filtered_executions = []
    for ex in result["executions"]:
        if ex["type"] == "book_table" and "book" not in actions:
            continue
        if ex["type"] == "send_plan" and "send" not in actions:
            continue
        filtered_executions.append(ex)

    return {
        "success": True,
        "all_success": result["all_success"],
        "executions": filtered_executions,
        "sent_result": result.get("sent_result"),
        "tool_logs_exec": result.get("tool_logs_exec", []),
        "summary": "全部预订和发送已完成" if result["all_success"] else "部分操作失败，请查看详情",
    }


@app.get("/api/agent/tools")
async def list_agent_tools():
    """列出 Agent 可用的所有工具"""
    from backend.agent.tools import TOOL_REGISTRY
    tools_info = {}
    for name, tool in TOOL_REGISTRY.items():
        tools_info[name] = {
            "description": tool["description"],
            "params": tool["params"],
        }
    return {"success": True, "tools": tools_info}


# ============================================
# 静态文件服务
# ============================================
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")

if os.path.exists(frontend_dir):
    @app.get("/")
    async def serve_frontend():
        return FileResponse(os.path.join(frontend_dir, "index.html"))


if __name__ == "__main__":
    import uvicorn
    from backend.config import SERVER_HOST, SERVER_PORT

    print("=" * 50)
    print("🚀 智能出行路线规划系统 v3.0")
    print(f"   API 文档: http://localhost:{SERVER_PORT}/docs")
    print(f"   前端页面: http://localhost:{SERVER_PORT}")
    print("=" * 50)
    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT, log_level="info")
