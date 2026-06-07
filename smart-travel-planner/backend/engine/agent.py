"""
Agent 景点餐饮推荐模块 + AI 智能调度框架 v3.0

核心升级：
1. 就近匹配餐饮：每个景点匹配最近的美食，消除折路
2. 路线更科学：景点→附近餐饮→下一个景点→附近餐饮
3. 多策略方案生成
4. 时段约束：出发/返程时间，AI严格在时间阈值内规划
5. 自定义权重支持
"""

import os
import math
from typing import Optional
from backend.config import DEFAULT_CENTER, NEARBY_FOOD_KM
from backend.engine.llm_client import create_llm_client


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """计算两点间距离（公里）"""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def estimate_poi_time(poi, transport: str = "公交") -> int:
    """估算单个POI的游玩/用餐时间（分钟）—— 适配短时场景"""
    if poi.category == "景点":
        # 短时场景：景点基础 60 分钟 + 排队（热门景点额外加）
        base = 60
        if poi.heat > 80:
            base += min(poi.peak_wait_min, 30)  # 排队上限30分钟
        return base + 15  # 含少量通勤缓冲
    elif poi.category == "饮品":
        return 30  # 饮品/咖啡 30 分钟
    else:
        return 45  # 餐饮约45分钟


def estimate_travel_time(poi_a, poi_b, transport: str = "公交") -> int:
    """估算两点间交通时间（分钟）"""
    dist = haversine_km(poi_a.lat, poi_a.lng, poi_b.lat, poi_b.lng)
    if transport == "自驾":
        return max(5, int(dist / 0.6))  # 市区40km/h
    elif transport == "步行":
        return max(3, int(dist / 0.08))  # 步行5km/h
    else:  # 公交
        return max(8, int(dist / 0.4))  # 含等车公交25km/h


