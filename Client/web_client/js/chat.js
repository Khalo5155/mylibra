// js/chat.js - 聊天页面核心逻辑（修复版）
document.addEventListener('DOMContentLoaded', function () {
    // ===================== DOM 元素获取 =====================
    const messageContainer = document.getElementById('message-container');
    const messageInput = document.getElementById('message-input');
    const sendBtn = document.getElementById('send-btn');
    const statusDot = document.getElementById('status-dot');
    const statusText = document.getElementById('status-text');

    // ===================== 全局变量 =====================
    let ws = null;
    let msgCount = 0;
    let aesCipher = null; // AES 加解密实例
    const audioPlayer = AudioPlayer.getInstance(); // 音频播放器
    let streamAudioBuffer = new Map(); // 缓存音频分片 {streamIndex: audioBase64}
    // 流式响应缓冲（对齐安卓端 WebSocketManager.java 逻辑）
    let streamBuffer = new Map(); // 有序存储分片 {streamIndex: responseData}，按streamIndex数值排序
    let lastStreamIndex = -1; // 上一个已处理的分片索引
    let streamFullText = ''; // 流式完整文本缓存（对齐安卓端StringBuilder）
    let currentStreamMessageEl = null; // 当前流式消息元素缓存
    let currentStreamTextContent = ''; // 当前累积的文本内容（修复1）
    let streamSaved = false; // 流式消息是否已保存

    // ===================== AES 加解密实现（和Python版本对齐） =====================
    class AESCipher {
        constructor(key) {
            // 密钥补全为16/24/32位（AES-128/192/256），和Python pad逻辑一致
            this.key = CryptoJS.enc.Utf8.parse(this.padKey(key));
            this.mode = CryptoJS.mode.ECB;
            this.padding = CryptoJS.pad.Pkcs7; // 对应Python的pad(PKCS7)
        }

        // 密钥补全（Python中key不足时会报错，前端做兼容补全）
        padKey(key) {
            const keyBytes = CryptoJS.enc.Utf8.parse(key);
            if (keyBytes.sigBytes <= 16) return key.padEnd(16, '\0');
            if (keyBytes.sigBytes <= 24) return key.padEnd(24, '\0');
            return key.padEnd(32, '\0').slice(0, 32);
        }

        // 加密文本（对应Python encrypt方法）
        encrypt(rawText) {
            if (!rawText) return "";
            const encrypted = CryptoJS.AES.encrypt(
                CryptoJS.enc.Utf8.parse(rawText),
                this.key,
                { mode: this.mode, padding: this.padding }
            );
            return encrypted.toString(); // Base64编码结果
        }

        // 解密文本（对应Python decrypt方法）
        decrypt(encText) {
            if (!encText) return "";
            try {
                const decrypted = CryptoJS.AES.decrypt(
                    encText,
                    this.key,
                    { mode: this.mode, padding: this.padding }
                );
                return decrypted.toString(CryptoJS.enc.Utf8);
            } catch (e) {
                console.error('AES解密失败', e);
                return encText; // 解密失败返回原文本
            }
        }

        // 加密二进制数据（对应Python encrypt_binary）
        encryptBinary(dataBytes) {
            const wordArray = CryptoJS.lib.WordArray.create(dataBytes);
            const encrypted = CryptoJS.AES.encrypt(
                wordArray,
                this.key,
                { mode: this.mode, padding: this.padding }
            );
            return encrypted.toString();
        }

        // 解密二进制数据（对应Python decrypt_binary）
        decryptBinary(encText) {
            if (!encText) return new Uint8Array();
            try {
                const decrypted = CryptoJS.AES.decrypt(
                    encText,
                    this.key,
                    { mode: this.mode, padding: this.padding }
                );
                // 转换为Uint8Array
                const bytes = [];
                const words = decrypted.words;
                for (let i = 0; i < decrypted.sigBytes; i++) {
                    const byte = (words[i >>> 2] >>> (24 - (i % 4) * 8)) & 0xff;
                    bytes.push(byte);
                }
                return new Uint8Array(bytes);
            } catch (e) {
                console.error('AES二进制解密失败', e);
                return new Uint8Array();
            }
        }
    }

    // ===================== 初始化 =====================
    // 初始化AES实例（从本地存储获取AES KEY）
    function initAESCipher() {
        const aesKey = localStorage.getItem('aesKey');
        if (!aesKey) {
            alert('请先在配置页面设置AES密钥！');
            return false;
        }
        aesCipher = new AESCipher(aesKey);
        return true;
    }

    loadChatHistory();
    // 先初始化AES，再初始化WebSocket
    if (initAESCipher()) {
        // 初始化音频播放器回调
        audioPlayer.setCallback({
            onPlayError: (errorMsg) => {
                console.error('音频播放错误：', errorMsg);
                // 可根据需要添加UI提示
                alert(errorMsg);
            }
        });
        initWebSocket();
    } else {
        updateConnectionStatus(false);
    }
    // 设置音频初始回调（不自动链接播放队列，由 playNextInQueue 自行管理）
    audioPlayer.setCallback({
        onPlayError: (errorMsg) => {
            console.error('音频播放错误：', errorMsg);
        },
        onPlayComplete: () => {
            console.log('音频播放完成');
        }
    });

    if (messageContainer.querySelector('.empty-tip')) {
        addMessage('bot', '你好！我是你的智能聊天助手，有什么可以帮你的吗？', false);
    }

    // ===================== WebSocket 连接 =====================
    function initWebSocket() {
        const wsUrl = localStorage.getItem('wsUrl');
        const apiKey = localStorage.getItem('apiKey');
        const identity = localStorage.getItem('identity');
        
        if (!wsUrl || !apiKey || !identity) {
            updateConnectionStatus(false);
            alert('请先完成所有配置（WebSocket地址/API Key/角色名/AES KEY）！');
            return;
        }

        try {
            if (ws) ws.close();

            // 拼接最终WS地址
            const baseWsUrl = wsUrl.replace("http://", "ws://").replace("https://", "wss://");
            const finalWsUrl = `${baseWsUrl}/ws/llm-tts?api_key=${encodeURIComponent(apiKey)}&client_role=${encodeURIComponent(identity)}`;
            console.log('连接 WebSocket 地址：', finalWsUrl);
            
            ws = new WebSocket(finalWsUrl);

            // WebSocket 事件监听
            ws.onopen = function () {
                updateConnectionStatus(true);
                sendBtn.disabled = false;
            };

            ws.onclose = function () {
                updateConnectionStatus(false, '连接已断开');
                sendBtn.disabled = true;
            };

            ws.onerror = function (err) {
                console.error('WebSocket 错误：', err);
                updateConnectionStatus(false, '连接出错');
                sendBtn.disabled = true;
            };

            ws.onmessage = function (event) {
                try {
                    const responseData = JSON.parse(event.data);
                    handleServerMessage(responseData);
                } catch (err) {
                    console.error('解析消息失败：', err);
                }
            };

        } catch (err) {
            console.error('WebSocket 初始化失败：', err);
            updateConnectionStatus(false, '初始化失败');
        }
    }

    // ===================== 发送消息（加密） =====================
    function sendMessage() {
        const content = messageInput.value.trim();
        const identity = localStorage.getItem('identity');
        const useStream = localStorage.getItem('useStream') === 'true';
        const targetPort = localStorage.getItem('targetPort') || '5000';
        console.log("Target port:"+targetPort)
        
        if (!content || !ws || ws.readyState !== WebSocket.OPEN || !aesCipher) return;

        // 加密用户消息
        const encryptedContent = aesCipher.encrypt(content);
        
        // 先保存用户消息到历史
        addMessage('user', content, true); // 显示原文，保存原文
        messageInput.value = '';

        // 发送新消息前清空流式缓冲（但不清理音频队列）
        clearStreamBuffer();
        
        msgCount++;
        const sendData = {
            message: encryptedContent,
            role: identity,
            mode: useStream ? 'stream' : 'normal',
            targetPort: parseInt(targetPort),
            msgCount: msgCount
        };

        ws.send(JSON.stringify(sendData));
    }

    // ===================== 处理服务端消息（解密） =====================
    function handleServerMessage(responseData) {
        if (responseData.type == 'server_response') {
            handleServerMessageText(responseData);
        } else if (responseData.type == 'server_stream_response') {
            handleServerMessageStream(responseData);
        }
    }

    // 非流式响应逻辑
    function handleServerMessageText(responseData) {
        try {
            // 解密文本内容
            const decryptedContent = aesCipher.decrypt(responseData.response);
            // 添加非流式消息到界面
            addMessage('bot', decryptedContent);
        } catch (err) {
            console.error('处理非流式消息失败：', err);
            addMessage('bot', '消息处理失败，请重试', false);
        }
    }

    // 流式响应逻辑（对齐安卓端 WebSocketManager.handleStreamResponse 逻辑）
    function handleServerMessageStream(responseData) {
        try {
            const { stream_index, is_final, response, full_response, audio } = responseData;
            
            // 1. 新流开始（stream_index=0）：重置缓冲和状态（对齐安卓端逻辑）
            if (stream_index === 0) {
                console.log('新流式响应开始，重置缓冲状态');
                clearStreamBuffer();
                lastStreamIndex = -1;
                streamFullText = '';
                currentStreamTextContent = ''; // 修复1：重置累积文本
                currentStreamMessageEl = null;
                // 解密full_response并初始化完整文本
                const decryptedFullText = aesCipher.decrypt(full_response);
                if (decryptedFullText) {
                    streamFullText = decryptedFullText;
                    currentStreamTextContent = decryptedFullText; // 修复1：设置累积文本
                }
            }

            // 2. 将当前分片存入缓冲队列
            streamBuffer.set(stream_index, responseData);

            // 3. 处理可消费的分片（按顺序处理，对齐安卓端processNextStreamFragment）
            processNextStreamFragment();

            // 4. 如果是最终分片
            if (is_final) {
                // 最终分片处理完后清空缓冲
                setTimeout(() => clearStreamBuffer(), 1000);
            }
        } catch (err) {
            console.error('处理流式消息失败：', err);
        }
    }

    // 处理可消费的流式分片（对齐安卓端processNextStreamFragment）
    function processNextStreamFragment(maxDepth = 20, currentDepth = 0) {
        try {
            // 终止条件1：超过最大递归深度
            if (currentDepth >= maxDepth) {
                console.warn('递归深度超限，终止流式分片处理');
                clearStreamBuffer(); // 清空缓冲避免死循环
                return;
            }

            const expectedIndex = lastStreamIndex + 1;
            if (streamBuffer.has(expectedIndex)) {
                const fragment = streamBuffer.get(expectedIndex);
                streamBuffer.delete(expectedIndex);
                parseStreamFragment(fragment);
                // 递归调用时增加深度计数
                processNextStreamFragment(maxDepth, currentDepth + 1);
            }
        } catch (err) {
            console.error('处理流式分片队列失败：', err);
            // 终止递归
            return;
        }
    }

    // 音频播放队列
    let pendingAudioQueue = []; // 待播放音频队列

    // 解析单个流式分片
    function parseStreamFragment(fragment) {
        let stream_index = -1;
        try {
            const { stream_index: idx, response, full_response, is_final, audio } = fragment;
            stream_index = idx;

            if (stream_index === -1) return;

            // 1. 处理文本（修复：full_response 和 response 互斥处理）
            if (full_response) {
                // full_response 包含完整文本，直接替换
                const decryptedFullText = aesCipher.decrypt(full_response);
                if (decryptedFullText) {
                    streamFullText = decryptedFullText;
                    currentStreamTextContent = decryptedFullText;
                }
            } else if (response) {
                // 没有 full_response 时，response 作为增量追加
                const decryptedResponse = aesCipher.decrypt(response);
                if (decryptedResponse) {
                    streamFullText += decryptedResponse;
                    currentStreamTextContent += decryptedResponse;
                }
            }

            // 2. 处理音频
            if (audio) {
                const decryptedAudioBinary = aesCipher.decryptBinary(audio);
                if (decryptedAudioBinary.length > 0) {
                    const safeBase64 = uint8ArrayToBase64(decryptedAudioBinary);
                    playAudioFragment(safeBase64);
                }
            }

            // 3. 更新UI
            if (currentStreamTextContent) {
                updateStreamMessage(stream_index, currentStreamTextContent, [], false);
            }

            // 4. 处理最终分片
            if (is_final) {
                const finalText = currentStreamTextContent;
                
                // 重置保存标记
                streamSaved = false;
                
                if (pendingAudioQueue.length > 0 || audioPlayer.isPlaying()) {
                    const checkQueueInterval = setInterval(() => {
                        if (!streamSaved && pendingAudioQueue.length === 0 && !audioPlayer.isPlaying()) {
                            clearInterval(checkQueueInterval);
                            streamSaved = true;
                            finalizeAndSaveStream(finalText, stream_index);
                        }
                    }, 500);
                    
                    setTimeout(() => {
                        if (!streamSaved) {
                            clearInterval(checkQueueInterval);
                            streamSaved = true;
                            finalizeAndSaveStream(finalText, stream_index);
                        }
                    }, 10000);
                } else {
                    if (!streamSaved) {
                        streamSaved = true;
                        finalizeAndSaveStream(finalText, stream_index);
                    }
                }
            }

            lastStreamIndex = stream_index;

        } catch (err) {
            console.error('解析流式分片失败:', err, fragment);
            if (stream_index !== -1) {
                lastStreamIndex = stream_index;
            }
        }
    }

    // 新增：完成流式消息并保存历史
    function finalizeAndSaveStream(finalText, streamIndex) {
        // // 1. 更新UI为最终状态，但不立即清空缓冲
        // updateStreamMessage(streamIndex, finalText, [], true);
        
        // 2. 保存聊天历史（在清空缓冲之前）
        if (finalText && finalText.trim()) {
            saveChatHistory('bot', finalText, null);
        }
        
        // 3. 延迟清空缓冲（给UI更新留出时间）
        setTimeout(() => {
            // 只清空流式缓冲，保留音频队列
            streamBuffer.clear();
            // 注意：不调用 clearStreamBuffer()，避免清空 pendingAudioQueue
        }, 500);
    }

    // 新增：播放单个音频片段（自动排队播放）
    function playAudioFragment(audioBase64) {
        if (!audioBase64 || typeof audioBase64 !== 'string' || audioBase64.length === 0) {
            console.warn('playAudioFragment: 音频数据无效');
            return;
        }
        
        console.log(`准备播放音频片段，当前队列长度: ${pendingAudioQueue.length}, 是否正在播放: ${audioPlayer.isPlaying()}`);
        
        // 转换Base64为音频项
        const audioItem = audioPlayer.createAudioBlobFromBase64(audioBase64, 'audio/mpeg');
        if (!audioItem) {
            console.error('音频转换失败');
            return;
        }
        
        // 将音频加入待播放队列
        pendingAudioQueue.push(audioItem);
        
        // 关键修复：如果当前没有正在播放的音频，立即开始播放
        if (!audioPlayer.isPlaying()) {
            console.log('开始播放音频队列');
            playNextInQueue();
        } else {
            console.log('音频已加入队列，等待当前播放完成');
        }
    }
    
    // 播放队列中的下一个音频
    function playNextInQueue() {
        if (pendingAudioQueue.length === 0) {
            console.log('音频队列已空，停止播放');
            // 恢复默认回调，避免循环触发
            audioPlayer.setCallback({
                onPlayError: (errorMsg) => {
                    console.error('音频播放错误:', errorMsg);
                },
                onPlayComplete: () => {
                    console.log('音频播放完成，队列为空');
                }
            });
            return;
        }
        
        const audioItem = pendingAudioQueue.shift();
        console.log(`播放剩余 ${pendingAudioQueue.length} 个音频`);
        
        if (audioItem && audioItem.url) {
            // 设置播放完成回调
            audioPlayer.setCallback({
                onPlayError: (errorMsg) => {
                    console.error('音频播放错误:', errorMsg);
                    // 释放当前音频资源
                    if (audioItem.url) URL.revokeObjectURL(audioItem.url);
                    // 继续播放下一个
                    playNextInQueue();
                },
                onPlayComplete: () => {
                    console.log('当前音频播放完成');
                    // 释放当前音频资源
                    if (audioItem.url) URL.revokeObjectURL(audioItem.url);
                    // 继续播放下一个
                    playNextInQueue();
                }
            });
            
            audioPlayer.playSingleAudio(audioItem);
        } else {
            console.warn('音频项无效，跳过');
            playNextInQueue();
        }
    }

    // 新增：重新绑定音频播放按钮
    function rebindAudioPlayButton(streamIndex, fullAudioBase64) {
        if (!currentStreamMessageEl || !fullAudioBase64) return;
        
        const audioBtn = currentStreamMessageEl.querySelector('.audio-play');
        if (audioBtn) {
            audioBtn.style.display = fullAudioBase64 ? 'inline' : 'none';
            
            // 移除旧的事件监听器，绑定新的
            const newBtn = audioBtn.cloneNode(true);
            audioBtn.parentNode.replaceChild(newBtn, audioBtn);
            
            newBtn.addEventListener('click', () => {
                playAudioQueue([fullAudioBase64]);
            });
        }
    }

    // 安全地将 Uint8Array 转换为 Base64（分块转换，避免展开运算符爆栈）
    function uint8ArrayToBase64(uint8Array) {
        // 分块大小：每批处理 8192 字节
        const CHUNK_SIZE = 8192;
        let binaryString = '';
        
        for (let i = 0; i < uint8Array.length; i += CHUNK_SIZE) {
            const chunk = uint8Array.slice(i, Math.min(i + CHUNK_SIZE, uint8Array.length));
            // 使用循环避免展开运算符
            for (let j = 0; j < chunk.length; j++) {
                binaryString += String.fromCharCode(chunk[j]);
            }
        }
        
        // 一次性对整个字符串做 btoa
        return btoa(binaryString);
    }

    // 清空流式缓冲
    function clearStreamBuffer() {
        try {
            streamBuffer.clear();
            streamFullText = '';
            currentStreamTextContent = '';
            lastStreamIndex = -1;
            currentStreamMessageEl = null;
            streamAudioBuffer.clear();
            // 关键修复：不要清空 pendingAudioQueue，否则会导致音频中断
            console.log('流式缓冲已清空，音频队列保留');
        } catch (err) {
            console.error('清空流式缓冲失败:', err);
        }
    }

    // ===================== 流式消息UI更新 =====================
    function updateStreamMessage(streamIndex, text, audioList, isFinal = false) {
        // 复用当前流式消息元素
        if (!currentStreamMessageEl) {
            currentStreamMessageEl = createBotMessageElement(streamIndex, text);
            messageContainer.appendChild(currentStreamMessageEl);
        } else {
            const contentEl = currentStreamMessageEl.querySelector('.message-content');
            if (contentEl) {
                contentEl.textContent = text; // 修复1：显示完整累积文本
            }
        }

        // 滚动到底部
        messageContainer.scrollTop = messageContainer.scrollHeight;
    }

    function createBotMessageElement(streamIndex, text) {
        // 移除空提示
        if (messageContainer.querySelector('.empty-tip')) {
            messageContainer.innerHTML = '';
        }

        const messageDiv = document.createElement('div');
        messageDiv.className = 'message bot-message';
        messageDiv.setAttribute('data-stream-index', streamIndex);

        const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        
        const contentDiv = document.createElement('div');
        contentDiv.className = 'message-content';
        contentDiv.textContent = text || '';
        
        const timeDiv = document.createElement('div');
        timeDiv.className = 'message-time';
        timeDiv.textContent = time;

        messageDiv.appendChild(contentDiv);
        messageDiv.appendChild(timeDiv);

        return messageDiv;
    }

    // ===================== TTS 音频播放 =====================
    function playAudioQueue(audioBase64List) {
        if (!audioBase64List || audioBase64List.length === 0) {
            console.warn('playAudioQueue: 没有音频数据');
            return;
        }
        
        console.log(`准备播放 ${audioBase64List.length} 个音频片段`);
        
        // 将Base64列表转为音频项并加入队列
        audioBase64List.forEach((base64, index) => {
            if (base64 && typeof base64 === 'string' && base64.length > 0) {
                const audioItem = base64ToBlob(base64, 'audio/mpeg');
                if (audioItem) {
                    audioPlayer.addAudioToQueue(audioItem);
                    console.log(`音频片段 ${index + 1} 已加入播放队列`);
                } else {
                    console.error(`音频片段 ${index + 1} 转换失败`);
                }
            } else {
                console.warn(`音频片段 ${index + 1} 为空或无效`);
            }
        });
        
        // 开始播放队列
        audioPlayer.playAudioFromQueue();
    }

    function playNextAudio() {
        // 直接调用队列播放逻辑
        audioPlayer.playAudioFromQueue();
    }

    function base64ToBlob(base64, mimeType) {
        return audioPlayer.createAudioBlobFromBase64(base64, mimeType);
    }

    // ===================== 聊天历史 =====================
    function addMessage(role, content, saveToHistory = true) {
        // 移除空提示
        if (messageContainer.querySelector('.empty-tip')) {
            messageContainer.innerHTML = '';
        }

        const div = document.createElement('div');
        div.className = role === 'user' ? 'message user-message' : 'message bot-message';

        const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        
        // 修复：使用安全的文本插入方式，避免HTML解析问题
        const contentDiv = document.createElement('div');
        contentDiv.textContent = content;
        
        const timeDiv = document.createElement('div');
        timeDiv.className = 'message-time';
        timeDiv.textContent = time;
        
        div.appendChild(contentDiv);
        div.appendChild(timeDiv);

        messageContainer.appendChild(div);
        messageContainer.scrollTop = messageContainer.scrollHeight;

        if (saveToHistory) saveChatHistory(role, content);
    }

    function saveChatHistory(role, content, audio = null) {
        // 安全检查：确保有有效内容
        if (!content && !audio) {
            console.warn('saveChatHistory: 没有可保存的内容');
            return;
        }

        const history = JSON.parse(localStorage.getItem('chatHistory') || '[]');
        
        // 对于流式消息，如果音频为 null，尝试从音频队列获取
        let audioBase64 = audio || '';
        
        history.push({ 
            role, 
            content: content || '',  // 确保至少为空字符串
            audio: audioBase64,
            time: new Date().toISOString(),
            isStream: role === 'bot' && !audio  // 标记是否为流式消息
        });
        
        // 限制历史记录数量
        if (history.length > 100) {
            history.shift();
        }
        
        localStorage.setItem('chatHistory', JSON.stringify(history));
    }

    function loadChatHistory() {
        const history = JSON.parse(localStorage.getItem('chatHistory') || '[]');
        if (history.length === 0) return;
        messageContainer.innerHTML = '';
        
        history.forEach(item => {
            if (item.role === 'bot' && item.audio) {
                // 创建带播放按钮的bot消息
                const msgEl = createBotMessageElement(Date.now(), item.content);
                messageContainer.appendChild(msgEl);
            } else {
                addMessage(item.role, item.content, false);
            }
        });
    }

    // ===================== 连接状态更新 =====================
    function updateConnectionStatus(isOnline, text = '') {
        if (isOnline) {
            statusDot.className = 'status-dot online';
            statusText.textContent = text || '已连接';
        } else {
            statusDot.className = 'status-dot offline';
            statusText.textContent = text || '未连接';
        }
    }

    // ===================== 事件绑定 =====================
    sendBtn.addEventListener('click', sendMessage);
    messageInput.addEventListener('keypress', e => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault(); // 阻止换行
            sendMessage();
        }
    });
});

// 页面卸载时销毁音频播放器
window.addEventListener('beforeunload', () => {
    const audioPlayer = AudioPlayer.getInstance();
    audioPlayer.destroy();
});