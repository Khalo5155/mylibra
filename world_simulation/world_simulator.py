"""独立运行的世界模拟服务。

HTTP JSON 协议：GET /health、POST /prompt_get、POST /chara_action。
导入本模块不会加载世界或启动服务，避免角色进程持有第二份状态。
"""

import argparse
import asyncio
import copy
import json
import os
import random
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from aiohttp import web

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORLD_DIR = Path(__file__).resolve().parent

import sys
sys.path.append(str(PROJECT_ROOT))
from LLM_basic import llm_get_pure
from utils.tool_funcs import extract_json


class WorldError(Exception):
    """可安全返回给客户端的世界模拟错误。"""


class World:
    def __init__(self, data_dir: Path = WORLD_DIR):
        self.data_dir = data_dir
        self.locations: dict[str, Any] = {}
        self.world_state: dict[str, Any] = {}
        self.chara_profiles: dict[str, Any] = {}
        self.chara_history: dict[str, list[dict[str, Any]]] = {}
        self.rules = ""

    def initialize(self) -> None:
        """加载唯一的权威状态；加载失败时拒绝启动。"""
        self.locations = self._read_json("locations.json")
        self.world_state = self._read_json("world_state.json")
        self.chara_profiles = self._read_json("chara_profiles.json")
        rules_path = self.data_dir / "rules.txt"
        self.rules = rules_path.read_text(encoding="utf-8") if rules_path.exists() else ""

        profiles = self.chara_profiles.get("profiles")
        if not isinstance(profiles, dict):
            raise WorldError("chara_profiles.json 缺少 profiles 对象")
        history_dir = self.data_dir / "agent_act_history"
        history_dir.mkdir(parents=True, exist_ok=True)
        for chara_name in profiles:
            path = history_dir / f"{chara_name}_history.json"
            history = self._read_json_path(path) if path.exists() else []
            if not isinstance(history, list):
                raise WorldError(f"{chara_name} 的行动历史不是列表")
            self.chara_history[chara_name] = history

        # 地点中的在场角色是由角色 location 派生的索引，不信任磁盘里的旧值。
        if self.sync_location_characters():
            self._atomic_write_json(self.data_dir / "locations.json", self.locations)

    def _read_json(self, filename: str) -> Any:
        return self._read_json_path(self.data_dir / filename)

    @staticmethod
    def _read_json_path(path: Path) -> Any:
        try:
            with path.open("r", encoding="utf-8") as file:
                return json.load(file)
        except (OSError, json.JSONDecodeError) as exc:
            raise WorldError(f"无法读取 {path}: {exc}") from exc

    @staticmethod
    def _atomic_write_json(path: Path, data: Any) -> None:
        """先写临时文件再替换，避免进程中断留下半个 JSON。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_name = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp"
            ) as temp_file:
                json.dump(data, temp_file, ensure_ascii=False, indent=4)
                temp_file.flush()
                os.fsync(temp_file.fileno())
                temp_name = temp_file.name
            os.replace(temp_name, path)
        finally:
            if temp_name and os.path.exists(temp_name):
                os.unlink(temp_name)

    def persist_character(self, chara_name: str) -> None:
        self._atomic_write_json(self.data_dir / "chara_profiles.json", self.chara_profiles)
        self._atomic_write_json(self.data_dir / "locations.json", self.locations)
        self._atomic_write_json(
            self.data_dir / "agent_act_history" / f"{chara_name}_history.json",
            self.chara_history[chara_name],
        )

    def sync_location_characters(self) -> bool:
        """用所有角色的 location 重建每个地图地点的当前在场角色列表。"""
        locations = self.locations.get("locations")
        profiles = self.chara_profiles.get("profiles")
        if not isinstance(locations, dict):
            raise WorldError("locations.json 缺少 locations 对象")
        if not isinstance(profiles, dict):
            raise WorldError("chara_profiles.json 缺少 profiles 对象")

        characters_by_location: dict[str, list[str]] = {name: [] for name in locations}
        for chara_name, profile in profiles.items():
            if not isinstance(profile, dict):
                continue
            state = profile.get("current_state")
            location_name = state.get("location") if isinstance(state, dict) else None
            # 角色可能正在 edge 上，或处于尚未录入地图的新地点；此时不归入地图节点。
            if location_name in characters_by_location:
                characters_by_location[location_name].append(chara_name)

        changed = False
        for location_name, location in locations.items():
            if not isinstance(location, dict):
                continue
            current_characters = characters_by_location[location_name]
            if location.get("current_characters") != current_characters:
                location["current_characters"] = current_characters
                changed = True
        return changed

    def _get_profile(self, chara_name: str) -> dict[str, Any]:
        profile = self.chara_profiles.get("profiles", {}).get(chara_name)
        if not isinstance(profile, dict):
            raise WorldError(f"角色不存在: {chara_name}")
        return profile

    def get_chara_prompt(self, chara_name: str) -> str:
        profile = self._get_profile(chara_name)
        state = copy.deepcopy(profile.get("current_state", {}))
        location_name = state.get("location") if isinstance(state, dict) else None
        prompt_data = {
            "current_state": state,
            "current_location_state": copy.deepcopy(
                self.locations.get("locations", {}).get(location_name)
            ),
            # "recent_actions": copy.deepcopy(self.chara_history.get(chara_name, [])[-5:]),
        }
        return json.dumps(prompt_data, ensure_ascii=False, indent=2)

    def build_action_prompt(self, chara_name: str, action: str) -> str:
        self._get_profile(chara_name)
        return f"""
