"""
LLM Agent 规划器 v6.0 —— Plan-then-Execute 模式

核心改进：从 6 轮串行 ReAct → 2 轮 Plan-then-Execute
  Phase 1: Plan  — 1 轮 LLM 输出完整工具调用计划
  Phase 2: Execute — 并行执行所有工具
  Phase 3: Generate — 1 轮 LLM 用所有结果生成 Final Answer

新增 SSE 流式输出：plan_stream() 方法 yield 实时事件，前端可展示思考链动画
"""

import json
import re
import time
from typing import Optional, AsyncGenerator, Dict, Any, List

from backend.data.poi_data import get_all_pois, get_poi_by_id
from backend.engine.intent import IntentResult
from backend.agent.tools import (
    ToolLogger,
    tool_search_pois,
    tool_check_queue,
    tool_book_table,
    tool_send_plan,
    TOOL_REGISTRY,
)


# ============================================
# 数据结构（保持不变）
# ============================================
class AgentPlan:
    """Agent 输出的完整方案"""

    def __init__(
        self,
        intent: IntentResult,
        itinerary: list[dict],
        total_cost_estimate: int = 0,
        total_duration: str = "",
        bookings: list[dict] = None,
        tool_logs: list[dict] = None,
        plan_text_for_sharing: str = "",
        reasoning: str = "",
        alternatives: list[dict] = None,  # 备选方案
        decision_notes: list[str] = None,  # 决策理由列表
    ):
        self.intent = intent
        self.itinerary = itinerary
        self.total_cost_estimate = total_cost_estimate
        self.total_duration = total_duration
        self.bookings = bookings or []
        self.tool_logs = tool_logs or []
        self.plan_text_for_sharing = plan_text_for_sharing
        self.reasoning = reasoning
        self.alternatives = alternatives or []
        self.decision_notes = decision_notes or []


# ============================================
# POI 速览（注入 System Prompt）
# ============================================
def _build_poi_summary() -> str:
    pois = get_all_pois()
    lines = ["| ID | 名称 | 分类 | 区域 | 人均 | 评分 | 标签 |",
             "|----|------|------|------|------|------|------|"]
    for p in pois:
        tags = "、".join(p.tags[:3])
        lines.append(
            f"| {p.id} | {p.name} | {p.category}/{p.sub_category} | {p.district} | "
            f"¥{p.price_avg} | {p.rating} | {tags} |"
        )
    return "\n".join(lines)


# ============================================
# Plan 阶段 System Prompt
# ============================================
PLAN_SYSTEM_PROMPT = f"""你是一个本地短时出行规划 Agent，专为郑州用户安排半天到一天的活动方案。

## 你的任务
分析用户需求，制定一个完整的**工具调用计划**。你需要一次性列出所有需要调用的工具和参数。

## 可用工具
1. **search_pois** — 搜索POI（景点/餐厅），参数: {{"query":"关键词","category":"景点或美食","budget_level":1-3,"prefer_tags":["标签"],"district":"区名可选"}}
2. **check_queue** — 查询排队，参数: {{"restaurant_id":"f003","restaurant_name":"巴奴","party_size":4,"preferred_time":"18:00"}}
3. **book_table** — 预订餐厅，参数: {{"restaurant_id":"f003","restaurant_name":"巴奴","party_size":4,"time":"18:00","special_requests":"需要宝宝椅"}}
4. **send_plan** — 发送计划（最后一步），参数: {{"recipient":"老婆","plan_text":"计划内容","channel":"sms"}}

## 输出格式（严格遵守，只输出 JSON 数组）
[
  {{"tool":"search_pois","params":{{"query":"亲子景点","category":"景点","budget_level":2,"prefer_tags":["亲子","户外"]}}}},
  {{"tool":"search_pois","params":{{"query":"健康轻食","category":"美食","budget_level":2,"prefer_tags":["健康","清淡"]}}}},
  {{"tool":"check_queue","params":{{"restaurant_id":"f001","restaurant_name":"萧记三鲜烩面","party_size":4,"preferred_time":"17:30"}}}},
  {{"tool":"book_table","params":{{"restaurant_id":"f001","restaurant_name":"萧记三鲜烩面","party_size":4,"time":"17:30"}}}}
]

## 规划策略
1. 先用 search_pois 搜索候选景点（1次）和餐厅（1次），分两次调用
2. 对最合适的1-2家餐厅调用 check_queue 确认排队情况
3. 如果排队可接受（<30分钟），调用 book_table 预订
4. 所有工具数量控制在 3-5 个
5. 参数必须真实合理，party_size 根据用户描述推断

## 约束指南
- "减肥"→ prefer_tags 加"健康""清淡"，避开"火锅""油炸"
- "带娃"→ category 选"景点" prefer_tags 加"亲子"，party_size 至少3人
- "N个人"→ party_size=N
- "附近"→ district 填用户提到的区域名

## 郑州 POI 速览（搜索时参考，不要伪造不存在的 POI ID）
{_build_poi_summary()}
"""


