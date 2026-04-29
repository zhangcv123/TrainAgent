#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
PROJECT_DIR="$(pwd)"

python_deps=(
  openai
  openai-agents
  pydantic
  prompt-toolkit
  wechatbot-sdk
)

# ── Python 虚拟环境 ────────────────────────────────────────────────────────────
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
python -m pip install "${python_deps[@]}"

# ── Codex CLI ─────────────────────────────────────────────────────────────────
if ! command -v node >/dev/null; then
  echo "未找到 node，请先安装 Node.js 22+ 后重新运行"
  exit 1
fi

node_major=$(node -e "process.stdout.write(String(process.versions.node.split('.')[0]))")
if (( node_major < 22 )); then
  echo "Node.js 版本过低（当前 $(node -v)），需要 22+，请升级后重新运行"
  exit 1
fi

if ! command -v npm >/dev/null; then
  echo "未找到 npm，请先安装 npm 后重新运行"
  exit 1
fi

echo "安装 codex CLI..."
npm install -g @openai/codex

# ── .codex/config.toml ────────────────────────────────────────────────────────
mkdir -p .codex

CODEX_CONFIG=".codex/config.toml"

if [[ ! -f "$CODEX_CONFIG" ]]; then
  cat > "$CODEX_CONFIG" <<TOML
model_provider = "aihubmix"

[model_providers.aihubmix]
name = "AIHubMix"
base_url = "https://aihubmix.com/v1"
env_key = "OPENAI_API_KEY"
wire_api = "responses"

[projects."$PROJECT_DIR"]
trust_level = "trusted"
TOML
  echo "已生成 $CODEX_CONFIG"
else
  if ! grep -qF "[projects.\"$PROJECT_DIR\"]" "$CODEX_CONFIG"; then
    printf '\n[projects."%s"]\ntrust_level = "trusted"\n' "$PROJECT_DIR" >> "$CODEX_CONFIG"
    echo "已向 $CODEX_CONFIG 追加当前项目 trust 配置"
  fi
fi

mkdir -p logs

echo "安装完成"
