# coding=utf-8
"""
AI 客户端模块

V3 GitHub Actions 修复版：
- 不再依赖 LiteLLM，避免间接安装 tiktoken 导致 Actions 失败。
- 使用 OpenAI-compatible Chat Completions 接口直连 DeepSeek / OpenAI 兼容模型。
"""

import os
from typing import Any, Dict, List

import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type


class AIClient:
    """统一的 AI 客户端（OpenAI-compatible API）"""

    def __init__(self, config: Dict[str, Any]):
        self.model = config.get("MODEL", "deepseek/deepseek-chat")
        self.api_key = (
            config.get("API_KEY")
            or os.environ.get("DEEPSEEK_API_KEY", "")
            or os.environ.get("AI_API_KEY", "")
            or os.environ.get("OPENAI_API_KEY", "")
        )
        self.api_base = (config.get("API_BASE") or os.environ.get("AI_API_BASE") or "").rstrip("/")
        self.temperature = config.get("TEMPERATURE", 1.0)
        self.max_tokens = config.get("MAX_TOKENS", 5000)
        self.timeout = int(config.get("TIMEOUT", os.environ.get("AI_TIMEOUT", 120)))
        self.num_retries = int(config.get("NUM_RETRIES", 2))
        self.fallback_models = config.get("FALLBACK_MODELS", []) or []

    def _resolve_api_base(self, model: str) -> str:
        if self.api_base:
            return self.api_base
        if model.startswith("deepseek/"):
            return "https://api.deepseek.com"
        return "https://api.openai.com/v1"

    def _resolve_model_name(self, model: str) -> str:
        # LiteLLM 使用 provider/model；直连官方兼容接口时只需要真实模型名。
        if model.startswith("deepseek/"):
            return model.split("/", 1)[1]
        if model.startswith("openai/"):
            return model.split("/", 1)[1]
        return model

    def _chat_once(self, model: str, messages: List[Dict[str, str]], **kwargs) -> str:
        api_base = self._resolve_api_base(model)
        url = f"{api_base}/chat/completions" if not api_base.endswith("/chat/completions") else api_base
        payload = {
            "model": self._resolve_model_name(model),
            "messages": messages,
            "temperature": kwargs.get("temperature", self.temperature),
        }
        max_tokens = kwargs.get("max_tokens", self.max_tokens)
        if max_tokens and max_tokens > 0:
            payload["max_tokens"] = max_tokens

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        response = requests.post(url, headers=headers, json=payload, timeout=kwargs.get("timeout", self.timeout))
        response.raise_for_status()
        data = response.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        if isinstance(content, list):
            content = "\n".join(
                item.get("text", str(item)) if isinstance(item, dict) else str(item)
                for item in content
            )
        return content or ""

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """调用 AI 模型进行对话。"""
        attempts = max(1, int(kwargs.get("num_retries", self.num_retries)) + 1)

        @retry(
            stop=stop_after_attempt(attempts),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            retry=retry_if_exception_type((requests.RequestException, TimeoutError)),
            reraise=True,
        )
        def call_primary() -> str:
            return self._chat_once(self.model, messages, **kwargs)

        try:
            return call_primary()
        except Exception:
            last_error = None
            for fallback in self.fallback_models:
                try:
                    return self._chat_once(fallback, messages, **kwargs)
                except Exception as exc:  # pragma: no cover - only used when provider fails
                    last_error = exc
            if last_error:
                raise last_error
            raise

    def validate_config(self) -> tuple[bool, str]:
        if not self.model:
            return False, "未配置 AI 模型（model）"
        if not self.api_key:
            return False, "未配置 AI API Key，请在 GitHub Secrets 设置 DEEPSEEK_API_KEY 或 AI_API_KEY"
        return True, ""
