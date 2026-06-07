"""
Agent 规划与执行模块

核心：
- tools.py:    Mock Tool 定义（搜POI、查位、预订、发计划）
- planner.py:  ReAct 规划器（LLM + Tool 调用链 → 时间轴方案）
- executor.py: 执行引擎（调用 Tools 完成预订/发送）
"""
