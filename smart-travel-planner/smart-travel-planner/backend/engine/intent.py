"""
意图识别 & 个性化引擎 v3.0

核心能力：
1. 自然语言为主入口（LLM深度解析出行描述）
2. 异常兜底：极低预算/跨城 → AI主动提示调整
3. 描述异常时回退关键词+标签匹配
4. 用户自定义权重（滑块）优先于画像默认权重
"""

from dataclasses import dataclass, field
from typing import Optional
import json
import re


@dataclass
class UserProfile:
    user_type: str        # 游客 / 学生 / 情侣 / 亲子 / 独行
    scene: str            # 远行出游 / 闲暇短途
    transport: str        # 自驾 / 公交 / 步行
    budget_level: int     # 1=经济, 2=中等, 3=自由
    speed_prefer: str     # 紧凑高效 / 悠闲舒适
    prefer_tags: list[str] = field(default_factory=list)
    avoid_tags: list[str] = field(default_factory=list)
    natural_description: str = ""


@dataclass
class AnomalyWarning:
    """异常检测结果"""
    type: str             # "low_budget" | "cross_city" | "time_tight"
    severity: str         # "info" | "warn" | "error"
    message: str          # 面向用户的提示
    suggestion: str       # 修改建议


@dataclass
class IntentResult:
    profile: UserProfile
    preference_weights: dict
    reasoning: str
    parsed_by_llm: bool = False
    anomalies: list[AnomalyWarning] = field(default_factory=list)


@dataclass
class TimeConstraint:
    """时段约束"""
    departure: str = ""   # "09:00"
    return_time: str = "" # "18:00"
    def valid(self) -> bool:
        return bool(self.departure) and bool(self.return_time)
    def total_minutes(self) -> int:
        try:
            dh, dm = map(int, self.departure.split(":"))
            rh, rm = map(int, self.return_time.split(":"))
            dep_min = dh * 60 + dm
            ret_min = rh * 60 + rm
            if ret_min <= dep_min:
                ret_min += 24 * 60  # 跨天
            return ret_min - dep_min
        except:
            return 480  # 默认8小时


# ============================================
# 关键词词典（兜底 + 异常检测参考）
# ============================================
USER_TYPE_PATTERNS = {
    "游客": {
        "keywords": ["外地", "第一次", "打卡", "必去", "经典", "代表性", "标志", "攻略", "知名"],
        "prefer_tags": ["热门", "地标", "经典"],
        "speed": "紧凑高效",
    },
    "学生": {
        "keywords": ["便宜", "性价比", "AA", "省钱", "实惠", "学生", "穷游", "免费"],
        "prefer_tags": ["实惠", "性价比", "免费"],
        "speed": "悠闲舒适",
    },
    "情侣": {
        "keywords": ["情侣", "约会", "浪漫", "拍照", "好看", "氛围", "安静", "夜景", "纪念日", "对象", "两人", "二人", "另一半", "男朋友", "女朋友", "纪念日"],
        "prefer_tags": ["夜景", "拍照", "浪漫"],
        "speed": "悠闲舒适",
    },
    "亲子": {
        "keywords": ["孩子", "带娃", "小朋友", "儿童", "全家", "老人", "一家"],
        "prefer_tags": ["亲子", "休闲", "安全"],
        "speed": "悠闲舒适",
    },
    "独行": {
        "keywords": ["一个人", "独自", "solo", "独处", "背包客"],
        "prefer_tags": ["安静", "自由", "小众"],
        "speed": "紧凑高效",
    },
}

SCENE_PATTERNS = {
    "远行出游": ["远行", "旅游", "出行", "游玩", "外地", "好几天", "周末游", "假期", "来玩", "攻略"],
    "闲暇短途": ["闲逛", "转转", "附近", "周边", "半天", "一日游", "随便", "散步", "溜达", "周末", "下班"],
}

TRANSPORT_PATTERNS = {
    "自驾":   ["开车", "自驾", "租车", "有车", "驾车"],
    "公交":   ["公交", "地铁", "公共交通", "绿色出行", "坐车"],
    "步行":   ["走路", "步行", "散步", "溜达", "徒步"],
}


