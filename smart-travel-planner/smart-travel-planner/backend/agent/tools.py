"""
Mock Tool 层 —— 本地场景短时活动规划与执行 Agent 的工具集

每个 Tool 返回标准结构 {"success": bool, "data": ..., "error": str|None}
包含 Mock API 调用逻辑，展示完整的 Tool 实现与异常处理
"""

import random
import time
import hashlib
from typing import Optional
from dataclasses import dataclass, field


# ============================================
# Tool 调用日志（白盒展示）
# ============================================
@dataclass
class ToolCallLog:
    """单次 Tool 调用记录"""
    tool_name: str
    params: dict
    result: dict
    duration_ms: float
    success: bool


class ToolLogger:
    """管理一连串 Tool 调用的日志记录"""
    def __init__(self):
        self.calls: list[ToolCallLog] = []
        self.total_tools_called = 0
        self.total_duration_ms = 0.0

    def log(self, tool_name: str, params: dict, result: dict, duration_ms: float):
        success = result.get("success", False)
        self.calls.append(ToolCallLog(
            tool_name=tool_name,
            params=params,
            result=result,
            duration_ms=duration_ms,
            success=success,
        ))
        self.total_tools_called += 1
        self.total_duration_ms += duration_ms


# ============================================
# Mock 数据池
# ============================================
MOCK_RESTAURANT_CAPACITY = {
    "f003": {"total_tables": 40, "occupied": 32, "queue_length": 8},   # 巴奴
    "f004": {"total_tables": 50, "occupied": 35, "queue_length": 12},  # 海底捞
    "f006": {"total_tables": 30, "occupied": 18, "queue_length": 4},   # 阿五鲤鱼
    "f009": {"total_tables": 20, "occupied": 14, "queue_length": 6},   # 彼酷哩
    "f011": {"total_tables": 25, "occupied": 20, "queue_length": 10},  # 胖哥俩
    "f012": {"total_tables": 35, "occupied": 20, "queue_length": 5},   # 烤鸭总店
    "f001": {"total_tables": 25, "occupied": 22, "queue_length": 15},  # 合记
    "f002": {"total_tables": 20, "occupied": 16, "queue_length": 7},   # 萧记
    "f005": {"total_tables": 15, "occupied": 10, "queue_length": 3},   # 方中山
    "f007": {"total_tables": 18, "occupied": 10, "queue_length": 2},   # 葛记
}

MOCK_SCENIC_TICKETS = {
    "s001": {"adult_price": 80, "child_price": 40, "remain": 200},     # 少林寺
    "s003": {"adult_price": 0, "child_price": 0, "remain": 50},         # 博物院
    "s004": {"adult_price": 280, "child_price": 180, "remain": 500},    # 方特
    "s005": {"adult_price": 30, "child_price": 15, "remain": 300},      # 动物园
    "s006": {"adult_price": 60, "child_price": 30, "remain": 150},      # 黄河
    "s007": {"adult_price": 0, "child_price": 0, "remain": 999},        # CBD
    "s008": {"adult_price": 20, "child_price": 10, "remain": 200},      # 植物园
    "s009": {"adult_price": 100, "child_price": 60, "remain": 400},     # 电影小镇
}


# ============================================
# Tool 定义
# ============================================

