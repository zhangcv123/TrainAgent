import os
import asyncio
import signal
import subprocess
import time
from collections import deque
from datetime import datetime
from agents import function_tool
from prompt_toolkit import PromptSession
from data_storage import registry
from agents import Runner

prompt_session = PromptSession()
_running_processes: dict[str, subprocess.Popen] = {}


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

def _mark_task_failed(file_path: str, message: str, logdir: str | None = None) -> None:
    updates = {"status": "failed", "problem": message}
    if logdir is not None:
        updates["logdir"] = logdir
    registry.update(file_path, **updates)


def _start_python_process(file_path: str, conda_env: str) -> str:
    """启动单个训练进程，不做队列判断。"""
    script_path = os.path.abspath(file_path)
    script_dir = os.path.dirname(script_path)

    if not os.path.isfile(script_path):
        _mark_task_failed(file_path, f"file not found: {file_path}")
        return f"error: file not found: {file_path}"

    if not conda_env:
        _mark_task_failed(file_path, f"missing conda env: {file_path}")
        return f"error: missing conda env: {file_path}"

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

    try:
        proc = subprocess.Popen(
            command,
            cwd=script_dir,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
    except OSError as exc:
        log.flush()
        log.close()
        _mark_task_failed(file_path, str(exc), logfile)
        return f"error: failed to start {file_path}: {exc}"
    else:
        log.flush()
        log.close()

    registry.update(
        file_path,
        pid=proc.pid,
        logdir=logfile,
        status="running",
    )
    _running_processes[file_path] = proc

    return (
        f"started\n"
        f"pid: {proc.pid}\n"
        f"logfile: {logfile}\n"
        f"cwd: {script_dir}\n"
        f"command: {' '.join(command)}"
    )


def stop_running_training_tasks(timeout_seconds: float = 5.0) -> str:
    """停止当前登记为 running 的训练任务。"""
    running_tasks = registry.running_tasks()
    if not running_tasks:
        return "no running tasks"

    stopped = []
    errors = []
    signaled_tasks = []
    deadline = time.monotonic() + timeout_seconds

    for task in running_tasks:
        file_path = task["file_path"]
        pid = task.get("pid")

        if pid is None:
            registry.update(
                file_path,
                status="stopped",
                problem="stopped by exit",
            )
            stopped.append(f"{file_path}: missing pid")
            continue

        try:
            os.killpg(int(pid), signal.SIGTERM)
        except ProcessLookupError:
            registry.update(file_path, pid=None, status="finished")
            _running_processes.pop(file_path, None)
            stopped.append(f"{file_path}: already exited")
        except OSError as exc:
            errors.append(f"{file_path}: failed to terminate pid {pid}: {exc}")
        else:
            signaled_tasks.append((task, int(pid)))

    for task, pid in signaled_tasks:
        file_path = task["file_path"]

        proc = _running_processes.get(file_path)
        remaining = max(0.0, deadline - time.monotonic())
        if proc is not None:
            try:
                proc.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                pass
        else:
            while remaining > 0 and registry._pid_is_running(pid):
                time.sleep(min(0.1, remaining))
                remaining = max(0.0, deadline - time.monotonic())

        if registry._pid_is_running(pid):
            try:
                os.killpg(int(pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            except OSError as exc:
                errors.append(f"{file_path}: failed to kill pid {pid}: {exc}")

            proc = _running_processes.get(file_path)
            if proc is not None:
                try:
                    proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    errors.append(f"{file_path}: pid {pid} still running")

        if not registry._pid_is_running(pid):
            registry.update(
                file_path,
                pid=None,
                status="stopped",
                problem="stopped by exit",
            )
            _running_processes.pop(file_path, None)
            stopped.append(f"{file_path}: stopped")

    lines = []
    if stopped:
        lines.append("stopped tasks:")
        lines.extend(stopped)
    if errors:
        lines.append("errors:")
        lines.extend(errors)
    return "\n".join(lines)


@function_tool
def stop_running_training(timeout_seconds: float = 5.0) -> str:
    """停止当前运行的训练任务及其子进程。"""
    return stop_running_training_tasks(timeout_seconds=timeout_seconds)


def start_next_pending_task() -> str:
    """自动串行调度：没有运行中任务时启动下一个 pending 任务。"""
    running_tasks = registry.running_tasks()
    if running_tasks:
        running = running_tasks[0]
        return (
            "running task exists\n"
            f"file_path: {running.get('file_path')}\n"
            f"pid: {running.get('pid')}\n"
            f"logfile: {running.get('logdir')}"
        )

    task = registry.next_pending_task()
    if task is None:
        return "no pending task"

    return _start_python_process(
        file_path=task["file_path"],
        conda_env=task["conda_env"],
    )


@function_tool
def start_training_queue() -> str:
    """按自动串行策略启动训练队列。已有任务运行时不会启动新任务。"""
    activated_count = registry.activate_registered_tasks()
    result = start_next_pending_task()
    return (
        f"activated_tasks: {activated_count}\n"
        f"{result}"
    )


@function_tool
def execute_python(file_path: str, conda_env: str) -> str:
    """在指定 conda 环境中串行执行 Python 文件，返回进程 pid 和日志路径。"""
    running_tasks = registry.running_tasks()
    if running_tasks:
        running = running_tasks[0]
        return (
            "blocked: another task is running\n"
            f"file_path: {running.get('file_path')}\n"
            f"pid: {running.get('pid')}\n"
            f"logfile: {running.get('logdir')}"
        )

    return _start_python_process(file_path, conda_env)


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
    running_tasks = registry.running_tasks()


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
