''' 
    agent_sandbox.py   -2026.4.4, khalo
    提供 Agent 写代码要用到的接口
'''
import subprocess
import os
import shutil

class SafeCondaSandbox:
    def __init__(
        self,
        conda_env: str,       # 你指定的conda环境名
        work_dir: str,        # 唯一允许操作的目录
        safe_commands: list = None  # 白名单命令
    ):
        self.conda_env = conda_env
        self.work_dir = os.path.abspath(work_dir)
        self.safe_commands = safe_commands or [
            # 核心运行
            "pip", "python", "conda",
            # 文件查看
            "dir", "ls", "echo", "type", "cat",
            # ✅ 允许创建/编辑代码文件（安全版）
            "copy con", "notepad", "nano", "vim", "touch"
        ]
        
        # 强制创建工作目录
        os.makedirs(self.work_dir, exist_ok=True)

        print("Sandbox Inited")

    def run(self, cmd: str) -> str:
        """
        唯一入口：Agent 只能调用这个方法执行命令
        自带 5 层安全校验
        """
        # ====================== 安全校验层 ======================
        cmd = cmd.strip()
        
        # 1. 禁止访问工作目录以外的路径
        if ".." in cmd or "/.." in cmd or "\\.." in cmd:
            return "❌ 禁止访问上级目录"
        
        # 2. 只允许白名单命令
        if not any(cmd.startswith(c) for c in self.safe_commands):
            return f"❌ 禁止执行命令，仅允许：{self.safe_commands}"
        
        # 3. 禁止修改环境变量
        if any(k in cmd for k in ["set ", "export ", "PATH=", "env="]):
            return "❌ 禁止修改系统环境变量"
        
        # 4. 禁止高危删除/系统操作
        dangerous = ["rm -rf", "del /f", "format", "reg", "sc ", "net "]
        if any(d in cmd for d in dangerous):
            return "❌ 禁止执行高危系统命令"

        # ====================== 隔离执行层 ======================
        # 核心：强制在 Conda 环境 + 工作目录内执行
        conda_activate = f"conda activate {self.conda_env}"
        full_cmd = f"{conda_activate} && cd /d {self.work_dir} && {cmd}"

        try:
            result = subprocess.run(
                full_cmd,
                shell=True,
                cwd=self.work_dir,    # 锁死工作目录
                capture_output=True,
                text=True,
                timeout=120
            )
            return result.stdout + result.stderr
        except Exception as e:
            return f"执行失败：{str(e)}"

# 声明沙箱
sandbox:SafeCondaSandbox = None

# 实例化沙箱
def init_sandbox():
    try:
        global sandbox
        #（只允许操作这个环境 + 这个目录）
        sandbox = SafeCondaSandbox(
            conda_env="mylibra_workbench",    # 你预先创建好的 Conda 环境
            work_dir="G:/Games/mylibra/agent/workbench"  # 唯一允许操作的目录
        )
        print("初始化Agent沙箱成功")
    except Exception as e:
        print(f"初始化Agent沙箱失败：{e}")
        return

# 对外接口
def run_sandbox(cmd:str):
    global sandbox
    # 懒汉式初始化
    if not sandbox:
        init_sandbox()
    # 运行Agent发来的cmd命令
    return sandbox.run(cmd=cmd)