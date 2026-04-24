import json
import demjson3
import os
import re
import sys
import time
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))  # 把项目根目录加入Python路径

from configs import global_config
IDENTITY = global_config.IDENTITY
import Vdb, KGraph
from Mcp import is_tool_call
from LLM_basic import llm_get_pure
from utils.tool_funcs import save_to_json, append_to_jsonl

from concurrent.futures import ThreadPoolExecutor
# 创建一个全局线程池，max_workers=1 表示按顺序一个一个处理后台任务
# 这样可以保证 buffer 的写入顺序不会乱
bg_executor = ThreadPoolExecutor(max_workers=1)

# ---------------------------------------------------------------------
# -------------------------- 全局信息定义 --------------------------
# ---------------------------------------------------------------------
# 上下文轮数限制
max_recent_rounds = 20
max_buffered_rounds = 10
# buffer长度限制
buffer_primary_rounds = 15 # 达到该轮数后清空并触发压缩、存入二级buffer
buffer_secondary_len = 15 # 达到该轮数后清空并触发压缩、存入三级buffer
buffer_thirdary_len = 10 # 达到该条数后清空并触发总结，更新到提示词中的长期记忆里
# 记忆长度限制（同 buffer 长度）
len_memory_recent = buffer_secondary_len
len_memory_midium = buffer_thirdary_len
len_memory_midterm = 2 # 测试用


# 路径相关
HISTORY_PATH =          f'./saved_context/{IDENTITY}/history.jsonl'
CONTEXT_PATH =          f'./saved_context/{IDENTITY}/context.json'
PROMPT_PATH =           f'./saved_context/{IDENTITY}/prompt_dict.json'
BUFFERED_CONTEXT_PATH = f'./saved_context/{IDENTITY}/buffered_context.json'
RECENT_CONTEXT_PATH =   f'./saved_context/{IDENTITY}/recent_context.json'
MEMORY_RECENT_PATH =    f'./saved_context/{IDENTITY}/memory_recent_queue.json' # 短期记忆，对应二级 buffer 里的内容
MEMORY_MIDIUM_PATH =    f'./saved_context/{IDENTITY}/memory_midium_queue.json' # 中期记忆，对应三级 buffer 里的内容
MEMORY_MIDTERM_PATH =   f'./saved_context/{IDENTITY}/memory_midterm_queue.json' # 暂时不知道干什么，测试用记忆块，用来存查到的日记
BUFFER1_PATH = f'./saved_context/{IDENTITY}/buffer.json'
BUFFER2_PATH = f'./saved_context/{IDENTITY}/memorybuffer.json'
BUFFER3_PATH = f'./saved_context/{IDENTITY}/memorybuffer2.json'


# ---------------------------------------------------------------------
# -------------------------- 上下文模块定义 --------------------------
# ---------------------------------------------------------------------
context_list = []
history_list = []

prompt_dict = {'personality':'', 'personality_midterm':'', 'memory':'', 'tool':''}
buffered_context_list = []
recent_context_list = []
memory_recent_queue = []
memory_midterm_queue = []

bufferlist_primary = []
bufferlist_secondary = []
bufferlist_thirdary = []


