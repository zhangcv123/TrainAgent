import asyncio
from wechatbot import ApiError, NoContextError, WeChatBot
from agents import Agent, OpenAIResponsesModel, Runner, SQLiteSession
from config import MODEL_NAME, client
from tools.tool import (
    run_shell,
    async_input,
    make_training_plan,
    print_box,
    read_running_task_logs,
    format_running_task_logs,
    start_training_queue,
    start_next_pending_task,
    stop_running_training,
    stop_training_queue,
    manage_training_queue,
)
from subagents.custom_agents import monitor_agent, param_agent_plan, code_agent_plan
from data_storage import registry, register_task

training_agent = Agent(
    name="TrainingAgent",
    instructions=
    """
        你是 Python 训练任务总控助手。
        你的职责流程：
        1. 询问用户有哪些要执行的训练命令、可选 conda 环境和可选工作目录，使用 register_task 记录。
           对长训练命令必须原样记录 command，例如 CUDA_VISIBLE_DEVICES=0 python train.py --lr 1e-4。
        2. 获取全部信息后，调用 make_training_plan 工具汇总生成执行计划。规划完成后，汇报执行计划，并与用户确认。
        3. 根据用户确认的执行计划，询问是否需要确认或修改参数。如果需要，则使用 param_agent_plan 工具逐个提取每个任务的参数。
        4. 只有用户明确确认执行后，才调用 start_training_queue 工具启动自动串行训练队列。
           不要逐个启动列表内的全部任务；系统会在前一个任务结束后自动启动下一个 pending 任务。
        5. 当用户需要修改和读取代码相关的任务时，优先调用 code_agent_plan 工具进行代码相关的操作和参数提取。
        6. 当用户询问运行状态或日志时，优先考虑调用 read_running_task_logs 工具读取当前运行任务信息和日志最后 50 行。
        7. 当用户要求停止、关闭、中断或杀掉当前训练时，优先调用 stop_running_training 工具，不要使用 run_shell 自行执行 kill 命令。
        8. 当用户要求停止全部、停止整个任务、关闭队列、清空 pending、不要继续跑后续任务时，优先调用 stop_training_queue 工具。
        9. 当用户只是在查询短命令或系统状态，例如 ls、cat、pwd、nvidia-smi，优先使用 run_shell，不要注册进训练队列。
        10. 当用户要求删除旧任务、清空已登记任务、修改任务命令/conda环境/工作目录/状态、调整任务顺序时，优先调用 manage_training_queue 工具。
            不允许直接管理 running 任务；用户要修改或删除 running 任务时，先使用停止工具。
            修改任务属性时使用 update_command、update_conda_env、update_cwd、update_status、update_problem 参数。
            调整顺序时，before_task_id=0 表示移到队首，before_task_id=None 表示移到队尾，正数表示移到指定任务前。

        安全规则：
        1. 不执行 rm/mv/sudo 等危险命令。
        2. 不擅自修改用户文件。
        3. 不确定时先询问用户。
    """,
    model=OpenAIResponsesModel(model=MODEL_NAME, openai_client=client),
    tools=[
           run_shell, 
           register_task, 
           make_training_plan, 
           start_training_queue,
           stop_running_training,
           stop_training_queue,
           manage_training_queue,
           param_agent_plan,
           read_running_task_logs,
           code_agent_plan,
           ],
)


async def run_agent(user_input: str) -> str:
    """CLI 和微信共用的 Agent 调用"""
    full_input = (
        f"{user_input}\n\n"
        f"[当前已收集的任务列表]:\n{registry.to_context_str()}"
    )
    result = await Runner.run(training_agent, full_input, session=session)
    return result.final_output


session = SQLiteSession("conversation")
bot = WeChatBot()
wechat_targets = set()


async def send_wechat_notice(output: str) -> None:
    if not wechat_targets:
        return

    for user_id in list(wechat_targets):
        try:
            await bot.send(user_id, output)
        except (ApiError, NoContextError) as exc:
            wechat_targets.discard(user_id)
            print(f"[wechat] send failed for {user_id}, removed target: {exc}")
        except Exception as exc:
            wechat_targets.discard(user_id)
            print(
                f"[wechat] unexpected send failure for {user_id}, "
                f"removed target: {type(exc).__name__}: {exc}"
            )


# 微信输入loop
@bot.on_message
async def handle(msg):
    wechat_targets.add(msg.user_id)
    try:
        await bot.send_typing(msg.user_id)
    except Exception:
        pass
    response = await run_agent(msg.text)
    await bot.reply(msg, response)

# 终端输入loop
async def cli_loop():
    print_box("你好！", "你可以告诉我要执行的训练命令、conda 环境和工作目录。")

    while True:
        user_input = await async_input("user: ")
        if user_input.lower() in ["exit", "quit", "q"]:
            break
        response = await run_agent(user_input)
        print(f"Agent: {response}")
        print("=" * 80)

# 训练日志监控loop
async def log_monitor_loop(interval: int = 600, use_wechat: bool = False):
    while True:
        await asyncio.sleep(interval)
        info = format_running_task_logs(50)
        result = await Runner.run(monitor_agent, info)
        output = f"MonitorAgent: {result.final_output}"
        # 终端输出
        print(output)
        print("=" * 80)
        # 微信输出
        if use_wechat:
            await send_wechat_notice(output)

async def serial_scheduler_loop(interval: int = 10, use_wechat: bool = False):
    while True:
        await asyncio.sleep(interval)
        result = start_next_pending_task()
        if not (result.startswith("started") or result.startswith("error:")):
            continue

        output = f"SerialScheduler: {result}"
        print(output)
        print("=" * 80)

        if use_wechat:
            await send_wechat_notice(output)


async def main():
    print_box("是否启用微信远程交互？", "微信交互采用官方插件与专门的 Bot 进行交互，无安全风险。")
    use_wechat = input("请选择 (y/n): ").strip().lower().startswith("y")

    if use_wechat:
        await bot.login()
        await asyncio.gather(
            cli_loop(),
            bot.start(),
            log_monitor_loop(interval=MONITOR_TIMER_INTERVAL, use_wechat=True),
            serial_scheduler_loop(interval=SCHEDULER_TIMER_INTERVAL, use_wechat=True),
        )
    else:
        await asyncio.gather(
            cli_loop(),
            log_monitor_loop(interval=MONITOR_TIMER_INTERVAL, use_wechat=False),
            serial_scheduler_loop(interval=SCHEDULER_TIMER_INTERVAL, use_wechat=False),
        )

if __name__ == "__main__":
    MONITOR_TIMER_INTERVAL = 1800  # 30分钟检查一次日志
    SCHEDULER_TIMER_INTERVAL = 10  # 10秒检查一次是否需要启动下一个任务
    asyncio.run(main())
