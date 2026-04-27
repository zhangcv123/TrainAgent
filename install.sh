#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

deps=(
  openai
  openai-agents
  pydantic
  prompt-toolkit
  wechatbot-sdk
)

echo "选择虚拟环境类型："
echo "1) .venv"
echo "2) conda"
read -rp "请输入 1 或 2: " choice

case "$choice" in
  1)
    python3 -m venv .venv
    source .venv/bin/activate
    ;;
  2)
    command -v conda >/dev/null || { echo "未找到 conda"; exit 1; }
    read -rp "请输入 conda 环境名: " env_name
    [[ -n "$env_name" ]] || { echo "conda 环境名不能为空"; exit 1; }

    if ! conda env list | awk '{print $1}' | grep -qx "$env_name"; then
      conda create -y -n "$env_name" python=3.10
    fi

    eval "$(conda shell.bash hook)"
    conda activate "$env_name"
    ;;
  *)
    echo "无效选择"
    exit 1
    ;;
esac

python -m pip install --upgrade pip
python -m pip install "${deps[@]}"
mkdir -p logs

echo "安装完成"
