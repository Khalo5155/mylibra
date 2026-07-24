'''
    负责运行模拟世界。包含交互式和自动化两部分。
'''
import os
import json
import sys
import random

# from pathlib import Path
# sys.path.append(str(Path(__file__).parent.parent))  # 把项目根目录加入Python路径
# from LLM_basic import llm_get_pure


class World:
    def __init__(self):
        self.locations = {}
        self.world_state = {}
        self.chara_profiles = {}

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
        except Exception as e:
            print(f"Error on initializing world: {e}")
            return False
        print("="*50+"\nworld_simulator: 读取世界完成！\n"+"="*50)


# 天气更新：更新各个location的天气状态
weather_list = ["sunny", "rainy", "cloudy", "stormy", "snowy", "foggy"]
weather_distribution = [0.3, 0.2, 0.2, 0.1, 0.1, 0.1]  # 对应的概率分布
def update_weather(world):
    for location in world.locations['locations'].values():
        location['weather'] = random.choices(weather_list, weights=weather_distribution)[0]
    # print([f"{loc['weather']}" for loc in world.locations['locations'].values()])


# Agent 状态更新：对health和mood施加随机扰动
def update_agent_states(world):
    for agent in world.chara_profiles['characters'].values():
        # 随机扰动health和mood
        agent['health'] = max(0, min(100, agent['health'] + random.randint(-5, 5)))
        agent['mood'] = max(0, min(100, agent['mood'] + random.randint(-5, 5)))


# 一般修改接口
def update_term(world, term_type, term_path, new_value):
    pass
    try:
        if term_type == 'location':
            world.locations['locations'][term_path] = new_value
        elif term_type == 'world_state':
            world.world_state[term_path] = new_value
        elif term_type == 'character':
            world.chara_profiles['characters'][term_path] = new_value
        else:
            print(f"Unknown term_type: {term_type}")
            return False
        return True
    except Exception as e:
        print(f"Error on update_term: {e}")
        return False





# 测试
def test():
    world = World()
    world.initialize()
    update_weather(world)
    update_agent_states(world)


if __name__ == "__main__":
    test()