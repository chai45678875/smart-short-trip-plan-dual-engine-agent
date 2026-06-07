"""
LLM API 客户端 - AI 智能调度框架

能力：
- 多模型适配切换（智谱/DeepSeek/本地）
- 免费模型兜底
- 测试连接
- 异步对话
"""

import os
import json
import httpx
from typing import Optional


class LLMClient:
    """统一 LLM 客户端"""

    def __init__(
        self,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        model: Optional[str] = None,
    ):
        from backend.config import LLM_CONFIGS, ACTIVE_LLM

        self.provider = provider or ACTIVE_LLM
        self.cfg = LLM_CONFIGS.get(self.provider, LLM_CONFIGS.get("glm-4-flash"))
        if self.cfg is None:
            # 兜底
            self.cfg = {
                "id": "glm-4-flash",
                "name": "GLM-4-Flash",
                "provider": "zhipu",
                "api_base": "https://open.bigmodel.cn/api/paas/v4",
                "api_key_env": "ZHIPU_API_KEY",
            }

        self.api_key = api_key or os.getenv(self.cfg.get("api_key_env", "ZHIPU_API_KEY"), "")
        self.api_base = (api_base or self.cfg.get("api_base", "")).rstrip("/")
        self.model = model or self.cfg.get("id", "glm-4-flash")

    def is_available(self) -> bool:
        return bool(self.api_key) and bool(self.api_base)

    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str:
        """发送对话请求，返回模型回复文本"""
        if not self.is_available():
            return "[LLM 未配置] 请先设置 API Key"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        body = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        async with httpx.AsyncClient(timeout=45.0) as client:
            try:
                resp = await client.post(
                    f"{self.api_base}/chat/completions",
                    headers=headers,
                    json=body,
                )
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]
            except httpx.HTTPStatusError as e:
                return f"[LLM HTTP错误] {e.response.status_code}: {e.response.text[:200]}"
            except Exception as e:
                return f"[LLM 调用失败] {str(e)}"

    async def test_connection(self) -> dict:
        """测试连接，返回状态字典"""
        if not self.is_available():
            return {"ok": False, "error": "API Key 或 API 地址未配置"}

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": "你好"}],
            "max_tokens": 10,
        }

        async with httpx.AsyncClient(timeout=20.0) as client:
            try:
                resp = await client.post(
                    f"{self.api_base}/chat/completions",
                    headers=headers,
                    json=body,
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"].get("content", "")
                return {
                    "ok": True,
                    "model": self.model,
                    "provider": self.cfg.get("provider", "unknown"),
                    "reply_preview": content[:60],
                }
            except Exception as e:
                return {"ok": False, "error": str(e)}

    def build_messages(self, system_prompt: str, user_message: str) -> list[dict]:
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]


# ============================================
# 单例 + 运行时配置覆盖
# ============================================
_RUNTIME_CONFIG = {
    "provider": None,
    "api_key": None,
    "api_base": None,
    "model": None,
}


def set_llm_runtime_config(provider=None, api_key=None, api_base=None, model=None):
    """运行时覆盖 LLM 配置（由前端 AI 配置面板调用）"""
    if provider is not None:
        _RUNTIME_CONFIG["provider"] = provider
    if api_key is not None:
        _RUNTIME_CONFIG["api_key"] = api_key
    if api_base is not None:
        _RUNTIME_CONFIG["api_base"] = api_base
    if model is not None:
        _RUNTIME_CONFIG["model"] = model


def get_llm_runtime_config() -> dict:
    return _RUNTIME_CONFIG.copy()


def create_llm_client() -> LLMClient:
    """根据运行时配置创建 LLM 客户端"""
    return LLMClient(
        provider=_RUNTIME_CONFIG.get("provider"),
        api_key=_RUNTIME_CONFIG.get("api_key"),
        api_base=_RUNTIME_CONFIG.get("api_base"),
        model=_RUNTIME_CONFIG.get("model"),
    )
