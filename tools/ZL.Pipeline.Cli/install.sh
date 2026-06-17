#!/usr/bin/env bash
# ============================================================================
# ZL.Pipeline.Cli 安装脚本
# 使用 pip install -e . 安装到虚拟环境或系统 Python
#
# 用法:
#   bash install.sh                    # 在当前虚拟环境中安装
#   bash install.sh --system           # 安装到系统 Python（需 --break-system-packages）
#   bash install.sh --uninstall        # 卸载
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ok()   { printf "${GREEN}[OK]${NC}     $*\n"; }
info() { printf "${YELLOW}[INFO]${NC}  $*\n"; }
err()  { printf "${RED}[ERROR]${NC} $*\n"; }

UNINSTALL=false
SYSTEM=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --system) SYSTEM=true; shift ;;
        --uninstall) UNINSTALL=true; shift ;;
        *) err "未知参数: $1"; exit 1 ;;
    esac
done

if [[ "$UNINSTALL" == "true" ]]; then
    echo "=== 卸载 ZL.Pipeline.Cli ==="
    pip uninstall -y zl-pipeline 2>/dev/null && ok "已卸载 zl-pipeline" || err "卸载失败"
    echo "完成"
    exit 0
fi

echo "=== 安装 ZL.Pipeline.Cli ==="

if [[ ! -f "$PROJECT_DIR/pyproject.toml" ]]; then
    err "$PROJECT_DIR/pyproject.toml 不存在"
    echo "      请确保在 tools/ZL.Pipeline.Cli/ 目录下运行"
    exit 1
fi

if [[ "$SYSTEM" == "true" ]]; then
    info "安装到系统 Python（--break-system-packages）"
    pip install -e "$PROJECT_DIR" --break-system-packages 2>&1 | tail -3
else
    info "安装到当前虚拟环境"
    pip install -e "$PROJECT_DIR" 2>&1 | tail -3
fi

ok "zl-pipeline 已安装"

echo ""
echo "=== 验证安装 ==="
if command -v zl-pipeline &>/dev/null; then
    ok "zl-pipeline 可用"
    zl-pipeline --help 2>&1 | head -10
else
    err "zl-pipeline 命令不可用"
    info "请检查 Python bin 目录是否在 PATH 中"
fi

echo ""
echo "✅ 安装完成"
echo ""
echo "快速开始:"
echo "  cd <your-project>"
echo "  zl-pipeline init              # 生成 pipeline.json"
echo "  zl-pipeline publish 1.0.1     # 发布"
echo "  zl-pipeline verify 1.0.1      # 验证"
