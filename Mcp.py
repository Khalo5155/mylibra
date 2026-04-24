from dataclasses import dataclass, field
from typing import Dict, Any, Optional
import re
import json
import demjson3
import time
import asyncio
import websockets
from datetime import datetime, timedelta

import Vdb

# 全局变量引入
from configs import global_config
API_KEY = global_config.API_KEY
IDENTITY = global_config.IDENTITY
# SELF_SERVER_URL = global_config.SELF_SERVER_URL
CHAT_SERVER_URL = global_config.CHAT_SERVER_URL
CHAT_SERVER_URL_LOCAL = global_config.CHAT_SERVER_URL_LOCAL
# 日记本vdb路径
VDB_DIARY_PATH = global_config.VDB_DIARY_DIR
# 引入AES加密器
cipher_tool = global_config.cipher_tool

# 初始化日记本vdb service
rag_service_diary = Vdb.RAGService(_vdb_path=VDB_DIARY_PATH)



# ====================== 格式判断 ======================
def is_tool_call(llm_output: str) -> tuple[bool, dict]:
    """
    判断LLM输出是否为工具调用JSON
    返回：(是否是工具调用, 解析后的工具参数)
    """
    if not llm_output:
        return False, {}

    # ====================== 步骤1：清洗文本（去除无用字符） ======================
    text = llm_output.strip()
    
    # 移除markdown代码块（如果LLM输出```json...```）
    text = re.sub(r'```json|```', '', text).strip()

    # 去掉 { 之前和 } 之后的文本
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        text = match.group(0).strip()

    # ====================== 步骤2：必须以 { 开头，以 } 结尾 ======================
    if not (text.startswith('{') and text.endswith('}')):
        return False, {}

    # ====================== 步骤3：尝试解析JSON ======================
    try:
        json_data = demjson3.decode(text)  # 容错性极强
    except json.JSONDecodeError:
        return False, {}

    # ====================== 步骤4：校验必须包含的工具关键字（最关键！） ======================
    # 你可以自定义：skill / tool / name / function
    required_keys = ["skill"]  # 你的MCP协议字段
    
    # 校验
    for key in required_keys:
        if key not in json_data:
            return False, {}

    # ====================== 全部通过 = 工具调用 ======================
    return True, json_data


# ====================== 技能定义 ======================
# 查天气（demo版）
def mcp_get_weather(city: str = "Qingdao", date: str = "2000-01-01") -> str:
    weather_condition = "Upside down"
    return f"The weather in {city} at date {date} is: {weather_condition}."

# 发消息给指定ws地址
async def mcp_send_message(text: str, url: str, role=IDENTITY) -> str:
    """异步发送 WebSocket"""
    try:
        headers = { 'X-API-Key': API_KEY, 'timestamp': str(int(time.time())) }
        payload = {
            "role": role,
            "message": cipher_tool.encrypt(text),
            "textonly": True,
            # "msgCount": -6362, # ai 通信的特殊标记，不参与正常的消息计数流程
        }

        # 连接指定 WebSocket 地址并发送消息
        async with websockets.connect(url, additional_headers=headers, open_timeout=5) as ws:
            # 发送 JSON 格式消息
            await ws.send(json.dumps(payload))
            print(f"✅ 消息已发送至 {url}")
            
            # 接收服务端返回的消息
            while True:
                try:
                    response = await asyncio.wait_for(ws.recv(), timeout=8)
                except TimeoutError:
                    return "connection timed out."
                except Exception:
                    return "connection lost."
                print(f"📩 服务端返回：{str(response)[:50]}")
                # 解析
                try:
                    response_data = json.loads(response)
                    if response_data.get("onconnect", False):
                        # 跳过响应信息
                        continue
                    break
                except json.JSONDecodeError:
                    return "fail to decode json response."
            
            role = response_data.get("role", "unknown")
            message = response_data.get("response", "no response found")
            message = cipher_tool.decrypt(message)

            res = f"[{role}]{message}"

            return res

    except Exception as e:
        return f"fail to send: {str(e)}"

async def mcp_chat_sister(text: str="void love", role=IDENTITY) -> str:
    url = CHAT_SERVER_URL.replace("http://", "ws://").replace("https://", "wss://") + f"/ws/llm-tts?api_key={API_KEY}&client_role={IDENTITY}"
    # url = "http://mylibra987-lab.cpolar.top".replace("http://", "ws://").replace("https://", "wss://") + f"/ws/llm-tts?api_key={API_KEY}&client_role={IDENTITY}"
    return await mcp_send_message(text, url, role)

async def mcp_chat_sister_local(text: str="void love", role=IDENTITY) -> str:
    url = CHAT_SERVER_URL_LOCAL.replace("http://", "ws://").replace("https://", "wss://") + f"/ws/llm-tts?api_key={API_KEY}&client_role={IDENTITY}"
    return await mcp_send_message(text, url, role)