def tool_search_pois(params: dict, poi_data: list) -> dict:
    """
    Tool: 搜索POI
    参数: {query, user_type, budget_level, prefer_tags, category, district}
    返回: {pois: [...], count: int}
    
    模拟场景：调用美团内部 POI 搜索 API
    """
    start = time.time()
    try:
        query = params.get("query", "")
        user_type = params.get("user_type", "")
        budget_level = params.get("budget_level", 2)
        prefer_tags = params.get("prefer_tags", [])
        category = params.get("category")
        district = params.get("district")

        # Mock API 延迟（模拟真实网络调用）
        time.sleep(0.05)

        results = []
        for poi in poi_data:
            # 分类筛选
            if category and poi.category != category and category != "全部":
                continue
            if district and poi.district != district:
                continue
            # 预算筛选
            if budget_level == 1 and poi.price_avg > 50:
                continue
            elif budget_level == 2 and poi.price_avg > 180:
                continue
            # 标签匹配（软偏好：匹配的加分，不匹配的内容也保留）
            # prefer_tags 是偏好表示，不是硬性过滤条件
            poi._prefer_match = False
            if prefer_tags:
                tag_match = any(t in poi.tags for t in prefer_tags)
                name_match = any(t in poi.name for t in prefer_tags) or \
                             any(t in poi.description for t in prefer_tags)
                if tag_match or name_match:
                    poi._prefer_match = True  # 偏好匹配标记

            results.append(poi.to_dict())
            # 将偏好匹配标记附加到结果字典（to_dict 不会包含）
            if hasattr(poi, '_prefer_match'):
                results[-1]['_prefer_match'] = poi._prefer_match

        # 按评分排序（偏好匹配的POI优先）
        results.sort(key=lambda p: (p.get("_prefer_match", False), p.get("rating", 0)), reverse=True)
        # 限制返回数量
        results = results[:10]

        duration = (time.time() - start) * 1000
        return {
            "success": True,
            "data": {"pois": results, "count": len(results)},
            "error": None,
            "_duration_ms": round(duration, 1),
        }

    except Exception as e:
        duration = (time.time() - start) * 1000
        return {
            "success": False,
            "data": None,
            "error": f"POI搜索异常: {str(e)}",
            "_duration_ms": round(duration, 1),
        }


def tool_check_queue(params: dict) -> dict:
    """
    Tool: 查询餐厅排队/空位
    参数: {restaurant_id, restaurant_name, party_size, preferred_time}
    返回: {queue_length, wait_minutes, has_available, available_times}
    
    模拟场景：调用美团排队取号 API，查询实时排队和预订情况
    """
    start = time.time()
    try:
        restaurant_id = params.get("restaurant_id", "")
        party_size = params.get("party_size", 2)
        preferred_time = params.get("preferred_time", "18:00")

        # Mock API 延迟
        time.sleep(0.08)

        capacity = MOCK_RESTAURANT_CAPACITY.get(
            restaurant_id,
            {"total_tables": 30, "occupied": 20, "queue_length": 8},
        )

        # 根据人数和时段计算等待时间
        base_wait = capacity["queue_length"] * 5  # 每桌约5分钟
        if party_size >= 6:
            base_wait += 15  # 大桌更难等
        if preferred_time in ["18:00", "18:30", "19:00"]:
            base_wait += 10  # 高峰期

        has_available = capacity["occupied"] < capacity["total_tables"] * 0.85
        available = capacity["total_tables"] - capacity["occupied"]
        wait_minutes = max(0, base_wait + random.randint(-5, 10))

        # 可预订时段
        available_times = []
        if has_available:
            available_times = [preferred_time,
                               f"{int(preferred_time[:2])+1:02d}:00" if int(preferred_time[:2]) < 21 else "21:00"]

        duration = (time.time() - start) * 1000
        return {
            "success": True,
            "data": {
                "restaurant_id": restaurant_id,
                "party_size": party_size,
                "preferred_time": preferred_time,
                "queue_length": capacity["queue_length"],
                "wait_minutes": wait_minutes,
                "has_available": has_available,
                "available_tables": available,
                "available_times": available_times,
                "status": "可预订" if has_available and wait_minutes < 30 else ("需排队" if wait_minutes < 60 else "排队较长"),
            },
            "error": None,
            "_duration_ms": round(duration, 1),
        }

    except Exception as e:
        duration = (time.time() - start) * 1000
        return {
            "success": False,
            "data": None,
            "error": f"排队查询异常: {str(e)}",
            "_duration_ms": round(duration, 1),
        }


