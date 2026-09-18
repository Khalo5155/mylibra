"""世界模拟核心与 HTTP 协议测试；不会请求真实 LLM。"""

import asyncio
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer

from world_simulation.world_simulator import (
    World,
    WorldSimulatorService,
    daily_scheduler,
    short_term_scheduler,
)


BASE_STATE = {
    "location": "dormitory",
    "health": 100,
    "mood": 90,
    "inventory": {},
}


class WorldSimulatorTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        data_dir = Path(self.temp_dir.name)
        (data_dir / "agent_act_history").mkdir()
        (data_dir / "rules.txt").write_text("行动必须符合物理规则。", encoding="utf-8")
        fixtures = {
            "locations.json": {
                "locations": {
                    "dormitory": {"weather": "sunny"},
                    "university": {"weather": "cloudy"},
                },
                "edges": {},
            },
            "world_state.json": {"description": "test world"},
            "chara_profiles.json": {
                "profiles": {
                    "Libra": {
                        "last_act_time": "2026-01-01 00:00:00",
                        "last_act": "sleep",
                        "current_state": copy.deepcopy(BASE_STATE),
                    },
                    "Yunru": {
                        "last_act_time": "2026-01-01 00:00:00",
                        "last_act": "study",
                        "current_state": {
                            **copy.deepcopy(BASE_STATE),
                            "location": "university",
                            "mood": 70,
                        },
                    }
                }
            },
        }
        for filename, data in fixtures.items():
            (data_dir / filename).write_text(json.dumps(data), encoding="utf-8")
        self.world = World(data_dir)
        self.world.initialize()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_prompt_does_not_mutate_profile(self):
        before = copy.deepcopy(self.world.chara_profiles)
        prompt = json.loads(self.world.get_chara_prompt("Libra"))
        self.assertEqual("sunny", prompt["current_location_state"]["weather"])
        self.assertEqual(["Libra"], prompt["current_location_state"]["current_characters"])
        self.assertEqual(before, self.world.chara_profiles)

    def test_initialize_rebuilds_and_persists_location_characters(self):
        self.assertEqual(
            ["Libra"],
            self.world.locations["locations"]["dormitory"]["current_characters"],
        )
        self.assertEqual(
            ["Yunru"],
            self.world.locations["locations"]["university"]["current_characters"],
        )
        saved = json.loads((self.world.data_dir / "locations.json").read_text(encoding="utf-8"))
        self.assertEqual(
            ["Libra"], saved["locations"]["dormitory"]["current_characters"]
        )

    def test_action_prompt_contains_all_character_profiles(self):
        prompt = self.world.build_action_prompt("Libra", "和 Yunru 打招呼")
        self.assertIn("全部角色档案", prompt)
        self.assertIn('"Libra"', prompt)
        self.assertIn('"Yunru"', prompt)
        self.assertIn("state_updates", prompt)

    def test_apply_refused_action_persists_actual_result(self):
        result = {
            "status": "refused",
            "reason": "门锁着",
            "actual_result": "尝试开门，但仍留在宿舍。",
            "summary": "仍在宿舍。",
            "new_state": copy.deepcopy(BASE_STATE),
        }
        response = self.world.apply_action_result("Libra", "穿墙出去", result)
        self.assertEqual("refused", response["status"])
        saved = json.loads((self.world.data_dir / "chara_profiles.json").read_text(encoding="utf-8"))
        self.assertEqual("尝试开门，但仍留在宿舍。", saved["profiles"]["Libra"]["last_act"])

    def test_state_patch_keeps_missing_and_ignores_extra_fields(self):
        self.world._get_profile("Libra")["current_state"]["inventory"] = {
            "chocolate": {"quantity": 5, "description": "sweet"}
        }
        result = {
            "status": "success",
            "reason": "",
            "actual_result": "吃了一块巧克力。",
            "summary": "巧克力少了一块。",
            "new_state": {
                "inventory": {
                    "chocolate": {"quantity": 4, "extra_nested": "ignored"},
                    "new_item": {"quantity": 1},
                },
                "extra_top_level": "ignored",
            },
        }
        self.world.apply_action_result("Libra", "吃巧克力", result)
        state = self.world._get_profile("Libra")["current_state"]
        self.assertEqual(4, state["inventory"]["chocolate"]["quantity"])
        self.assertEqual("sweet", state["inventory"]["chocolate"]["description"])
        self.assertEqual(100, state["health"])
        self.assertNotIn("extra_nested", state["inventory"]["chocolate"])
        self.assertNotIn("new_item", state["inventory"])
        self.assertNotIn("extra_top_level", state)

    def test_action_updates_multiple_characters_and_location_presence(self):
        result = {
            "status": "success",
            "reason": "",
            "actual_result": "Libra 来到大学并和 Yunru 交谈。",
            "summary": "两人在大学见面，Yunru 心情变好。",
            "state_updates": {
                "Libra": {"location": "university"},
                "Yunru": {"mood": 85},
            },
        }
        response = self.world.apply_action_result("Libra", "去大学找 Yunru", result)

        self.assertEqual(["Libra", "Yunru"], response["affected_characters"])
        self.assertEqual("university", self.world._get_profile("Libra")["current_state"]["location"])
        self.assertEqual(85, self.world._get_profile("Yunru")["current_state"]["mood"])
        self.assertEqual(
            [], self.world.locations["locations"]["dormitory"]["current_characters"]
        )
        self.assertEqual(
            ["Libra", "Yunru"],
            self.world.locations["locations"]["university"]["current_characters"],
        )
        yunru_prompt = json.loads(self.world.get_chara_prompt("Yunru"))
        self.assertEqual(
            ["Libra", "Yunru"],
            yunru_prompt["current_location_state"]["current_characters"],
        )

        saved_profiles = json.loads(
            (self.world.data_dir / "chara_profiles.json").read_text(encoding="utf-8")
        )
        saved_locations = json.loads(
            (self.world.data_dir / "locations.json").read_text(encoding="utf-8")
        )
        self.assertEqual(85, saved_profiles["profiles"]["Yunru"]["current_state"]["mood"])
        self.assertEqual(
            ["Libra", "Yunru"],
            saved_locations["locations"]["university"]["current_characters"],
        )

    def test_http_protocol_and_auth(self):
        async def scenario():
            app = WorldSimulatorService(self.world, "secret").create_app()
            async with TestClient(TestServer(app)) as client:
                unauthorized = await client.get("/health")
                self.assertEqual(401, unauthorized.status)
                headers = {"X-API-Key": "secret"}
                prompt_response = await client.post(
                    "/prompt_get", json={"chara_name": "Libra"}, headers=headers
                )
                self.assertEqual(200, prompt_response.status)
                self.assertEqual("success", (await prompt_response.json())["status"])

                model_result = {
                    "status": "success",
                    "reason": "",
                    "actual_result": "吃了一块巧克力。",
                    "summary": "心情变好。",
                    "state_updates": {"Libra": {"mood": 95}},
                }
                with patch(
                    "world_simulation.world_simulator.llm_get_pure",
                    return_value=json.dumps(model_result, ensure_ascii=False),
                ):
                    action_response = await client.post(
                        "/chara_action",
                        json={"chara_name": "Libra", "action": "吃巧克力"},
                        headers=headers,
                    )
                data = await action_response.json()
                self.assertEqual(200, action_response.status)
                self.assertEqual("success", data["status"])
                self.assertEqual(95, self.world._get_profile("Libra")["current_state"]["mood"])

        asyncio.run(scenario())

    def test_short_term_scheduler_updates_after_two_hour_wait(self):
        async def scenario():
            service = WorldSimulatorService(self.world)
            sleep_calls = []

            async def fake_sleep(delay):
                sleep_calls.append(delay)
                if len(sleep_calls) > 1:
                    raise asyncio.CancelledError

            model_result = json.dumps({"new_state": {"mood": 80}}, ensure_ascii=False)
            with patch("world_simulation.world_simulator.asyncio.sleep", side_effect=fake_sleep), \
                 patch("world_simulation.world_simulator.random.randint", return_value=1), \
                 patch("world_simulation.world_simulator.llm_get_pure", return_value=model_result):
                with self.assertRaises(asyncio.CancelledError):
                    await short_term_scheduler(service)

            state = self.world._get_profile("Libra")["current_state"]
            self.assertEqual(2 * 60 * 60, sleep_calls[0])
            self.assertEqual(80, state["mood"])
            self.assertEqual(100, state["health"])

        asyncio.run(scenario())

    def test_daily_scheduler_resets_plan_and_updates_weather(self):
        async def scenario():
            service = WorldSimulatorService(self.world)
            state = self.world._get_profile("Libra")["current_state"]
            state["today_plan"] = {"study": {"description": "review"}}
            sleep_calls = []

            async def fake_sleep(delay):
                sleep_calls.append(delay)
                if len(sleep_calls) > 1:
                    raise asyncio.CancelledError

            with patch("world_simulation.world_simulator.asyncio.sleep", side_effect=fake_sleep), \
                 patch("world_simulation.world_simulator.random.randint", return_value=-10), \
                 patch("world_simulation.world_simulator.random.choices", return_value=["rainy"]):
                with self.assertRaises(asyncio.CancelledError):
                    await daily_scheduler(service)

            self.assertTrue(0 < sleep_calls[0] <= 24 * 60 * 60)
            self.assertEqual({}, state["today_plan"])
            self.assertEqual(90, state["health"])
            self.assertEqual(80, state["mood"])
            self.assertEqual(
                "rainy", self.world.locations["locations"]["dormitory"]["weather"]
            )

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()