# ============================================
# 核心方法
# ============================================
async def recognize_intent(
    user_input: str = "",
    user_type_hint: Optional[str] = None,
    transport_hint: Optional[str] = None,
    budget_hint: Optional[int] = None,
    prefer_tags: Optional[list[str]] = None,
    avoid_tags: Optional[list[str]] = None,
    time_constraint: Optional[TimeConstraint] = None,
    custom_weights: Optional[dict] = None,  # 用户滑块自定义权重
    use_llm: bool = True,
) -> IntentResult:
    """
    意图识别主入口 v3.0
    1. LLM优先解析自然语言（description 是主入口）
    2. 异常检测：极低预算 / 跨城 / 时间紧张
    3. 异常或LLM不可用时 → 回退关键词+标签
    4. 自定义权重优先于画像默认权重
    """
    input_lower = user_input.lower() if user_input else ""
    anomalies: list[AnomalyWarning] = []

    # 尝试 LLM 解析（自然语言为主入口）
    if use_llm and user_input.strip():
        llm_result = await _parse_with_llm(user_input)
        if llm_result:
            profile = llm_result.profile
            # 合并显式 hint（用户手动选择的优先级更高）
            if user_type_hint: profile.user_type = user_type_hint
            if transport_hint: profile.transport = transport_hint
            if budget_hint: profile.budget_level = budget_hint
            if prefer_tags: profile.prefer_tags = prefer_tags
            if avoid_tags: profile.avoid_tags = avoid_tags

            # 异常检测
            anomalies = _detect_anomalies(profile, time_constraint, input_lower)

            # 权重：自定义 > 画像默认
            if custom_weights:
                weights = _build_custom_weights(profile, custom_weights)
            else:
                weights = _compute_weights(profile)
            reasoning = _generate_reasoning(profile, weights, parsed_by_llm=True)

            return IntentResult(
                profile=profile,
                preference_weights=weights,
                reasoning=reasoning,
                parsed_by_llm=True,
                anomalies=anomalies,
            )

    # 回退：关键词匹配 + 标签
    user_type = user_type_hint or _match_type(input_lower, USER_TYPE_PATTERNS)
    scene = _match_type(input_lower, SCENE_PATTERNS)
    transport = transport_hint or _match_type(input_lower, TRANSPORT_PATTERNS)
    budget = budget_hint or _infer_budget(input_lower)
    speed = USER_TYPE_PATTERNS.get(user_type, {}).get("speed", "悠闲舒适")
    base_tags = USER_TYPE_PATTERNS.get(user_type, {}).get("prefer_tags", [])
    if prefer_tags:
        base_tags = prefer_tags

    profile = UserProfile(
        user_type=user_type,
        scene=scene,
        transport=transport,
        budget_level=budget,
        speed_prefer=speed,
        prefer_tags=base_tags,
        avoid_tags=avoid_tags or [],
        natural_description=user_input,
    )

    anomalies = _detect_anomalies(profile, time_constraint, input_lower)

    if custom_weights:
        weights = _build_custom_weights(profile, custom_weights)
    else:
        weights = _compute_weights(profile)
    reasoning = _generate_reasoning(profile, weights, parsed_by_llm=False)
    return IntentResult(profile=profile, preference_weights=weights, reasoning=reasoning, parsed_by_llm=False, anomalies=anomalies)