class RuleEngine:
    """规则引擎 - 科学的路线编排"""

    @staticmethod
    def score_poi(poi, profile, weights, current_lat=DEFAULT_CENTER[0], current_lng=DEFAULT_CENTER[1]):
        rating_score = poi.rating / 5.0
        price_diff = abs(poi.price_level - profile.budget_level)
        price_score = 1.0 - price_diff * 0.33
        tag_hits = sum(1 for t in profile.prefer_tags if t in poi.tags)
        tag_score = min(tag_hits / max(len(profile.prefer_tags), 1), 1.0) if profile.prefer_tags else 0.5
        dist = haversine_km(poi.lat, poi.lng, current_lat, current_lng)
        dist_score = max(0, 1.0 - dist / 10.0)
        heat_score = poi.heat / 100.0
        total = (
            weights.get("rating", 0.30) * rating_score +
            weights.get("price", 0.20) * price_score +
            weights.get("tag_match", 0.20) * tag_score +
            weights.get("distance", 0.15) * dist_score +
            weights.get("heat", 0.15) * heat_score
        )
        return round(total, 4)

    @staticmethod
    def find_nearby_foods(spot, foods: list, max_km: float = NEARBY_FOOD_KM) -> list:
        """为景点找到附近的餐饮，按距离排序"""
        nearby = []
        for f in foods:
            d = haversine_km(spot.lat, spot.lng, f.lat, f.lng)
            if d <= max_km:
                nearby.append((f, d))
        nearby.sort(key=lambda x: x[1])
        return [f for f, _ in nearby]

    @staticmethod
    def build_scientific_route(
        spots: list, foods: list, profile, weights,
        max_pois: int = 6,
        time_constraint=None,  # TimeConstraint object
    ) -> tuple:
        """
        科学路线编排 v3.0：
        1. 景点按综合得分排序
        2. 每个景点绑定附近最佳餐饮
        3. 时段约束：确保总时间在[出发, 返程]以内
        4. 返回 (route_pois, total_minutes, time_overflow)
        """
        from backend.engine.intent import TimeConstraint

        scored_spots = [(s, RuleEngine.score_poi(s, profile, weights)) for s in spots]
        scored_spots.sort(key=lambda x: x[1], reverse=True)
        ordered_spots = [s for s, _ in scored_spots]

        max_minutes = None
        if time_constraint and isinstance(time_constraint, TimeConstraint) and time_constraint.valid():
            max_minutes = time_constraint.total_minutes()

        route = []
        used_food_ids = set()
        total_minutes = 0
        transport = profile.transport if hasattr(profile, 'transport') else "公交"
        prev = None

        for spot in ordered_spots:
            # 时段约束：预估加入此景点+餐饮的总时间
            spot_time = estimate_poi_time(spot, transport)
            travel_to = estimate_travel_time(prev, spot, transport) if prev else 0

            # 找附近餐饮
            nearby = RuleEngine.find_nearby_foods(spot, foods)
            chosen = None
            food_time = 0
            travel_food = 0
            for f in nearby:
                if f.id not in used_food_ids:
                    chosen = f
                    food_time = estimate_poi_time(f, transport)
                    travel_food = estimate_travel_time(spot, f, transport)
                    break

            total_this_stop = travel_to + spot_time + travel_food + food_time

            # 时段约束检查
            if max_minutes is not None and total_minutes + total_this_stop > max_minutes:
                # 尝试只加景点不加餐饮
                if total_minutes + travel_to + spot_time <= max_minutes:
                    if len(route) < max_pois:
                        route.append(spot)
                        total_minutes += travel_to + spot_time
                        prev = spot
                    continue
                else:
                    continue  # 时间不够，跳过

            if len(route) >= max_pois:
                break

            route.append(spot)
            total_minutes += travel_to
            if chosen and len(route) < max_pois:
                route.append(chosen)
                used_food_ids.add(chosen.id)
                total_minutes += spot_time + travel_food + food_time
            else:
                total_minutes += spot_time
            prev = chosen if chosen else spot

        time_overflow = False
        if max_minutes is not None and total_minutes > max_minutes:
            time_overflow = True

        return route, total_minutes, time_overflow

    @staticmethod
    def generate_route_text(route_name: str, pois: list, profile, reasoning: str,
                            total_minutes: int = 0, time_constraint_info: str = "") -> str:
        lines = [f"## {route_name}", "",
                 f"**画像**: {profile.user_type} | {profile.scene} | {profile.transport}",
                 f"**推荐依据**: {reasoning}", ""]
        if time_constraint_info:
            lines.append(f"**时段**: {time_constraint_info}")
            lines.append("")
        lines.append("### 行程安排")
        lines.append("")
        total_cost = 0
        for i, poi in enumerate(pois, 1):
            icon = "🏛" if poi.category == "景点" else "🍽"
            tags_str = " · ".join(poi.tags[:3])
            total_cost += poi.price_avg
            est_time = estimate_poi_time(poi, profile.transport)
            lines.append(f"**{i}. {icon} {poi.name}**  ⭐{poi.rating}  ⏱ 约{est_time}分")
            lines.append(f"   📍 {poi.district} | 💰 人均¥{poi.price_avg} | {'🔥' * min(3, poi.heat // 30 + 1)}")
            lines.append(f"   🏷 {tags_str}")
            lines.append(f"   📝 {poi.description}")
            lines.append(f"   🕐 建议时段: {poi.best_time}")
            if poi.peak_wait_min > 0:
                lines.append(f"   ⚠ 高峰期排队约 {poi.peak_wait_min} 分钟")
            lines.append("")
        total_hours = total_minutes / 60 if total_minutes else (len(pois) * 1.5)
        lines.append("---")
        lines.append(f"💰 预估总费用: ¥{total_cost} | ⏱ 预计总时长: {total_minutes//60}小时{total_minutes%60}分")
        lines.append(f"🔢 共串联 {len(pois)} 个点位")
        lines.append("")
        lines.append("> ⚠ 本路线由 AI 自动生成，仅供参考。您可以根据自身喜好手动调整。")
        return "\n".join(lines)

    @staticmethod
    def generate_plan(
        pois: list, profile, weights: dict, count: int = 3,
        time_constraint=None,  # TimeConstraint
    ) -> list[dict]:
        """
        生成多套差异化方案 v3.0
        支持时段约束，默认排除远距离区域
        """
        from backend.config import MAX_POI_PER_ROUTE
        from backend.engine.intent import TimeConstraint
        from backend.data.poi_data import REMOTE_DISTRICTS

        # 排除远距离区域（短时规划适配）
        pois = [p for p in pois if p.district not in REMOTE_DISTRICTS]
        spots = [p for p in pois if p.category == "景点"]
        foods = [p for p in pois if p.category == "美食"]
        plans = []

        tc_info = ""
        if time_constraint and isinstance(time_constraint, TimeConstraint) and time_constraint.valid():
            tc_info = f"{time_constraint.departure} → {time_constraint.return_time}（{time_constraint.total_minutes()//60}小时{time_constraint.total_minutes()%60}分）"

        if not spots:
            sorted_all = sorted(pois, key=lambda p: (p.rating, p.heat), reverse=True)
            route = sorted_all[:MAX_POI_PER_ROUTE]
            plans.append({
                "name": "⭐ 口碑优选路线",
                "description": "基于综合评分的精选推荐",
                "pois": [p.to_dict() for p in route],
                "summary": RuleEngine.generate_route_text(
                    "⭐ 口碑优选路线", route, profile, "综合评分最高"
                ),
                "total_minutes": 0,
                "time_overflow": False,
            })
            return plans

        # 方案 A：个性推荐（画像定制 + 就近餐饮 + 时段约束）
        route_a, minutes_a, overflow_a = RuleEngine.build_scientific_route(
            spots, foods, profile, weights, MAX_POI_PER_ROUTE, time_constraint
        )
        desc_a = f"基于「{profile.user_type}」画像定制，景点与附近美食就近搭配，避免折路"
        if time_constraint and time_constraint.valid():
            desc_a += f"（严格控制在{tc_info}内）"
        plans.append({
            "name": "💡 个性推荐路线",
            "description": desc_a,
            "pois": [p.to_dict() for p in route_a],
            "summary": RuleEngine.generate_route_text(
                "💡 方案A：个性推荐路线", route_a, profile,
                f"结合{profile.user_type}偏好，每个景点匹配最近优质餐饮，最小化路途折返",
                total_minutes=minutes_a, time_constraint_info=tc_info,
            ),
            "total_minutes": minutes_a,
            "time_overflow": overflow_a,
        })

        # 方案 B：高效打卡（距离优先 + 时段约束）
        sorted_by_dist = sorted(spots, key=lambda s: haversine_km(s.lat, s.lng, DEFAULT_CENTER[0], DEFAULT_CENTER[1]))
        route_b, minutes_b, overflow_b = [], 0, False
        used_b = set()
        max_minutes = time_constraint.total_minutes() if (time_constraint and time_constraint.valid()) else None
        prev_b = None
        for spot in sorted_by_dist:
            travel = estimate_travel_time(prev_b, spot, profile.transport) if prev_b else 0
            spot_t = estimate_poi_time(spot, profile.transport)
            nearby = RuleEngine.find_nearby_foods(spot, foods)
            chosen_b = None
            food_t = 0
            for f in nearby:
                if f.id not in used_b:
                    chosen_b = f
                    food_t = estimate_poi_time(f, profile.transport)
                    break
            total_b = travel + spot_t + (food_t if chosen_b else 0)
            if max_minutes is not None and minutes_b + total_b > max_minutes:
                if minutes_b + travel + spot_t <= max_minutes and len(route_b) < MAX_POI_PER_ROUTE:
                    route_b.append(spot)
                    minutes_b += travel + spot_t
                    prev_b = spot
                continue
            if len(route_b) >= MAX_POI_PER_ROUTE:
                break
            route_b.append(spot)
            minutes_b += travel + spot_t
            if chosen_b and len(route_b) < MAX_POI_PER_ROUTE:
                route_b.append(chosen_b)
                used_b.add(chosen_b.id)
                minutes_b += food_t
            prev_b = chosen_b if chosen_b else spot
        if max_minutes is not None and minutes_b > max_minutes:
            overflow_b = True
        plans.append({
            "name": "⏱ 高效打卡路线",
            "description": "由市中心向外辐射，景点就近用餐，路程最省" + (f"（控制在{tc_info}内）" if tc_info else ""),
            "pois": [p.to_dict() for p in route_b],
            "summary": RuleEngine.generate_route_text(
                "⏱ 方案B：高效打卡路线", route_b, profile,
                "按距离由近到远串联，每个景点绑定最近餐饮，最大化时间效率",
                total_minutes=minutes_b, time_constraint_info=tc_info,
            ),
            "total_minutes": minutes_b,
            "time_overflow": overflow_b,
        })

        # 方案 C：口碑优先（评分最高景点 + 时段约束）
        sorted_spots = sorted(spots, key=lambda s: (s.rating, s.heat), reverse=True)
        route_c, minutes_c, overflow_c = [], 0, False
        used_c = set()
        prev_c = None
        max_minutes2 = time_constraint.total_minutes() if (time_constraint and time_constraint.valid()) else None
        for spot in sorted_spots:
            travel = estimate_travel_time(prev_c, spot, profile.transport) if prev_c else 0
            spot_t = estimate_poi_time(spot, profile.transport)
            nearby = RuleEngine.find_nearby_foods(spot, foods)
            chosen_c = None
            food_t = 0
            for f in nearby:
                if f.id not in used_c:
                    chosen_c = f
                    food_t = estimate_poi_time(f, profile.transport)
                    break
            total_c = travel + spot_t + (food_t if chosen_c else 0)
            if max_minutes2 is not None and minutes_c + total_c > max_minutes2:
                if minutes_c + travel + spot_t <= max_minutes2 and len(route_c) < MAX_POI_PER_ROUTE:
                    route_c.append(spot)
                    minutes_c += travel + spot_t
                    prev_c = spot
                continue
            if len(route_c) >= MAX_POI_PER_ROUTE:
                break
            route_c.append(spot)
            minutes_c += travel + spot_t
            if chosen_c and len(route_c) < MAX_POI_PER_ROUTE:
                route_c.append(chosen_c)
                used_c.add(chosen_c.id)
                minutes_c += food_t
            prev_c = chosen_c if chosen_c else spot
        if max_minutes2 is not None and minutes_c > max_minutes2:
            overflow_c = True
        plans.append({
            "name": "⭐ 口碑优先路线",
            "description": "优先推荐高评分景点与餐厅，品质体验有保障" + (f"（控制在{tc_info}内）" if tc_info else ""),
            "pois": [p.to_dict() for p in route_c],
            "summary": RuleEngine.generate_route_text(
                "⭐ 方案C：口碑优先路线", route_c, profile,
                "综合评分最高的景点优先，并匹配同区域高分餐厅，品质与便利兼顾",
                total_minutes=minutes_c, time_constraint_info=tc_info,
            ),
            "total_minutes": minutes_c,
            "time_overflow": time_constraint.valid() and minutes_c > time_constraint.total_minutes() if time_constraint and time_constraint.valid() else False,
        })

        return plans[:count]


