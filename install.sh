#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${PROJECT_DIR}/.venv"
PYTHON_BIN="python3"

cd "${PROJECT_DIR}"

echo "==> 检查 Python"
if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "未找到 python3，请先安装 Python 3.10 或更新版本。"
  exit 1
fi

"${PYTHON_BIN}" --version

echo "==> 创建虚拟环境: ${VENV_DIR}"
"${PYTHON_BIN}" -m venv "${VENV_DIR}"

echo "==> 激活虚拟环境"
# shellcheck source=/dev/null
source "${VENV_DIR}/bin/activate"

echo "==> 更新 pip"
python -m pip install --upgrade pip

echo "==> 安装项目依赖"
python -m pip install \
  openai \
  openai-agents \
  pydantic \
  prompt-toolkit \
  wechatbot-sdk

echo "==> 创建日志目录"
mkdir -p "${PROJECT_DIR}/logs"

echo "==> 检查 conda"
if command -v conda >/dev/null 2>&1; then
  conda --version
else
  echo "未检测到 conda。项目可以启动，但训练任务执行需要用户提供可用的 conda 环境。"
fi

cat <<'MSG'

安装完成。

下一步：
  source .venv/bin/activate
  python launch.py

运行前请检查 config.py 中的 BASE_URL、API_KEY 和 MODEL_NAME。
MSG