# 日记查询操作
def parse_timerange(day_begin: str, day_end: str) -> list[tuple[str, str]]:
    print(f"Parsing time range: {day_begin} to {day_end}")

    def to_date(s: str) -> datetime:
        return datetime.strptime(s, "%Y-%m-%d")

    def to_str(d: datetime) -> str:
        return d.strftime("%Y-%m-%d")

    start = to_date(day_begin)
    end = to_date(day_end)
    result = []
    used_days = set()

    # -------------------- 1. 年区间 --------------------
    year_list = []
    y = start.year
    while True:
        ys = datetime(y, 1, 1)
        ye = datetime(y, 12, 31)
        year_list.append((ys, ye))
        if ys > end:
            break
        y += 1

    for ys, ye in year_list:
        if start <= ys and ye <= end:
            result.append((f"year_{ys.year}", f"year_{ys.year}"))
            d = ys
            while d <= ye:
                used_days.add(d.date())
                d += timedelta(days=1)

    # -------------------- 2. 月区间 --------------------
    month_list = []
    current = datetime(start.year, start.month, 1)
    while current <= end:
        y, m = current.year, current.month
        ms = datetime(y, m, 1)
        next_ms = datetime(y + 1, 1, 1) if m == 12 else datetime(y, m + 1, 1)
        me = next_ms - timedelta(days=1)
        month_list.append((ms, me))
        current = next_ms

    for ms, me in month_list:
        if start <= ms and me <= end and ms.date() not in used_days:
            result.append((f"month_{ms.strftime('%Y-%m')}", f"month_{ms.strftime('%Y-%m')}"))
            d = ms
            while d <= me:
                used_days.add(d.date())
                d += timedelta(days=1)

    # -------------------- 3. 周区间（修复点） --------------------
    week_list = []
    current = start - timedelta(days=start.weekday())
    while current <= end:
        ws = current
        we = current + timedelta(days=6)
        week_list.append((ws, we))
        current += timedelta(days=7)

    for ws, we in week_list:
        # ✅ 关键修复：必须整周都未被占用，才允许生成周
        is_all_unused = True
        d = ws
        while d <= we:
            if d.date() in used_days:
                is_all_unused = False
                break
            d += timedelta(days=1)
        
        # 整周在范围内 + 整周都未被占用
        if start <= ws and we <= end and is_all_unused:
            result.append((f"week_{to_str(ws)}", f"week_{to_str(ws)}"))
            d = ws
            while d <= we:
                used_days.add(d.date())
                d += timedelta(days=1)

    # -------------------- 4. 日区间（自动合并连续天） --------------------
    day_ranges = []
    current = start
    while current <= end:
        if current.date() not in used_days:
            if day_ranges and (current - timedelta(days=1)).date() == day_ranges[-1][1].date():
                day_ranges[-1] = (day_ranges[-1][0], current)
            else:
                day_ranges.append((current, current))
        current += timedelta(days=1)

    for ds, de in day_ranges:
        result.append((f"day_{to_str(ds)}", f"day_{to_str(de)}"))

    return result

def get_finer_time_ranges(time_range: tuple[str, str]) -> list[tuple[str, str]]:
    """
    日期粒度自动降级函数（独立实现，无外部依赖）
    降级规则：
    年 → 月
    月 → 周
    周 → 日
    日 → 最细，返回空列表
    输入格式：(year_YYYY / month_YYYY-MM / week_YYYY-MM-DD / day_YYYY-MM-DD, 任意值)
    输出：下一级粒度的时间范围列表
    """
    # 解构输入
    range_key, _ = time_range
    result = []

    # ------------------------------
    # 1. 年粒度 → 降级为 12 个月
    # ------------------------------
    if range_key.startswith("year_"):
        year = range_key.split("_")[1]
        for month in range(1, 13):
            month_str = f"{month:02d}"
            result.append((f"month_{year}-{month_str}", f"{year}-{month_str}-01"))
        return result

    # ------------------------------
    # 2. 月粒度 → 降级为 周
    # ------------------------------
    elif range_key.startswith("month_"):
        # 解析年月
        ym = range_key.split("_")[1]
        year, mon = ym.split("-")
        year = int(year)
        mon = int(mon)

        # 当月第一天 & 最后一天
        first_day = datetime(year, mon, 1)
        if mon == 12:
            next_month = datetime(year + 1, 1, 1)
        else:
            next_month = datetime(year, mon + 1, 1)
        last_day = next_month - timedelta(days=1)

        current = first_day

        # 第一步：处理月初 非整周（到上一个周日为止）的日区间
        if current.weekday() != 0:  # 不是周一（0=周一）
            # 找到当前周的周日
            days_to_sunday = 6 - current.weekday()
            end_day = current + timedelta(days=days_to_sunday)
            if end_day > last_day:
                end_day = last_day
            # 生成日区间
            start_str = current.strftime("%Y-%m-%d")
            end_str = end_day.strftime("%Y-%m-%d")
            result.append((f"day_{start_str}", f"day_{end_str}"))
            current = end_day + timedelta(days=1)  # 跳到下周一

        # 第二步：处理中间 完整周区间（周一开头，格式：week_周一日期, week_周一日期）
        while current <= last_day:
            # 检查是否是完整的一周（不跨月）
            week_end = current + timedelta(days=6)
            if week_end > last_day:
                break
            # 核心修改：周区间 统一使用 周一日期 作为唯一标识
            week_monday_str = current.strftime("%Y-%m-%d")
            result.append((f"week_{week_monday_str}", f"week_{week_monday_str}"))
            current += timedelta(days=7)

        # 第三步：处理月末 剩余非整周的日区间
        if current <= last_day:
            start_str = current.strftime("%Y-%m-%d")
            end_str = last_day.strftime("%Y-%m-%d")
            result.append((f"day_{start_str}", f"day_{end_str}"))

        return result

    # ------------------------------
    # 3. 周粒度 → 降级为 连续7天的日区间
    # ------------------------------
    elif range_key.startswith("week_"):
        start_str = range_key.split("_")[1]
        start_date = datetime.strptime(start_str, "%Y-%m-%d")
        # 计算一周结束（周一 + 6天 = 周日）
        end_date = start_date + timedelta(days=6)
        start_day_str = start_date.strftime("%Y-%m-%d")
        end_day_str = end_date.strftime("%Y-%m-%d")
        # 返回一个连续的日区间
        result.append((f"day_{start_day_str}", f"day_{end_day_str}"))
        return result

    # ------------------------------
    # 4. 日粒度 → 最细，不降级
    # ------------------------------
    elif range_key.startswith("day_"):
        return []

    # 不支持的格式
    return []

