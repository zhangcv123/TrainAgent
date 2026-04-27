from openai import AsyncOpenAI
from agents import set_tracing_disabled


BASE_URL = "https://api.deepseek.com/v1"
API_KEY = "sk-cb52f39e6c3b44deacf1f213175c40af"
MODEL_NAME = "deepseek-v4-flash"

# BASE_URL = ""
# API_KEY = ""
# MODEL_NAME = "openai/gpt-5.4"

# 非官方API没有trace相关功能的调用
set_tracing_disabled(True)
client = AsyncOpenAI(base_url=BASE_URL, api_key=API_KEY)
