from datetime import datetime, timedelta
import time
import threading
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))  # 把项目根目录加入Python路径

from diary.write_diary import update_all_diary

# ----------------------
# 把你要自动执行的函数放这里
# ----------------------
def daily_task():
    """每天0点自动执行的任务（替换成你的真实逻辑）"""
    print("=" * 40)
    nowtime = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"【自动任务执行】当前时间：{nowtime}")
    
    # 这里放你真正要跑的代码
    nowday = nowtime.split(' ')[0]
    print(nowday)
    if update_all_diary(nowday):
        print("Update successful")
    else:
        print("Update incomplete")
    
    print("=" * 40)

# ----------------------
# 0点定时调度核心（不用改）
# ----------------------
def get_next_midnight() -> float:
    """计算距离下一个0点的秒数"""
    now = datetime.now()
    # 今天0点
    today_midnight = datetime(now.year, now.month, now.day)
    # 下一个0点
    next_midnight = today_midnight + timedelta(days=1)
    # 返回秒数
    return (next_midnight - now).total_seconds()

def run_schedule_at_midnight():
    """无限循环：每天0点执行任务"""
    while True:
        # 等待到0点
        wait_seconds = get_next_midnight()
        print(f"\n等待下一个0点... 还需 {wait_seconds:.0f} 秒")
        
        # 休眠（不占CPU）
        time.sleep(wait_seconds)
        
        # 到0点，执行任务
        daily_task()

# ----------------------
# 启动后台定时线程（推荐）
# ----------------------
def start_daily_background_task():
    """启动后台守护线程，不阻塞主程序"""
    task_thread = threading.Thread(target=run_schedule_at_midnight, daemon=True)
    task_thread.start()
    print("✅ 每日0点自动任务已启动，后台运行中...")




if __name__ == "__main__":
    # daily_task()
    # exit(0)
    print("自动化进程已启动，将在每天00:00执行任务")
    
    # 启动定时任务
    run_schedule_at_midnight()
    
    # 如果你想后台运行，用下面这行，替换上面一行
    # start_daily_background_task()