def tool_book_table(params: dict) -> dict:
    """
    Tool: 预订餐厅/下单
    参数: {restaurant_id, restaurant_name, party_size, time, special_requests}
    返回: {booking_id, status, details}
    
    模拟场景：调用美团预订下单 API，生成预订号并返回确认信息
    """
    start = time.time()
    try:
        restaurant_id = params.get("restaurant_id", "")
        restaurant_name = params.get("restaurant_name", "未知餐厅")
        party_size = params.get("party_size", 2)
        booking_time = params.get("time", "18:00")
        special_requests = params.get("special_requests", "")

        # Mock API 延迟
        time.sleep(0.12)

        # 生成Mock预订号
        booking_id = f"MT-{restaurant_id}-{int(time.time()) % 100000:05d}"

        duration = (time.time() - start) * 1000
        return {
            "success": True,
            "data": {
                "booking_id": booking_id,
                "restaurant_name": restaurant_name,
                "party_size": party_size,
                "booking_time": booking_time,
                "special_requests": special_requests,
                "status": "confirmed",
                "message": f"{restaurant_name} {party_size}人位 预订成功",
                "confirm_code": hashlib.md5(booking_id.encode()).hexdigest()[:6].upper(),
            },
            "error": None,
            "_duration_ms": round(duration, 1),
        }

    except Exception as e:
        duration = (time.time() - start) * 1000
        return {
            "success": False,
            "data": None,
            "error": f"预订失败: {str(e)}",
            "_duration_ms": round(duration, 1),
        }


def tool_send_plan(params: dict) -> dict:
    """
    Tool: 发送计划
    参数: {recipient, plan_text, channel}
    返回: {sent, message_id}
    
    模拟场景：调用美团消息/分享 API，将行程计划发送给指定收件人
    """
    start = time.time()
    try:
        recipient = params.get("recipient", "老婆")
        plan_text = params.get("plan_text", "")
        channel = params.get("channel", "sms")

        # Mock API 延迟
        time.sleep(0.06)

        duration = (time.time() - start) * 1000
        return {
            "success": True,
            "data": {
                "message_id": hashlib.md5(f"{recipient}{time.time()}".encode()).hexdigest()[:8],
                "recipient": recipient,
                "channel": channel,
                "sent_at": time.strftime("%H:%M:%S"),
                "preview": plan_text[:100] + "..." if len(plan_text) > 100 else plan_text,
                "status": "delivered",
            },
            "error": None,
            "_duration_ms": round(duration, 1),
        }

    except Exception as e:
        duration = (time.time() - start) * 1000
        return {
            "success": False,
            "data": None,
            "error": f"发送失败: {str(e)}",
            "_duration_ms": round(duration, 1),
        }


# ============================================
# Tool 注册表
# ============================================
TOOL_REGISTRY = {
    "search_pois": {
        "name": "search_pois",
        "description": "搜索符合条件的POI（景点/餐厅），支持分类、预算、标签筛选",
        "params": ["query", "user_type", "budget_level", "prefer_tags", "category", "district"],
        "fn": tool_search_pois,
    },
    "check_queue": {
        "name": "check_queue",
        "description": "查询餐厅实时排队状态和空位情况",
        "params": ["restaurant_id", "restaurant_name", "party_size", "preferred_time"],
        "fn": tool_check_queue,
    },
    "book_table": {
        "name": "book_table",
        "description": "预订餐厅桌位，返回预订确认信息",
        "params": ["restaurant_id", "restaurant_name", "party_size", "time", "special_requests"],
        "fn": tool_book_table,
    },
    "send_plan": {
        "name": "send_plan",
        "description": "将行程计划发送给指定收件人（老婆/朋友）",
        "params": ["recipient", "plan_text", "channel"],
        "fn": tool_send_plan,
    },
}


def get_tool(name: str):
    """获取Tool函数"""
    return TOOL_REGISTRY.get(name, {}).get("fn")
