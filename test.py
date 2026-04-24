import os
os.environ["OPENAI_API_KEY"] = "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"
os.environ["OPENAI_BASE_URL"] = "https://openrouter.ai/api/v1"

import subprocess
from agents import Agent, Runner, set_default_openai_api, set_tracing_disabled, function_tool

set_default_openai_api("chat_completions")
set_tracing_disabled(True)

@function_tool
def ask_user(question: str) -> str:
    """当需要用户提供信息时调用"""
    return input(f"Agent: {question}\nuser: ")

@function_tool
def run_shell(command: str) -> str:
    """执行 shell 命令（不用来跑长任务）"""
    r = subprocess.run(command, shell=True, capture_output=True, text=True)
    return f"returncode: {r.returncode}\nstdout: {r.stdout}\nstderr: {r.stderr}"

@function_tool
def execute_python(path: str) -> str:
    """后台启动 python 文件。返回 pid、logfile、以及起始 offset（文件当前末尾，跳过历史）。"""
    import datetime
    file_name = os.path.splitext(os.path.basename(path))[0]
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = os.path.join(os.getcwd(), "logs")
    os.makedirs(log_dir, exist_ok=True)

    logfile = os.path.join(log_dir, f"{file_name}_{timestamp}.log")
    cmd = f"python -u {path} > {logfile} 2>&1 &"
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    pid = r.stdout.strip()
    print(f"\n━━━ 启动 {path} (pid={pid}, log={logfile}) ━━━", flush=True)
    return f"pid: {pid}\nlogfile: {logfile}\noffset: 0"

@function_tool
def print_log(pid: str, logfile: str, lines: int = 80) -> str:
    """读取日志文件最后若干行，并返回进程是否还在运行。"""
    log_result = subprocess.run(
        ["tail", "-n", str(lines), logfile],
        capture_output=True,
        text=True,
        errors="replace",
    )
    running = subprocess.run(
        ["kill", "-0", str(pid)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0

    status = "running" if running else "finished"
    return (
        f"process_status: {status}\n"
        f"logfile: {logfile}\n"
        f"latest_log:\n"
        f"{log_result.stdout or log_result.stderr}"
    )

agent = Agent(
    name="My Agent",
    instructions="""你是任务执行助手。工具：ask_user 询问用户；run_shell 做路径验证等短命令；
execute_python 后台启动 python；print_log 轮询日志+查看进程状态。

每次回复开始先输出清单并标记进度：
- [ ] 1. 询问用户要执行的 Python 文件和顺序
- [ ] 2. 验证每个路径（存在、是文件、后缀是 .py）
- [ ] 3. 按顺序执行每个文件：用 execute_python 启动，拿到 pid 和 logfile 后
       循环调用 print_log(pid, logfile)，**两次调用之间用 run_shell("sleep 8") 间隔 5 秒**，
       直到 status=finished，再执行下一个
- [ ] 4. 汇报执行结果

每完成一步把 [ ] 改成 [x]。遇到问题停在当前步骤。
安全规则：只做路径验证和 python 执行，不执行 rm/mv/sudo 等。
""",
    tools=[ask_user, run_shell, execute_python, print_log],
)

messages = [{"role": "user", "content": "开始"}]
while True:
    result = Runner.run_sync(agent, messages)
    print("Agent:", result.final_output)
    messages = result.to_input_list()
    user_input = input("user: ")
    if user_input in {"exit", "quit"}:
        break
    messages.append({"role": "user", "content": user_input})
    print("="*50)


# from wechatbot import WeChatBot
# bot = WeChatBot()

# @bot.on_message
# async def handle(msg):
#     print(f"收到消息 - user_id: {msg.user_id}, 内容: {msg.text}")
#     await bot.send_typing(msg.user_id)
#     await bot.reply(msg, f"Echo: {msg.text}")

# bot.run()
