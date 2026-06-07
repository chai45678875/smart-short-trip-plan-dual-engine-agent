"""
系统配置 - AI智能配置框架
多模型适配 + 免费兜底 + 本地私有化LLM预留 + 多档位套餐
"""
import os

# ============================================
# LLM 模型库（多模型适配）
# ============================================
LLM_MODELS = [
    # 免费兜底（永久保留）
    {"id": "glm-4-flash", "name": "GLM-4-Flash（永久免费）", "provider": "zhipu", "tier": "free", "api_base": "https://open.bigmodel.cn/api/paas/v4", "api_key_env": "ZHIPU_API_KEY"},
    # 标准版
    {"id": "glm-4-air",   "name": "GLM-4-Air（推荐，输出稳定）", "provider": "zhipu", "tier": "standard", "api_base": "https://open.bigmodel.cn/api/paas/v4", "api_key_env": "ZHIPU_API_KEY"},
    {"id": "glm-4",       "name": "GLM-4（旗舰）", "provider": "zhipu", "tier": "pro", "api_base": "https://open.bigmodel.cn/api/paas/v4", "api_key_env": "ZHIPU_API_KEY"},
    {"id": "deepseek-chat","name": "DeepSeek-V3", "provider": "deepseek", "tier": "standard", "api_base": "https://api.deepseek.com/v1", "api_key_env": "DEEPSEEK_API_KEY"},
    # 私有化预留（本地/自托管）
    {"id": "local",       "name": "本地私有化 LLM", "provider": "local", "tier": "custom", "api_base": "http://localhost:8000/v1", "api_key_env": "LOCAL_API_KEY"},
]

# 模型ID -> 配置映射
LLM_CONFIGS = {m["id"]: m for m in LLM_MODELS}

# 当前使用的模型（可被用户配置覆盖）
ACTIVE_LLM = os.getenv("ACTIVE_LLM", "glm-4-flash")

# ============================================
# 套餐档位
# ============================================
PACKAGES = [
    {"id": "free",     "name": "免费体验版", "desc": "使用 GLM-4-Flash 永久免费模型，满足基础对话与规划需求",      "models": ["glm-4-flash"]},
    {"id": "standard", "name": "标准版",     "desc": "GLM-4-Air / DeepSeek-V3，输出稳定，适合日常使用",            "models": ["glm-4-air", "deepseek-chat"]},
    {"id": "pro",      "name": "专业版",     "desc": "GLM-4 旗舰模型 + 优先响应，适合高质量深度规划",              "models": ["glm-4", "glm-4-air", "deepseek-chat"]},
    {"id": "custom",   "name": "私有化版",   "desc": "接入本地私有化 LLM，支持微调与二次迭代，数据完全自主可控", "models": ["local"]},
]

# ============================================
# 服务配置
# ============================================
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 8000

# ============================================
# 推荐策略配置
# ============================================
MAX_POI_PER_ROUTE = 4       # 单条路线最多串联 POI 数（景点+餐饮），短时场景控制在4个以内
ROUTE_COUNT = 3              # 生成方案套数
DEFAULT_CITY = "郑州"
DEFAULT_CENTER = (34.7466, 113.6253)

# 就近匹配阈值（公里）：景点和餐饮超过此距离认为不"就近"
NEARBY_FOOD_KM = 3.0