你是世界模拟器的行动裁决模块。请根据既有世界信息裁决角色提出的行动，不得无条件迎合角色。
返回且仅返回严格 JSON：
{{"status":"success 或 refused","reason":"拒绝理由，成功时为空","actual_result":"实际发生的结果","summary":"所有状态变化的简述","state_updates":{{"受影响的角色名":{{仅包含该角色需要更新的 current_state 字段}}}}}}
规则：
1. 可行则 success；受物理条件、地点、持有物、角色状态或世界规则限制则 refused。
2. 即使拒绝，尝试也可能产生合理后果；写入 actual_result 和 state_updates。无状态后果则 state_updates 返回空对象。
3. 必须考虑行动对所有在场角色的影响。若发起者的行动改变了其他角色的状态，也要在 state_updates 中以对应角色名给出补丁。
4. state_updates 中每个值都是对该角色 current_state 的更新补丁，只返回发生变化的已有字段；未返回的字段自动保持原值。
5. 不得虚构角色名，不得新增原状态不存在的字段，也不得修改 current_state 之外的角色档案字段。
6. health、mood 若返回，必须为 0 到 100 的数字。

世界规则：{self.rules}
世界状态：{json.dumps(self.world_state, ensure_ascii=False)}
地点数据：{json.dumps(self.locations, ensure_ascii=False)}
全部角色档案：{json.dumps(self.chara_profiles, ensure_ascii=False)}
行动发起者：{chara_name}
角色请求的行动：{action}
        """.strip()

    def apply_action_result(self, chara_name: str, action: str, result: dict[str, Any]) -> dict[str, Any]:
        status = result.get("status")
        if status not in {"success", "refused"}:
            raise WorldError("推演结果的 status 必须是 success 或 refused")
        self._get_profile(chara_name)
        state_updates = result.get("state_updates")
        if state_updates is None and isinstance(result.get("new_state"), dict):
            # 兼容旧裁决结果及尚未更新的调用方。
            state_updates = {chara_name: result["new_state"]}
        if not isinstance(state_updates, dict):
            raise WorldError("推演结果缺少 state_updates 更新对象")

        merged_states: dict[str, dict[str, Any]] = {}
        for affected_name, state_patch in state_updates.items():
            if affected_name not in self.chara_profiles.get("profiles", {}):
                continue
            if not isinstance(state_patch, dict):
                raise WorldError(f"state_updates.{affected_name} 必须是对象")
            old_state = self._get_profile(affected_name).get("current_state")
            if not isinstance(old_state, dict):
                raise WorldError(f"{affected_name} 的 current_state 不是对象")
            merged_state = self._merge_existing_fields(old_state, state_patch)
            for field_name in ("health", "mood"):
                value = merged_state.get(field_name)
                if value is not None and (
                    not isinstance(value, (int, float)) or isinstance(value, bool)
                ):
                    raise WorldError(f"state_updates.{affected_name}.{field_name} 必须是数字")
                if value is not None:
                    merged_state[field_name] = max(0, min(100, value))
            merged_states[affected_name] = merged_state

        for field_name in ("actual_result", "summary"):
            if not isinstance(result.get(field_name), str) or not result[field_name].strip():
                raise WorldError(f"推演结果缺少 {field_name}")
        if status == "refused" and not str(result.get("reason", "")).strip():
            raise WorldError("拒绝行动时必须提供 reason")

        now = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        profile = self._get_profile(chara_name)
        for affected_name, merged_state in merged_states.items():
            self._get_profile(affected_name)["current_state"] = merged_state
        profile["last_act_time"] = now
        profile["last_act"] = result["actual_result"]
        self.sync_location_characters()
        history_item = {
            "time": now,
            "requested_action": action,
            "status": status,
            "reason": str(result.get("reason", "")),
            "actual_result": result["actual_result"],
            "summary": result["summary"],
            "affected_characters": list(merged_states),
        }
        self.chara_history[chara_name].append(history_item)
        self.persist_character(chara_name)
        return history_item

    @classmethod
    def _merge_existing_fields(cls, original: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
        """递归合并补丁；只允许修改 original 已存在的键。"""
        merged = copy.deepcopy(original)
        for key, patch_value in patch.items():
            if key not in original:
                continue
            original_value = original[key]
            if isinstance(original_value, dict) and isinstance(patch_value, dict):
                merged[key] = cls._merge_existing_fields(original_value, patch_value)
            else:
                merged[key] = copy.deepcopy(patch_value)
        return merged


class WorldSimulatorService:
    def __init__(self, world: World, api_key: str = ""):
        self.world = world
        self.api_key = api_key
        self.action_lock = asyncio.Lock()

    @web.middleware
    async def auth_middleware(self, request: web.Request, handler):
        if self.api_key and request.headers.get("X-API-Key") != self.api_key:
            return web.json_response({"status": "error", "error": "unauthorized"}, status=401)
        return await handler(request)

    async def health(self, _request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    @staticmethod
    async def _json_body(request: web.Request) -> dict[str, Any]:
        try:
            body = await request.json()
        except (json.JSONDecodeError, web.HTTPBadRequest) as exc:
            raise WorldError("请求体必须是 JSON 对象") from exc
        if not isinstance(body, dict):
            raise WorldError("请求体必须是 JSON 对象")
        return body

    async def prompt_get(self, request: web.Request) -> web.Response:
        try:
            body = await self._json_body(request)
            chara_name = body.get("chara_name")
            if not isinstance(chara_name, str) or not chara_name.strip():
                raise WorldError("chara_name 不能为空")
            return web.json_response({
                "status": "success",
                "chara_name": chara_name,
                "prompt": self.world.get_chara_prompt(chara_name),
            })
        except WorldError as exc:
            return web.json_response({"status": "error", "error": str(exc)}, status=400)

    async def chara_action(self, request: web.Request) -> web.Response:
        try:
            body = await self._json_body(request)
            chara_name, action = body.get("chara_name"), body.get("action")
            if not isinstance(chara_name, str) or not chara_name.strip():
                raise WorldError("chara_name 不能为空")
            if not isinstance(action, str) or not action.strip():
                raise WorldError("action 不能为空")
            if len(action) > 2000:
                raise WorldError("action 不能超过 2000 个字符")

            async with self.action_lock:
                prompt = self.world.build_action_prompt(chara_name, action.strip())
                raw_result = await asyncio.to_thread(
                    llm_get_pure, [{"role": "system", "content": prompt}], "doubao"
                )
                result = extract_json(raw_result)
                if not isinstance(result, dict):
                    raise WorldError("行动推演模型未返回有效 JSON")
                response = self.world.apply_action_result(chara_name, action.strip(), result)
            return web.json_response(response)
        except WorldError as exc:
            return web.json_response({"status": "error", "error": str(exc)}, status=400)
        except Exception as exc:
            print(f"chara_action internal error: {exc}")
            return web.json_response({"status": "error", "error": "世界模拟器内部错误"}, status=500)

    def create_app(self) -> web.Application:
        app = web.Application(middlewares=[self.auth_middleware], client_max_size=32 * 1024)
        app.add_routes([
            web.get("/health", self.health),
            web.post("/prompt_get", self.prompt_get),
            web.post("/chara_action", self.chara_action),
        ])
        app.cleanup_ctx.append(self._scheduler_context)
        return app

    async def _scheduler_context(self, _app: web.Application):
        tasks = [
            asyncio.create_task(short_term_scheduler(self), name="world-short-term-scheduler"),
            asyncio.create_task(daily_scheduler(self), name="world-daily-scheduler"),
        ]
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


async def short_term_scheduler(service: WorldSimulatorService) -> None:
    """每隔两小时小幅扰动角色状态，并推演上次行动以来的状态变化。"""
    while True:
        await asyncio.sleep(2 * 60 * 60)
        try:
            async with service.action_lock:
                profiles = service.world.chara_profiles.get("profiles", {})
                for chara_name, profile in profiles.items():
                    try:
                        state = profile.get("current_state")
                        if not isinstance(state, dict):
                            continue

                        # 小幅自然扰动；其他状态字段由下面的 LLM 推演决定。
                        for field_name in ("health", "mood"):
                            value = state.get(field_name)
                            if isinstance(value, (int, float)) and not isinstance(value, bool):
                                state[field_name] = max(0, min(100, value + random.randint(-3, 3)))

                        now = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                        prompt = f"""
