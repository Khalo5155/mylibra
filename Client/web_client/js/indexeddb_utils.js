// ---------- IndexedDB 工具函数（修正版） ----------
function openDB() {
    return new Promise((resolve, reject) => {
        // 版本号从1提升到2，强制触发onupgradeneeded升级事件
        const request = indexedDB.open('ChatAppDB', 2);

        // 数据库升级/首次创建时触发
        request.onupgradeneeded = (e) => {
            const db = e.target.result;
            // 加固逻辑：如果settings仓库不存在则创建
            if (!db.objectStoreNames.contains('settings')) {
                db.createObjectStore('settings', { keyPath: 'key' });
            }
        };

        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
        // 新增：版本冲突阻塞处理
        request.onblocked = () => {
            console.warn('数据库版本更新被阻塞，请关闭其他同页面标签页后重试');
            reject(new Error('数据库更新被阻塞'));
        };
    });
}

// 保存键值对到IndexedDB
async function saveSetting(key, value) {
    const db = await openDB();
    return new Promise((resolve, reject) => {
        const transaction = db.transaction('settings', 'readwrite');
        const store = transaction.objectStore('settings');
        store.put({ key, value });
        transaction.oncomplete = () => {
            db.close(); // 操作完成主动关闭连接，避免多页面版本锁
            resolve();
        };
        transaction.onerror = () => {
            db.close();
            reject(transaction.error);
        };
    });
}

// 从IndexedDB读取值
async function getSetting(key) {
    const db = await openDB();
    return new Promise((resolve, reject) => {
        const transaction = db.transaction('settings', 'readonly');
        const store = transaction.objectStore('settings');
        const request = store.get(key);
        request.onsuccess = () => {
            db.close();
            resolve(request.result ? request.result.value : null);
        };
        request.onerror = () => {
            db.close();
            reject(request.error);
        };
    });
}

// 从IndexedDB删除键值对
async function deleteSetting(key) {
    const db = await openDB();
    return new Promise((resolve, reject) => {
        const transaction = db.transaction('settings', 'readwrite');
        const store = transaction.objectStore('settings');
        store.delete(key);
        transaction.oncomplete = () => {
            db.close();
            resolve();
        };
        transaction.onerror = () => {
            db.close();
            reject(transaction.error);
        };
    });
}