import os
import httpx
from openai import AsyncOpenAI
from agents import set_tracing_disabled
from agents import (
    set_tracing_disabled,
    set_default_openai_client,
    set_default_openai_api,
)

BASE_URL = "https://xxx/v1"
API_KEY = ""
MODEL_NAME = "gpt-5.5"

BASE_URL_CODEX = "https://xxx/v1"
API_KEY_CODEX = "xxx"

# 非官方API没有trace相关功能的调用
set_tracing_disabled(True)
set_default_openai_api("responses")

client = AsyncOpenAI(
    base_url=BASE_URL,
    api_key=API_KEY,
    http_client=httpx.AsyncClient(
        trust_env=False,
        timeout=60.0,
    ),
)

set_default_openai_client(client, use_for_tracing=False)



# import os
# import httpx
# from openai import OpenAI

# client = OpenAI(
#     api_key="",
#     base_url="http://127.0.0.1:8080/v1",
#     http_client=httpx.Client(
#         trust_env=False,
#         timeout=60.0,
#     ),
# )

# resp = client.responses.create(
#     model="gpt-5.4",
#     input="hello",
# )

# print(resp.output_text)


