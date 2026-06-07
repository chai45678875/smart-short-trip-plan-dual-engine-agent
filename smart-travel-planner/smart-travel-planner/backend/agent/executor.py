"""
执行引擎 —— 负责按方案调用 Tools 完成预订/发送等操作

将 Planner 生成的方案中的预订项逐一执行
"""

import time
from typing import Optional

from backend.agent.tools import (
    ToolLogger,
    tool_book_table,
    tool_send_plan,
)


class AgentExecutor:
    """
    执行引擎
    
    职责：
    1. 接收 AgentPlan → 提取需要执行的预订项
    2. 逐项调用 book_table / send_plan
    3. 返回执行结果 + 日志
    """

    def __init__(self):
        self.logger = ToolLogger()

    def reset(self):
        self.logger = ToolLogger()

    def execute(self, plan, send_to: str = None) -> dict:
        """
        执行方案中的所有预订/发送动作
        
        返回：
        {
            "executions": [...],  # 每步执行结果
            "all_success": bool,
            "sent_result": {...},  # 发送结果（如果执行了发送）
        }
        """
        self.reset()
        executions = []
        all_success = True
        sent_result = None

        # Step 1: 执行所有预订
        for it in plan.itinerary:
            if not it.get("booking"):
                continue

            booking_info = it["booking"]
            result = tool_book_table({
                "restaurant_id": it["poi_id"],
                "restaurant_name": it["poi_name"],
                "party_size": booking_info.get("party_size", 2),
                "time": booking_info.get("time", "18:00"),
                "special_requests": it.get("notes", ""),
            })

            self.logger.log("book_table", {
                "restaurant_id": it["poi_id"],
                "restaurant_name": it["poi_name"],
                "party_size": booking_info.get("party_size", 2),
                "time": booking_info.get("time", "18:00"),
            }, result, result.get("_duration_ms", 0))

            exec_record = {
                "type": "book_table",
                "item": it["activity"],
                "restaurant": it["poi_name"],
                "success": result["success"],
                "result": result.get("data"),
                "error": result.get("error"),
            }
            executions.append(exec_record)

            if not result["success"]:
                all_success = False
                # 尝试降级：如果预订失败，保留为通用推荐
                exec_record["fallback"] = f"预订失败，已降级为直接前往 {it['poi_name']}"

        # Step 2: 智能推断发送对象
        recipient = send_to
        if not recipient:
            user_type = str(plan.intent.profile.user_type)
            if "亲子" in user_type or "family" in user_type.lower():
                recipient = "老婆"
            elif "情侣" in user_type or "couple" in user_type.lower():
                recipient = "女朋友"
            elif "朋友" in user_type or "friend" in user_type.lower():
                recipient = "小张"
            else:
                recipient = "家人"

        send_result = tool_send_plan({
            "recipient": recipient,
            "plan_text": plan.plan_text_for_sharing,
            "channel": "sms",
        })

        self.logger.log("send_plan", {
            "recipient": recipient,
            "channel": "sms",
        }, send_result, send_result.get("_duration_ms", 0))

        sent_result = {
            "success": send_result["success"],
            "data": send_result.get("data"),
            "error": send_result.get("error"),
        }
        executions.append({
            "type": "send_plan",
            "item": f"发送计划给 {recipient}",
            "success": send_result["success"],
            "result": send_result.get("data"),
            "error": send_result.get("error"),
        })

        if not send_result["success"]:
            all_success = False

        # Step 3: 汇总日志
        tool_logs = [{
            "tool": c.tool_name,
            "params": c.params,
            "success": c.success,
            "duration_ms": c.duration_ms,
            "result_summary": self._summarize_result(c),
        } for c in self.logger.calls]

        return {
            "executions": executions,
            "all_success": all_success,
            "sent_result": sent_result,
            "tool_logs_exec": tool_logs,
        }

    def _summarize_result(self, call) -> str:
        from backend.agent.tools import ToolCallLog
        data = call.result.get("data", {})
        if call.tool_name == "book_table":
            return f"预订 {data.get('confirm_code', '')} | {data.get('status', '')}"
        elif call.tool_name == "send_plan":
            return f"已发送至 {data.get('recipient', '')} via {data.get('channel', '')}"
        return str(data)[:80]


# 全局单例
_executor = None


def get_executor() -> AgentExecutor:
    global _executor
    if _executor is None:
        _executor = AgentExecutor()
    return _executor
