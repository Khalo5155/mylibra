// js/audio.js - 音频播放管理（Promise链实现，移除callback）
class AudioPlayer {
    // 单例实例
    static #instance;
    // 音频播放队列 [ { blob: Blob, url: string, name: string } ]
    #playQueue = [];
    // 播放状态锁（Promise链执行中）
    #isPlaying = false;
    // 音频播放核心元素
    #audioElement = null;
    // 当前播放的Promise控制器
    #currentPlayController = null;

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

    // 初始化音频元素
    #initAudioElement() {
        if (!this.#audioElement) {
            this.#audioElement = new Audio();
        }
    }

    // 创建Promise控制器（用于手动resolve/reject）
    #createController() {
        let resolve, reject;
        const promise = new Promise((res, rej) => {
            resolve = res;
            reject = rej;
        });
        return { promise, resolve, reject };
    }

    // Base64转音频Blob
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
            
            // 生成临时名称
            const name = `audio_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
            
            return { blob, url, name };
        } catch (e) {
            console.error('Base64转Blob失败', e);
            throw new Error('音频格式转换失败：' + e.message);
        }
    }

    // 添加音频到播放队列
    addAudioToQueue(audioItem) {
        if (!audioItem || !audioItem.blob || !audioItem.url) return false;
        
        this.#playQueue.push(audioItem);
        console.log(`音频已加入队列，当前队列长度：${this.#playQueue.length}`);
        
        // 添加后自动尝试播放（如果未在播放）
        if (!this.#isPlaying) {
            this.#processQueue();
        }
        return true;
    }

    // 处理播放队列（Promise链核心）
    async #processQueue() {
        if (this.#isPlaying || this.#playQueue.length === 0) return;

        this.#isPlaying = true;
        const currentAudio = this.#playQueue[0];

        try {
            // 播放当前音频（返回Promise）
            await this.#playAudioItem(currentAudio);
            
            // 播放成功：移除当前项并释放URL
            this.#playQueue.shift();
            URL.revokeObjectURL(currentAudio.url);
            console.log(`音频播放完成：${currentAudio.name}`);

        } catch (error) {
            // 播放失败：移除当前项并释放URL
            console.error(`音频播放失败：${currentAudio.name}`, error);
            this.#playQueue.shift();
            if (currentAudio.url) {
                URL.revokeObjectURL(currentAudio.url);
            }

        } finally {
            // 重置播放状态，继续处理下一个
            this.#isPlaying = false;
            this.#currentPlayController = null;
            this.#processQueue();
        }
    }

    // 播放单个音频项（返回Promise）
    #playAudioItem(audioItem) {
        return new Promise((resolve, reject) => {
            if (!audioItem || !audioItem.url) {
                reject(new Error('音频URL不存在'));
                return;
            }

            // 保存当前控制器，用于暂停/停止时手动reject
            this.#currentPlayController = { resolve, reject };

            // 重置音频元素事件
            this.#audioElement.onerror = (e) => {
                reject(new Error(`播放失败：${e.message || '未知错误'}`));
            };

            this.#audioElement.onended = () => {
                resolve();
            };

            // 开始播放
            try {
                this.#audioElement.src = audioItem.url;
                this.#audioElement.play().catch((e) => {
                    reject(new Error(`play()调用失败：${e.message}`));
                });
                console.log(`开始播放音频：${audioItem.name}`);
            } catch (e) {
                reject(new Error(`播放音频失败：${e.message}`));
            }
        });
    }

    // 播放单个音频（非队列模式，返回Promise）
    playSingleAudio(audioItem) {
        // 停止当前队列播放
        this.stop();

        return new Promise((resolve, reject) => {
            if (!audioItem || !audioItem.url) {
                reject(new Error('音频文件不存在'));
                return;
            }

            const cleanup = () => {
                this.#audioElement.removeEventListener('ended', onEnd);
                this.#audioElement.removeEventListener('error', onError);
            };

            const onEnd = () => {
                cleanup();
                URL.revokeObjectURL(audioItem.url);
                resolve();
            };

            const onError = (e) => {
                cleanup();
                URL.revokeObjectURL(audioItem.url);
                reject(new Error(`播放失败：${e.message || '未知错误'}`));
            };

            // 绑定事件
            this.#audioElement.addEventListener('ended', onEnd);
            this.#audioElement.addEventListener('error', onError);

            // 开始播放
            try {
                this.#audioElement.src = audioItem.url;
                this.#audioElement.play().catch((e) => {
                    cleanup();
                    reject(new Error(`play()调用失败：${e.message}`));
                });
                console.log(`开始播放单个音频：${audioItem.name}`);
            } catch (e) {
                cleanup();
                reject(new Error(`播放单个音频失败：${e.message}`));
            }
        });
    }

    // 批量添加音频分片并播放（新增：支持Promise链播放列表）
    playAudioList(audioItems) {
        if (!Array.isArray(audioItems) || audioItems.length === 0) {
            return Promise.reject(new Error('音频列表为空'));
        }

        // 停止当前播放
        this.stop();

        // 构建Promise链，逐个播放
        const playChain = audioItems.reduce((chain, audioItem) => {
            return chain.then(() => {
                if (!audioItem || !audioItem.url) {
                    return Promise.resolve(); // 跳过无效项
                }
                return this.playSingleAudio(audioItem);
            });
        }, Promise.resolve());

        return playChain;
    }

    // 停止播放并清空队列
    stop() {
        // 暂停当前音频
        if (this.#audioElement) {
            this.#audioElement.pause();
            this.#audioElement.src = '';
            
            // 手动reject当前播放的Promise
            if (this.#currentPlayController) {
                this.#currentPlayController.reject(new Error('播放已被停止'));
                this.#currentPlayController = null;
            }
        }

        // 清空队列并释放所有音频URL
        this.#playQueue.forEach(item => {
            if (item.url) URL.revokeObjectURL(item.url);
        });
        this.#playQueue = [];

        // 重置状态
        this.#isPlaying = false;
        console.log('音频已停止，队列已清空');
    }

    // 销毁音频播放器
    destroy() {
        // 停止播放
        this.stop();

        // 清理音频元素
        if (this.#audioElement) {
            this.#audioElement = null;
        }

        // 重置单例
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