import asyncio
from wechatbot import WeChatBot
from agents import Agent, OpenAIChatCompletionsModel, Runner, SQLiteSession
from config import MODEL_NAME, client
from tools.tool import run_shell, async_input, make_training_plan, print_box, read_running_task_logs, format_running_task_logs
from subagents.custom_agents import monitor_agent, executor_training_plan, param_agent_plan
from data_storage import registry, register_task

training_agent = Agent(
    name="TrainingAgent",
    instructions=
    """
        你是 Python 训练任务总控助手。
        你的职责流程：
        1. 询问用户有哪些要执行的文件路径及对应的 conda 环境,使用 register_task 记录。
        2. 获取全部信息后，调用 make_training_plan 工具汇总生成执行计划。规划完成后，汇报执行计划，并与用户确认;
        3. 根据用户确认的执行计划，询问是否需要确认或修改参数。如果需要，则使用 param_agent_plan 工具逐个提取每个任务的参数。
        4. 用户确认后，则调用 executor_training_plan 工具执行训练任务。
        5. 当用户询问运行状态或日志时，优先考虑调用 read_running_task_logs 工具读取当前运行任务信息和日志最后 50 行。

        安全规则：
        1. 不执行 rm/mv/sudo 等危险命令。
        2. 不擅自修改用户文件。
        3. 不确定时先询问用户。
    """,
    model=OpenAIChatCompletionsModel(model=MODEL_NAME, openai_client=client),
    tools=[
           run_shell, 
           register_task, 
           make_training_plan, 
           executor_training_plan, 
           param_agent_plan,
           read_running_task_logs
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

# 微信输入loop
@bot.on_message
async def handle(msg):
    wechat_targets.add(msg.user_id)
    await bot.send_typing(msg.user_id)
    response = await run_agent(msg.text)
    await bot.reply(msg, response)

# 终端输入loop
async def cli_loop():
    print_box("你好！", "你可以告诉我要执行的 Python 文件路径和 conda 环境。")

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
        if use_wechat and wechat_targets:
            for user_id in wechat_targets:
                await bot.send_message(user_id, output)

async def main():
    print_box("是否启用微信远程交互？", "微信交互采用官方插件与专门的 Bot 进行交互，无安全风险。")
    use_wechat = input("请选择 (y/n): ").strip().lower().startswith("y")

    if use_wechat:
        await bot.login()
        await asyncio.gather(
            cli_loop(),
            bot.start(),
            log_monitor_loop(interval=600, use_wechat=True),
        )
    else:
        await asyncio.gather(
            cli_loop(),
            log_monitor_loop(interval=600, use_wechat=False),
        )

if __name__ == "__main__":
    asyncio.run(main())
