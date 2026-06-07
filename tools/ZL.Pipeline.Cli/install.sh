#!/usr/bin/env bash
# ============================================================================
# ZL.Pipeline.Cli 安装脚本
# 将 zl-pipeline 命令安装到系统 PATH 中
#
# 用法:
#   bash install.sh                    # 安装到 ~/.local/bin (推荐)
#   bash install.sh --prefix /usr/local  # 安装到指定目录
#   bash install.sh --uninstall         # 卸载
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLI_SCRIPT="$SCRIPT_DIR/zl-pipeline.py"

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

ok()   { printf "${GREEN}[OK]${NC}     $*\n"; }
info() { printf "[INFO]    $*\n"; }

# 解析参数
PREFIX="${PREFIX:-$HOME/.local/bin}"
UNINSTALL=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --prefix) PREFIX="$2"; shift 2 ;;
        --uninstall) UNINSTALL=true; shift ;;
        *) echo "未知参数: $1"; exit 1 ;;
    esac
done

mkdir -p "$PREFIX"

if [[ "$UNINSTALL" == "true" ]]; then
    echo "=== 卸载 ZL.Pipeline.Cli ==="
    rm -f "$PREFIX/zl-pipeline"
    ok "已移除 $PREFIX/zl-pipeline"
    echo "完成"
    exit 0
fi

echo "=== 安装 ZL.Pipeline.Cli ==="

if [[ ! -f "$CLI_SCRIPT" ]]; then
    echo "${RED}[ERROR]${NC} $CLI_SCRIPT 不存在"
    echo "      请确保在 tools/ZL.Pipeline.Cli/ 目录下运行"
    exit 1
fi

# 创建包装脚本
WRAPPER="$PREFIX/zl-pipeline"
cat > "$WRAPPER" << WRAPPER_EOF
#!/usr/bin/env bash
# ZL.Pipeline.Cli 包装脚本 — 自动定位工具目录
exec python3 "$CLI_SCRIPT" "\$@"
WRAPPER_EOF

chmod +x "$WRAPPER"
ok "已安装: $WRAPPER"

if [[ ":$PATH:" != *":$PREFIX:"* ]]; then
    info "注意: $PREFIX 不在 PATH 中"
    info "建议添加: export PATH=\"\$PATH:$PREFIX\" 到 ~/.zshrc"
fi

echo ""
echo "=== 验证安装 ==="
if command -v zl-pipeline &>/dev/null; then
    ok "zl-pipeline 可用"
    zl-pipeline --help 2>&1 | head -10
else
    info "请执行: export PATH=\"\$PATH:$PREFIX\""
    info "然后: zl-pipeline --help"
fi

echo ""
echo "✅ 安装完成"
echo ""
echo "快速开始:"
echo "  cd <your-project>"
echo "  zl-pipeline init              # 生成 pipeline.json"
echo "  zl-pipeline publish 1.0.1     # 发布"
echo "  zl-pipeline publish --dry-run # 验证"
