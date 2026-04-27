import requests
import threading
import queue

# 定义超时常量
REQUEST_TIMEOUT = 20

def worker_post(url, payload, headers, result_queue):
    """单个请求的工作线程函数"""
    try:
        response = requests.post(
            url=url,
            json=payload,
            timeout=REQUEST_TIMEOUT,
            headers=headers
        )
        response.raise_for_status()  # 校验状态码
        # 请求成功则将结果放入队列
        result_queue.put(response)
    except requests.exceptions.RequestException as e:
        # 失败则放入None（或异常信息，按需调整）
        result_queue.put(None)
        print(f"请求失败: {str(e)}")

def worker_get(url, headers, result_queue):
    """单个请求的工作线程函数（GET请求）"""
    try:
        response = requests.get(
            url=url,
            timeout=REQUEST_TIMEOUT,
            headers=headers
        )
        response.raise_for_status()  # 校验状态码
        # 请求成功则将结果放入队列
        result_queue.put(response)
    except requests.exceptions.RequestException as e:
        # 失败则放入None（或异常信息，按需调整）
        result_queue.put(None)
        print(f"请求失败: {str(e)}")

def send_request(url, payload, headers, request_count=1, method='POST'):
    """
    并发发送多个请求，只要一个成功就立即返回
    
    Args:
        url: 请求地址
        payload: 请求体
        headers: 请求头
        request_count: 并发请求数，默认3
    
    Returns:
        第一个成功的响应JSON，全部失败则返回None
    """
    # 创建结果队列（用于接收第一个成功的结果）
    result_queue = queue.Queue(maxsize=1)  # 队列最大容量1，确保只存第一个结果
    threads = []

    # 启动多个线程发送请求
    if method.upper() == 'POST':
        worker_func = worker_post
        worker_args = (url, payload, headers, result_queue)
    elif method.upper() == 'GET':
        worker_func = worker_get
        worker_args = (url, headers, result_queue)
    else:
        raise ValueError("Unsupported HTTP method: only 'POST' and 'GET' are allowed")

    for i in range(request_count):
        t = threading.Thread(
            target = worker_func,
            args = worker_args
        )
        t.daemon = True  # 守护线程，主程序退出时自动结束
        threads.append(t)
        t.start()

    # 等待第一个结果返回（阻塞，直到队列有数据）
    try:
        result = result_queue.get(timeout=REQUEST_TIMEOUT * 2)  # 总超时时间
    except queue.Empty:
        print("所有请求均超时")
        result = None

    # 强制终止所有未完成的线程（无需等待剩余请求）
    # 注：线程无法直接终止，这里通过主线程退出+守护线程特性实现
    for t in threads:
        t.join(timeout=0.1)  # 短暂等待，避免资源泄漏

    return result