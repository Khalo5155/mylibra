"""角色扮演进程使用的世界模拟器 HTTP 客户端。"""

import asyncio
import os
from typing import Any

import aiohttp
import requests


class WorldSimulatorClientError(RuntimeError):
    pass


def _base_url() -> str:
    return os.getenv("WORLD_SIMULATOR_URL", "http://127.0.0.1:8765").rstrip("/")


def _headers() -> dict[str, str]:
    key = os.getenv("WORLD_SIMULATOR_API_KEY") or os.getenv("LOCAL_API_KEY", "")
    return {"X-API-Key": key} if key else {}


def get_chara_prompt(chara_name: str, timeout: float = 3.0) -> str:
    """同步获取状态提示词，供同步上下文拼接流程调用。"""
    try:
        response = requests.post(
            f"{_base_url()}/prompt_get",
            json={"chara_name": chara_name},
            headers=_headers(),
            timeout=timeout,
        )
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise WorldSimulatorClientError(f"无法连接世界模拟器: {exc}") from exc
    if response.status_code != 200 or data.get("status") != "success":
        raise WorldSimulatorClientError(data.get("error", f"HTTP {response.status_code}"))
    prompt = data.get("prompt")
    if not isinstance(prompt, str):
        raise WorldSimulatorClientError("prompt_get 响应缺少 prompt")
    return prompt


async def perform_chara_action(chara_name: str, action: str, timeout: float = 120.0) -> dict[str, Any]:
    """提交行动；返回 success/refused，通信或服务错误则抛异常。"""
    client_timeout = aiohttp.ClientTimeout(total=timeout, connect=5)
    try:
        async with aiohttp.ClientSession(timeout=client_timeout, headers=_headers()) as session:
            async with session.post(
                f"{_base_url()}/chara_action",
                json={"chara_name": chara_name, "action": action},
            ) as response:
                data = await response.json()
                if response.status != 200 or data.get("status") == "error":
                    raise WorldSimulatorClientError(data.get("error", f"HTTP {response.status}"))
    except WorldSimulatorClientError:
        raise
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
        raise WorldSimulatorClientError(f"世界模拟器请求失败: {exc}") from exc
    if data.get("status") not in {"success", "refused"}:
        raise WorldSimulatorClientError("chara_action 响应包含未知 status")
    return data