# ============================================
# Generate 阶段 System Prompt
# ============================================
GENERATE_SYSTEM_PROMPT = """你是一个本地短时出行方案生成 Agent。基于已执行的工具调用结果，制定最终时间轴方案。

## 输出格式（严格 JSON）
{
  "itinerary": [
    {
      "time_range": "14:00-15:30",
      "activity": "游玩郑州动物园",
      "poi_id": "s005",
      "poi_name": "郑州动物园",
      "category": "景点",
      "notes": "亲子友好，小朋友看熊猫",
      "price_estimate": 45,
      "decision_reason": "亲子标签匹配，评分4.5分"
    }
  ],
  "total_cost_estimate": 450,
  "total_duration": "约4小时30分钟",
  "plan_text_for_sharing": "搞定了，下午出发：\\n14:00-15:30 郑州动物园\\n...",
  "reasoning": "根据用户亲子+减肥需求，选择了动物园和轻食餐厅...",
  "alternatives": [
    {"poi_name": "郑州植物园", "reason": "备选景点，距离更近但趣味性稍低"}
  ],
  "decision_notes": [
    "避开火锅类餐厅（减肥需求）",
    "选择排队<15分钟的餐厅（时间效率优先）"
  ]
}

## 规则
1. time_range 必须连贯、合理（从14:00开始编排）
2. 每个活动之间留 10-15 分钟通勤间隔，但不要把通勤作为独立的 itinerary 节点
3. itinerary 中每个节点必须是真实的目的地（景点/美食/饮品），必须有 poi_id；禁止生成「前往XX」「通勤」「交通」等无 poi_id 的节点
4. 短时场景适配：景点游玩 60-90 分钟，餐饮 45 分钟，饮品 30 分钟；总行程控制在半天以内
5. 带娃场景的活动不超过 90 分钟/个
6. 决策理由必须基于实际工具返回数据，不要编造
7. 备选方案是对已搜索但未采用的POI的推荐
"""


