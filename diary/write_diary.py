'''
日记模块，分日、周、月、年四个部分。
 - day: 记录上一次更新日记的日期 (last_day)，读取history.json，按日生成日记 (插入day.jsonl)，然后更新 last_day 为最近一次日记的日期。
 - week: 记录上一次更新周记的日期 (last_week)，读取day.json，按周生成周记 (插入week.jsonl)，然后更新 last_week 为最近一次周记的日期。
 - month, year: 递归同上
管理日记VDB，负责在每次更新后插入。
* 日记格式：{"type":"day/week/month/year", "date":"xxx", "content":"xxx"}
'''

import json
import re
import os
from datetime import datetime, date, timedelta
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))  # 把项目根目录加入Python路径

from LLM import llm_get_pure
import Vdb

from configs import global_config
HISTORY_PATH = global_config.HISTORY_PATH
DIARY_DIR = global_config.DIARY_DIR
# DIARY_DIR = "./diary/testDir"


DAILY_PATH = os.path.join(DIARY_DIR, "day.jsonl")
WEEKLY_PATH = os.path.join(DIARY_DIR, "week.jsonl")
MONTHLY_PATH = os.path.join(DIARY_DIR, "month.jsonl")
YEAR_PATH = os.path.join(DIARY_DIR, "year.jsonl")
RECORD_PATH = os.path.join(DIARY_DIR, "last_record.json")

rag_service_diary = Vdb.RAGService(_vdb_path=global_config.VDB_DIARY_DIR)
last_record = None


