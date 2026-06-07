"""
Agent 景点餐饮推荐模块（对外接口）v3.0

数据流：用户输入需求 → AI框架拉取后端全量数据 → Agent+LLM生成路线+推荐内容 → 返回前端
新增：时段约束、自定义权重、异常提示
"""

from dataclasses import dataclass
from typing import Optional
from backend.data.poi_data import get_all_pois, filter_pois, POI
from backend.engine.intent import recognize_intent, get_quick_profile, IntentResult, UserProfile, TimeConstraint, AnomalyWarning
from backend.engine.agent import RuleEngine, LLMRoutePlanner


@dataclass
class RoutePlan:
    intent: IntentResult
    plans: list[dict]
    raw_poi_count: int
    anomalies: list[AnomalyWarning]


async def generate_route(
    description: str = "",
    quick_profile: Optional[str] = None,
    user_type: Optional[str] = None,
    transport: Optional[str] = None,
    budget: Optional[int] = None,
    prefer_tags: Optional[list[str]] = None,
    avoid_tags: Optional[list[str]] = None,
    district: Optional[str] = None,
    max_price: Optional[int] = None,
    min_rating: float = 0.0,
    plan_count: int = 3,
    use_llm: bool = True,
    departure_time: str = "",
    return_time: str = "",
    custom_weights: Optional[dict] = None,
) -> RoutePlan:
    """
    Agent 推荐主流程 v3.0（异步）
    1. 意图识别（LLM优先解析自然语言 → 异常检测）
    2. POI 筛选 → 候选集
    3. 路线生成 → 多套科学方案（含时段约束）
    4. LLM 增强文案（可选）
    """
    # 时段约束
    tc = TimeConstraint(departure_time, return_time) if (departure_time and return_time) else None

    # Step 1: 意图识别（description 是主入口）
    if quick_profile:
        profile = get_quick_profile(quick_profile)
        if profile is None:
            intent = await recognize_intent(
                description, user_type, transport, budget, prefer_tags, avoid_tags,
                time_constraint=tc, custom_weights=custom_weights, use_llm=use_llm
            )
        else:
            if user_type: profile.user_type = user_type
            if transport: profile.transport = transport
            if budget: profile.budget_level = budget
            if prefer_tags: profile.prefer_tags = prefer_tags
            if avoid_tags: profile.avoid_tags = avoid_tags
            if description: profile.natural_description = description
            from backend.engine.intent import _compute_weights, _generate_reasoning, _build_custom_weights, _detect_anomalies
            if custom_weights:
                w = _build_custom_weights(profile, custom_weights)
            else:
                w = _compute_weights(profile)
            anomalies = _detect_anomalies(profile, tc, description)
            intent = IntentResult(profile=profile, preference_weights=w,
                                   reasoning=_generate_reasoning(profile, w), parsed_by_llm=False,
                                   anomalies=anomalies)
    else:
        intent = await recognize_intent(
            description, user_type, transport, budget, prefer_tags, avoid_tags,
            time_constraint=tc, custom_weights=custom_weights, use_llm=use_llm
        )

    p = intent.profile

    # Step 2: POI 筛选（排除远距离区域，适配短时规划）
    candidate_pois = filter_pois(
        district=district,
        max_price=max_price or _budget_to_price(p.budget_level),
        min_rating=min_rating,
        exclude_remote=True,
    )
    if p.avoid_tags:
        candidate_pois = [poi for poi in candidate_pois if not any(t in poi.tags for t in p.avoid_tags)]

    # Step 3: 路线生成（含时段约束）
    plans = RuleEngine.generate_plan(
        pois=candidate_pois,
        profile=p,
        weights=intent.preference_weights,
        count=plan_count,
        time_constraint=tc,
    )

    # Step 4: LLM 增强文案
    for plan in plans:
        enhanced = await LLMRoutePlanner.enhance_plan_summary(plan, p, intent.reasoning)
        if enhanced and not enhanced.startswith("["):
            plan["ai_summary"] = enhanced

    return RoutePlan(intent=intent, plans=plans, raw_poi_count=len(candidate_pois), anomalies=intent.anomalies)


def _budget_to_price(budget_level: int) -> Optional[int]:
    if budget_level == 1:
        return 50
    elif budget_level == 2:
        return 150
    return None