# ============================================
# SSE 事件构造工具
# ============================================
def sse_event(event_type: str, data: dict) -> str:
    """构造一条 SSE 事件"""
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# ============================================
# LLM Plan-then-Execute Planner v6.0
# ============================================
class LLMReActPlanner:
    """
    Plan-then-Execute Agent 规划器

    流程：
    Phase 1: Plan  — LLM 输出工具调用计划 JSON
    Phase 2: Execute — 并发执行所有工具
    Phase 3: Generate — LLM 生成 Final Answer
    如果 LLM 不可用，自动降级到 FallbackPlanner
    """

    MAX_TURNS = 2  # 最多 2 轮 Plan（Plan 阶段解析失败时重试）
    LLM_TIMEOUT = 45  # 单次 LLM 调用超时（秒）

    def __init__(self):
        self.logger = ToolLogger()
        self.all_pois = get_all_pois(exclude_remote=True)
        self.poi_dict = {p.id: p for p in self.all_pois}

    def reset(self):
        self.logger = ToolLogger()

    # ============================================
    # 主入口：同步模式（向后兼容）
    # ============================================
    async def plan(self, user_input: str, intent: IntentResult) -> AgentPlan:
        """同步规划入口，向后兼容"""
        self.reset()
        start_time = time.time()

        try:
            # Plan 阶段
            tool_plan = await self._plan_phase(user_input, intent)
            if not tool_plan:
                print("[Planner] Plan 阶段失败，降级")
                return FallbackPlanner().plan(user_input, intent)

            # Execute 阶段
            all_pois, all_results = await self._execute_phase(tool_plan, intent)

            # Generate 阶段
            final = await self._generate_phase(user_input, intent, all_results, all_pois)
            if final:
                return self._build_plan_from_final(final, intent, all_pois, start_time)

        except Exception as e:
            print(f"[Planner] 异常: {e}，降级到规则模板")

        return self._build_fallback_from_observations(intent, all_pois if 'all_pois' in dir() else [], start_time)

    # ============================================
    # SSE 流式接口（新）
    # ============================================
    async def plan_stream(
        self, user_input: str, intent: IntentResult
    ) -> AsyncGenerator[str, None]:
        """
        SSE 流式规划 — 实时推送思考链事件

        yield 的每条都是完整的 SSE 事件字符串
        """
        self.reset()
        start_time = time.time()
        profile = intent.profile

        # Event 1: 开始分析
        yield sse_event("phase", {
            "phase": "analyzing",
            "icon": "🧠",
            "message": f"正在分析需求：{profile.user_type}场景 | 预算Lv{profile.budget_level} | {profile.transport}",
            "tags": [profile.user_type, f"预算Lv{profile.budget_level}", profile.transport] + profile.prefer_tags[:3],
        })

        # 检查 LLM 可用性
        from backend.engine.llm_client import create_llm_client
        client = create_llm_client()
        if not client.is_available():
            yield sse_event("phase", {
                "phase": "degraded",
                "icon": "🟡",
                "message": "LLM 未配置，使用规则模板生成方案",
                "reason": "api_key_unavailable"
            })
            # 降级到 Fallback，但仍然流式输出
            fallback_plan = FallbackPlanner().plan(user_input, intent)
            yield self._build_final_sse_event(fallback_plan, intent)
            return

        # Event 2: Plan 阶段
        yield sse_event("phase", {
            "phase": "planning",
            "icon": "📋",
            "message": "Agent 正在制定工具调用计划...",
        })

        tool_plan = await self._plan_phase(user_input, intent)
        if not tool_plan:
            yield sse_event("phase", {
                "phase": "degraded",
                "icon": "🟡",
                "message": "LLM 规划失败，降级到规则模板",
            })
            fallback_plan = FallbackPlanner().plan(user_input, intent)
            yield self._build_final_sse_event(fallback_plan, intent)
            return

        # 推送计划摘要
        tool_names = [t["tool"] for t in tool_plan]
        yield sse_event("phase", {
            "phase": "plan_done",
            "icon": "✅",
            "message": f"计划制定完成，共 {len(tool_plan)} 个步骤：{' → '.join(tool_names)}",
            "steps": tool_names,
        })

        # Event 3-N: Execute 阶段（逐个流式输出）
        yield sse_event("phase", {
            "phase": "executing",
            "icon": "⚡",
            "message": f"开始执行 {len(tool_plan)} 个工具调用...",
        })

        all_pois = []
        all_results = []

        for tp in tool_plan:
            # yield 工具开始事件
            yield sse_event("tool_call", {
                "tool": tp["tool"],
                "icon": self._tool_icon(tp["tool"]),
                "action_label": self._tool_label(tp["tool"], tp["params"]),
                "params_summary": self._params_summary(tp["tool"], tp["params"]),
                "status": "executing",
            })

            # 执行工具
            action_input_str = json.dumps(tp["params"], ensure_ascii=False)
            result = await self._execute_single_tool(tp["tool"], action_input_str, intent, all_pois)
            all_results.append({"tool": tp["tool"], "params": tp["params"], "result": result})

            # 收集 POI 数据
            if tp["tool"] == "search_pois" and result.get("success"):
                pois = result.get("data", {}).get("pois", [])
                all_pois.extend(pois)

            # yield 工具完成事件
            yield sse_event("tool_call", {
                "tool": tp["tool"],
                "icon": "✅" if result.get("success") else "❌",
                "action_label": self._tool_label(tp["tool"], tp["params"]),
                "status": "done" if result.get("success") else "failed",
                "summary": self._visual_summary(tp["tool"], result),
                "detail": self._tool_detail(tp["tool"], result),
                "duration_ms": result.get("_duration_ms", 0),
            })

        # Event N+1: Generate 阶段
        yield sse_event("phase", {
            "phase": "generating",
            "icon": "✨",
            "message": "Agent 正在综合所有信息，生成最优方案...",
        })

        final = await self._generate_phase(user_input, intent, all_results, all_pois)
        if not final:
            yield sse_event("phase", {
                "phase": "degraded",
                "icon": "🟡",
                "message": "方案生成失败，使用已获取数据构造方案",
            })
            plan = self._build_fallback_from_observations(intent, all_pois, start_time)
        else:
            plan = self._build_plan_from_final(final, intent, all_pois, start_time)

        # Event Final: 输出完整方案
        yield self._build_final_sse_event(plan, intent)

    # ============================================
    # Phase 1: Plan — LLM 输出工具调用计划
    # ============================================
    async def _plan_phase(self, user_input: str, intent: IntentResult) -> Optional[list]:
        """让 LLM 一次性输出所有工具调用计划"""
        from backend.engine.llm_client import create_llm_client

        client = create_llm_client()
        if not client.is_available():
            return None

        profile = intent.profile
        user_msg = self._build_user_message(user_input, intent)

        # 在用户消息后追加格式要求
        plan_instruction = (
            f"{user_msg}\n\n"
            f"请一次性规划所有需要的工具调用，只输出 JSON 数组。\n"
            f"用户画像: 类型={profile.user_type}, 预算=Lv{profile.budget_level}, "
            f"偏好={profile.prefer_tags}, 避开={profile.avoid_tags}\n"
        )

        for attempt in range(self.MAX_TURNS):
            try:
                response = await client.chat(
                    messages=[
                        {"role": "system", "content": PLAN_SYSTEM_PROMPT},
                        {"role": "user", "content": plan_instruction},
                    ],
                    temperature=0.3,
                    max_tokens=1024,
                )

                if response.startswith("[LLM"):
                    print(f"[Plan Phase] LLM 错误: {response}")
                    continue

                # 解析 JSON 数组
                tool_plan = self._parse_tool_plan(response)
                if tool_plan:
                    return tool_plan

                print(f"[Plan Phase] 第{attempt+1}次尝试解析失败，重试...")
                plan_instruction += "\n上次输出格式不正确，请严格只输出JSON数组。"

            except Exception as e:
                print(f"[Plan Phase] 异常: {e}")
                continue

        return None

    def _parse_tool_plan(self, text: str) -> Optional[list]:
        """解析 LLM 输出的工具调用计划 JSON 数组"""
        # 尝试直接解析整个文本
        text = text.strip()
        # 移除 markdown 代码块标记
        if text.startswith("```"):
            text = re.sub(r'^```\w*\n?', '', text)
            text = re.sub(r'\n?```$', '', text)

        # 找到 JSON 数组
        arr_start = text.find("[")
        arr_end = text.rfind("]")
        if arr_start < 0 or arr_end <= arr_start:
            return None

        json_str = text[arr_start:arr_end + 1]

        try:
            plan = json.loads(json_str)
            if not isinstance(plan, list):
                return None

            # 验证每个 item 格式
            valid_plan = []
            for item in plan:
                if not isinstance(item, dict):
                    continue
                tool = item.get("tool", "")
                if tool not in TOOL_REGISTRY:
                    print(f"[Plan Phase] 未知工具: {tool}")
                    continue
                valid_plan.append({
                    "tool": tool,
                    "params": item.get("params", {}),
                })

            return valid_plan if valid_plan else None

        except json.JSONDecodeError as e:
            print(f"[Plan Phase] JSON 解析失败: {e}")
            return None

    # ============================================
    # Phase 2: Execute — 执行工具调用
    # ============================================
    async def _execute_phase(self, tool_plan: list, intent: IntentResult) -> tuple:
        """批量执行所有工具（向后兼容）"""
        all_pois = []
        all_results = []

        for tp in tool_plan:
            action_input_str = json.dumps(tp["params"], ensure_ascii=False)
            result = await self._execute_single_tool(tp["tool"], action_input_str, intent, all_pois)
            all_results.append({"tool": tp["tool"], "params": tp["params"], "result": result})
            if tp["tool"] == "search_pois" and result.get("success"):
                pois = result.get("data", {}).get("pois", [])
                all_pois.extend(pois)

        return all_pois, all_results

    # ============================================
    # Phase 3: Generate — LLM 生成最终方案
    # ============================================
    async def _generate_phase(
        self, user_input: str, intent: IntentResult,
        all_results: list, all_pois: list,
    ) -> Optional[dict]:
        """用所有工具结果让 LLM 生成最终方案"""
        from backend.engine.llm_client import create_llm_client

        client = create_llm_client()
        if not client.is_available():
            return None

        # 构造工具结果摘要
        results_text = "## 工具调用结果汇总\n\n"
        for i, r in enumerate(all_results):
            results_text += f"### {i+1}. {r['tool']}\n"
            results_text += f"参数：{json.dumps(r['params'], ensure_ascii=False)}\n"
            if r["result"].get("success"):
                data = r["result"].get("data", {})
                if r["tool"] == "search_pois":
                    pois = data.get("pois", [])
                    results_text += f"找到 {len(pois)} 个：\n"
                    for p in pois[:8]:
                        results_text += f"  - [{p.get('id')}] {p.get('name')} | {p.get('category')} | ¥{p.get('price_avg')} | {p.get('rating')}分 | {p.get('district', '')}\n"
                elif r["tool"] == "check_queue":
                    results_text += f"{data.get('restaurant_name','')} 排队 {data.get('wait_minutes',0)} 分钟 | 状态: {data.get('status','')}\n"
                elif r["tool"] == "book_table":
                    results_text += f"预订确认: {data.get('confirm_code','')} | {data.get('status','')}\n"
                else:
                    results_text += f"{json.dumps(data, ensure_ascii=False)[:200]}\n"
            else:
                results_text += f"❌ 失败: {r['result'].get('error', '未知错误')}\n"
            results_text += "\n"

        profile = intent.profile
        generate_prompt = (
            f"用户目标：「{user_input}」\n"
            f"用户画像：{profile.user_type} 场景 | 预算 Lv{profile.budget_level} | "
            f"出行{profile.transport} | 偏好{profile.prefer_tags} | 避开{profile.avoid_tags}\n\n"
            f"{results_text}\n"
            f"请基于以上工具调用结果，制定完整的时间轴方案。只输出 Final Answer JSON。"
        )

        try:
            response = await client.chat(
                messages=[
                    {"role": "system", "content": GENERATE_SYSTEM_PROMPT},
                    {"role": "user", "content": generate_prompt},
                ],
                temperature=0.3,
                max_tokens=1024,
            )

            if response.startswith("[LLM"):
                print(f"[Generate Phase] LLM 错误: {response}")
                return None

            return self._parse_final_answer(response)

        except Exception as e:
            print(f"[Generate Phase] 异常: {e}")
            return None

    # ============================================
    # Tool 执行（内部方法）
    # ============================================
    async def _execute_single_tool(
        self, action_name: str, action_input_str: str,
        intent: IntentResult, all_found_pois: list,
    ) -> dict:
        """执行单个工具"""
        try:
            params = json.loads(action_input_str)
        except json.JSONDecodeError:
            return {
                "success": False, "data": None,
                "error": f"参数 JSON 解析失败", "_duration_ms": 0,
            }

        tool_start = time.time()

        if action_name == "search_pois":
            profile = intent.profile
            params.setdefault("user_type", profile.user_type)
            params.setdefault("budget_level", profile.budget_level)
            params.setdefault("prefer_tags", profile.prefer_tags)
            result = tool_search_pois(params=params, poi_data=self.all_pois)
        elif action_name == "check_queue":
            params.setdefault("party_size", self._infer_party_size(intent))
            result = tool_check_queue(params=params)
        elif action_name == "book_table":
            params.setdefault("party_size", self._infer_party_size(intent))
            result = tool_book_table(params=params)
        elif action_name == "send_plan":
            result = tool_send_plan(params=params)
        else:
            result = {"success": False, "data": None, "error": f"未知工具: {action_name}", "_duration_ms": 0}

        duration_ms = (time.time() - tool_start) * 1000
        result.setdefault("_duration_ms", duration_ms)

        self.logger.log(
            tool_name=action_name, params=params, result=result,
            duration_ms=result.get("_duration_ms", duration_ms),
        )

        return result

    # ============================================
    # 消息构建 / 解析
    # ============================================
    def _build_user_message(self, user_input: str, intent: IntentResult) -> str:
        p = intent.profile
        parts = [
            f"用户目标：「{user_input}」",
            f"分析画像：{p.user_type} | 场景={p.scene} | 交通={p.transport} | 预算Lv{p.budget_level}",
            f"偏好：{p.prefer_tags or '无'} | 避开：{p.avoid_tags or '无'}",
        ]
        if intent.anomalies:
            parts.append("异常提醒：")
            for a in intent.anomalies:
                parts.append(f"  - {a.message} | 建议：{a.suggestion}")
        return "\n".join(parts)

    def _parse_final_answer(self, text: str) -> Optional[dict]:
        """提取 Final Answer JSON"""
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r'^```\w*\n?', '', text)
            text = re.sub(r'\n?```$', '', text)

        # 找 JSON 对象
        brace_start = text.find("{")
        brace_end = text.rfind("}")
        if brace_start < 0 or brace_end <= brace_start:
            return None

        json_str = text[brace_start:brace_end + 1]
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            try:
                fixed = re.sub(r',\s*}', '}', json_str)
                fixed = re.sub(r',\s*]', ']', fixed)
                return json.loads(fixed)
            except json.JSONDecodeError:
                return None

    # ============================================
    # 结果构建
    # ============================================
    def _build_plan_from_final(
        self, final: dict, intent: IntentResult,
        all_pois: list, start_time: float,
    ) -> AgentPlan:
        itinerary = final.get("itinerary", [])
        # 1. 过滤掉无 poi_id 的交通/通勤节点（LLM 可能错误生成）
        clean_itin = []
        for item in itinerary:
            poi_id = item.get("poi_id", "")
            activity = item.get("activity", "")
            # 跳过明显是交通节点的无 poi_id 项
            if not poi_id and any(k in activity for k in ["前往", "通勤", "交通", "换乘", "到达"]):
                continue
            if poi_id and poi_id in self.poi_dict:
                poi = self.poi_dict[poi_id]
                item.setdefault("poi_name", poi.name)
                item.setdefault("category", poi.category)
                item.setdefault("price_estimate", poi.price_avg)
                # 直接带上坐标，前端无需二次查找
                item.setdefault("lat", poi.lat)
                item.setdefault("lng", poi.lng)
            clean_itin.append(item)

        # 2. 重新计算时间轴，确保连贯且符合短时场景
        clean_itin = self._recalculate_times(clean_itin)

        bookings = [item["booking"] for item in clean_itin if item.get("booking")]
        tool_logs = [{
            "tool": c.tool_name, "params": c.params,
            "success": c.success, "duration_ms": c.duration_ms,
            "summary": self._summarize_tool_result(c),
        } for c in self.logger.calls]

        total_ms = (time.time() - start_time) * 1000
        reasoning = final.get("reasoning", (
            f"🧠 Plan-then-Execute Agent | 耗时 {total_ms:.0f}ms\n"
            f"  → 工具调用：{len(self.logger.calls)} 次\n"
            f"  → 搜索 POI：{len(all_pois)} 个候选项\n"
            f"  → 时间轴：{len(clean_itin)} 个活动节点\n"
        ))

        # 重新计算总时长
        total_duration = self._compute_total_duration(clean_itin)

        return AgentPlan(
            intent=intent, itinerary=clean_itin,
            total_cost_estimate=final.get("total_cost_estimate", 0),
            total_duration=total_duration,
            bookings=bookings, tool_logs=tool_logs,
            plan_text_for_sharing=final.get("plan_text_for_sharing", ""),
            reasoning=reasoning,
            alternatives=final.get("alternatives", []),
            decision_notes=final.get("decision_notes", []),
        )

    @staticmethod
    def _recalculate_times(itinerary: list) -> list:
        """重新计算 itinerary 的时间轴，过滤后保持连贯"""
        if not itinerary:
            return []
        # 取第一个节点的原始开始时间，或默认 14:00
        first_range = itinerary[0].get("time_range", "14:00-15:00")
        try:
            start_str = first_range.split("-")[0]
            current_h, current_m = map(int, start_str.split(":"))
        except Exception:
            current_h, current_m = 14, 0

        def add_min(m):
            nonlocal current_h, current_m
            current_m += m
            while current_m >= 60:
                current_h += 1
                current_m -= 60

        new_itin = []
        for i, item in enumerate(itinerary):
            cat = item.get("category", "")
            if cat == "景点":
                duration = 60
            elif cat == "饮品":
                duration = 30
            else:
                duration = 45

            st = f"{current_h:02d}:{current_m:02d}"
            add_min(duration)
            et = f"{current_h:02d}:{current_m:02d}"
            new_item = dict(item)
            new_item["time_range"] = f"{st}-{et}"
            new_itin.append(new_item)

            if i < len(itinerary) - 1:
                add_min(10)  # 通勤缓冲
        return new_itin

    @staticmethod
    def _compute_total_duration(itinerary: list) -> str:
        if not itinerary:
            return ""
        try:
            first = itinerary[0].get("time_range", "14:00-15:00").split("-")[0]
            last = itinerary[-1].get("time_range", "17:00-18:00").split("-")[1]
            fh, fm = map(int, first.split(":"))
            lh, lm = map(int, last.split(":"))
            total_min = (lh * 60 + lm) - (fh * 60 + fm)
            if total_min <= 0:
                total_min += 24 * 60
            return f"约{total_min // 60}小时{total_min % 60}分钟"
        except Exception:
            return ""

    def _build_fallback_from_observations(
        self, intent: IntentResult, all_pois: list, start_time: float,
    ) -> AgentPlan:
        """从已获取的 Observation 构造降级方案"""
        scenic = [p for p in all_pois if p.get("category") == "景点"]
        foods = [p for p in all_pois if p.get("category") == "美食"]
        itinerary = []
        current_h, current_m = 14, 0

        def add_min(m):
            nonlocal current_h, current_m
            current_m += m
            while current_m >= 60:
                current_h += 1; current_m -= 60

        for s in scenic[:1]:
            st = f"{current_h:02d}:{current_m:02d}"; add_min(60)
            et = f"{current_h:02d}:{current_m:02d}"
            itinerary.append({"time_range": f"{st}-{et}", "activity": f"游玩 {s.get('name', '景点')}",
                "poi_id": s.get("id", ""), "poi_name": s.get("name", ""), "category": "景点",
                "notes": s.get("description", ""), "price_estimate": s.get("price_avg", 0),
                "lat": s.get("lat"), "lng": s.get("lng")})
            add_min(15)

        drinks = [f for f in foods if f.get("sub_category") == "饮品"]
        if drinks:
            d = drinks[0]; st = f"{current_h:02d}:{current_m:02d}"; add_min(30)
            et = f"{current_h:02d}:{current_m:02d}"
            itinerary.append({"time_range": f"{st}-{et}", "activity": f"饮品 · {d.get('name', '')}",
                "poi_id": d.get("id", ""), "poi_name": d.get("name", ""), "category": "饮品",
                "notes": "休息片刻", "price_estimate": d.get("price_avg", 25),
                "lat": d.get("lat"), "lng": d.get("lng")})

        restaurants = [f for f in foods if f.get("sub_category") != "饮品"]
        for r in restaurants[:1]:
            st = f"{current_h:02d}:{current_m:02d}"; add_min(45)
            et = f"{current_h:02d}:{current_m:02d}"
            itinerary.append({"time_range": f"{st}-{et}", "activity": f"晚餐 · {r.get('name', '')}",
                "poi_id": r.get("id", ""), "poi_name": r.get("name", ""), "category": "美食",
                "notes": r.get("description", ""), "price_estimate": r.get("price_avg", 0),
                "lat": r.get("lat"), "lng": r.get("lng")})

        tool_logs = [{"tool": c.tool_name, "params": c.params, "success": c.success,
            "duration_ms": c.duration_ms, "summary": self._summarize_tool_result(c)} for c in self.logger.calls]
        total_ms = (time.time() - start_time) * 1000
        total_cost = sum(it.get("price_estimate", 0) for it in itinerary) * self._infer_party_size(intent)

        return AgentPlan(
            intent=intent, itinerary=itinerary, total_cost_estimate=total_cost,
            total_duration=f"约{current_h-14}小时{current_m}分钟", bookings=[], tool_logs=tool_logs,
            plan_text_for_sharing=self._build_share_text(intent, itinerary),
            reasoning=f"🧠 Plan-then-Execute (降级) | 耗时 {total_ms:.0f}ms | 工具调用 {len(self.logger.calls)} 次",
        )

    def _build_final_sse_event(self, plan: AgentPlan, intent: IntentResult) -> str:
        """构造最终的 SSE 事件"""
        profile = intent.profile
        return sse_event("final", {
            "intent": {
                "user_type": profile.user_type, "scene": profile.scene,
                "transport": profile.transport, "budget_level": profile.budget_level,
                "prefer_tags": profile.prefer_tags, "reasoning": intent.reasoning,
            },
            "plan": {
                "itinerary": plan.itinerary,
                "total_cost_estimate": plan.total_cost_estimate,
                "total_duration": plan.total_duration,
                "bookings": plan.bookings,
                "plan_text_for_sharing": plan.plan_text_for_sharing,
                "alternatives": plan.alternatives,
                "decision_notes": plan.decision_notes,
            },
            "debug": {
                "reasoning": plan.reasoning,
                "tool_logs": plan.tool_logs,
                "tool_calls_count": len(plan.tool_logs),
            },
        })

    # ============================================
    # 可视化辅助方法
    # ============================================
    def _tool_icon(self, tool_name: str) -> str:
        return {"search_pois": "🔍", "check_queue": "⏱", "book_table": "📋", "send_plan": "📤"}.get(tool_name, "🔧")

    def _tool_label(self, tool_name: str, params: dict) -> str:
        if tool_name == "search_pois":
            q = params.get("query", "")
            cat = params.get("category", "")
            return f"搜索{cat or '全类'}：{q}"
        elif tool_name == "check_queue":
            name = params.get("restaurant_name", params.get("restaurant_id", ""))
            ps = params.get("party_size", "?")
            return f"查询排队：{name} · {ps}人"
        elif tool_name == "book_table":
            name = params.get("restaurant_name", "")
            ps = params.get("party_size", "?")
            return f"预订餐厅：{name} · {ps}人"
        elif tool_name == "send_plan":
            return f"发送计划给：{params.get('recipient', '好友')}"
        return f"执行：{tool_name}"

    def _params_summary(self, tool_name: str, params: dict) -> str:
        filtered = {k: v for k, v in params.items() if k not in ("user_type", "budget_level", "prefer_tags", "special_requests")}
        return json.dumps(filtered, ensure_ascii=False) if filtered else ""

    def _visual_summary(self, tool_name: str, result: dict) -> str:
        if not result.get("success"):
            return f"❌ {result.get('error', '执行失败')}"
        data = result.get("data", {})
        if tool_name == "search_pois":
            count = data.get("count", len(data.get("pois", [])))
            pois = data.get("pois", [])
            top_names = [p.get("name", "") for p in pois[:3]]
            return f"找到 {count} 个结果：{'、'.join(top_names) if top_names else ''}"
        elif tool_name == "check_queue":
            wait = data.get("wait_minutes", 0)
            if wait >= 60: return f"排队约 {wait} 分钟 ⚠️ 较长"
            elif wait >= 30: return f"排队约 {wait} 分钟 ⚡ 适中"
            return f"排队约 {wait} 分钟 ✅ 较快"
        elif tool_name == "book_table":
            return f"预订成功！确认码: {data.get('confirm_code', '无')}"
        elif tool_name == "send_plan":
            return f"已发送 ✅"
        return json.dumps(data, ensure_ascii=False)[:60]

    def _tool_detail(self, tool_name: str, result: dict) -> str:
        """详细数据用于卡片展开"""
        if not result.get("success"): return ""
        data = result.get("data", {})
        if tool_name == "search_pois":
            pois = data.get("pois", [])[:5]
            return "\n".join([f"{p.get('name')} | ¥{p.get('price_avg')} | {p.get('rating')}分" for p in pois])
        return ""

    def _infer_party_size(self, intent: IntentResult) -> int:
        p = intent.profile
        if p.user_type == "亲子": return 3
        elif p.user_type == "情侣": return 2
        return 1

    def _build_share_text(self, intent: IntentResult, itinerary: list) -> str:
        lines = ["搞定了，下午出发："]
        for it in itinerary:
            lines.append(f"{it['time_range']} → {it['activity']}")
        if itinerary and itinerary[-1].get("poi_name"):
            lines.append(f"\n晚餐计划在「{itinerary[-1]['poi_name']}」")
        lines.append("\n看看这个安排好不好？")
        return "\n".join(lines)

    def _summarize_tool_result(self, call) -> str:
        data = call.result.get("data", {})
        if call.tool_name == "search_pois":
            return f"找到 {data.get('count', 0)} 个候选 POI"
        elif call.tool_name == "check_queue":
            return f"排队 {data.get('wait_minutes', 0)} 分钟 | {data.get('status', '')}"
        elif call.tool_name == "book_table":
            return f"预订 {data.get('confirm_code', '')} | {data.get('status', '')}"
        elif call.tool_name == "send_plan":
            return f"已发送至 {data.get('recipient', '')}"
        return str(data)[:100]


