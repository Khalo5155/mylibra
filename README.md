# mylibra
带LLM长期记忆功能的AI角色扮演系统，支持基于本地GPT-SoVITS的TTS，支持远程访问（要自己弄到公网地址）。

本项目的TTS功能在GPT-SoVITS项目的基础上实现。
GPT-SoVITS b站视频：https://www.bilibili.com/video/BV14xS8BDE1w/?spm_id_from=333.337.search-card.all.click&vd_source=74de7d3031e7d0d9a418d929e351b377
GPT-SoVITS 项目文档：https://www.yuque.com/baicaigongchang1145haoyuangong/ib3g1e

# 当前内容：

基础API调用（LLM_basic）：
 - 管理多种模型的api client。

上下文工程（LLM_context）：
 - 模块化上下文：包括系统提示词、记忆模块、对话多级缓冲队列、中期提示词注入等模块。
 - user_input 处理：RAG部分+[时间标签]+[身份标签] + [user_input_text]。其中RAG部分是临时的，不会进入上下文历史中。

中短期记忆（上下文）：
 - 三级缓冲结构：一级缓冲存对话，二三级存压缩后文本，缓冲满后压缩内容并清空、逐级向上push。顶层缓冲满后对提示词中的所谓长期记忆部分（prompt_dict["memory"]）进行更新。当前三级缓冲理论上最多能存下15\*15\*10=2250轮对话信息，长期记忆那部分则是永远保持更新的总结性记忆。

长期记忆（持久化存储）：
 - 日记系统：分为文本模块（./saved_context/{IDENTITY}/diary/）和数据库模块（./vector_db/{IDENTITY}/diary/）。文本模块按日周月年四个jsonl存储；数据库模块统一存储、根据day/week/month/year的日期前缀进行区分。由自动化脚本（./diary/auto_trigger.py）在每天0点自动触发更新，调用日记提示词和人格模块让IDENTITY角色自己书写。

MCP（调试中，不稳定）：
 - chat_sister: 给另一台机器上运行的 mylibra 发消息。也可以是本地运行的另一个服务端。
 - search_diary: 按时间范围查日记。范围以日为单位，跨周月年的区间会被自动合并成对应的周记/月记/年记。最后返回拼接了所有查询结果的字符串。
 - use_cmd: 在隔离环境中使用受限的一些控制台命令。

TTS（TTS.py; [mylibra-TTS]）：
 - 给GPT-SoVITS做了个推理调用的接口，并能够运行在本地WebSocket服务器（asyncio）上，能接受文本请求，并按照指定参数（指定参考语音）返回TTS音频。

服务端（server.py）：
 - 需要公网ip。目前用的cpolar。
 - 与客户端（比如Android）建立WebSocket连接，接收文本数据（user-input），响应llm回复的文本和tts的音频。
 - 支持流式响应：实时切句，转TTS，再发送[文本-语音]分片。

客户端（[Mylibra_App_v1]）：
 - 本地STT：百度API。
 - 发送文本消息，处理响应文本和音频。适配了服务端的流式响应，用有序字典和音频队列实现音频播放的保序性。

其他模块：
 - LLM：实现对话的核心功能。其余功能被拆分到LLM_basic（API管理）和LLM_context（上下文管理）中。
 - Vdb：使用faiss数据库。
 - TTS：这个功能被抽离到子项目[mylibra-TTS]中实现了，主项目里它只负责调用。
 - STT：本地的语音识别。支持麦克风实时监听。*理想中还应该有个buffer，如果在LLM回复过程中又有了新的输入，就先存进buffer里，等回复结束后再发过去。
 - STT_LLM_TTS：本机的总流程，以及向 server.py 提供的接口类。
 - server：服务端实现。基于WebSocket。—— 目前的API-KEY还暴露在请求url中，后面找机会改掉
 - diary/: 自动写日记的监控程序，0点自动更新
 - [mylibra-TTS]：负责TTS的子项目。目前仅支持GPT-SoVITS的本地推理，如果以后要用其他模型的话，可能还得再写个单独的。把它抽离出来本身就是为了简化环境配置、避免这个项目和GPTSoVITS的项目杂糅。
 - [Mylibra_App_v1]：安卓客户端。用于远程通讯。

# 配置步骤：

- 主项目（mylibra）：
 1. 创建虚拟环境 conda create -n mylibra python=3.9
 2. 激活环境 conda activate mylibra
 3. 在项目目录（mylibra/）中打开cmd控制台，下载依赖包 pip install -r requirements.txt

- TTS 项目（mylibra-TTS）：
  1. 下载GPT-SoVITS的整合包（https://www.yuque.com/r/goto?url=https%3A%2F%2Fwww.modelscope.cn%2Fmodels%2FFlowerCry%2Fgpt-sovits-7z-pacakges%2Fresolve%2Fmaster%2FGPT-SoVITS-v2pro-20250604-nvidia50.7z）
  2. 解压缩后把该项目整个粘贴到根目录下（GPT-SoVITS-v2pro-20250604-nvidia50/mylibra-TTS/）
  3. 在整合包环境的基础上补全所需的额外依赖。在VSCode中打开GPTSoVITS整合包的根目录，在命令行中运行./runtime/python.exe -m pip install ... 来下载缺失的包。