# ----------------------------------------------------
# --------------------- 数据存取 ----------------------
# ----------------------------------------------------
def load_last_record():
    """加载上次更新记录，不存在则创建默认值"""
    if os.path.exists(RECORD_PATH):
        with open(RECORD_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    # 默认初始日期
    default = {
        "last_day": "2026-03-02",
        "last_week": "2026-03-02",
        "last_month": "2026-02",
        "last_year": "2025"
    }
    save_last_record(default)
    return default

def save_last_record(data: dict):
    """保存更新记录"""
    with open(RECORD_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_history_jsonl(file_path: str = HISTORY_PATH) -> list[list[dict]]:
    """
    读取 history.jsonl 文件
    每行格式: [{"role":"xxx","content":"xxx"},...],
    返回: 列表套列表 -> [ 对话段1, 对话段2, ... ]
    """
    history = []
    
    if not os.path.exists(file_path):
        return history

    with open(file_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            try:
                # 解析一行 = 一段对话列表
                chat_segment = json.loads(line)
                if isinstance(chat_segment, list):
                    history.append(chat_segment)
            except json.JSONDecodeError as e:
                print(f"[警告] 第 {line_num} 行解析失败: {e}")

    return history

def load_daily_jsonl(file_path: str = DAILY_PATH) -> list[dict]:
    """
    读取 daily.jsonl 文件
    每行格式: {"type":"day","date":"2026-03-30","content":"xxx"}
    返回: 日记列表 -> [ 日日记1, 日日记2, ... ]
    """
    daily_list = []
    
    if not os.path.exists(file_path):
        return daily_list

    with open(file_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            try:
                diary = json.loads(line)
                if isinstance(diary, dict):
                    daily_list.append(diary)
            except json.JSONDecodeError as e:
                print(f"[警告] 第 {line_num} 行解析失败: {e}")

    return daily_list

def load_weekly_jsonl(file_path: str = WEEKLY_PATH) -> list[dict]:
    """
    读取 weekly.jsonl 文件
    每行格式: {"type":"week","date":"2026-03-30","content":"xxx"}
    返回: 日记列表 -> [ 周日记1, 周日记2, ... ]
    """
    weekly_list = []
    
    if not os.path.exists(file_path):
        return weekly_list

    with open(file_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            try:
                diary = json.loads(line)
                if isinstance(diary, dict):
                    weekly_list.append(diary)
            except json.JSONDecodeError as e:
                print(f"[警告] 第 {line_num} 行解析失败: {e}")

    return weekly_list

def load_monthly_jsonl(file_path: str = MONTHLY_PATH) -> list[dict]:
    """
    读取 monthly.jsonl 文件
    每行格式: {"type":"month","date":"2026-03","content":"xxx"}
    返回: 日记列表 -> [ 月日记1, 月日记2, ... ]
    """
    monthly_list = []
    
    if not os.path.exists(file_path):
        return monthly_list

    with open(file_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            try:
                diary = json.loads(line)
                if isinstance(diary, dict):
                    monthly_list.append(diary)
            except json.JSONDecodeError as e:
                print(f"[警告] 第 {line_num} 行解析失败: {e}")

    return monthly_list


# ----------------------------------------------------
# --------------------- 工具函数 ----------------------
# ----------------------------------------------------
def append_to_jsonl(file_path: str, data: dict):
    """追加一行数据到 jsonl 文件"""
    with open(file_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False) + "\n")

def parse_datetime(text: str) -> str:
    """从 text 中提取时间：[2026-03-30, 13:23]"""
    pattern = r'\[(\d{4}-\d{2}-\d{2}, \d{2}:\d{2})\]'
    match = re.search(pattern, text)
    return match.group(1) if match else None


# ----------------------------------------------------
# --------------------- 更新检查 ----------------------
# ----------------------------------------------------
def check_day(nowday: str, lastday: str) -> list[tuple]:
    """
    判断是否需要生成新的【日日记】
    :param nowday: 当前日期，格式：YYYY-MM-DD
    :param lastday: 上次更新日期，格式：YYYY-MM-DD
    :return: 用于历史记录提取的时间窗列表（无需更新则返回空列表）
    """
    # 字符串转日期对象（只保留年月日，忽略时间）
    try:
        now = datetime.strptime(nowday, "%Y-%m-%d").date()
        last = datetime.strptime(lastday, "%Y-%m-%d").date()
        print(f"check day: {last} - {now}")
    except ValueError:
        # 日期格式错误
        print("check_day: wrong date format")
        return []
    
    # 只要当前日期 > 上次日期 + 24hours，就需要生成新日记
    last_till = last + timedelta(days=1)
    if now > last_till:
        # 生成 24 hour 间隔的时间窗
        result = []
        # 从上次日期开始，逐一生成时间窗
        current_date = last_till
        while current_date < now:
            # 开始时间：当前日期 + 00:00
            start_str = f"{current_date.strftime('%Y-%m-%d')}, 00:00"
            # 结束时间：下一天 + 00:00
            next_date = current_date + timedelta(days=1)
            end_str = f"{next_date.strftime('%Y-%m-%d')}, 00:00"
            
            result.append((start_str, end_str))
            # 日期向后推一天
            current_date = next_date
        
        return result
    else:
        return []

def check_week(now_date: str, last_week: str) -> list[tuple]:
    """
    判断是否需要生成新的【周日记】
    :param now_date: 当前日期，格式：YYYY-MM-DD
    :param last_week: 上次周记日期，格式：YYYY-MM-DD
    :return: 用于日记记录提取的时间窗列表（格式：YYYY-MM-DD）
    """
    try:
        now = datetime.strptime(now_date, "%Y-%m-%d").date()
        last = datetime.strptime(last_week, "%Y-%m-%d").date()
        print(f"check week: {last} - {now}")
    except ValueError:
        print("check_week: wrong date format")
        return []

    result = []
    current = last
    while True:
        # 计算当前日期所在周的 周一 00:00
        year, week, _ = current.isocalendar()
        week_start = datetime.fromisocalendar(year, week, 1).date()
        # 下一周周一
        next_week_start = week_start + timedelta(weeks=1)

        # 终止条件：本周已经 >= 当前日期所在周
        if next_week_start > now:
            break

        # 只有 本周周一大于上次周记的周一 才生成
        if week_start > last:
            start_str = f"{week_start.strftime('%Y-%m-%d')}"
            end_str = f"{next_week_start.strftime('%Y-%m-%d')}"
            result.append((start_str, end_str))

        current = next_week_start

    return result

def check_month(now_date: str, last_month: str) -> list[tuple]:
    """
    判断是否需要生成新的【月日记】
    :param now_date: 当前日期，格式：YYYY-MM-DD
    :param last_month: 上次月报日期，格式：YYYY-MM
    :return: 用于周记记录提取的时间窗列表（格式：YYYY-MM-DD）
    """
    try:
        now = datetime.strptime(now_date, "%Y-%m-%d").date()
        # 把上次日期转为标准日期
        last = datetime.strptime(last_month + "-01", "%Y-%m-%d").date()
        print(f"check month: {last} - {now}")
    except ValueError:
        print("check_month: wrong date format")
        return []

    result = []
    current = last
    while True:
        # 当月1号
        month_start = current.replace(day=1)
        # 下月1号
        if month_start.month == 12:
            next_month_start = month_start.replace(year=month_start.year+1, month=1, day=1)
        else:
            next_month_start = month_start.replace(month=month_start.month+1, day=1)

        # 终止条件：下月 > 当前日期
        if next_month_start > now:
            break
        
        # 只有 本月开始 > 上次日期 才生成
        if month_start > last:
            start_str = f"{month_start.strftime('%Y-%m-%d')}"
            end_str = f"{next_month_start.strftime('%Y-%m-%d')}"
            result.append((start_str, end_str))

        current = next_month_start

    return result

def check_year(now_date: str, last_year: str) -> list[tuple]:
    """
    判断是否需要生成新的【年日记】
    :param now_date: 当前日期，格式：YYYY-MM-DD
    :param last_year: 上次年报日期，格式：YYYY
    :return: 用于月记记录提取的时间窗列表（格式：YYYY-MM）
    """
    try:
        now = datetime.strptime(now_date, "%Y-%m-%d").date()
        # 把上次年份转为标准日期
        last = datetime.strptime(last_year + "-01-01", "%Y-%m-%d").date()
        print(f"check year: {last} - {now}")
    except ValueError:
        print("check_year: wrong date format")
        return []

    result = []
    current = last
    while True:
        # 当年1月1号
        year_start = current.replace(month=1, day=1)
        # 下一年1月1号
        next_year_start = year_start.replace(year=year_start.year+1)

        # 终止条件：下一年 > 当前日期
        if next_year_start > now:
            break

        # 只有 本年开始 > 上次日期 才生成
        if year_start > last:
            start_str = f"{year_start.strftime('%Y-%m')}"
            end_str = f"{next_year_start.strftime('%Y-%m')}"
            result.append((start_str, end_str))

        current = next_year_start

    return result



# ------------------------------------------------------
# --------------------- 按时间提取 ----------------------
# ------------------------------------------------------
# [{"role": "user", "content": "[2026-03-30, 13:24][Khalo]forget her."}, {"role": "assistant", "content": "Okay!"}]
def retrieve_history_by_time(
    history_list: list[list[dict]],
    time_range: tuple[str, str]
) -> list[str]:
    '''
    从多层对话列表中，按时间范围筛选所有消息
    :param history_list: 从 history.jsonl 读出的结构 -> [ [对话段], [对话段]... ]
    :param time_range: 前闭后闭，(开始时间, 结束时间) 例：("2026-03-30, 00:00", "2026-03-30, 23:59")
    :return: 时间范围内的所有对话消息（扁平列表）
    '''
    start_str, end_str = time_range
    result = []

    # 把范围时间转成 datetime
    try:
        start_time = datetime.strptime(start_str, "%Y-%m-%d, %H:%M")
        end_time = datetime.strptime(end_str, "%Y-%m-%d, %H:%M")
    except ValueError:
        return result

    # 遍历每一段对话
    for chat_segment in history_list:
        text = '\n'.join([f"{e['role']}: {e['content']}" for e in chat_segment])
        time_str = parse_datetime(text)

        if not time_str:
            continue

        # 消息时间格式化
        try:
            msg_time = datetime.strptime(time_str, "%Y-%m-%d, %H:%M")
        except ValueError:
            continue

        # 判断是否在范围内
        if start_time <= msg_time <= end_time:
            result.append(text)

    return result

# {"type": "day", "date": "2026-03-30", "content": "xxx"}
def retrieve_daily_by_time(day_diary_list: list[dict], time_range: tuple[str, str]):
    start_str, end_str = time_range
    result = []

    # 转换时间范围
    try:
        start_time = datetime.strptime(start_str, "%Y-%m-%d")
        end_time = datetime.strptime(end_str, "%Y-%m-%d")
    except ValueError:
        return result

    for diary in day_diary_list:
        date_str = diary.get("date", "")
        if not date_str:
            continue

        # 日日记格式：2026-03-30
        try:
            diary_time = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            continue

        # 判断是否在时间范围内
        if start_time <= diary_time <= end_time:
            result.append(diary)

    return result

# {"type": "week", "date": "2026-03-30", "content": "xxx"}
def retrieve_weekly_by_time(week_diary_list: list[dict], time_range: tuple[str, str]):
    start_str, end_str = time_range
    result = []

    # 转换时间范围
    try:
        start_time = datetime.strptime(start_str, "%Y-%m-%d")
        end_time = datetime.strptime(end_str, "%Y-%m-%d")
    except ValueError:
        return result

    for diary in week_diary_list:
        date_str = diary.get("date", "")
        if not date_str:
            continue

        # 周日记格式：2026-03-30
        try:
            diary_time = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            continue

        # 判断是否在时间范围内
        if start_time <= diary_time <= end_time:
            result.append(diary)

    return result

# {"type": "month", "date": "2026-03", "content": "xxx"}
def retrieve_monthly_by_time(month_diary_list: list[dict], time_range: tuple[str, str]):
    start_str, end_str = time_range
    result = []

    # 转换时间范围
    try:
        start_time = datetime.strptime(start_str, "%Y-%m")
        end_time = datetime.strptime(end_str, "%Y-%m")
    except ValueError:
        return result

    for diary in month_diary_list:
        date_str = diary.get("date", "")
        if not date_str:
            continue

        # 月日记格式：2026-03
        try:
            diary_time = datetime.strptime(date_str, "%Y-%m")
        except ValueError:
            continue

        # 判断是否在时间范围内
        if start_time <= diary_time <= end_time:
            result.append(diary)

    return result


# -------------------------------------------------------
# --------------------- 日记生成-分 ----------------------
# -------------------------------------------------------
def update_oneday(time_range:tuple[str,str]) -> str:
    try:
        start_str, end_str = time_range
        today_date = start_str.split(',')[0]

        print(f"生成 day 日记：{today_date}")

        # 提取历史记录
        history_list = load_history_jsonl(HISTORY_PATH)
        retrieved_history_list = retrieve_history_by_time(
            history_list=history_list,
            time_range=time_range
        )
        if not retrieved_history_list:
            # 空历史，不用生成，直接过
            print("update_oneday: jump empty")
            return today_date
        # 呼唤llm写日记
        content = generate_diary(
            prompt=global_config.prompt_diary_day,
            content_list=retrieved_history_list
        )
        if (not content) or (len(content) < 50):
            print("生成内容过短，跳过：", content)
            return ""
        # 写入jsonl文件
        day_data = {
            "type": "day",
            "date": today_date,
            "content": content
        }
        append_to_jsonl(DAILY_PATH, day_data)

        # 插入数据库
        rag_service_diary.store(
            texts=[day_data["content"]],
            metadatas=[{'time': "day_"+day_data["date"]}],
            threshold=11
        )

        return today_date
    except Exception as e:
        # 标准异常处理：打印错误信息，方便排查问题
        print(f"生成 day 日记失败，错误信息：{str(e)}")
        return ""

def update_oneweek(time_range:tuple[str,str]) -> str:
    try:
        start_str, end_str = time_range
        today_date = start_str

        print(f"生成 week 日记：{start_str}, {end_str}")

        # 提取日记记录
        daily_list = load_daily_jsonl(DAILY_PATH)
        retrieved_daily_list = retrieve_daily_by_time(
            day_diary_list=daily_list,
            time_range=(start_str, end_str)
        )
        if not retrieved_daily_list:
            # 空历史，不用生成，直接过
            print("update_oneweek: jump empty")
            return start_str
        # 呼唤llm写周记
        content = generate_diary(
            prompt=global_config.prompt_diary_week,
            content_list=[e['content'] for e in retrieved_daily_list]
        )
        if (not content) or (len(content) < 50):
            print("生成内容过短，跳过：", content)
            return ""
        # 写入jsonl文件
        week_data = {
            "type": "week",
            "date": today_date,
            "content": content
        }
        append_to_jsonl(WEEKLY_PATH, week_data)

        # 插入数据库
        rag_service_diary.store(
            texts=[week_data["content"]],
            metadatas=[{'time': "week_"+week_data["date"]}],
            threshold=11
        )

        return start_str
    except Exception as e:
        # 标准异常处理：打印错误信息，方便排查问题
        print(f"生成 week 日记失败，错误信息：{str(e)}")
        return ""

def update_onemonth(time_range:tuple[str,str]) -> str:
    try:
        start_str, end_str = time_range
        today_date = start_str

        print(f"生成 month 日记：{start_str}, {end_str}")

        # 提取周记记录
        weekly_list = load_weekly_jsonl(WEEKLY_PATH)
        retrieved_weekly_list = retrieve_weekly_by_time(
            week_diary_list=weekly_list,
            time_range=time_range
        )
        if not retrieved_weekly_list:
            # 尝试提取日记记录（如果周记没有，说明周记的时间窗内可能只有日日记）
            daily_list = load_daily_jsonl(DAILY_PATH)
            retrieved_daily_list = retrieve_daily_by_time(
                day_diary_list=daily_list,
                time_range=(start_str, end_str)
            )
            retrieved_weekly_list = retrieved_daily_list
            if not retrieved_daily_list:
                # 空历史，不用生成，直接过
                print("update_onemonth: jump empty")
                return today_date[:7]
        # 呼唤llm写月记
        content = generate_diary(
            prompt=global_config.prompt_diary_month,
            content_list=[e['content'] for e in retrieved_weekly_list]
        )
        if (not content) or (len(content) < 50):
            print("生成内容过短，跳过：", content)
            return ""
        # 写入jsonl文件
        month_data = {
            "type": "month",
            "date": today_date[:7],  # YYYY-MM
            "content": content
        }
        append_to_jsonl(MONTHLY_PATH, month_data)

        # 插入数据库
        rag_service_diary.store(
            texts=[month_data["content"]],
            metadatas=[{'time': "month_"+month_data["date"]}],
            threshold=11
        )

        return today_date[:7]
    except Exception as e:
        # 标准异常处理：打印错误信息，方便排查问题
        print(f"生成 month 日记失败，错误信息：{str(e)}")
        return ""

def update_oneyear(time_range:tuple[str,str]) -> str:
    try:
        start_str, end_str = time_range
        today_date = start_str

        print(f"生成 year 日记：{start_str}, {end_str}")

        # 提取月记记录
        monthly_list = load_monthly_jsonl(MONTHLY_PATH)
        retrieved_monthly_list = retrieve_monthly_by_time(
            month_diary_list=monthly_list,
            time_range=time_range
        )
        if not retrieved_monthly_list:
            # 尝试提取周记记录（如果月记没有，说明月记的时间窗内可能只有周记）
            weekly_list = load_weekly_jsonl(WEEKLY_PATH)
            retrieved_weekly_list = retrieve_weekly_by_time(
                week_diary_list=weekly_list,
                time_range=time_range
            )
            retrieved_monthly_list = retrieved_weekly_list
            if not retrieved_weekly_list:
                # 尝试提取日记记录（如果周记没有，说明周记的时间窗内可能只有日记）
                daily_list = load_daily_jsonl(DAILY_PATH)
                retrieved_daily_list = retrieve_daily_by_time(
                    day_diary_list=daily_list,
                    time_range=(start_str, end_str)
                )
                retrieved_monthly_list = retrieved_daily_list
                if not retrieved_daily_list:
                    # 空历史，不用生成，直接过
                    print("update_oneyear: jump empty")
                    return today_date[:4]
        # 呼唤llm写年记
        content = generate_diary(
            prompt=global_config.prompt_diary_year,
            content_list=[e['content'] for e in retrieved_monthly_list]
        )
        if (not content) or (len(content) < 50):
            print("生成内容过短，跳过：", content)
            return ""
        # 写入jsonl文件
        year_data = {
            "type": "year",
            "date": today_date[:4],  # YYYY
            "content": content
        }
        append_to_jsonl(YEAR_PATH, year_data)

        # 插入数据库
        rag_service_diary.store(
            texts=[year_data["content"]],
            metadatas=[{'time': "year_"+year_data["date"]}],
            threshold=11
        )

        return today_date[:4]
    except Exception as e:
        # 标准异常处理：打印错误信息，方便排查问题
        print(f"生成 year 日记失败，错误信息：{str(e)}")
        return ""


# -------------------------------------------------------
# --------------------- 日记生成-总 ----------------------
# -------------------------------------------------------
def generate_diary(prompt, content_list:list[str]) -> str:
    # if prompt==global_config.prompt_diary_day:
    #     return "day "*20
    # elif prompt==global_config.prompt_diary_week:
    #     return "week "*20
    # elif prompt==global_config.prompt_diary_month:
    #     return "month "*20
    # else:
    #     return "year "*20
    if content_list == []:
        return
    text = '\n'.join(content_list)
    content = prompt+text
    question = [{'role': 'system', 'content': content}]
    response = llm_get_pure(question)
    return response

def get_diary_prompt(type:str) -> str:
    if type=="day":
        return global_config.prompt_diary_day
    elif type=="week":
        return global_config.prompt_diary_week
    elif type=="month":
        return global_config.prompt_diary_month
    elif type=="year":
        return global_config.prompt_diary_year
    else:
        print("get_diary_prompt: no such type", type)
        return "error"

def update_all_diary(today_date: str) -> bool:
    """
    自动检查并生成日/周/月/年日记
    :param today_date: 今天日期，格式：YYYY-MM-DD
    """
    global last_record
    last_record = load_last_record()
    updated = False

    # 1. 更新【日日记】
    time_range_days = check_day(today_date, last_record["last_day"])
    if time_range_days != []:
        for tr in time_range_days:
            retry = 3 # 重试最多三次
            last_day = update_oneday(tr)
            while not last_day:
                retry -= 1
                if retry <= 0:
                    break
                last_day = update_oneday(tr)
            if retry <= 0:
                # 出现错误，流程终止
                print("fail on generating day", last_day)
                return False
            
            last_record["last_day"] = last_day
        updated = True

    # 2. 更新【周日记】
    time_range_weeks = check_week(today_date, last_record["last_week"])
    if time_range_weeks != []:
        for tr in time_range_weeks:
            retry = 3 # 重试最多三次
            last_week = update_oneweek(tr)
            while not last_week:
                retry -= 1
                if retry <= 0:
                    break
                last_week = update_oneweek(tr)
            if retry <= 0:
                # 出现错误，流程终止
                print("fail on generating week:", last_week)
                return False
            
            last_record["last_week"] = last_week
        updated = True

    # 3. 更新【月日记】
    time_range_months = check_month(today_date, last_record["last_month"])
    if time_range_months != []:
        for tr in time_range_months:
            retry = 3 # 重试最多三次
            last_month = update_onemonth(tr)
            while not last_month:
                retry -= 1
                if retry <= 0:
                    break
                last_month = update_onemonth(tr)
            if retry <= 0:
                # 出现错误，流程终止
                print("fail on generating month", last_month)
                return False
            
            last_record["last_month"] = last_month
        updated = True

    # 4. 更新【年日记】
    time_range_years = check_year(today_date, last_record["last_year"])
    if time_range_years != []:
        for tr in time_range_years:
            retry = 3 # 重试最多三次
            last_year = update_oneyear(tr)
            while not last_year:
                retry -= 1
                if retry <= 0:
                    break
                last_year = update_oneyear(tr)
            if retry <= 0:
                # 出现错误，流程终止
                print("fail on generating year", last_year)
                return False
            
            last_record["last_year"] = last_year
        updated = True

    # 保存更新后的记录
    if updated:
        save_last_record(last_record)
        print("✅ 日记更新完成，已保存最新记录")
    else:
        print("✅ 无需更新日记")
    
    return True





# 测试
if __name__ == "__main__":
    # time_range = ("2026-03-30", "2026-04-08")
    # start_str, end_str = time_range
    # daily_list = load_daily_jsonl(DAILY_PATH)
    # retrieved_daily_list = retrieve_daily_by_time(
    #     day_diary_list=daily_list,
    #     time_range=(start_str, end_str)
    # )
    # print(retrieved_daily_list)
    # exit(0)

    if update_all_diary("2026-04-15"):
        print("Update successful")
    else:
        print("Update incomplete")
    
    exit(0)