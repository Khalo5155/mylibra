import os
from dotenv import load_dotenv
load_dotenv()

from openai import OpenAI
# from Test_memory import memory_llmRequest, memory_llmWrite, memory_load, memory_write

from configs import global_config
IDENTITY = global_config.IDENTITY
maxToken = 200

# doubao
doubao_api_key = os.getenv("DOUBAO_API_KEY")
# Install SDK:  pip install 'volcengine-python-sdk[ark]'
from volcenginesdkarkruntime import Ark
doubao_client = Ark(
    # The base URL for model invocation
    base_url="https://ark.cn-beijing.volces.com/api/v3",
    # Get API Key：https://console.volcengine.com/ark/region:ark+cn-beijing/apikey
    api_key=doubao_api_key, 
    # Deep thinking takes longer; set a larger timeout, with 1,800 seconds or more recommended
    timeout=1800,
)
doubao_model = "doubao-seed-2-0-pro-260215"
# doubao_model = "doubao-seed-2-0-lite-260215"
# doubao_model = "doubao-1-5-lite-32k-250115"

# DeepSeek online
import requests
DeepSeek_API_KEY = os.getenv("DEEPSEEK_API_KEY")
deepseek_client = OpenAI(
            api_key=DeepSeek_API_KEY,
            base_url="https://api.deepseek.com/v1"
        )

# OpenAI
openai_client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url="https://openrouter.ai/api/v1"
)

# NLN
client_n1n = OpenAI(
    base_url="https://api.n1n.ai/v1",  # 关键：n1n 聚合接口
    api_key=os.getenv("N1N_API_KEY")    # 您的 n1n API Key
)


# 无状态llm_get，输入结构化上下文字典列表，输出回复
def llm_get_pure(question: list, llmType='deepseek') -> str:
    global maxToken

    response = ''
    if llmType == 'doubao':
        # 创建一个对话请求
        completion = doubao_client.chat.completions.create(
            model = doubao_model,
            messages = question,
            thinking={
                "type": "disabled", # 不使用深度思考能力
                # "type": "enabled", # 使用深度思考能力
                # "type": "auto", # 模型自行判断是否使用深度思考能力
            },
        )
        response = completion.choices[0].message.content
    
    elif llmType == 'deepseek':
        # 构建请求URL和 headers
        url = "https://api.deepseek.com/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {DeepSeek_API_KEY}"
        }
        # 构建请求体
        payload = {
            "model": "deepseek-chat",  # 可根据需要替换为其他DeepSeek模型
            "messages": question,      # 使用处理后的对话历史
            "temperature": 0.99,        # 温度参数，控制输出随机性
            "max_tokens": 1024,         # 最大生成token数
        }
        try:
            # 发送POST请求
            res = requests.post(url, json=payload, headers=headers, verify=False)
            res.raise_for_status()  # 检查请求是否成功
            # 解析响应结果
            result = res.json()
            response = result["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(f"DeepSeek API调用出错: {str(e)}")
            response = "抱歉，调用DeepSeek时出现错误，请稍后再试"

    elif llmType == 'gmn':
        try:
            nln_response = client_n1n.chat.completions.create(
                model="gemini-2.5-flash-nothinking",
                stream=False,
                messages=[
                    {
                        "role": e['role'],
                        "content": [
                            {"type": "text", "text": e['content']}
                        ]
                    }
                    for e in question
                ]
            )
            response = nln_response.choices[0].message.content
        except Exception as e:
            print(f"NLN API调用出错: {str(e)}")
            response = "Error in calling nln api"

    elif llmType == 'gpt':
        response = openai_client.responses.create(
            model="gpt-5-nano",
            input=question
        ).output_text
    
    elif llmType == 'claude-4.5':
        response = openai_client.responses.create(
            model="anthropic/claude-haiku-4.5",
            input=question
        ).output_text

    # elif llmType=='local':
    #     try:
    #         # 调用本地模型生成回答
    #         conversation_str = ""
    #         for msg in question:
    #             conversation_str += f"{msg['role']}: {msg['content']}\n"
    #         response = local_model_generate(conversation_str, max_new_tokens=maxToken)
    #     except Exception as e:
    #         print(f"本地模型调用出错: {str(e)}")
    #         response = "抱歉，本地模型调用出现错误，请检查模型是否存在"
    
    else:
        response = 'no such model yet'
    
    return response