# ============================================
# 异常检测
# ============================================
def _detect_anomalies(profile: UserProfile, time_constraint: Optional[TimeConstraint], input_text: str) -> list[AnomalyWarning]:
    anomalies = []

    # 1. 极低预算检测：预算Lv1 且 文本中有跨区域/远郊意图
    budget_keywords = ["便宜", "省钱", "穷", "免费", "10块", "20块", "30块", "不花钱", "最低"]
    if profile.budget_level == 1 and any(w in input_text for w in budget_keywords):
        anomalies.append(AnomalyWarning(
            type="low_budget",
            severity="warn",
            message="检测到您的预算非常有限",
            suggestion="已为您优先推荐免费景点和经济实惠的餐饮，如需要更多选择可以适当放宽预算。"
        ))

    # 2. 跨城检测：登封市（少林寺/嵩山）距市区约80公里
    cross_city_keywords = ["少林寺", "嵩山", "登封", "中岳"]
    if any(w in input_text for w in cross_city_keywords):
        time_ok = True
        if time_constraint and time_constraint.valid():
            time_ok = time_constraint.total_minutes() >= 480  # 至少8小时
        anomalies.append(AnomalyWarning(
            type="cross_city",
            severity="warn",
            message="少林寺/嵩山位于登封市，距郑州市区约80公里，单程约1.5小时",
            suggestion="建议预留至少6-8小时游玩时间。如需当天往返，请确保出发时间不过晚。" + 
                      ("" if time_ok else " 当前时间可能不够往返登封，建议调整出发/返程时间。")
        ))

    # 3. 时间紧张检测
    if time_constraint and time_constraint.valid():
        total_min = time_constraint.total_minutes()
        if total_min < 240:
            anomalies.append(AnomalyWarning(
                type="time_tight",
                severity="warn",
                message=f"您的可用时间仅{total_min//60}小时{total_min%60}分钟，较为紧张",
                suggestion="建议精简行程至2-3个核心景点，优先就近安排餐饮。"
            ))
        elif total_min < 360:
            anomalies.append(AnomalyWarning(
                type="time_tight",
                severity="info",
                message=f"可用时间约{total_min//60}小时，时间适中",
                suggestion="可安排3-4个景点+2餐，建议集中在同一区域。"
            ))

    return anomalies


# ============================================
# LLM 解析
# ============================================
async def _parse_with_llm(user_input: str) -> Optional[IntentResult]:
    """使用 LLM 深度解析自然语言描述 —— 这是主入口"""
    try:
        from backend.engine.llm_client import create_llm_client
        client = create_llm_client()
        if not client.is_available():
            return None

        system_prompt = (
            "你是一位出行需求分析师。请从用户的自然语言描述中提取结构化信息，"
            "以严格的 JSON 格式返回，不要包含任何 markdown 代码块标记。\n\n"
            "JSON 字段说明：\n"
            "- user_type: 用户画像（游客/学生/情侣/亲子/独行），选最贴切的\n"
            "- scene: 出行场景（远行出游/闲暇短途）\n"
            "- transport: 出行方式（自驾/公交/步行），根据描述推断\n"
            "- budget_level: 预算档位（1经济/2中等/3自由），数字\n"
            "- prefer_tags: 偏好标签列表（如 拍照、夜景、实惠、历史文化等），至少3个\n"
            "- avoid_tags: 需要避开的标签列表\n\n"
            "重要原则：\n"
            "1. 从自然语言中仔细提取，不要凭空编造\n"
            "2. 注意用户隐含意图：说'省钱'→学生/经济; 说'带孩子'→亲子; 说'拍照好看'→情侣/打卡\n"
            "3. 如果描述模糊但选择了标签，优先参考标签\n"
            "4. prefer_tags 要具体、丰富（如 本地特色、网红打卡、历史文化、亲子 等）\n"
        )
        messages = client.build_messages(system_prompt, f"用户描述：{user_input}")
        resp = await client.chat(messages, temperature=0.3, max_tokens=512)

        if resp.startswith("[") and not resp.startswith("{"):
            return None

        text = resp.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        text = text.strip()

        data = json.loads(text)
        profile = UserProfile(
            user_type=data.get("user_type", "游客"),
            scene=data.get("scene", "远行出游"),
            transport=data.get("transport", "公交"),
            budget_level=int(data.get("budget_level", 2)),
            speed_prefer=USER_TYPE_PATTERNS.get(data.get("user_type", "游客"), {}).get("speed", "悠闲舒适"),
            prefer_tags=data.get("prefer_tags", []),
            avoid_tags=data.get("avoid_tags", []),
            natural_description=user_input,
        )
        weights = _compute_weights(profile)
        reasoning = _generate_reasoning(profile, weights, parsed_by_llm=True)
        return IntentResult(profile=profile, preference_weights=weights, reasoning=reasoning, parsed_by_llm=True)
    except Exception as e:
        print(f"[LLM意图解析失败] {e}")
        return None


