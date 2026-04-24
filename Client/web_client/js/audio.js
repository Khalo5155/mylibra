// js/audio.js - 音频播放管理（参照安卓端AudioManager逻辑实现）
class AudioPlayer {
    // 单例实例
    static #instance;
    // 音频播放队列 [ { blob: Blob, url: string, name: string } ]
    #playQueue = [];
    // 播放状态锁
    #isPlaying = false;
    // 播放锁对象（保证队列操作原子性）
    #playLock = {};
    // 音频播放核心元素
    #audioElement = null;
    // 回调函数
    #callback = null;

    // 单例获取方法
    static getInstance() {
        if (!AudioPlayer.#instance) {
            AudioPlayer.#instance = new AudioPlayer();
        }
        return AudioPlayer.#instance;
    }

    constructor() {
        this.#initAudioElement();
    }

    // 初始化音频元素（对应安卓initMediaPlayer）
    #initAudioElement() {
        if (!this.#audioElement) {
            this.#audioElement = new Audio();
            // 播放错误监听
            this.#audioElement.onerror = (e) => {
                console.error('音频播放失败', e);
                const errorMsg = `播放失败：${e.message || '未知错误'}`;
                this.#callback?.onPlayError?.(errorMsg);
                
                this.#isPlaying = false;
                this.playAudioFromQueue(); // 继续播放下一个
            };

            // 播放完成监听
            this.#audioElement.onended = () => {
                console.log('音频播放完成');
                // 释放当前音频URL
                const currentAudio = this.#playQueue.shift();
                if (currentAudio?.url) {
                    URL.revokeObjectURL(currentAudio.url);
                }
                
                this.#isPlaying = false;
                this.playAudioFromQueue(); // 继续播放下一个
            };
        }
    }

    // 设置回调函数
    setCallback(callback) {
        this.#callback = callback;
    }

    // Base64转音频Blob（对应安卓createTempAudioFile）
    createAudioBlobFromBase64(base64Str, mimeType = 'audio/mpeg') {
        try {
            // 移除Base64前缀（如果有）
            const pureBase64 = base64Str.replace(/^data:audio\/\w+;base64,/, '');
            const byteCharacters = atob(pureBase64);
            const byteNumbers = new Array(byteCharacters.length);
            for (let i = 0; i < byteCharacters.length; i++) {
                byteNumbers[i] = byteCharacters.charCodeAt(i);
            }
            const byteArray = new Uint8Array(byteNumbers);
            const blob = new Blob([byteArray], { type: mimeType });
            const url = URL.createObjectURL(blob);
            
            // 生成临时名称（对应安卓临时文件前缀）
            const name = `audio_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
            
            return { blob, url, name };
        } catch (e) {
            console.error('Base64转Blob失败', e);
            this.#callback?.onPlayError?.('音频格式转换失败：' + e.message);
            return null;
        }
    }

    // 添加音频到播放队列（对应安卓addAudioToQueue）
    addAudioToQueue(audioItem) {
        if (!audioItem || !audioItem.blob || !audioItem.url) return;
        
        // 队列操作加锁（JS单线程，用同步锁即可）
        Object.freeze(this.#playLock);
        try {
            this.#playQueue.push(audioItem);
            console.log(`音频已加入队列，当前队列长度：${this.#playQueue.length}`);
        } finally {
            Object.seal(this.#playLock);
        }
    }

    // 从队列播放音频（对应安卓playAudioFromQueue）
    playAudioFromQueue() {
        // 队列操作加锁
        Object.freeze(this.#playLock);
        try {
            // 队列为空或正在播放，直接返回
            if (this.#playQueue.length === 0 || this.#isPlaying) return;
            
            this.#isPlaying = true;
            const currentAudio = this.#playQueue[0];
            
            // 音频不存在，清理并继续
            if (!currentAudio || !currentAudio.url) {
                this.#playQueue.shift();
                this.#isPlaying = false;
                this.playAudioFromQueue();
                return;
            }

            // 播放当前音频
            try {
                this.#audioElement.src = currentAudio.url;
                this.#audioElement.play();
                console.log(`开始播放音频：${currentAudio.name}`);
            } catch (e) {
                console.error('播放音频失败', e);
                this.#callback?.onPlayError?.('播放失败：' + e.message);
                // 释放URL并移除当前项
                URL.revokeObjectURL(currentAudio.url);
                this.#playQueue.shift();
                this.#isPlaying = false;
                this.playAudioFromQueue();
            }
        } finally {
            Object.seal(this.#playLock);
        }
    }

    // 播放单个音频（非队列模式，对应安卓playSingleAudio）
    playSingleAudio(audioItem) {
        if (!audioItem || !audioItem.url) {
            this.#callback?.onPlayError?.('音频文件不存在');
            return;
        }

        // 停止当前播放
        if (this.#isPlaying) {
            this.#audioElement.pause();
            this.#isPlaying = false;
        }

        // 移除旧的结束事件监听器
        const oldHandler = this.#audioElement.onended;
        if (oldHandler) {
            this.#audioElement.removeEventListener('ended', oldHandler);
        }

        const onSingleEnd = () => {
            console.log(`单个音频播放完成: ${audioItem.name}`);
            URL.revokeObjectURL(audioItem.url);
            this.#isPlaying = false;
            this.#audioElement.removeEventListener('ended', onSingleEnd);
            // 关键修复：确保回调被触发
            if (this.#callback?.onPlayComplete) {
                this.#callback.onPlayComplete();
            }
        };
        
        this.#audioElement.addEventListener('ended', onSingleEnd);
        
        // 错误处理
        this.#audioElement.onerror = (e) => {
            console.error('音频播放错误:', e);
            URL.revokeObjectURL(audioItem.url);
            this.#isPlaying = false;
            if (this.#callback?.onPlayError) {
                this.#callback.onPlayError('播放失败');
            }
            if (this.#callback?.onPlayComplete) {
                this.#callback.onPlayComplete();
            }
        };

        try {
            this.#audioElement.src = audioItem.url;
            this.#audioElement.play().catch(e => {
                console.error('play() 调用失败:', e);
                this.#audioElement.onerror(e);
            });
            this.#isPlaying = true;
            console.log(`开始播放单个音频: ${audioItem.name}`);
        } catch (e) {
            console.error('播放单个音频失败:', e);
            this.#callback?.onPlayError?.('播放失败：' + e.message);
            URL.revokeObjectURL(audioItem.url);
            this.#isPlaying = false;
            this.#callback?.onPlayComplete?.();
        }
    }

    // 销毁音频播放器（对应安卓onDestroy）
    destroy() {
        // 停止播放
        if (this.#audioElement) {
            this.#audioElement.pause();
            this.#audioElement.src = '';
            this.#audioElement = null;
        }

        // 清理队列并释放URL
        Object.freeze(this.#playLock);
        try {
            this.#playQueue.forEach(item => {
                if (item.url) URL.revokeObjectURL(item.url);
            });
            this.#playQueue = [];
        } finally {
            Object.seal(this.#playLock);
        }

        this.#isPlaying = false;
        this.#callback = null;
        AudioPlayer.#instance = null;
    }

    // 获取播放状态
    isPlaying() {
        return this.#isPlaying;
    }

    // 获取队列长度
    getQueueLength() {
        return this.#playQueue.length;
    }
}

// 暴露全局实例
window.AudioPlayer = AudioPlayer;