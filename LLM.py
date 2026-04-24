import time
import json
import asyncio


from configs import global_config
IDENTITY = global_config.IDENTITY
import Vdb
from Mcp import is_tool_call, handle_toolcall
from LLM_basic import llm_get_pure, doubao_client, doubao_model, deepseek_client, client_n1n
from LLM_context import context_init, update_context_round, append_history, get_tmp_context, get_tmp_context_withprompt, toolcall_check


maxToken = 1000

# -----------------------------------------------------------------------
# ------------------------------- 功能函数 -------------------------------
# -----------------------------------------------------------------------
# 专门返回处理后输入（时间Tag和角色Tag）的功能函数
def get_tagged_input(user_input: str, user_role: str='Khalo') -> str:
    # 加上当前角色标识
    if user_role != '' and user_role.lower() != 'system':
        user_input = '['+user_role+']' + user_input
    # 加上当前时间
    local_time = time.localtime()
    time_str = time.strftime("%Y-%m-%d, %H:%M", local_time)
    user_input = f'[{time_str}]' + user_input

    return user_input

# 专门返回处理后输入（Tag+RAG）的功能函数
def get_processed_input(user_input: str, user_role: str='Khalo', rag_service: Vdb.RAGService=None) -> str:
    # 先加Tag
    user_input = get_tagged_input(user_input, user_role)

    '''在用户消息之前加上提取的记忆信息，以增强回复'''
    global maxContext, maxCurrentContext, maxrounds

    # 提取记忆并生成prompt
    print("(get processed input) memory search: ", user_input)
    time_memoryLookup = time.perf_counter()

    # 现版本Milvus向量数据库
    extracted_memory = rag_service.retrieve(user_input)
    extracted_memory = "\n".join([
        ";".join([f"{k}:{v}" for k, v in item["metadata"].items()]) 
        for item in extracted_memory
    ])
    print("memory search time: ", time.perf_counter()-time_memoryLookup)
    print("memory search result: ", extracted_memory)

    # 检查是否真的提取出了记忆
    if extracted_memory == []:
        return user_input

    # 生成提示词
    prompt = '(related informations: '
    prompt += extracted_memory
    # 拼接user_input
    user_input_with_memory = f"{prompt})\n{user_input}"

    return user_input_with_memory




# -----------------------------------------------------------------------
# ---------------------------- 主要LLM调用方法 ---------------------------
# -----------------------------------------------------------------------
# 一般的非流式 llm 调用
def llm_get(user_input: str, user_role: str='Khalo', rag_service: Vdb.RAGService=None,
            llmType="doubao", tmp_prompt: str="") -> str:
    # user_role 为 system 时调整上下文角色
    request_role = "user"
    if user_role.lower() == 'system':
        request_role = "system"

    processed_user_input = get_tagged_input(user_input, user_role)

    # 获取临时拼接后的上下文
    if tmp_prompt == "":
        question = get_tmp_context(role=request_role, content=processed_user_input)
    else:
        # 在用户输入前插入一条系统提示词信息
        question = get_tmp_context_withprompt(role=request_role, content=processed_user_input, tmp_prompt=tmp_prompt)

    # 获取llm回复
    response = llm_get_pure(question=question, llmType=llmType)

    # 对 toolcall 轮数进行特殊处理
    is_toolcall, user_input, user_role = toolcall_check(response, user_input, user_role)
    print("is_toolcall:",is_toolcall)

    if response:
        # 更新一轮上下文
        print("llm normal: update context")
        update_context_round(
            role1=request_role, content1=get_tagged_input(user_input, user_role), # 带标签不带记忆的用户输入
            role2="assistant", content2=response, # 大模型回复
            rag_service=rag_service
        )
        # 添加到历史记录
        append_history(
            role1=request_role, content1=get_tagged_input(user_input, user_role),
            role2="assistant", content2=response
        )
    
    # 返回结果
    return response