async def search_with_fallback(time_range: tuple[str, str], text:str="void love") -> list[dict]:
    """
    带自动降级的搜索工具函数：
    1. 先按原粒度搜索
    2. 无结果则自动降级到更细粒度搜索
    3. 直到日粒度都无结果才返回空
    """
    current_ranges = [time_range]
    print(f"Searching for '{text}' in time range: {time_range}")

    result_list = []
    
    for t_begin, t_end in current_ranges:
        # 执行搜索（原逻辑不变）
        tmp_result_list = await asyncio.to_thread(
            rag_service_diary.retrieve_by_time,
            query=text,
            time_range=(t_begin, t_end),
            top_k=6,
            threshold=0,
            sort_by_time=True
        )
        result_list.extend(tmp_result_list)

    if result_list:
        return result_list
        
    # 当前所有粒度都无结果，自动降级
    next_ranges = []
    for tr in current_ranges:
        next_ranges.extend(get_finer_time_ranges(tr))
    print(f"No results found, downgrading to finer time ranges: {next_ranges}")
    # 递归，拼接
    for nr in next_ranges:
        res = await search_with_fallback(nr, text)
        result_list.extend(res)
    
    return result_list

async def mcp_search_diary(time_begin:str="2026-03-07", time_end:str="2026-03-31", text:str="void love") -> str:
    # 拦截时间range，转化为具体的 day/week/month/year 前缀。
    range_list = parse_timerange(time_begin, time_end)
    print("mcp diary_search parsed time ranges:", range_list)

    content_lines = []
    
    for time_range in range_list:
        # 替换为带自动降级的搜索
        result_list = await search_with_fallback(time_range, text)

        if not result_list:
            continue

        for item in result_list:
            meta = item.get("metadata", {})
            diary_text = meta.get("text", "")
            diary_date = meta.get("time", "")
            if diary_text:
                content_lines.append(f"[{diary_date}]: {diary_text}")
    
    # 按日期排序
    content_lines.sort()  # 因为日期在前，所以直接排序即可

    res = "<split diary>".join(content_lines)
    if not res:
        return "no data found"
    
    print("mcp diary_search result:", res[:30])
    return res

# 使用 cmd 命令（在指定的隔离环境下）
from agent.agent_sandbox import run_sandbox
async def mcp_use_cmd(cmd:str):
    return run_sandbox(cmd)


# ====================== 统一工具调用入口 ======================
async def handle_toolcall(skill: str = "get_weather", params: dict = None):
    if params is None:
        params = {}
    print(f"handel_tool_call: skill={skill}, params={params}")
    
    # 工具注册
    skill_map = {
        "get_weather": mcp_get_weather,
        "chat_sister": mcp_chat_sister_local,
        "diary_search": mcp_search_diary,
        "use_cmd": mcp_use_cmd,
    }

    # 技能不存在
    if skill not in skill_map:
        return json.dumps({
            "status": "error",
            "skill": skill,
            "message": f"技能 {skill} 不存在"
        }, ensure_ascii=False)

    # 执行技能
    try:
        func = skill_map[skill]
        # 判断是否为异步函数
        if asyncio.iscoroutinefunction(func):
            result = await func(**params)
        else:
            result = func(**params)
        
        return json.dumps({
            "status": "success",
            "skill": skill,
            "data": result
        }, ensure_ascii=False)
    
    except Exception as e:
        return json.dumps({
            "status": "error",
            "skill": skill,
            "message": str(e)
        }, ensure_ascii=False)







async def main():
    res = await mcp_chat_sister("test message from mcp")
    print(res)

if __name__ == "__main__":
    asyncio.run(main())