你是世界模拟器的定时状态推演模块。请推演角色从上一次行动至今，各项已有状态字段产生的自然变化。
返回且仅返回严格 JSON，格式为：{{"new_state":{{仅包含需要更新的已有状态字段}}}}。
new_state 是补丁：没变化的字段不要返回，不得新增原状态中不存在的字段。

世界规则：{service.world.rules}
世界状态：{json.dumps(service.world.world_state, ensure_ascii=False)}
地点数据：{json.dumps(service.world.locations, ensure_ascii=False)}
角色：{chara_name}
上一次行动时间：{profile.get("last_act_time")}
上一次行动：{profile.get("last_act")}
当前时间：{now}
当前状态：{json.dumps(state, ensure_ascii=False)}
""".strip()
                        raw_result = await asyncio.to_thread(
                            llm_get_pure, [{"role": "system", "content": prompt}], "doubao"
                        )
                        result = extract_json(raw_result)
                        state_patch = result.get("new_state") if isinstance(result, dict) else None
                        if isinstance(state_patch, dict):
                            profile["current_state"] = service.world._merge_existing_fields(
                                state, state_patch
                            )
                    except Exception as exc:
                        print(f"short-term scheduler failed for {chara_name}: {exc}")

                service.world._atomic_write_json(
                    service.world.data_dir / "chara_profiles.json",
                    service.world.chara_profiles,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"short-term scheduler error: {exc}")


async def daily_scheduler(service: WorldSimulatorService) -> None:
    """每天零点重置日计划、较大幅扰动角色状态并更新全部地点天气。"""
    weather_list = ["sunny", "rainy", "cloudy", "stormy", "snowy", "foggy"]
    weather_weights = [0.3, 0.2, 0.2, 0.1, 0.1, 0.1]

    while True:
        now = datetime.now()
        next_midnight = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        await asyncio.sleep(max(0, (next_midnight - now).total_seconds()))
        try:
            async with service.action_lock:
                for profile in service.world.chara_profiles.get("profiles", {}).values():
                    state = profile.get("current_state")
                    if not isinstance(state, dict):
                        continue
                    if "today_plan" in state:
                        state["today_plan"] = {}
                    for field_name in ("health", "mood"):
                        value = state.get(field_name)
                        if isinstance(value, (int, float)) and not isinstance(value, bool):
                            state[field_name] = max(0, min(100, value + random.randint(-15, 15)))

                for location in service.world.locations.get("locations", {}).values():
                    if isinstance(location, dict):
                        location["weather"] = random.choices(
                            weather_list, weights=weather_weights, k=1
                        )[0]

                service.world._atomic_write_json(
                    service.world.data_dir / "chara_profiles.json",
                    service.world.chara_profiles,
                )
                service.world._atomic_write_json(
                    service.world.data_dir / "locations.json",
                    service.world.locations,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"daily scheduler error: {exc}")


def create_app(data_dir: Path = WORLD_DIR, api_key: Optional[str] = None) -> web.Application:
    world = World(data_dir)
    world.initialize()
    if api_key is None:
        api_key = os.getenv("WORLD_SIMULATOR_API_KEY") or os.getenv("LOCAL_API_KEY", "")
    return WorldSimulatorService(world, api_key).create_app()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the mylibra world simulator service")
    parser.add_argument("--host", default=os.getenv("WORLD_SIMULATOR_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("WORLD_SIMULATOR_PORT", "8765")))
    args = parser.parse_args()
    print(f"world_simulator listening on http://{args.host}:{args.port}")
    web.run_app(create_app(), host=args.host, port=args.port)


def test():
    world = World(WORLD_DIR)
    world.initialize()
    print(world.get_chara_prompt("Libra"))

if __name__ == "__main__":
    # test()
    main()