# 流式回复版本的llm_get，返回生成器而不是完整的response字符串
def llm_get_stream(user_input: str, user_role: str='Default', rag_service: Vdb.RAGService=None, llmType="deepseek", tmp_prompt: str=""):
    # user_role 为 system 时调整上下文角色
    request_role = "user"
    if user_role.lower() == 'system':
        request_role = "system"
    
    processed_user_input = get_tagged_input(user_input, user_role)
    
    # 获取临时拼接后的上下文
    if tmp_prompt == "":
        question = get_tmp_context(role=request_role, content=processed_user_input)
    else:
        question = get_tmp_context_withprompt(role=request_role, content=processed_user_input, tmp_prompt=tmp_prompt)
    
    # 流式调用LLM
    full_response = ""
    if llmType == 'doubao':
        try:
            # 豆包流式调用接口
            stream = doubao_client.chat.completions.create(
                model=doubao_model,
                messages=question,
                stream=True,  # 开启流式
                thinking={
                    "type": "disabled",
                },
                max_tokens=maxToken
            )
            
            # 逐块生成回复
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content is not None:
                    chunk_content = chunk.choices[0].delta.content
                    full_response += chunk_content
                    yield chunk_content  # 逐段返回流式内容
                    
        except Exception as e:
            print(f"豆包流式调用出错: {str(e)}")
            yield f"Error: {str(e)}"
    
    elif llmType == 'deepseek':
        try:
            # DeepSeek 流式调用接口
            stream = deepseek_client.chat.completions.create(
                model="deepseek-chat",  # 或 "deepseek-v3.2" 等具体模型名
                messages=question,  # question 格式应该符合 OpenAI 标准：[{"role": "user", "content": "..."}]
                stream=True,  # 开启流式
                max_tokens=maxToken,
                temperature=0.99,  # 可选：控制随机性
            )
            
            # 逐块生成回复
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content is not None:
                    chunk_content = chunk.choices[0].delta.content
                    full_response += chunk_content
                    yield chunk_content  # 逐段返回流式内容
                    
        except Exception as e:
            print(f"DeepSeek 流式调用出错: {str(e)}")
            yield f"Error: {str(e)}"
    
    elif llmType == 'gmn':
        try:
            print("using: gemini-2.5-flash-nothinking")
            stream = client_n1n.chat.completions.create(
                model="gemini-2.5-flash-nothinking",
                stream=True,
                stream_options={"include_usage": True},
                messages=[
                    {
                        "role": e["role"],
                        "content": e["content"]  # 必须字符串格式
                    }
                    for e in question
                ]
            )

            # 流式输出
            for chunk in stream:
                try:
                    if chunk.choices and chunk.choices[0].delta:
                        content = chunk.choices[0].delta.content
                        if content:
                            full_response += content
                            yield content
                except:
                    continue

        except Exception as e:
            print(f"NLN API调用出错: {str(e)}")
            yield f"Error: {str(e)}"
        
    # 其他模型暂不支持流式，返回提示
    else:
        yield f"Error: LLM type '{llmType}' does not support stream response"
        return
    
    # 流式回复完成后，更新上下文（清洗格式+保存）
    if full_response:
        # 对 toolcall 轮数进行特殊处理
        is_toolcall, user_input, user_role = toolcall_check(full_response, user_input, user_role)
        print("is_toolcall:",is_toolcall)
        request_role = "user"
        if user_role.lower() == 'system':
            request_role = "system"

        # 更新一轮上下文
        print("llm stream: update context")
        update_context_round(
            role1=request_role, content1=get_tagged_input(user_input, user_role), # 带标签不带记忆的用户输入
            role2="assistant", content2=full_response, # 大模型回复
            rag_service=rag_service
        )
        # 添加到历史记录
        append_history(
            role1=request_role, content1=get_tagged_input(user_input, user_role),
            role2="assistant", content2=full_response
        )
        print("llm stream: context updated")

def Test_LLM_Initialize():
    context_init()



if __name__ == '__main__':
    loadcontext = True
    Test_LLM_Initialize()
    rag_service = Vdb.RAGService(global_config.VDB_DIR)

    while True:
        user_input = input("(message)>>>: ")
        # for chunk in llm_get_stream(user_input=user_input, user_role="Khalo", rag_service=rag_service):
            # print(chunk, end="", flush=True)  # end=""不换行，flush强制刷新输出
        response = llm_get(user_input, rag_service=rag_service, llmType='deepseek')

        # 检查mcp
        istoolcall, mcpJsonRequest = is_tool_call(response.strip())
        if istoolcall:
            print("开始执行mcp")
            # 提取到命令，进入执行
            skill = mcpJsonRequest.get("skill", "")
            params = mcpJsonRequest.get("params", {})
            mcpJsonResponse = asyncio.run(handle_toolcall(skill, params))
            mcpResult = f"Result of toolcall: {json.dumps(mcpJsonResponse)}"
            response = llm_get(user_input=mcpResult, user_role='system', rag_service=rag_service)
        
        print(response)