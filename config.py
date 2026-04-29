import os
from openai import AsyncOpenAI
from agents import set_tracing_disabled

BASE_URL = "https://openrouter.ai/api/v1"
API_KEY = ""
MODEL_NAME = "deepseek/deepseek-v4-flash"

BASE_URL_CODEX = "https://aihubmix.com/v1"
API_KEY_CODEX = ""
# 非官方API没有trace相关功能的调用
set_tracing_disabled(True)
client = AsyncOpenAI(base_url=BASE_URL, api_key=API_KEY)
