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
