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
_running_processes: dict[int, subprocess.Popen] = {}


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

def _mark_task_failed(task_id: int, message: str, logdir: str | None = None) -> None:
    updates = {"status": "failed", "problem": message}
    if logdir is not None:
        updates["logdir"] = logdir
    registry.update(task_id, **updates)


def _start_command_process(task: dict) -> str:
    """启动单个命令进程，不做队列判断。"""
    task_id = task["task_id"]
    command_text = task["command"]
    conda_env = task.get("conda_env")
    cwd = task.get("cwd") or os.getcwd()
    cwd = os.path.abspath(os.path.expanduser(cwd))

    if not os.path.isdir(cwd):
        _mark_task_failed(task_id, f"cwd not found: {cwd}")
        return f"error: cwd not found: {cwd}"

    log_dir = os.path.abspath("logs")
    os.makedirs(log_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    logfile = os.path.join(log_dir, f"task_{task_id}_{timestamp}.log")
    log = open(logfile, "w", encoding="utf-8")

    if conda_env:
        command = [
            "conda",
            "run",
            "--no-capture-output",
            "-n",
            conda_env,
            "bash",
            "-lc",
            command_text,
        ]
    else:
        command = ["bash", "-lc", command_text]

    try:
        proc = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
    except OSError as exc:
        log.flush()
        log.close()
        _mark_task_failed(task_id, str(exc), logfile)
        return f"error: failed to start task {task_id}: {exc}"
    else:
        log.flush()
        log.close()

    registry.update(
        task_id,
        pid=proc.pid,
        logdir=logfile,
        cwd=cwd,
        status="running",
    )
    _running_processes[task_id] = proc

    return (
        f"started\n"
        f"task_id: {task_id}\n"
        f"pid: {proc.pid}\n"
        f"logfile: {logfile}\n"
        f"cwd: {cwd}\n"
        f"command: {command_text}\n"
        f"process_command: {' '.join(command)}"
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
        task_id = task["task_id"]
        pid = task.get("pid")

        if pid is None:
            registry.update(
                task_id,
                status="stopped",
                problem="stopped by exit",
            )
            stopped.append(f"task {task_id}: missing pid")
            continue

        try:
            os.killpg(int(pid), signal.SIGTERM)
        except ProcessLookupError:
            registry.update(task_id, pid=None, status="finished")
            _running_processes.pop(task_id, None)
            stopped.append(f"task {task_id}: already exited")
        except OSError as exc:
            errors.append(f"task {task_id}: failed to terminate pid {pid}: {exc}")
        else:
            signaled_tasks.append((task, int(pid)))

    for task, pid in signaled_tasks:
        task_id = task["task_id"]

        proc = _running_processes.get(task_id)
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
                errors.append(f"task {task_id}: failed to kill pid {pid}: {exc}")

            proc = _running_processes.get(task_id)
            if proc is not None:
                try:
                    proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    errors.append(f"task {task_id}: pid {pid} still running")

        if not registry._pid_is_running(pid):
            registry.update(
                task_id,
                pid=None,
                status="stopped",
                problem="stopped by exit",
            )
            _running_processes.pop(task_id, None)
            stopped.append(f"task {task_id}: stopped")

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


def stop_training_queue_tasks(timeout_seconds: float = 5.0) -> str:
    """停止当前运行训练，并取消后续 pending 训练任务。"""
    running_result = stop_running_training_tasks(timeout_seconds=timeout_seconds)
    stopped_pending = registry.stop_pending_tasks()

    if not stopped_pending and running_result == "no running tasks":
        return "no training tasks to stop"

    lines = ["training queue stopped"]
    if running_result:
        lines.append("running stop result:")
        lines.append(running_result)
    if stopped_pending:
        lines.append("stopped pending tasks:")
        lines.extend(
            f"task {task['task_id']}: {task['command']}"
            for task in stopped_pending
        )
    else:
        lines.append("stopped pending tasks: none")
    return "\n".join(lines)


@function_tool
def stop_training_queue(timeout_seconds: float = 5.0) -> str:
    """停止当前运行训练，并取消后续 pending 训练任务。"""
    return stop_training_queue_tasks(timeout_seconds=timeout_seconds)


def _format_queue_task(task: dict) -> str:
    return (
        f"task {task.get('task_id')}: "
        f"status={task.get('status')}, "
        f"command={task.get('command')}, "
        f"conda_env={task.get('conda_env')}, "
        f"cwd={task.get('cwd')}"
    )


@function_tool
def manage_training_queue(
    action: str,
    task_ids: list[int] | None = None,
    status_filter: list[str] | None = None,
    before_task_id: int | None = None,
    update_command: str | None = None,
    update_conda_env: str | None = None,
    update_cwd: str | None = None,
    update_status: str | None = None,
    update_problem: str | None = None,
) -> str:
    """管理非 running 队列任务：remove、clear、update、reorder。

    reorder 时 before_task_id=0 表示移动到队首，before_task_id=None 表示移动到队尾，
    before_task_id 为正数时表示移动到对应 task 前面。
    """
    updates = {}
    if update_command is not None:
        updates["command"] = update_command
    if update_conda_env is not None:
        updates["conda_env"] = update_conda_env
    if update_cwd is not None:
        updates["cwd"] = update_cwd
    if update_status is not None:
        updates["status"] = update_status
    if update_problem is not None:
        updates["problem"] = update_problem

    result = registry.manage_queue(
        action=action,
        task_ids=task_ids,
        status_filter=status_filter,
        updates=updates or None,
        before_task_id=before_task_id,
    )

    if not result.get("ok"):
        lines = ["queue management failed", "errors:"]
        lines.extend(result.get("errors", []))
        return "\n".join(lines)

    lines = [
        f"queue {result.get('action')} succeeded",
        result.get("message", ""),
    ]
    changed = result.get("changed", [])
    if changed:
        lines.append("changed tasks:")
        lines.extend(_format_queue_task(task) for task in changed)
    lines.append("current queue:")
    lines.append(registry.to_context_str())
    return "\n".join(line for line in lines if line)


def start_next_pending_task() -> str:
    """自动串行调度：没有运行中任务时启动下一个 pending 任务。"""
    running_tasks = registry.running_tasks()
    if running_tasks:
        running = running_tasks[0]
        return (
            "running task exists\n"
            f"task_id: {running.get('task_id')}\n"
            f"command: {running.get('command')}\n"
            f"pid: {running.get('pid')}\n"
            f"logfile: {running.get('logdir')}"
        )

    task = registry.next_pending_task()
    if task is None:
        return "no pending task"

    return _start_command_process(task)


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
def execute_command(command: str, conda_env: str | None = None, cwd: str | None = None) -> str:
    """串行执行一条长命令，返回进程 pid 和日志路径。"""
    running_tasks = registry.running_tasks()
    if running_tasks:
        running = running_tasks[0]
        return (
            "blocked: another task is running\n"
            f"task_id: {running.get('task_id')}\n"
            f"command: {running.get('command')}\n"
            f"pid: {running.get('pid')}\n"
            f"logfile: {running.get('logdir')}"
        )

    command = command.strip()
    if not command:
        return "error: missing command"

    if conda_env is not None:
        conda_env = conda_env.strip() or None
    task_cwd = os.path.abspath(os.path.expanduser(cwd)) if cwd else os.getcwd()
    task = registry.add(command=command, conda_env=conda_env, cwd=task_cwd)
    registry.update(task["task_id"], status="pending")
    return _start_command_process(task)


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
                f"task_id: {task.get('task_id')}",
                f"command: {task.get('command')}",
                f"conda_env: {task.get('conda_env')}",
                f"cwd: {task.get('cwd')}",
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
