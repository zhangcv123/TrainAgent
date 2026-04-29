from openai import AsyncOpenAI
from agents import set_tracing_disabled


BASE_URL = "https://openrouter.ai/api/v1"
API_KEY = "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"
MODEL_NAME = "openai/gpt-5.4-mini"

# BASE_URL = ""
# API_KEY = ""
# MODEL_NAME = "openai/gpt-5.4"

# 非官方API没有trace相关功能的调用
set_tracing_disabled(True)
client = AsyncOpenAI(base_url=BASE_URL, api_key=API_KEY)
