// js/chat.js - 聊天页面核心逻辑（适配Promise链音频播放）
document.addEventListener('DOMContentLoaded', function () {
    // ===================== DOM 元素获取 =====================
    const messageContainer = document.getElementById('message-container');
    const messageInput = document.getElementById('message-input');
    const sendBtn = document.getElementById('send-btn');
    const statusDot = document.getElementById('status-dot');
    const statusText = document.getElementById('status-text');
    const botRoleDisplay = document.getElementById('bot-role-display');

    // ===================== 全局变量 =====================
    let ws = null;
    let msgCount = 0;
    let aesCipher = null;
    const audioPlayer = AudioPlayer.getInstance();
    // 流式响应核心存储
    let streamClips = new Array(20).fill(null);
    let lastClipIndex = 0;
    let finalClipIndex = -1;
    let finalWaitTimer = null;
    let streamFullText = '';
    let currentStreamMessageEl = null;
    let currentStreamTextContent = '';
    let streamSaved = false;
    let currentBotRole = '';
    // 移除原pendingAudioQueue（改用AudioPlayer内部队列）
    // 音频分片列表
    let currentStreamAudioFragments = [];

    // ===================== IndexedDB 封装 =====================
    const DB_NAME = 'chatHistoryDB';
    const DB_VERSION = 1;
    const STORE_NAME = 'chatHistory';

    // 打开/创建 IndexedDB 数据库
    function openDB() {
        return new Promise((resolve, reject) => {
            const request = indexedDB.open(DB_NAME, DB_VERSION);

            // 数据库升级/初始化
            request.onupgradeneeded = (event) => {
                const db = event.target.result;
                // 创建对象仓库，主键自增，添加时间索引
                if (!db.objectStoreNames.contains(STORE_NAME)) {
                    const store = db.createObjectStore(STORE_NAME, { keyPath: 'id', autoIncrement: true });
                    store.createIndex('timeIndex', 'time', { unique: false });
                }
            };

            request.onsuccess = (event) => {
                resolve(event.target.result);
            };

            request.onerror = (event) => {
                console.error('IndexedDB 打开失败:', event.target.error);
                reject(event.target.error);
            };

            request.onblocked = () => {
                console.error('IndexedDB 被阻塞，请关闭其他标签页后重试');
                reject(new Error('数据库被阻塞'));
            };
        });
    }

    // 添加聊天记录到 IndexedDB
    async function addChatRecord(record) {
        try {
            const db = await openDB();
            const transaction = db.transaction(STORE_NAME, 'readwrite');
            const store = transaction.objectStore(STORE_NAME);
            
            // 添加新记录
            await store.add(record);
            
            // 检查并删除超过100条的旧记录
            await deleteOldRecords(db);
            
            db.close();
            return true;
        } catch (error) {
            console.error('保存聊天记录失败:', error);
            return false;
        }
    }

    // 删除超过100条的旧记录
    async function deleteOldRecords(db) {
        return new Promise((resolve, reject) => {
            const transaction = db.transaction(STORE_NAME, 'readwrite');
            const store = transaction.objectStore(STORE_NAME);
            const countRequest = store.count();

            countRequest.onsuccess = () => {
                const total = countRequest.result;
                if (total <= 100) {
                    resolve();
                    return;
                }

                // 获取需要删除的旧记录ID
                const deleteCount = total - 100;
                const index = store.index('timeIndex');
                const cursorRequest = index.openCursor(null, 'next');
                const deleteIds = [];

                cursorRequest.onsuccess = (event) => {
                    const cursor = event.target.result;
                    if (cursor && deleteIds.length < deleteCount) {
                        deleteIds.push(cursor.value.id);
                        cursor.continue();
                    } else {
                        // 执行删除
                        deleteIds.forEach(id => store.delete(id));
                        resolve();
                    }
                };

                cursorRequest.onerror = (err) => reject(err);
            };

            countRequest.onerror = (err) => reject(err);
        });
    }

    // 从 IndexedDB 获取所有聊天记录
    async function getAllChatRecords() {
        try {
            const db = await openDB();
            const transaction = db.transaction(STORE_NAME, 'readonly');
            const store = transaction.objectStore(STORE_NAME);
            const index = store.index('timeIndex');
            
            // 按时间升序获取所有记录
            const records = await new Promise((resolve, reject) => {
                const request = index.openCursor(null, 'next');
                const results = [];
                
                request.onsuccess = (event) => {
                    const cursor = event.target.result;
                    if (cursor) {
                        results.push(cursor.value);
                        cursor.continue();
                    } else {
                        resolve(results);
                    }
                };
                
                request.onerror = (err) => reject(err);
            });

            db.close();
            return records;
        } catch (error) {
            console.error('获取聊天记录失败:', error);
            return [];
        }
    }

    // ===================== AES 加解密实现 =====================
    class AESCipher {
        constructor(key) {
            this.key = CryptoJS.enc.Utf8.parse(this.padKey(key));
            this.mode = CryptoJS.mode.ECB;
            this.padding = CryptoJS.pad.Pkcs7;
        }
        padKey(key) {
            const keyBytes = CryptoJS.enc.Utf8.parse(key);
            if (keyBytes.sigBytes <= 16) return key.padEnd(16, '\0');
            if (keyBytes.sigBytes <= 24) return key.padEnd(24, '\0');
            return key.padEnd(32, '\0').slice(0, 32);
        }
        encrypt(rawText) {
            if (!rawText) return "";
            const encrypted = CryptoJS.AES.encrypt(
                CryptoJS.enc.Utf8.parse(rawText),
                this.key,
                { mode: this.mode, padding: this.padding }
            );
            return encrypted.toString();
        }
        decrypt(encText) {
            if (!encText) return "";
            try {
                const decrypted = CryptoJS.AES.decrypt(encText, this.key, { mode: this.mode, padding: this.padding });
                return decrypted.toString(CryptoJS.enc.Utf8);
            } catch (e) {
                console.error('AES解密失败', e);
                return encText;
            }
        }
        encryptBinary(dataBytes) {
            const wordArray = CryptoJS.lib.WordArray.create(dataBytes);
            const encrypted = CryptoJS.AES.encrypt(wordArray, this.key, { mode: this.mode, padding: this.padding });
            return encrypted.toString();
        }
        decryptBinary(encText) {
            if (!encText) return new Uint8Array();
            try {
                const decrypted = CryptoJS.AES.decrypt(encText, this.key, { mode: this.mode, padding: this.padding });
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
    function initAESCipher() {
        const aesKey = localStorage.getItem('aesKey');
        if (!aesKey) {
            alert('请先在配置页面设置AES密钥！');
            return false;
        }
        aesCipher = new AESCipher(aesKey);
        return true;
    }

    // 重构：异步加载聊天历史
    async function initChatHistory() {
        await loadChatHistory();
        // 仅当无历史记录时显示欢迎语
        if (messageContainer.querySelector('.empty-tip')) {
            addMessage('bot', '你好！我是你的智能聊天助手，有什么可以帮你的吗？', false, '默认助手');
        }
    }

    // 初始化时序调整
    setTimeout(async () => {
        await initChatHistory();
    }, 0);

    if (initAESCipher()) {
        initWebSocket();
    } else {
        updateConnectionStatus(false);
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
            // 异步关闭旧连接
            const closeOldWs = () => {
                return new Promise((resolve) => {
                    if (!ws) return resolve();
                    // 监听旧连接关闭事件
                    ws.onclose = () => {
                        ws = null;
                        resolve();
                    };
                    // 强制关闭（带标准关闭码）
                    ws.close(1000, 'Reconnect');
                    // 5秒兜底
                    setTimeout(resolve, 5000);
                });
            };

            // 先关旧连接，再建新连接
            closeOldWs().then(() => {
                const baseWsUrl = wsUrl.replace("http://", "ws://").replace("https://", "wss://");
                const finalWsUrl = `${baseWsUrl}/ws/llm-tts?api_key=${encodeURIComponent(apiKey)}&client_role=${encodeURIComponent(identity)}`;
                console.log('连接 WebSocket 地址：', finalWsUrl);
                
                ws = new WebSocket(finalWsUrl);
                
                // 添加10秒连接超时
                const connectTimeout = setTimeout(() => {
                    console.error('WebSocket连接超时');
                    ws.close(1002, 'Connection timeout');
                    updateConnectionStatus(false, '连接超时');
                    sendBtn.disabled = true;
                }, 10000);
                
                // 连接成功
                ws.onopen = function () {
                    clearTimeout(connectTimeout);
                    updateConnectionStatus(true);
                    sendBtn.disabled = false;
                };
                // 连接关闭
                ws.onclose = function () {
                    clearTimeout(connectTimeout);
                    updateConnectionStatus(false, '连接已断开');
                    sendBtn.disabled = true;
                };
                // 连接错误
                ws.onerror = function (err) {
                    clearTimeout(connectTimeout);
                    console.error('WebSocket 错误：', err);
                    updateConnectionStatus(false, '连接出错');
                    sendBtn.disabled = true;
                };
                // 消息处理逻辑
                ws.onmessage = function (event) {
                    try {
                        const responseData = JSON.parse(event.data);
                        if (responseData.role) {
                            currentBotRole = responseData.role;
                            botRoleDisplay.textContent = `当前角色：${currentBotRole}`;
                            botRoleDisplay.style.display = 'block';
                        }
                        handleServerMessage(responseData);
                    } catch (err) {
                        console.error('解析消息失败：', err);
                    }
                };
            });
        } catch (err) {
            console.error('WebSocket 初始化失败：', err);
            updateConnectionStatus(false, '初始化失败');
        }
    }

    // ===================== 发送消息 =====================
    function sendMessage() {
        const content = messageInput.value.trim();
        const identity = localStorage.getItem('identity');
        const useStream = localStorage.getItem('useStream') === 'true';
        const targetPort = localStorage.getItem('targetPort') || '5000';
        
        if (!content || !ws || ws.readyState !== WebSocket.OPEN || !aesCipher) return;

        const encryptedContent = aesCipher.encrypt(content);
        addMessage('user', content, true);
        messageInput.value = '';
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

    // ===================== 处理服务端消息 =====================
    function handleServerMessage(responseData) {
        if (responseData.type == 'server_response') {
            handleServerMessageText(responseData);
        } else if (responseData.type == 'server_stream_response') {
            handleServerMessageStream(responseData);
        }
    }

    // 非流式响应
    function handleServerMessageText(responseData) {
        try {
            const decryptedContent = aesCipher.decrypt(responseData.response);
            let audioBase64List = [];
            if (responseData.audio) {
                const decryptedAudio = aesCipher.decryptBinary(responseData.audio);
                audioBase64List = [uint8ArrayToBase64(decryptedAudio)];
            }
            const botRole = responseData.role || currentBotRole || '未知角色';
            addMessage('bot', decryptedContent, true, botRole, JSON.stringify(audioBase64List));
        } catch (err) {
            console.error('处理非流式消息失败：', err);
            addMessage('bot', '消息处理失败，请重试', false, '未知角色');
        }
    }

    // 流式响应
    function handleServerMessageStream(responseData) {
        try {
            const { stream_index, is_final } = responseData;
            
            if (stream_index === 0) {
                clearStreamBuffer();
            }

            expandStreamClipsIfNeeded(stream_index);
            streamClips[stream_index] = responseData;

            if (is_final) {
                finalClipIndex = stream_index;
                if (finalWaitTimer) clearTimeout(finalWaitTimer);
                finalWaitTimer = setTimeout(handleFinalClipTimeout, 10000);
            }

            checkAndProcessContinuousClips(stream_index);

        } catch (err) {
            console.error('处理流式消息失败：', err);
        }
    }

    // 动态扩展数组
    function expandStreamClipsIfNeeded(index) {
        if (index >= streamClips.length) {
            const expandLength = index + 1 - streamClips.length;
            streamClips = streamClips.concat(new Array(expandLength).fill(null));
            console.log(`streamClips数组已扩展，新长度：${streamClips.length}`);
        }
    }

    // 检查连续分片并处理
    function checkAndProcessContinuousClips(currentIndex) {
        let allReceived = true;
        for (let i = lastClipIndex; i <= currentIndex; i++) {
            if (streamClips[i] === null) {
                allReceived = false;
                break;
            }
        }

        if (allReceived) {
            for (let i = lastClipIndex; i <= currentIndex; i++) {
                const fragment = streamClips[i];
                parseStreamFragment(fragment);
                streamClips[i] = null;
            }
            lastClipIndex = currentIndex + 1;

            if (finalClipIndex !== -1 && lastClipIndex > finalClipIndex) {
                if (finalWaitTimer) clearTimeout(finalWaitTimer);
                saveStreamCompleteHistory();
            }
        } else {
            console.log(`分片 ${lastClipIndex} 到 ${currentIndex} 未完全接收，等待后续分片`);
        }
    }

    // 最终分片超时处理
    function handleFinalClipTimeout() {
        console.log('最终分片10秒超时，执行兜底处理');
        if (finalClipIndex >= 0) {
            for (let i = lastClipIndex; i <= finalClipIndex; i++) {
                if (streamClips[i] !== null) {
                    parseStreamFragment(streamClips[i]);
                    streamClips[i] = null;
                }
            }
            lastClipIndex = finalClipIndex + 1;
        }
        saveStreamCompleteHistory();
    }

    // 流式消息完成后统一保存历史
    function saveStreamCompleteHistory() {
        if (streamSaved) return;
        
        const finalText = streamFullText || currentStreamTextContent;
        const finalBotRole = currentBotRole || '未知角色';
        const audioFragmentsJson = JSON.stringify(currentStreamAudioFragments);

        if (finalText && finalText.trim()) {
            streamSaved = true;
            saveChatHistory('bot', finalText, audioFragmentsJson, finalBotRole);
            if (currentStreamMessageEl && currentStreamAudioFragments.length > 0) {
                addAudioPlayButton(currentStreamMessageEl, audioFragmentsJson);
            }
            console.log('流式消息历史保存完成，音频分片数：', currentStreamAudioFragments.length);
        }
        clearStreamBuffer();
    }

    // 解析单个分片
    function parseStreamFragment(fragment) {
        try {
            const { stream_index: idx, response, full_response, audio } = fragment;

            if (idx === -1) return;

            // 处理文本
            if (full_response) {
                const decryptedFullText = aesCipher.decrypt(full_response);
                if (decryptedFullText) {
                    streamFullText = decryptedFullText;
                    currentStreamTextContent = decryptedFullText;
                }
            } else if (response) {
                const decryptedResponse = aesCipher.decrypt(response);
                if (decryptedResponse) {
                    streamFullText += decryptedResponse;
                    currentStreamTextContent += decryptedResponse;
                }
            }

            // 处理音频（添加到AudioPlayer队列）
            if (audio) {
                console.log("parseStreamFragment: Process audio fragment", idx);
                const decryptedAudioBinary = aesCipher.decryptBinary(audio);
                if (decryptedAudioBinary.length > 0) {
                    const safeBase64 = uint8ArrayToBase64(decryptedAudioBinary);
                    currentStreamAudioFragments.push(safeBase64);
                    console.log("audio fragments count: "+currentStreamAudioFragments.length);
                    // 转换为audioItem并添加到播放队列（Promise链自动处理）
                    try {
                        const audioItem = audioPlayer.createAudioBlobFromBase64(safeBase64, 'audio/mpeg');
                        if (audioItem) {
                            audioPlayer.addAudioToQueue(audioItem);
                        }
                    } catch (e) {
                        console.error('创建音频Blob失败:', e);
                    }
                }
            }

            // 更新UI
            const botRole = fragment.role || currentBotRole || '未知角色';
            if (currentStreamTextContent) {
                updateStreamMessage(idx, currentStreamTextContent, botRole);
            }

        } catch (err) {
            console.error('解析流式分片失败:', err, fragment);
        }
    }

    // 按序播放音频分片列表（适配Promise链）
    function playAudioFragmentList(audioFragmentsJson, playBtn) {
        try {
            const audioFragments = JSON.parse(audioFragmentsJson);
            // 无音频分片时直接重置状态
            if (!Array.isArray(audioFragments) || audioFragments.length === 0) {
                if (playBtn) {
                    playBtn.textContent = '🔊 播放音频';
                    playBtn.dataset.isPlaying = 'false';
                }
                return;
            }
            
            // 转换为audioItem列表
            const audioItems = audioFragments.map(base64 => {
                return audioPlayer.createAudioBlobFromBase64(base64, 'audio/mpeg');
            }).filter(Boolean); // 过滤无效项

            // 使用AudioPlayer的Promise链播放列表
            audioPlayer.playAudioList(audioItems)
                .then(() => {
                    console.log('音频列表播放完成');
                    // 播放完成：重置按钮状态
                    if (playBtn) {
                        playBtn.textContent = '🔊 播放音频';
                        playBtn.dataset.isPlaying = 'false';
                    }
                })
                .catch((e) => {
                    console.error('音频列表播放失败:', e);
                    // 播放失败：也重置按钮状态
                    if (playBtn) {
                        playBtn.textContent = '🔊 播放音频';
                        playBtn.dataset.isPlaying = 'false';
                    }
                });
        } catch (err) {
            console.error('解析音频分片列表失败:', err);
            // 解析出错：重置按钮状态
            if (playBtn) {
                playBtn.textContent = '🔊 播放音频';
                playBtn.dataset.isPlaying = 'false';
            }
        }
    }

    // Uint8Array转Base64
    function uint8ArrayToBase64(uint8Array) {
        const CHUNK_SIZE = 8192;
        let binaryString = '';
        for (let i = 0; i < uint8Array.length; i += CHUNK_SIZE) {
            const chunk = uint8Array.slice(i, Math.min(i + CHUNK_SIZE, uint8Array.length));
            for (let j = 0; j < chunk.length; j++) {
                binaryString += String.fromCharCode(chunk[j]);
            }
        }
        return btoa(binaryString);
    }

    // 清空缓冲
    function clearStreamBuffer() {
        try {
            streamClips = new Array(20).fill(null);
            lastClipIndex = 0;
            finalClipIndex = -1;
            if (finalWaitTimer) clearTimeout(finalWaitTimer);
            finalWaitTimer = null;
            streamFullText = '';
            currentStreamTextContent = '';
            currentStreamMessageEl = null;
            currentStreamAudioFragments = [];
            streamSaved = false;
            
            console.log('流式缓冲已清空');
        } catch (err) {
            console.error('清空流式缓冲失败:', err);
        }
    }

    // 音频播放按钮（适配Promise链）
    function addAudioPlayButton(parentEl, audioData) {
        if (parentEl.querySelector('.audio-play-btn')) return;

        const playBtn = document.createElement('button');
        playBtn.className = 'audio-play-btn';
        playBtn.textContent = '🔊 播放音频';
        playBtn.style.marginTop = '5px';
        playBtn.style.padding = '3px 8px';
        playBtn.style.border = 'none';
        playBtn.style.borderRadius = '4px';
        playBtn.style.backgroundColor = '#007bff';
        playBtn.style.color = '#fff';
        playBtn.style.cursor = 'pointer';
        // 初始化播放状态到按钮的dataset属性
        playBtn.dataset.isPlaying = 'false';

        playBtn.addEventListener('click', () => {
            // 从dataset读取播放状态
            const isPlaying = playBtn.dataset.isPlaying === 'true';
            if (isPlaying) {
                // 停止播放
                audioPlayer.stop();
                playBtn.textContent = '🔊 播放音频';
                playBtn.dataset.isPlaying = 'false';
            } else {
                // 播放音频列表，传递按钮引用给播放函数
                playAudioFragmentList(audioData, playBtn);
                playBtn.textContent = '⏹️ 停止播放';
                playBtn.dataset.isPlaying = 'true';
            }
        });

        parentEl.appendChild(playBtn);
}

    // ===================== 流式消息UI更新 =====================
    function updateStreamMessage(streamIndex, text, botRole) {
        if (!currentStreamMessageEl) {
            currentStreamMessageEl = createBotMessageElement(streamIndex, text, botRole, '');
            messageContainer.appendChild(currentStreamMessageEl);
        } else {
            const contentEl = currentStreamMessageEl.querySelector('.message-content');
            if (contentEl) contentEl.textContent = text;
        }
        messageContainer.scrollTop = messageContainer.scrollHeight;
    }

    function createBotMessageElement(streamIndex, text, botRole, audioData = '') {
        if (messageContainer.querySelector('.empty-tip')) {
            messageContainer.innerHTML = '';
        }

        const messageDiv = document.createElement('div');
        messageDiv.className = 'message bot-message';
        messageDiv.setAttribute('data-stream-index', streamIndex);

        const roleDiv = document.createElement('div');
        roleDiv.className = 'message-role';
        roleDiv.textContent = botRole || '未知角色';

        const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        const contentDiv = document.createElement('div');
        contentDiv.className = 'message-content';
        contentDiv.textContent = text || '';
        const timeDiv = document.createElement('div');
        timeDiv.className = 'message-time';
        timeDiv.textContent = time;

        messageDiv.appendChild(roleDiv);
        messageDiv.appendChild(contentDiv);
        messageDiv.appendChild(timeDiv);

        if (audioData) addAudioPlayButton(messageDiv, audioData);
        return messageDiv;
    }

    // ===================== 消息渲染+历史 =====================
    function addMessage(role, content, saveToHistory = true, botRole = '', audioData = '') {
        if (messageContainer.querySelector('.empty-tip')) {
            messageContainer.innerHTML = '';
        }

        const div = document.createElement('div');
        div.className = role === 'user' ? 'message user-message' : 'message bot-message';

        const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        
        if (role === 'bot' && botRole) {
            const roleDiv = document.createElement('div');
            roleDiv.className = 'message-role';
            roleDiv.textContent = botRole;
            div.appendChild(roleDiv);
        }
        
        const contentDiv = document.createElement('div');
        contentDiv.textContent = content;
        const timeDiv = document.createElement('div');
        timeDiv.className = 'message-time';
        timeDiv.textContent = time;

        div.appendChild(contentDiv);
        div.appendChild(timeDiv);

        if (role === 'bot' && audioData) addAudioPlayButton(div, audioData);

        messageContainer.appendChild(div);
        messageContainer.scrollTop = messageContainer.scrollHeight;

        if (saveToHistory) saveChatHistory(role, content, audioData, botRole);
    }

    // 保存历史（异步函数）
    async function saveChatHistory(role, content, audioData = null, botRole = '') {
        if (!content && !audioData) return;
        const record = {
            role,
            content: content || '',
            audio: audioData || '',
            time: new Date().toISOString(),
            botRole: botRole || ''
        };
        await addChatRecord(record);
    }

    // 加载历史（异步函数）
    async function loadChatHistory() {
        const history = await getAllChatRecords();
        if (history.length === 0) {
            return;
        }
        
        messageContainer.innerHTML = '';
        history.forEach(item => {
            if (item.role === 'bot') {
                addMessage(item.role, item.content, false, item.botRole, item.audio);
            } else {
                addMessage(item.role, item.content, false);
            }
        });
    }

    // 连接状态
    function updateConnectionStatus(isOnline, text = '') {
        if (isOnline) {
            statusDot.className = 'status-dot online';
            statusText.textContent = text || '已连接';
        } else {
            statusDot.className = 'status-dot offline';
            statusText.textContent = text || '未连接';
        }
    }

    // 事件绑定
    sendBtn.addEventListener('click', sendMessage);
    messageInput.addEventListener('keypress', e => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
});

// 页面卸载销毁播放器
window.addEventListener('beforeunload', () => {
    const audioPlayer = AudioPlayer.getInstance();
    audioPlayer.destroy();
});