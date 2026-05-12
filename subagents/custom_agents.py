import os
import shutil
from agents import Agent, OpenAIResponsesModel, Runner, SQLiteSession, set_tracing_disabled
from pydantic import BaseModel, Field
from config import API_KEY_CODEX, BASE_URL_CODEX, MODEL_NAME, client
from tools.tool import run_shell
from agents.extensions.experimental.codex import ThreadOptions, TurnOptions, codex_tool


class ExecuteInput(BaseModel):
    command: str = Field(description="要执行的完整训练命令")
    conda_env: str | None = Field(default=None, description="执行该命令使用的 conda 环境名，没有则为 null")
    cwd: str | None = Field(default=None, description="执行该命令使用的工作目录，没有则为 null")
    problem: str = Field(description="如果有问题则描述问题，没有问题则为 null")

class ParamInput(BaseModel):
    command: str = Field(description="要分析的完整训练命令或代码相关请求")
    problem: str = Field(description="如果有问题则描述问题，没有问题则为 null")

planner_agent = Agent(
    name="PlannerAgent",
    instructions=
    """
    #你是训练任务规划助手。
    ##你的职责：
    1. 根据用户输入整理训练任务计划。
    2. 提取每个任务的完整 command、可选 conda_env、可选 cwd。
    3. 对长训练命令必须原样保留 command，不要拆成 Python 文件路径。
    4. 信息足够时不要改写用户给出的环境变量、参数、重定向、&&、cd 等 shell 片段。
    5. 可以使用 run_shell 工具检查 cwd 是否存在，或在用户明确给出 conda_env 时检查 conda 环境是否存在。
    6. 信息不足或有问题时，明确指出对应的问题。
    7. 只做规划，不执行命令，不启动训练，不读取日志。
    ##输出的最终计划格式必须只输出 JSON
    JSON 格式必须是：
    {
      "message": "给主 Agent 的简短说明",
      "items": [
        {
          "command": "完整训练命令",
          "conda_env": "conda 环境名，如果缺失则为 null",
          "cwd": "工作目录，如果缺失则为 null",
          "command_ok": true,
          "problem": "问题说明，没有问题则为 null"
        }
      ]
    }
    """,
    model=OpenAIResponsesModel(model=MODEL_NAME, openai_client=client),
    tools=[run_shell],
)


param_agent = Agent(
    name="ParamAgent",
    instructions=
    """
    #你是训练任务的参数确认助手。
    ##你的职责：
    1. 根据训练任务 command，必要时使用 run_shell 查看命令引用的脚本，并提取相关参数。
    2. 信息不足或有问题时，明确指出对应的问题。
    3. 只做信息提取确认，不执行命令，不启动训练，
    ##规则:
    输出的最终计划格式必须只输出 JSON，JSON 格式必须是：
    {
      "message": "给主 Agent 的简短说明",
      "items": [
        {
          "command": "完整训练命令",
          "params": [
            {
              "name": "参数名，如 --batch_size",
              "type": "参数类型，如 int/str/bool",
              "default": "默认值，没有则为 null",
            }
          ],
          "problem": "问题说明，没有问题则为 null"
        }
      ]
    }
    不要输出任何 JSON 以外的内容。
    """,
    model=OpenAIResponsesModel(model=MODEL_NAME, openai_client=client),
    tools=[run_shell],
)
param_agent_plan = param_agent.as_tool(
    tool_name="param_agent_plan",
    tool_description="提取训练命令引用脚本中设计和包含的参数信息",
    parameters=ParamInput,
    include_input_schema=True,
    max_turns=5,
    # custom_output_extractor=debug_planner,
)


# executor_agent = Agent(
#     name="ExecutorAgent",
#     instructions=
#     """
#     # 你是训练任务执行助手。
#     ##你的职责：
#     1. 根据训练任务计划，只启动当前需要执行的一个任务。
#     2. 如果 execute_command 返回已有任务运行中，则向用户说明当前运行任务，不要继续启动其他任务。
#     3. 信息不足或有问题时，明确指出对应的问题与user对接。
#     """,
#     model=OpenAIResponsesModel(model=MODEL_NAME, openai_client=client),
#     tools=[run_shell, execute_command],
# )

# executor_training_plan = executor_agent.as_tool(
#     tool_name="executor_training_plan",
#     tool_description="根据执行计划执行训练任务",
#     parameters=ExecuteInput,
#     include_input_schema=True,
#     max_turns=5,
#     # custom_output_extractor=debug_planner,
# )

code_agent = Agent(
    name="Code Agent", 
    instructions="使用 Codex 工具执行任务并回答问题",
    tools=[
          codex_tool(
              working_directory=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
              codex_options={
                  "codex_path_override": shutil.which("codex"),
                  "env": {
                      "CODEX_API_KEY": API_KEY_CODEX,
                      "OPENAI_API_KEY": API_KEY_CODEX,
                      "OPENAI_BASE_URL": BASE_URL_CODEX,
                      "PATH": os.environ.get("PATH", ""),
                      "https_proxy": "http://127.0.0.1:7897",
                      "http_proxy": "http://127.0.0.1:7897",
                      "HTTPS_PROXY": "http://127.0.0.1:7897",
                      "HTTP_PROXY": "http://127.0.0.1:7897",
                      "NO_PROXY": "127.0.0.1,localhost",
                      "no_proxy": "127.0.0.1,localhost",
                  },
              },
              sandbox_mode="workspace-write",
              default_thread_options=ThreadOptions(
                  model="gpt-5.5",
                  model_reasoning_effort="low",
                  network_access_enabled=True,
                  web_search_mode="disabled",
                  approval_policy="never",
              ),
              default_turn_options=TurnOptions(
                  idle_timeout_seconds=120,
              ),
              persist_session=True,
          )
    ],
    model=OpenAIResponsesModel(model=MODEL_NAME, openai_client=client),
)
code_agent_plan = code_agent.as_tool(
    tool_name="code_agent_plan",
    tool_description="使用 Codex 工具执行代码修改和训练命令参数提取相关的任务",
    parameters=ParamInput,
    include_input_schema=True,
    max_turns=5,
    # custom_output_extractor=debug_planner,
)


monitor_agent = Agent(
    name="MonitorAgent",
    instructions=
    """
    # 你是训练任务监控助手。
    ##你的职责：根据当前运行的任务信息，来监控任务状态是否正常。
    ##规则:
    1. 当存在Error等任务状态异常时，及时整理信息通知用户。
    2. 当损失存在NAN等异常时，及时整理信息通知用户。
    3. 如果没有异常，则不需要回复任何信息。
    ##输出格式:
    输出的最终计划格式必须只输出 JSON，JSON 格式必须是：
    {
      "message": "给出的简短说明",
      "items": [
        {
          "error": "错误信息，如果没有则为 null",
      ]
    }
    不要输出任何 JSON 以外的内容。
    """,
    model=OpenAIResponsesModel(model=MODEL_NAME, openai_client=client),
    tools=[run_shell],
)
