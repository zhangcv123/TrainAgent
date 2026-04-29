import os
import shutil
from agents import Agent, OpenAIChatCompletionsModel, Runner, SQLiteSession, set_tracing_disabled
from pydantic import BaseModel, Field
from config import API_KEY_CODEX, BASE_URL_CODEX, MODEL_NAME, client
from tools.tool import run_shell, execute_python
from agents.extensions.experimental.codex import ThreadOptions, TurnOptions, codex_tool


class ExecuteInput(BaseModel):
    file_path: str = Field(description="要执行的 Python 文件路径")
    conda_env: str = Field(description="执行该文件使用的 conda 环境名")
    problem: str = Field(description="如果有问题则描述问题，没有问题则为 null")

class ParamInput(BaseModel):
    file_path: str = Field(description="要执行的 Python 文件路径")
    problem: str = Field(description="如果有问题则描述问题，没有问题则为 null")

planner_agent = Agent(
    name="PlannerAgent",
    instructions=
    """
    #你是训练任务规划助手。
    ##你的职责：
    1. 根据用户输入整理训练任务计划。
    2. 提取每个任务的 Python 文件路径、conda 环境。
    3. 使用run_shell工具检查路径和conda环境是否存在。
    4. 信息不足或有问题时，明确指出对应的问题。
    5. 只做规划，不执行命令，不启动训练，不读取日志。
    ##输出的最终计划格式必须只输出 JSON
    JSON 格式必须是：
    {
      "message": "给主 Agent 的简短说明",
      "items": [
        {
          "file_path": "Python 文件路径",
          "conda_env": "conda 环境名，如果缺失则为 null",
          "path_ok": true,
          "problem": "问题说明，没有问题则为 null"
        }
      ]
    }
    """,
    model=OpenAIChatCompletionsModel(model=MODEL_NAME, openai_client=client),
    tools=[run_shell],
)


param_agent = Agent(
    name="ParamAgent",
    instructions=
    """
    #你是训练任务的参数确认助手。
    ##你的职责：
    1. 根据训练任务计划，依次使用 run_shell 来访问文件，并提取相关参数。
    2. 信息不足或有问题时，明确指出对应的问题。
    3. 只做信息提取确认，不执行命令，不启动训练，
    ##规则:
    输出的最终计划格式必须只输出 JSON，JSON 格式必须是：
    {
      "message": "给主 Agent 的简短说明",
      "items": [
        {
          "file_path": "Python 文件路径",
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
    model=OpenAIChatCompletionsModel(model=MODEL_NAME, openai_client=client),
    tools=[run_shell],
)
param_agent_plan = param_agent.as_tool(
    tool_name="param_agent_plan",
    tool_description="提取执行文件中设计和包含的参数信息",
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
#     2. 如果 execute_python 返回已有任务运行中，则向用户说明当前运行任务，不要继续启动其他任务。
#     3. 信息不足或有问题时，明确指出对应的问题与user对接。
#     """,
#     model=OpenAIChatCompletionsModel(model=MODEL_NAME, openai_client=client),
#     tools=[run_shell, execute_python],
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
                    "OPENAI_API_KEY": API_KEY_CODEX,
                    "OPENAI_BASE_URL": BASE_URL_CODEX,
                    "PATH": os.environ.get("PATH", ""),
                    "https_proxy": "http://127.0.0.1:7897", 
                    "http_proxy": "http://127.0.0.1:7897",
                    "HTTPS_PROXY": "http://127.0.0.1:7897",
                    "HTTP_PROXY": "http://127.0.0.1:7897",
                }
            },
            sandbox_mode="workspace-write",
            default_thread_options=ThreadOptions(
                model="gpt-5.4-mini",
                model_reasoning_effort="low",
                network_access_enabled=True,
                web_search_mode="disabled",
                approval_policy="never",
            ),
            default_turn_options=TurnOptions(
                idle_timeout_seconds=60,
            ),
            persist_session=True,
        )
    ],
    model=OpenAIChatCompletionsModel(model=MODEL_NAME, openai_client=client),
)
code_agent_plan = code_agent.as_tool(
    tool_name="code_agent_plan",
    tool_description="使用 Codex 工具执行代码修改和参数提取相关的任务",
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
    model=OpenAIChatCompletionsModel(model=MODEL_NAME, openai_client=client),
    tools=[run_shell],
)
