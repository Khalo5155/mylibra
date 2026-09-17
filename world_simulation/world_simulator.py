'''
    负责运行模拟世界。包含交互式和自动化两部分。
'''
import os
import json
import sys
import random
import time

from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))  # 把项目根目录加入Python路径
from LLM_basic import llm_get_pure

from utils.tool_funcs import extract_json

chara_history_dir = "./world_simulation/agent_act_history/"

class World:
    def __init__(self):
        self.locations = {} # 世界地图
        self.world_state = {} # 大世界设定
        self.chara_profiles = {} # 角色档案
        self.chara_history = {} # 角色行动历史

    def initialize(self):
        # 从文件中读取
        print("="*50+"\nworld_simulator: 正在读取世界...\n"+"="*50)
        try:
            # 读取world_simulation/locations.json
            with open('./world_simulation/locations.json', 'r', encoding='utf-8') as f:
                self.locations = json.load(f)
            
            # 读取world_state.json
            with open('./world_simulation/world_state.json', 'r', encoding='utf-8') as f:
                self.world_state = json.load(f)

            # 读取chara_profiles.json
            with open('./world_simulation/chara_profiles.json', 'r', encoding='utf-8') as f:
                self.chara_profiles = json.load(f)

            # 读取角色行动历史
            for chara_name in self.chara_profiles['profiles'].keys():
                history_path = os.path.join(chara_history_dir, f"{chara_name}_history.json")
                if os.path.exists(history_path):
                    with open(history_path, 'r', encoding='utf-8') as f:
                        self.chara_history[chara_name] = json.load(f)
                else:
                    self.chara_history[chara_name] = []
        
        except Exception as e:
            print(f"Error on initializing world: {e}")
            return False
        print("="*50+"\nworld_simulator: 读取世界完成！\n"+"="*50)

    def write_to_file(self):
        # 将变量内容写回json
        try:
            # 写回 locations.json
            with open('./world_simulation/locations.json', 'w', encoding='utf-8') as f:
                json.dump(self.locations, f, ensure_ascii=False, indent=4)

            # 写回 world_state.json
            with open('./world_simulation/world_state.json', 'w', encoding='utf-8') as f:
                json.dump(self.world_state, f, ensure_ascii=False, indent=4)

            # 写回 chara_profiles.json
            with open('./world_simulation/chara_profiles.json', 'w', encoding='utf-8') as f:
                json.dump(self.chara_profiles, f, ensure_ascii=False, indent=4)

            # 写回角色行动历史
            for chara_name, history in self.chara_history.items():
                history_path = os.path.join(chara_history_dir, f"{chara_name}_history.json")
                with open(history_path, 'w', encoding='utf-8') as f:
                    json.dump(history, f, ensure_ascii=False, indent=4)

            print("=" * 50 + "\nworld_simulator: 世界状态已保存！\n" + "=" * 50)
            return True
        except Exception as e:
            print(f"Error on writing world: {e}")
            return False



# 天气更新：更新各个location的天气状态
weather_list = ["sunny", "rainy", "cloudy", "stormy", "snowy", "foggy"]
weather_distribution = [0.3, 0.2, 0.2, 0.1, 0.1, 0.1]  # 对应的概率分布
def update_weather(world):
    for location in world.locations['locations'].values():
        location['weather'] = random.choices(weather_list, weights=weather_distribution)[0]
    # print([f"{loc['weather']}" for loc in world.locations['locations'].values()])


# Agent 状态更新
# 进行一次agent行动（通过文字描述，LLM实现具体修改）
def agent_action(world, chara_name:str, action:str):
    chara_profile = world.chara_profiles['profiles'][chara_name]
    # print(chara_profile)
    # 打包json发给llm
    result = llm_get_pure([{'role': 'system', 'content': f'当前角色的状态json如下：{str(chara_profile["current_state"])}。请根据Action内容描述：{action}，推测当前角色经过action之后的各项状态，以相同的json格式返回。'}], "doubao")
    # print(result)
    # 解析llm返回的json
    new_profile = extract_json(result)
    # 更新chara_profile
    if new_profile:
        chara_profile['current_state'] = new_profile

        chara_profile['last_act_time'] = time.strftime("%Y-%m-%d, %H:%M", time.localtime())
        chara_profile['last_act'] = action

        world.chara_profiles['profiles'][chara_name].update(chara_profile)
        
        print(chara_profile)
# 时钟行动
def agent_action_clock(world, chara_name:str, timestr:str):
    chara_profile = world.chara_profiles['profiles'][chara_name]
    # 打包json发给llm
    result = llm_get_pure([{'role': 'system', 'content': f'当前角色的状态json如下：{str(chara_profile["current_state"])}。上一次行动时间：{chara_profile["last_act_time"]}。请根据时间点：{timestr}，推测当前角色在该时间点的各项状态，以相同的json格式返回。在返回的json中新增一个act_content字段，描述角色的本次行动。'}], "doubao")
    # 解析llm返回的json
    new_profile = extract_json(result)
    # 更新chara_profile
    if new_profile:
        chara_profile['last_act_time'] = timestr
        chara_profile['last_act'] = new_profile.get('act_content', None)

        new_profile.pop("act_content", None)
        chara_profile['current_state'] = new_profile

        world.chara_profiles['profiles'][chara_name].update(chara_profile)
# 每日24点自动更新
def update_agent_states(world):
    for agent in world.chara_profiles['profiles'].values():
        # 随机扰动health和mood
        agent['current_state']['health'] = max(0, min(100, agent['current_state']['health'] + random.randint(-5, 5)))
        agent['current_state']['mood'] = max(0, min(100, agent['current_state']['mood'] + random.randint(-5, 5)))
        # 根据当日行动更新状态
        pass
        # 清空today_plan
        agent['current_state']['today_plan'] = {}






# 测试
def test():
    world = World()
    world.initialize()
    update_weather(world)
    update_agent_states(world)
    agent_action(world, "Libra", "团建出去吃饭")
    agent_action_clock(world, "Libra", time.strftime("%Y-%m-%d, %H:%M", time.localtime()))


if __name__ == "__main__":
    test()