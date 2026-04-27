import os
import asyncio
import subprocess
from collections import deque
from datetime import datetime
from agents import function_tool
from prompt_toolkit import PromptSession
from data_storage import registry
from agents import Runner

prompt_session = PromptSession()
async def async_input(prompt: str = "") -> str:
    return await prompt_session.prompt_async(prompt)

@function_tool
def run_shell(command: str) -> str:
    """执行 shell 命令（不用来跑长任务）"""
    r = subprocess.run(command, shell=True, capture_output=True, text=True)
    return f"returncode: {r.returncode}\nstdout: {r.stdout}\nstderr: {r.stderr}"

@function_tool
async def make_training_plan(user_message: str) -> str:
    """把用户的训练任务描述整理成执行计划"""
    from subagents.custom_agents import planner_agent

    full = (
        f"[用户补充说明]:\n{user_message.strip() or '无'}\n\n"
        f"[任务列表]:\n{registry.to_context_str()}"
    )
    result = await Runner.run(planner_agent, full)
    return result.final_output

@function_tool
def execute_python(file_path: str, conda_env: str) -> str:
    """在指定 conda 环境中执行 Python 文件，返回进程 pid 和日志路径。"""
    script_path = os.path.abspath(file_path)
    script_dir = os.path.dirname(script_path)

    if not os.path.isfile(script_path):
        return f"error: file not found: {file_path}"

    log_dir = os.path.abspath("logs")
    os.makedirs(log_dir, exist_ok=True)

    name = os.path.splitext(os.path.basename(script_path))[0]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    logfile = os.path.join(log_dir, f"{name}_{timestamp}.log")
    log = open(logfile, "w", encoding="utf-8")

    command = [
        "conda",
        "run",
        "--no-capture-output",
        "-n",
        conda_env,
        "python",
        "-u",
        script_path,
    ]

    proc = subprocess.Popen(
        command,
        cwd=script_dir,
        stdout=log,
        stderr=subprocess.STDOUT,
        text=True,
    )
    log.flush()
    log.close()

    registry.update(
        file_path,
        pid=proc.pid,
        logdir=logfile,
        status="running",
    )

    return (
        f"started\n"
        f"pid: {proc.pid}\n"
        f"logfile: {logfile}\n"
        f"cwd: {script_dir}\n"
        f"command: {' '.join(command)}"
    )

@function_tool
def read_running_task_logs(lines: int = 50) -> str:
    """读取当前运行任务的信息，以及每个任务日志文件最后 lines 行。"""
    return format_running_task_logs(lines)


def _tail_file(file_path: str, lines: int) -> str:
    if not file_path:
        return "logdir 为空"
    if not os.path.isfile(file_path):
        return f"日志文件不存在: {file_path}"

    with open(file_path, "r", encoding="utf-8", errors="replace") as log:
        content = "".join(deque(log, maxlen=lines)).rstrip()
    return content or "日志文件暂无内容"


def format_running_task_logs(lines: int = 50) -> str:
    registry.refresh_statuses()
    running_tasks = [
        task for task in registry.tasks
        if task.get("status") == "running"
    ]

    if not running_tasks:
        return "当前没有运行中的任务"

    blocks = []
    for index, task in enumerate(running_tasks, start=1):
        log_tail = _tail_file(task.get("logdir"), lines)
        blocks.append(
            "\n".join([
                f"任务 {index}",
                f"file_path: {task.get('file_path')}",
                f"conda_env: {task.get('conda_env')}",
                f"status: {task.get('status')}",
                f"pid: {task.get('pid')}",
                f"logdir: {task.get('logdir')}",
                f"最后 {lines} 行日志:",
                log_tail,
            ])
        )
    return "\n\n".join(blocks)

async def debug_planner(run_result):
    print("\n========== Planner 调试 ==========")

    # TrainingAgent 调用 make_training_plan 时传给 Planner 的参数
    inv = getattr(run_result, "agent_tool_invocation", None)
    if inv is not None:
        print("Planner 收到的输入:")
        print(inv.tool_arguments)
    else:
        print("没有拿到 tool_arguments")

    # PlannerAgent 自己最终输出的内容
    print("\nPlanner 输出:")
    print(run_result.final_output)

    print("=================================\n")

    # 必须返回字符串，返回给 TrainingAgent 继续使用
    return str(run_result.final_output)


def print_box(title: str, body: str, width: int = 40):
    print("\033[32m" + "=" * width + "\033[0m")
    print(f"\033[32m  {title}\033[0m")
    print("\033[32m" + "-" * width + "\033[0m")
    print(f"  {body}")
    print("\033[32m" + "=" * width + "\033[0m")