# ---------------------------------------------------------------------
# -------------------------- 工具函数 --------------------------
# ---------------------------------------------------------------------
# mcp调用的上下文管理相关
in_toolcall = False
toolcall_rounds = 0
last_user_input = ""
last_user_role = ""
last_skill = ""
def toolcall_check(full_response:str, user_input:str, user_role:str):
    print(f"toolcall_check entered: full_response={full_response[:30]}, user_input={user_input[:30]}, user_role={user_role}")
    global in_toolcall, toolcall_rounds, last_user_input, last_user_role, last_skill, last_mcpjson
    global recent_context_list

    istoolcall, mcpjson = is_tool_call(full_response)
    skill = mcpjson.get("skill", "")
    
    
    print("toolcall check entered")
    # 检查是不是toolcall
    if istoolcall:
        # 解析toolcall的种类，根据skill类别灵活选择是否保留记录
        if skill in ["chat_sister"]:
            last_skill = skill
            # 保存上下文记录
            return istoolcall, user_input, user_role
        # 其他的不保存记录，按后续规则正常清理
        
        if not in_toolcall:
            # 说明是第一轮toolcall，保存该轮的用户输入
            last_user_input = user_input
            last_user_role = user_role
            print("toolcall_check: saved input and role:", user_input, user_role)
        in_toolcall = True
        toolcall_rounds += 1
    
    if in_toolcall and True:
        if not istoolcall:
            print("on cleaning toolcalls:")
            # toolcall 轮结束，清洗上下文
            for _ in range(min(toolcall_rounds, len(recent_context_list) // 2)):
                mcpresp = recent_context_list.pop()
                toolcallmsg = recent_context_list.pop()
                print("cleaning toolcall rounds:", toolcallmsg, mcpresp)
            # 对一些结果进行特殊处理
            if last_skill == "diary_search":
                # 把搜索的日记加入中期记忆队列里
                print("Add diary search result to midterm memory:", user_input[:30])
                diary_content = {"content":str(user_input)}
                if diary_content:
                    push_midterm_memory(diary_content)

            # 把这一轮的 user_input 和 user_role 改成 toolcall 前的版本
            user_input = last_user_input
            user_role = last_user_role
            # 状态恢复
            in_toolcall = False
            toolcall_rounds = 0
            last_user_input = ""
            last_user_role = ""
    
    last_skill = skill

    return in_toolcall, user_input, user_role

# ---------------------------------------------------------------------
# 知识图谱抽取
# 插入主方法
def KG_insert(node1:str, relation:str, node2:str, KG_service:KGraph.KnowledgeGraphCRUD=None) -> bool:
    pass
    return True

# 相似度检查
def KG_checksim(node1:str, relation:str, node2:str, threshold:float=0.8, rag_service:Vdb.RAGService=None, KG_service:KGraph.KnowledgeGraphCRUD=None) -> bool:
    '''冗余信息拒绝插入'''
    try:
        # 检查节点名称相似度
        pass
        # 如果是节点描述（node2为空），检查该节点下描述的相似度
        pass
        # 如果是关系插入，检查该关系的相似度
        pass
    except Exception as e:
        print(f"【KG_checksim 错误】: {e}")
        return False
    return True

# 抽取主方法
def KG_extract(text:str, KG_service:KGraph.KnowledgeGraphCRUD=None) -> bool:
    '''从文本中提取关系图并尝试插入KGraph'''
    if not text.strip() or not KG_service:
        print("error: 输入文本或KG服务实例为空")
        return False
    
    reslist = []

    try:
        # 调用LLM抽取关系。支持三元组（关系插入）或二元组（增加节点描述）
        pass

        # 遍历抽取结果，进行相似度检查并插入KG
        pass

        return True
    
    except Exception as e:
        print(f"【KG_extract 错误】: {e}")
        return False
    
    return False

# ---------------------------------------------------------------------
# 对话压缩
def zip_context(rounds: list[dict]) -> str:
    '''把要压缩的上下文发给llm，返回压缩后结果'''
    print("zip_context entered.")
    try:
        namemap = {'user':'', 'system':"system", 'assistant':IDENTITY}
        text_str = '\n'.join([f"{namemap[e['role']]}: {e['content']}" for e in rounds])
        _len_before = len(text_str)
        prompt = global_config.prompt_zip_context
        prompt += text_str
        print("zip_context prompt:", prompt[:30], "...", prompt[-30:])

        # 调用LLM
        response = llm_get_pure([{"role": "system", "content": prompt}])
        
        print(f"context zipped successfully: {_len_before} -> {len(response)}")
        return response

    except Exception as e:
        print(f"【zip_context 错误】{e}")
        return ""

# 记忆压缩
def zip_memory(memtext: str) -> str:
    '''把要压缩的记忆文本发给llm，返回压缩后结果'''
    print("zip_memory entered.")
    _len_before = len(memtext)
    prompt = global_config.prompt_zip_memory
    prompt += memtext
    response = llm_get_pure([{"role": "system", "content": prompt}])
    print(f"memory zipped successfully: {_len_before} -> {len(response)}")
    return response


# ---------------------------------------------------------------------
# -------------------------- 上下文模块读入 --------------------------
# ---------------------------------------------------------------------
# 读取本地存储的上下文
def load_context(path=CONTEXT_PATH):
    """从JSON文件加载上下文"""
    global context_list
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                context_list = json.load(f)
            print(f"上下文加载成功，当前上下文长度: {len(context_list)}")
        except json.JSONDecodeError:
            print("上下文文件格式错误，将使用空上下文")
            context_list = []
    else:
        print(f"路径不存在：{path}")

# 读取本地存储的提示词
def load_prompt(path=PROMPT_PATH):
    global prompt_dict
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                prompt_dict = json.load(f)
            print(f"提示词加载成功")
        except json.JSONDecodeError:
            print("提示词文件格式错误！")
            exit(0)
    else:
        print(f"路径不存在：{path}")

# 读取本地存储的 buffer区 上下文
def load_buffered_context(path=BUFFERED_CONTEXT_PATH):
    """从JSON文件加载上下文"""
    global buffered_context_list
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                buffered_context_list = json.load(f)
            print(f"buffer 上下文加载成功，当前上下文长度: {len(buffered_context_list)}")
        except json.JSONDecodeError:
            print("buffer 上下文文件格式错误")
            buffered_context_list = []
    else:
        print(f"路径不存在：{path}")

# 读取本地存储的 recent区 上下文
def load_recent_context(path=RECENT_CONTEXT_PATH):
    """从JSON文件加载上下文"""
    global recent_context_list
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                recent_context_list = json.load(f)
            print(f"recent 上下文加载成功，当前上下文长度: {len(recent_context_list)}")
        except json.JSONDecodeError:
            print("recent 上下文文件格式错误")
            recent_context_list = []
    else:
        print(f"路径不存在：{path}")

# ---------------------------------------------------------------------
# 读取本地存储的 memory_recent_queue
def load_memory_recent_queue(path=MEMORY_RECENT_PATH):
    global memory_recent_queue
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                memory_recent_queue = json.load(f)
            print(f"memory_recent_queue加载成功，当前memory_recent_queue长度: {len(memory_recent_queue)}")
        except json.JSONDecodeError:
            print("文件格式错误，memory_recent_queue 加载失败")
            memory_recent_queue = []
    else:
        print(f"路径不存在：{path}")

# 读取本地存储的 memory_midium_queue
def load_memory_midium_queue(path=MEMORY_MIDIUM_PATH):
    global memory_midium_queue
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                memory_midium_queue = json.load(f)
            print(f"memory_midium_queue加载成功，当前memory_midium_queue长度: {len(memory_midium_queue)}")
        except json.JSONDecodeError:
            print("文件格式错误，memory_midium_queue 加载失败")
            memory_midium_queue = []
    else:
        print(f"路径不存在：{path}")

# 读取本地存储的 memory_midterm_queue
def load_memory_midterm_queue(path=MEMORY_MIDTERM_PATH):
    global memory_midterm_queue
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                memory_midterm_queue = json.load(f)
            print(f"memory_midterm_queue 加载成功，当前 memory_midterm_queue 长度: {len(memory_midterm_queue)}")
        except json.JSONDecodeError:
            print("文件格式错误，memory_midterm_queue 加载失败")
            memory_midterm_queue = []
    else:
        print(f"路径不存在：{path}")

# ---------------------------------------------------------------------
# 读取本地存储的一级 buffer
def load_context_buffer(path=BUFFER1_PATH):
    """从JSON文件加载 buffer"""
    global bufferlist_primary
    print("loading buffer.json...")
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                bufferlist_primary = json.load(f)
            print(f"buffer加载成功，当前buffer长度: {len(bufferlist_primary)}")
        except json.JSONDecodeError:
            print("文件格式错误，buffer 加载失败")
            bufferlist_primary = []
    else:
        print(f"路径不存在：{path}")

# 读取本地存储的二级 buffer
def load_memory_buffer(path=BUFFER2_PATH):
    """从JSON文件加载 buffer"""
    global bufferlist_secondary
    print("loading memorybuffer.json...")
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                bufferlist_secondary = json.load(f)
            print(f"memorybuffer加载成功，当前memorybuffer长度: {len(bufferlist_secondary)}")
        except json.JSONDecodeError:
            print("文件格式错误，memorybuffer 加载失败")
            bufferlist_secondary = []
    else:
        print(f"路径不存在：{path}")

# 读取本地存储的三级 buffer
def load_memory_buffer2(path=BUFFER3_PATH):
    """从JSON文件加载 buffer"""
    global bufferlist_thirdary
    print("loading memorybuffer.json...")
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                bufferlist_thirdary = json.load(f)
            print(f"memorybuffer2加载成功，当前memorybuffer2长度: {len(bufferlist_thirdary)}")
        except json.JSONDecodeError:
            print("文件格式错误，memorybuffer2 加载失败")
            bufferlist_thirdary = []
    else:
        print(f"路径不存在：{path}")


# ---------------------------------------------------------------------
# -------------------------- 上下文模块拼接 --------------------------
# ---------------------------------------------------------------------
# 拼接 system prompt
def cat_system_prompt(order:list[str]=["personality", "memory", "tool"]) -> str:
    global prompt_dict
    try:
        prompt_list = []
        for key in order:
            prompt_list.append(prompt_dict[key])
        return '\n'.join(prompt_list)
    except Exception as e:
        print(f"cat_system_prompt: error -- {e}")

# 拼接 recent memory
def cat_recent_memory() -> str:
    global memory_recent_queue
    try:
        return '\n'.join([f"{e['time']}: {e['content']}" for e in memory_recent_queue])
    except Exception as e:
        print(f"cat_recent_memory: error -- {e}")

# 拼接 midium memory
def cat_midium_memory() -> str:
    global memory_midium_queue
    try:
        return '\n'.join([f"{e['time']}: {e['content']}" for e in memory_midium_queue])
    except Exception as e:
        print(f"cat_midium_memory: error -- {e}")

# 拼接 midterm memory
def cat_midterm_memory() -> str:
    global memory_midterm_queue
    try:
        return '\n'.join([e['content'] for e in memory_midterm_queue])
    except Exception as e:
        print(f"cat_midterm_memory: error -- {e}")

# 拼接完整上下文
def cat_context() -> list[dict]:
    try:
        # 系统提示词
        system_prompt = cat_system_prompt().strip()
        # 记忆模块
        memory_prompt = ("Here's your working memory: " + cat_recent_memory() + "\n" + cat_midium_memory()).strip()
        # 中期提示词
        midterm_prompt = prompt_dict["personality_midterm"].strip()

        # 提示词部分（最前）
        context_system_prompt = [{"role":"system", "content":system_prompt.strip()}]
        # 中间注入部分（buffered context 和 recent context 之间）
        context_mid = [{"role":"system", "content":memory_prompt}]
        # 尾部注入部分（recent context 之后，正式对话之前）
        context_tail = [{"role":"system", "content":midterm_prompt}]


        context_list_integrated = context_system_prompt + buffered_context_list + context_mid + recent_context_list + context_tail

        # 顺带保存这个完整的上下文到文件里
        save_to_json(context_list_integrated, CONTEXT_PATH)

        return context_list_integrated
    except Exception as e:
        print(f"cat_context: error -- {e}")
        return e


# ---------------------------------------------------------------------
# -------------------------- 上下文模块管理 --------------------------
# ---------------------------------------------------------------------
# 尾插 recent context 一句
def push_recent_context_one(jsoncon: dict[str:str, str:str], rag_service: Vdb.RAGService=None) -> None:
    global recent_context_list

    # push
    recent_context_list.append(jsoncon)

    # 检查轮数，处理超出部分
    while len(recent_context_list) > 2*max_recent_rounds:
        # 切片
        roundcontent = recent_context_list[:2]
        # push 给 buffered_context 和一级缓冲
        push_buffered_context(roundcontent)
        push_primary_buffer(roundcontent, rag_service)
        # 更新 recent 上下文
        recent_context_list = recent_context_list[2:]
    
    # 保存到文件
    save_to_json(recent_context_list, RECENT_CONTEXT_PATH)

# 尾插 recent context 一轮
def push_recent_context(roundcontent: list[dict[str:str, str:str]], rag_service: Vdb.RAGService=None) -> None:
    global recent_context_list

    # push
    recent_context_list.extend(roundcontent)

    # 检查轮数，处理超出部分
    while len(recent_context_list) > 2*max_recent_rounds:
        # 切片
        roundcontent = recent_context_list[:2]

        # push 给 buffered_context 和一级缓冲
        push_buffered_context(roundcontent)
        # push_primary_buffer(roundcontent, rag_service)
        bg_executor.submit(push_primary_buffer, roundcontent, rag_service)

        # 更新 recent 上下文
        recent_context_list = recent_context_list[2:]
    
    # 保存到文件
    save_to_json(recent_context_list, RECENT_CONTEXT_PATH)

# 尾插 buffered context 一轮
def push_buffered_context(roundcontent: list[dict[str:str, str:str]]) -> None:
    global buffered_context_list

    # push
    buffered_context_list.extend(roundcontent)

    # 检查轮数，FIFO 丢弃超出部分
    while len(buffered_context_list) > 2*max_buffered_rounds:
        buffered_context_list = buffered_context_list[2:]
    
    # 保存到文件
    save_to_json(buffered_context_list, BUFFERED_CONTEXT_PATH)

# ---------------------------------------------------------------------
# 尾插短期记忆（len_memory_recent 轮对话一压缩）
def push_recent_memory(memtext:str) -> None:
    global memory_recent_queue

    # push
    memory_recent_queue.append({"content":memtext, "time":time.strftime("%Y-%m-%d, %H:%M", time.localtime())})

    # 检查轮数，FIFO 丢弃超出部分
    while len(memory_recent_queue) > len_memory_recent:
        memory_recent_queue = memory_recent_queue[2:]
    
    # 保存到文件
    save_to_json(memory_recent_queue, MEMORY_RECENT_PATH)

# 尾插中期记忆（len_memory_midium 段一压缩）
def push_midium_memory(memtext:str) -> None:
    global memory_midium_queue

    # push
    memory_midium_queue.append({"content":memtext, "time":time.strftime("%Y-%m-%d, %H:%M", time.localtime())})

    # 检查轮数，FIFO 丢弃超出部分
    while len(memory_midium_queue) > len_memory_midium:
        memory_midium_queue = memory_midium_queue[2:]
    
    # 保存到文件
    save_to_json(memory_midium_queue, MEMORY_MIDIUM_PATH)

# 尾插临时记忆
def push_midterm_memory(memtext:str) -> None:
    global memory_midterm_queue

    # push
    memory_midterm_queue.append(memtext)

    # 检查轮数，FIFO 丢弃超出部分
    while len(memory_midterm_queue) > len_memory_midterm:
        memory_midterm_queue = memory_midterm_queue[2:]

    # 保存到文件
    save_to_json(memory_midterm_queue, MEMORY_MIDTERM_PATH)

# ---------------------------------------------------------------------
# push 一级buffer（存储原对话）
def push_primary_buffer(roundcontent: list[dict[str:str, str:str]], rag_service: Vdb.RAGService=None) -> None:
    global bufferlist_primary
    print(f"push_primary_buffer, len_before: {len(bufferlist_primary)}")

    # push
    bufferlist_primary.extend(roundcontent)

    # 检查是否已满，满则压缩 + push给二级buffer和短期记忆队列 + 清空
    if len(bufferlist_primary) > 2*buffer_primary_rounds:
        # 压缩
        zipped = zip_context(bufferlist_primary)
        if not zipped:
            print("push_primary_buffer: 压缩失败，跳过")
            return

        print("primary buffer zipped.")

        # push给二级buffer
        push_secondary_buffer(zipped, rag_service)
        # push给短期记忆队列
        push_recent_memory(zipped)


        # 压缩结果存入数据库
        if rag_service is not None:
            if rag_service.store([zipped]):
                print("pushed zipped buffer1 to memory.")
            else:
                print("failed to push zipped buffer1 into memory.")

        # 清空一级 buffer
        bufferlist_primary.clear()

    print(f"push_primary_buffer, len_after: {len(bufferlist_primary)}")
    # 写入文件
    save_to_json(bufferlist_primary, BUFFER1_PATH)

# push 二级buffer（存储短期记忆）
def push_secondary_buffer(memtext: str, rag_service: Vdb.RAGService=None) -> None:
    global bufferlist_secondary
    print(f"push_secondary_buffer -- len_before:{len(bufferlist_secondary)}")

    # push
    bufferlist_secondary.append({"content":memtext, "time":time.strftime("%Y-%m-%d, %H:%M", time.localtime())})

    # 检查是否已满，满则压缩 + push给三级buffer和中期记忆队列 + 清空
    if len(bufferlist_secondary) > buffer_secondary_len:
        # 压缩
        memstr = '\n'.join([f"{e['time']}: {e['content']}" for e in bufferlist_secondary])
        zipped = zip_memory(memstr)
        if not zipped:
            print("push_secondary_buffer: 压缩失败，跳过")
            return

        print("secondary buffer zipped.")

        # push给三级buffer
        push_thirdary_buffer(zipped, rag_service)
        # push给中期记忆队列
        push_midium_memory(zipped)


        # 压缩结果存入数据库
        if rag_service is not None:
            if rag_service.store([zipped]):
                print("pushed zipped buffer2 to memory.")
            else:
                print("failed to push zipped buffer2 into memory.")

        # 清空二级 buffer
        bufferlist_secondary.clear()
    
    print(f"push_secondary_buffer -- len_after:{len(bufferlist_secondary)}")
    # 写入文件
    save_to_json(bufferlist_secondary, BUFFER2_PATH)

# push 三级buffer（存储中期记忆）
def push_thirdary_buffer(memtext: str, rag_service: Vdb.RAGService=None) -> None:
    global bufferlist_thirdary
    print(f"push_thirdary_buffer -- len_before:{len(bufferlist_thirdary)}")

    # push
    bufferlist_thirdary.append({"content":memtext, "time":time.strftime("%Y-%m-%d, %H:%M", time.localtime())})

    # 检查是否已满，满则压缩 + 更新长期记忆 + 清空
    if len(bufferlist_thirdary) >= buffer_thirdary_len:
        print("memorybuffer zip triggered")

        # 压缩
        memstr = "Here's your old memories: " + prompt_dict['memory'] + "Here's your new memories: "
        memstr += '\n'.join([f"{e['time']}: {e['content']}" for e in bufferlist_thirdary])
        zipped = zip_memory(memstr)
        print("memory buffer zipped.")

        # 更新系统提示词中的长期记忆
        prompt = "Here's the important things you should remember, you have kept these into your memory:\n"
        prompt_dict['memory'] = prompt + zipped
        print("memory prompt updated.")

        # 存入数据库
        if rag_service != None:
            if rag_service.store([zipped]):
                print("pushed memory buffer3 to memory.")
            else:
                print("failed to push memory buffer3 into memory.")
        else:
            print("rag_service is None, insert failed")
        
        # 压缩完成，清空三级 buffer
        print("memorybuffer zip complete, memorybuffer list cleared.")
        bufferlist_thirdary.clear()
    
    print(f"push_thirddary_buffer -- len_after:{len(bufferlist_thirdary)}")
    # 写入文件
    save_to_json(bufferlist_thirdary, BUFFER3_PATH)


# ---------------------------------------------------------------------
# -------------------------- 对外接口 --------------------------
# ---------------------------------------------------------------------
# 初始化
def context_init():
    load_prompt()
    load_buffered_context()
    load_recent_context()

    load_memory_recent_queue()
    load_memory_midium_queue()
    load_memory_midterm_queue()

    load_context_buffer()
    load_memory_buffer()
    load_memory_buffer2()

    global context_list
    context_list = cat_context()

# 往上下文中更新一句
def update_context(role:str="user", content:str="", rag_service: Vdb.RAGService=None) -> None:
    jsoncon = {"role": role, "content": content}
    push_recent_context_one(jsoncon, rag_service)

# 假装往上下文中更新一句，返回拼接后的临时上下文列表
def get_tmp_context(role:str="user", content:str="") -> list[dict]:
    jsoncon = {"role": role, "content": content}
    return cat_context() + [jsoncon]

# 假装往上下文中更新一句（带增强提示词的版本），返回拼接后的临时上下文列表
def get_tmp_context_withprompt(role:str="user", content:str="", tmp_prompt:str="") -> list[dict]:
    jsoncon_prompt = {"role": "system", "content": tmp_prompt}
    jsoncon = {"role": role, "content": content}
    return cat_context() + [jsoncon_prompt, jsoncon]

# 往上下文中更新一轮
def update_context_round(role1:str="user", content1:str="", role2:str="assistant", content2:str="", rag_service: Vdb.RAGService=None) -> None:
    jsoncon1 = {"role": role1, "content": content1}
    jsoncon2 = {"role": role2, "content": content2}
    push_recent_context([jsoncon1, jsoncon2], rag_service)

# 添加到历史记录
def append_history(role1:str="user", content1:str="", role2:str="assistant", content2:str=""):
    jsoncon1 = {"role": role1, "content": content1}
    jsoncon2 = {"role": role2, "content": content2}
    append_to_jsonl([jsoncon1, jsoncon2], HISTORY_PATH)

# 获取完整上下文列表
def get_full_context() -> list[dict]:
    return cat_context()







# ---------------------------------------------------------------------
# -------------------------- Test --------------------------
# ---------------------------------------------------------------------

def main():
    load_prompt()

    load_buffered_context()
    load_recent_context()
    load_memory_recent_queue()
    load_memory_midterm_queue()

    system_prompt = cat_system_prompt()
    context_system_prompt = [{"role":"system", "content":system_prompt}]
    memory_prompt = "Please remember these memories in following conversation: " + cat_recent_memory()
    context_memory_prompt = [{"role":"system", "content":memory_prompt}]

    load_context()
    context_list_integrated = context_system_prompt + buffered_context_list + context_memory_prompt + recent_context_list

    save_to_json(context_list_integrated, "./saved_context/integrated_context.json")



if __name__ == "__main__":
    main()