class LLMRoutePlanner:
    """LLM 智能路线规划器"""

    @staticmethod
    async def enhance_plan_summary(plan: dict, profile, reasoning: str) -> str:
        """用 LLM 为路线生成更自然的说明文案"""
        try:
            client = create_llm_client()
            if not client.is_available():
                return plan.get("summary", "")

            poi_text = "\n".join([
                f"{i+1}. {p['name']}（{p['category']}，{p['district']}，评分{p['rating']}，人均¥{p['price_avg']}，标签：{', '.join(p['tags'])}）"
                for i, p in enumerate(plan.get("pois", []))
            ])

            system_prompt = (
                "你是一位资深旅行规划师。请根据以下用户画像和POI列表，"
                "写一段200字以内的温暖、有感染力的路线推荐语，说明这条路线的亮点和适合人群。"
                "不要罗列每个点，而是像一个朋友在推荐。"
            )
            user_msg = f"用户画像：{profile.user_type}，{profile.scene}，预算Lv{profile.budget_level}，偏好{', '.join(profile.prefer_tags)}\n\n路线点位：\n{poi_text}"
            messages = client.build_messages(system_prompt, user_msg)
            resp = await client.chat(messages, temperature=0.8, max_tokens=512)
            return resp.strip()
        except Exception as e:
            print(f"[LLM增强失败] {e}")
            return plan.get("summary", "")