# ============================================
# 权重计算
# ============================================
def _build_custom_weights(profile: UserProfile, custom: dict) -> dict:
    """
    根据用户滑块构建自定义权重 v3.1
    custom: {"economy": 0-100, "time_efficiency": 0-100, "distance": 0-100}

    设计原则：滑块值作为相对比例，主导因子预算 75%
    - 省钱(💰) → price 权重     → 拉满时 price 占 75%
    - 效率(⏱) → rating 权重    → 拉满时 rating 占 75%
    - 就近(📍) → distance 权重  → 拉满时 distance 占 75%
    三者为相对比例，一个拉高会挤占其他
    """
    eco = custom.get("economy", 50)
    eff = custom.get("time_efficiency", 50)
    dist = custom.get("distance", 50)

    total_slider = max(eco + eff + dist, 1)

    # 三因子共预算75%，留25%给热度+标签匹配
    main_budget = 0.75

    w_price = (eco / total_slider) * main_budget
    w_rating = (eff / total_slider) * main_budget
    w_distance = (dist / total_slider) * main_budget

    # 固定热度权重
    w_heat = 0.10

    # 标签匹配权重（确保总和为1）
    w_tag = max(0.0, 1.0 - w_price - w_rating - w_distance - w_heat)

    return {
        "rating": round(w_rating, 4),
        "price": round(w_price, 4),
        "heat": round(w_heat, 4),
        "distance": round(w_distance, 4),
        "tag_match": round(w_tag, 4),
    }


def _compute_weights(profile: UserProfile) -> dict:
    weights = {"rating": 0.30, "price": 0.20, "heat": 0.15, "distance": 0.15, "tag_match": 0.20}
    if profile.user_type == "学生":
        weights["price"] = 0.35
        weights["rating"] = 0.20
        weights["heat"] = 0.10
    elif profile.user_type == "情侣":
        weights["tag_match"] = 0.30
        weights["heat"] = 0.10
    elif profile.user_type == "亲子":
        weights["tag_match"] = 0.25
        weights["rating"] = 0.25
    elif profile.user_type == "独行":
        weights["distance"] = 0.25
        weights["heat"] = 0.10
    if profile.speed_prefer == "紧凑高效":
        weights["distance"] = 0.25
        weights["heat"] = 0.10
    return weights


def _match_type(text: str, patterns: dict) -> str:
    for type_name, config in patterns.items():
        keywords = config.get("keywords", []) if isinstance(config, dict) else config
        for kw in keywords:
            if kw in text:
                return type_name
    return list(patterns.keys())[0]


def _infer_budget(text: str) -> int:
    if any(w in text for w in ["便宜", "实惠", "省钱", "穷", "免费", "经济", "学生", "低预算"]):
        return 1
    if any(w in text for w in ["不差钱", "随便", "高端", "豪华", "奢侈", "贵的", "不心疼"]):
        return 3
    return 2


def _generate_reasoning(profile: UserProfile, weights: dict, parsed_by_llm: bool = False) -> str:
    source = "由 LLM 智能解析" if parsed_by_llm else "由关键词匹配推断"
    parts = [
        f"{source}：识别为「{profile.user_type}」身份，",
        f"场景「{profile.scene}」，出行方式「{profile.transport}」，预算档位 Lv{profile.budget_level}。",
    ]
    if profile.prefer_tags:
        parts.append(f"偏好：{', '.join(profile.prefer_tags)}。")
    if profile.avoid_tags:
        parts.append(f"避开：{', '.join(profile.avoid_tags)}。")
    parts.append(f"节奏：{profile.speed_prefer}。")
    parts.append(f"权重：价格{weights['price']:.0%} 标签{weights['tag_match']:.0%} 距离{weights['distance']:.0%} 评分{weights['rating']:.0%}")
    return "".join(parts)


QUICK_PROFILES = {
    "tourist": UserProfile("游客", "远行出游", "公交", 2, "紧凑高效", ["热门", "地标", "历史文化"]),
    "student": UserProfile("学生", "闲暇短途", "公交", 1, "悠闲舒适", ["实惠", "免费", "性价比"]),
    "couple":  UserProfile("情侣", "闲暇短途", "步行", 2, "悠闲舒适", ["夜景", "拍照", "安静"]),
    "family":  UserProfile("亲子", "闲暇短途", "自驾", 2, "悠闲舒适", ["亲子", "休闲", "安全"]),
    "solo":    UserProfile("独行", "远行出游", "公交", 2, "紧凑高效", ["安静", "自由", "小众"]),
}


def get_quick_profile(profile_key: str) -> Optional[UserProfile]:
    return QUICK_PROFILES.get(profile_key)
