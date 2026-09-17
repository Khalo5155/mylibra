// ============================================================
        // 使用 IndexedDB 存储图片（解决大图传输问题）
        // ============================================================

        const DB_NAME = 'BackgroundDB';
        const STORE_NAME = 'backgrounds';
        const DB_VERSION = 1;

        // DOM 元素
        const uploadArea = document.getElementById('uploadArea');
        const fileInput = document.getElementById('fileInput');
        const previewContainer = document.getElementById('previewContainer');
        const previewImage = document.getElementById('previewImage');
        const fileName = document.getElementById('fileName');
        const fileSize = document.getElementById('fileSize');
        const applyBtn = document.getElementById('applyBtn');
        const removeBtn = document.getElementById('removeBtn');
        const opacitySlider = document.getElementById('opacitySlider');
        const opacityValue = document.getElementById('opacityValue');
        const statusMessage = document.getElementById('statusMessage');
        const statusText = document.getElementById('statusText');
        const bgStatus = document.getElementById('bgStatus');
        const storageUsed = document.getElementById('storageUsed');
        const clearStorageBtn = document.getElementById('clearStorageBtn');

        // ============================================================
        // IndexedDB 工具函数
        // ============================================================

        function openDB() {
            return new Promise((resolve, reject) => {
                const request = indexedDB.open(DB_NAME, DB_VERSION);
                request.onupgradeneeded = (event) => {
                    const db = event.target.result;
                    if (!db.objectStoreNames.contains(STORE_NAME)) {
                        db.createObjectStore(STORE_NAME, { keyPath: 'id' });
                    }
                };
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error);
            });
        }

        async function saveImageToDB(id, data) {
            const db = await openDB();
            return new Promise((resolve, reject) => {
                const tx = db.transaction(STORE_NAME, 'readwrite');
                const store = tx.objectStore(STORE_NAME);
                const request = store.put({ id, data, timestamp: Date.now() });
                request.onsuccess = () => resolve();
                request.onerror = () => reject(request.error);
                tx.oncomplete = () => db.close();
            });
        }

        async function getImageFromDB(id) {
            const db = await openDB();
            return new Promise((resolve, reject) => {
                const tx = db.transaction(STORE_NAME, 'readonly');
                const store = tx.objectStore(STORE_NAME);
                const request = store.get(id);
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error);
                tx.oncomplete = () => db.close();
            });
        }

        async function deleteImageFromDB(id) {
            const db = await openDB();
            return new Promise((resolve, reject) => {
                const tx = db.transaction(STORE_NAME, 'readwrite');
                const store = tx.objectStore(STORE_NAME);
                const request = store.delete(id);
                request.onsuccess = () => resolve();
                request.onerror = () => reject(request.error);
                tx.oncomplete = () => db.close();
            });
        }

        async function getAllImages() {
            const db = await openDB();
            return new Promise((resolve, reject) => {
                const tx = db.transaction(STORE_NAME, 'readonly');
                const store = tx.objectStore(STORE_NAME);
                const request = store.getAll();
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error);
                tx.oncomplete = () => db.close();
            });
        }

        async function getStorageSize() {
            const items = await getAllImages();
            let totalSize = 0;
            items.forEach(item => {
                if (item.data) {
                    totalSize += item.data.length;
                }
            });
            return totalSize;
        }

        // ============================================================
        // 核心功能
        // ============================================================

        let currentFileData = null; // { base64, name, size, type }
        let currentImageId = 'bg_image';

        // 初始化
        document.addEventListener('DOMContentLoaded', async function() {
            // 加载保存的透明度
            const savedOpacity = localStorage.getItem('bgOpacity');
            if (savedOpacity) {
                opacitySlider.value = savedOpacity;
                opacityValue.textContent = Math.round(parseFloat(savedOpacity) * 100) + '%';
            }

            // 从 IndexedDB 加载已保存的背景
            await loadSavedBackground();

            // 更新存储信息
            await updateStorageInfo();

            // 向父页面请求当前背景（用于同步）
            if (window.parent !== window) {
                window.parent.postMessage({ type: 'requestBackground' }, '*');
            }
        });

        // 监听父页面消息
        window.addEventListener('message', async function(event) {
            const data = event.data;
            if (!data) return;

            if (data.type === 'updateBackground') {
                // 父页面通知更新背景（通常是来自另一个 iframe 的同步）
                if (data.bgImage) {
                    // 如果收到的是 base64，保存到 IndexedDB
                    await saveImageToDB(currentImageId, data.bgImage);
                    await applyBackgroundFromDB();
                } else {
                    await deleteImageFromDB(currentImageId);
                    await clearBackgroundDisplay();
                }
            }

            if (data.type === 'requestBackground') {
                // 父页面请求背景配置，发送当前背景
                const saved = await getImageFromDB(currentImageId);
                if (saved && saved.data) {
                    const opacity = parseFloat(opacitySlider.value);
                    window.parent.postMessage({
                        type: 'updateBackground',
                        bgImage: saved.data,
                        bgOpacity: opacity
                    }, '*');
                }
            }
        });

        // ============================================================
        // 上传与预览
        // ============================================================

        uploadArea.addEventListener('click', () => fileInput.click());

        uploadArea.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadArea.classList.add('dragover');
        });

        uploadArea.addEventListener('dragleave', () => {
            uploadArea.classList.remove('dragover');
        });

        uploadArea.addEventListener('drop', (e) => {
            e.preventDefault();
            uploadArea.classList.remove('dragover');
            if (e.dataTransfer.files.length) {
                handleFile(e.dataTransfer.files[0]);
            }
        });

        fileInput.addEventListener('change', (e) => {
            if (e.target.files.length) {
                handleFile(e.target.files[0]);
            }
        });

        function handleFile(file) {
            if (!file.type.startsWith('image/')) {
                showStatus('请上传图片文件！', 'error');
                return;
            }

            // 限制文件大小 10MB
            if (file.size > 10 * 1024 * 1024) {
                showStatus('图片太大！请选择小于 10MB 的图片', 'error');
                return;
            }

            showStatus('正在读取图片...', 'loading');

            const reader = new FileReader();
            reader.onload = function(e) {
                const base64 = e.target.result;
                const sizeInKB = (base64.length * 3 / 4) / 1024;

                // 显示预览
                previewImage.src = base64;
                previewContainer.classList.add('show');
                fileName.textContent = file.name;
                fileSize.textContent = `(${sizeInKB.toFixed(1)} KB)`;

                currentFileData = {
                    base64: base64,
                    name: file.name,
                    size: file.size,
                    type: file.type
                };

                applyBtn.disabled = false;
                hideStatus();
                showStatus('图片已加载，点击"应用到背景"生效', 'info');
            };

            reader.onerror = function() {
                showStatus('读取文件失败，请重试', 'error');
            };

            reader.readAsDataURL(file);
        }

        // ============================================================
        // 应用背景
        // ============================================================

        applyBtn.addEventListener('click', async function() {
            if (!currentFileData) return;

            try {
                applyBtn.disabled = true;
                applyBtn.textContent = '保存中...';
                showStatus('正在保存背景...', 'loading');

                // 1. 保存到 IndexedDB
                await saveImageToDB(currentImageId, currentFileData.base64);

                // 2. 应用到页面
                await applyBackgroundFromDB();

                // 3. 同步到父页面和其他 iframe
                syncToParent(currentFileData.base64);

                // 4. 更新存储信息
                await updateStorageInfo();

                showStatus('✅ 背景已应用成功！', 'success');
                bgStatus.textContent = '已设置 ✓';
                bgStatus.style.color = '#1a8a1a';

            } catch (err) {
                console.error('保存失败:', err);
                showStatus('保存失败，请重试', 'error');
            } finally {
                applyBtn.disabled = false;
                applyBtn.textContent = '应用到背景';
            }
        });

        // ============================================================
        // 从 IndexedDB 加载并应用背景
        // ============================================================

        async function loadSavedBackground() {
            try {
                const saved = await getImageFromDB(currentImageId);
                if (saved && saved.data) {
                    // 显示预览
                    previewImage.src = saved.data;
                    previewContainer.classList.add('show');
                    fileName.textContent = '已保存的背景';
                    const sizeInKB = (saved.data.length * 3 / 4) / 1024;
                    fileSize.textContent = `(${sizeInKB.toFixed(1)} KB)`;
                    currentFileData = { base64: saved.data };

                    // 应用到页面
                    await applyBackgroundFromDB();

                    bgStatus.textContent = '已设置 ✓';
                    bgStatus.style.color = '#1a8a1a';
                    applyBtn.disabled = false;

                    // 同步到父页面
                    syncToParent(saved.data);
                }
            } catch (err) {
                console.warn('加载保存的背景失败:', err);
            }
        }

        async function applyBackgroundFromDB() {
            const saved = await getImageFromDB(currentImageId);
            if (saved && saved.data) {
                const opacity = parseFloat(opacitySlider.value);
                // 应用到本页面
                document.body.style.setProperty('--bg-image', `url(${saved.data})`);
                document.body.style.setProperty('--bg-opacity', opacity);
                // 保存到 localStorage 供其他页面快速读取
                localStorage.setItem('bgImage', saved.data);
                localStorage.setItem('bgOpacity', opacity);
            }
        }

        async function clearBackgroundDisplay() {
            document.body.style.setProperty('--bg-image', 'none');
            document.body.style.setProperty('--bg-opacity', '0');
            previewContainer.classList.remove('show');
            currentFileData = null;
            applyBtn.disabled = true;
            bgStatus.textContent = '未设置';
            bgStatus.style.color = '#888';
            localStorage.removeItem('bgImage');
            localStorage.removeItem('bgOpacity');
            await updateStorageInfo();
        }

        // ============================================================
        // 同步到父页面
        // ============================================================

        function syncToParent(base64) {
            if (window.parent === window) return;

            const opacity = parseFloat(opacitySlider.value);

            // 直接发送 base64（现在从 IndexedDB 读取，数据已经存在）
            // 如果图片太大，父页面会自行处理
            try {
                window.parent.postMessage({
                    type: 'updateBackground',
                    bgImage: base64,
                    bgOpacity: opacity
                }, '*');
            } catch (e) {
                console.warn('同步到父页面失败（可能图片过大），但本地已保存', e);
                // 即使发送失败，本地已经保存成功
                showStatus('⚠️ 背景已本地保存，但同步到主页面失败（图片可能过大），刷新后生效', 'info');
            }
        }

        // ============================================================
        // 移除背景
        // ============================================================

        removeBtn.addEventListener('click', async function() {
            try {
                await deleteImageFromDB(currentImageId);
                await clearBackgroundDisplay();

                // 通知父页面移除背景
                if (window.parent !== window) {
                    window.parent.postMessage({
                        type: 'updateBackground',
                        bgImage: null,
                        bgOpacity: parseFloat(opacitySlider.value)
                    }, '*');
                }

                showStatus('已移除背景', 'success');
            } catch (err) {
                console.error('移除失败:', err);
                showStatus('移除失败，请重试', 'error');
            }
        });

        // ============================================================
        // 透明度控制
        // ============================================================

        opacitySlider.addEventListener('input', async function() {
            const val = parseFloat(this.value);
            opacityValue.textContent = Math.round(val * 100) + '%';

            // 如果有保存的背景，实时更新透明度
            const saved = await getImageFromDB(currentImageId);
            if (saved && saved.data) {
                document.body.style.setProperty('--bg-opacity', val);
                localStorage.setItem('bgOpacity', val);

                // 同步到父页面
                if (window.parent !== window) {
                    window.parent.postMessage({
                        type: 'updateBackground',
                        bgImage: saved.data,
                        bgOpacity: val
                    }, '*');
                }
            }
        });

        // ============================================================
        // 存储信息
        // ============================================================

        async function updateStorageInfo() {
            try {
                const size = await getStorageSize();
                const sizeKB = (size / 1024).toFixed(1);
                const sizeMB = (size / (1024 * 1024)).toFixed(2);
                if (size > 1024 * 1024) {
                    storageUsed.textContent = `${sizeMB} MB`;
                } else {
                    storageUsed.textContent = `${sizeKB} KB`;
                }
            } catch (e) {
                storageUsed.textContent = '未知';
            }
        }

        clearStorageBtn.addEventListener('click', async function() {
            if (confirm('确定要清除所有存储的背景图片吗？')) {
                try {
                    const db = await openDB();
                    const tx = db.transaction(STORE_NAME, 'readwrite');
                    const store = tx.objectStore(STORE_NAME);
                    store.clear();
                    await new Promise((resolve) => {
                        tx.oncomplete = () => {
                            db.close();
                            resolve();
                        };
                    });
                    await clearBackgroundDisplay();
                    showStatus('已清除所有存储', 'success');
                    await updateStorageInfo();
                } catch (err) {
                    console.error('清除失败:', err);
                    showStatus('清除失败，请重试', 'error');
                }
            }
        });

        // ============================================================
        // 状态消息
        // ============================================================

        function showStatus(text, type = 'info') {
            statusMessage.className = 'status-message show ' + type;
            if (type === 'loading') {
                statusText.innerHTML = `<span class="spinner"></span> ${text}`;
            } else {
                statusText.textContent = text;
            }
        }

        function hideStatus() {
            statusMessage.className = 'status-message';
        }

        // ============================================================
        // 页面可见性变化时重新同步
        // ============================================================

        document.addEventListener('visibilitychange', async function() {
            if (!document.hidden) {
                // 页面重新可见时，从 IndexedDB 加载背景
                await loadSavedBackground();
                await updateStorageInfo();
            }
        });