# ============================================
# FallbackPlanner（保持原逻辑，新增决策理由）
# ============================================
class FallbackPlanner:
    """规则引擎兜底"""

    def plan(self, user_input: str, intent: IntentResult) -> AgentPlan:
        from backend.agent.tools import ToolLogger as TL, tool_search_pois as tsp, tool_check_queue as tcq, tool_book_table as tbt

        logger = TL()
        all_pois = get_all_pois(exclude_remote=True)
        profile = intent.profile

        search_result = tsp(
            params={"query": user_input, "user_type": profile.user_type,
                     "budget_level": profile.budget_level, "prefer_tags": profile.prefer_tags},
            poi_data=all_pois,
        )
        logger.log("search_pois", {"query": user_input}, search_result, search_result.get("_duration_ms", 0))

        poi_candidates = search_result.get("data", {}).get("pois", []) if search_result["success"] else []
        scenic = [p for p in poi_candidates if p["category"] == "景点"]
        foods = [p for p in poi_candidates if p["category"] == "美食"]

        itinerary, bookings = [], []
        current_h, current_m = 14, 0
        decision_notes = []

        def add_min(m):
            nonlocal current_h, current_m
            current_m += m
            while current_m >= 60: current_h += 1; current_m -= 60

        is_family = profile.user_type == "亲子"

        if scenic:
            sc = scenic[0]
            st = f"{current_h:02d}:{current_m:02d}"; add_min(60)
            et = f"{current_h:02d}:{current_m:02d}"
            itinerary.append({
                "time_range": f"{st}-{et}", "activity": f"游玩 {sc['name']}",
                "poi_id": sc["id"], "poi_name": sc["name"], "category": "景点",
                "notes": sc.get("description", ""), "price_estimate": sc.get("price_avg", 0),
                "decision_reason": f"匹配亲子标签，评分{sc.get('rating')}分",
                "lat": sc.get("lat"), "lng": sc.get("lng"),
            })
            add_min(15)

        drinks = [f for f in foods if f.get("sub_category") == "饮品"]
        if drinks:
            d = drinks[0]
            st = f"{current_h:02d}:{current_m:02d}"; add_min(30)
            et = f"{current_h:02d}:{current_m:02d}"
            itinerary.append({
                "time_range": f"{st}-{et}", "activity": f"休整 · {d['name']}",
                "poi_id": d["id"], "poi_name": d["name"], "category": "饮品",
                "notes": "休息补充能量", "price_estimate": d.get("price_avg", 25),
                "lat": d.get("lat"), "lng": d.get("lng"),
            })

        restaurants = [f for f in foods if f.get("sub_category") not in ("饮品", "快餐")]
        if restaurants:
            r = restaurants[0]
            party_size = 3 if is_family else 1

            qr = tcq({"restaurant_id": r["id"], "restaurant_name": r["name"], "party_size": party_size, "preferred_time": f"{current_h:02d}:00"})
            logger.log("check_queue", {"restaurant_id": r["id"], "restaurant_name": r["name"], "party_size": party_size}, qr, qr.get("_duration_ms", 0))

            br = tbt({"restaurant_id": r["id"], "restaurant_name": r["name"], "party_size": party_size, "time": f"{current_h:02d}:00"})
            logger.log("book_table", {"restaurant_id": r["id"], "restaurant_name": r["name"], "party_size": party_size}, br, br.get("_duration_ms", 0))

            booking_info = None
            if br["success"]:
                bd = br["data"]
                booking_info = {"booking_id": bd["booking_id"], "confirm_code": bd["confirm_code"], "party_size": party_size, "cost_estimate": r.get("price_avg", 100) * party_size}
                bookings.append(booking_info)

            queue_note = ""
            if qr["success"]:
                wait = qr["data"].get("wait_minutes", 0)
                queue_note = f"排队约{wait}分钟"

            st = f"{current_h:02d}:{current_m:02d}"; add_min(45)
            et = f"{current_h:02d}:{current_m:02d}"
            itinerary.append({
                "time_range": f"{st}-{et}", "activity": f"晚餐 · {r['name']}",
                "poi_id": r["id"], "poi_name": r["name"], "category": "美食",
                "notes": f"{queue_note} | {r.get('description', '')}", "price_estimate": r.get("price_avg", 100) * party_size,
                "booking": booking_info,
                "decision_reason": f"基于实时排队数据({queue_note})选定，评分{r.get('rating')}分",
                "lat": r.get("lat"), "lng": r.get("lng"),
            })

        total_cost = sum(it.get("price_estimate", 0) for it in itinerary)
        duration = f"约{current_h-14}小时{current_m}分钟"
        tool_logs = [{"tool": c.tool_name, "params": c.params, "success": c.success, "duration_ms": c.duration_ms, "summary": self._summarize(c)} for c in logger.calls]
        plan_text = self._share_text(itinerary, is_family)

        decision_notes.append("使用规则模板编排（LLM 未配置）")

        return AgentPlan(
            intent=intent, itinerary=itinerary, total_cost_estimate=total_cost, total_duration=duration,
            bookings=bookings, tool_logs=tool_logs, plan_text_for_sharing=plan_text,
            reasoning=f"🟡 降级模式（规则模板）| 场景：{profile.user_type}，预算 Lv{profile.budget_level} | 工具调用：{len(logger.calls)} 次",
            decision_notes=decision_notes,
        )

    def _share_text(self, itinerary: list, is_family: bool) -> str:
        lines = ["搞定了，下午出发："]
        for it in itinerary:
            lines.append(f"{it['time_range']} → {it['activity']}")
        if itinerary and itinerary[-1].get("booking"):
            lines.append(f"\n晚餐已预订「{itinerary[-1]['poi_name']}」")
        lines.append("\n看看这个安排好不好？")
        return "\n".join(lines)

    def _summarize(self, call) -> str:
        data = call.result.get("data", {})
        if call.tool_name == "search_pois": return f"找到 {data.get('count', 0)} 个候选 POI"
        elif call.tool_name == "check_queue": return f"排队 {data.get('wait_minutes', 0)} 分钟"
        elif call.tool_name == "book_table": return f"预订确认 {data.get('confirm_code', '')}"
        return str(data)[:80]


# ============================================
# 全局单例
# ============================================
_planner = None


def get_planner() -> LLMReActPlanner:
    global _planner
    if _planner is None:
        _planner = LLMReActPlanner()
    return _planner
