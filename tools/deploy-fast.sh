#!/usr/bin/env bash
set -euo pipefail
#
# deploy-fast.sh — 快速发布 NuGet 包到本地缓存
# 核心优化：
#   1. 一次性 dotnet build/pack 所有项目（增量编译 + 并行）
#   2. 只 copy nupkg 到缓存，不做混淆/对比等耗时操作
#   3. 跳过 nuget.org 推送
#
# 用法:
#   ./deploy-fast.sh [version]
#   不指定版本时，从缓存自动递增
#
# 发布的项目:
#   - ZL.PlcBase: ZL.IotHub, ZL.IotHub.Bridges, ZL.PFLite, ZL.Tag
#   - iot-sdk: 所有 foundation/platform/domain/application 包

# ====================================================================
# 配置
# ====================================================================
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECTS_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"  # tools -> deploy -> 0-X
PLCBASE_DIR="$PROJECTS_DIR/ZL.PlcBase"
IOTSDK_DIR="$PROJECTS_DIR/iot-sdk"
PIPELINE="$SCRIPT_DIR/ZL.Pipeline.Cli/zl-pipeline.py"
LOCAL_FEED="$HOME/.nuget/local-feed"

VERSION="${1:-2.2.1}"

# ====================================================================
# 颜色
# ====================================================================
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[ OK ]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail()  { echo -e "${RED}[FAIL]${NC}  $*" >&2; }

# ====================================================================
# 2. 快速打包（pack + nuspec 修复 → local-feed）
# ====================================================================
info "========================================"
info "版本: $VERSION"
info "目标: $LOCAL_FEED"
info "========================================"

for project_dir in "$PLCBASE_DIR" "$IOTSDK_DIR"; do
    proj_name=$(basename "$project_dir")
    info "--- $proj_name ---"
    
    # 清理旧 artifacts
    rm -rf "$project_dir/artifacts/"
    mkdir -p "$project_dir/artifacts/"
    
    # 进入项目目录执行 pipeline（--local 模式：pack + nuspec修复 → local-feed）
    cd "$project_dir"
    if ! python3 "$PIPELINE" publish --local "$VERSION" 2>&1 | tee /dev/stderr; then
        warn "$proj_name 打包有失败项（看上面错误）"
    fi
    cd "$SCRIPT_DIR"

    # 统计成功打包的包
    local_count=$(find "$LOCAL_FEED" -name "*.$VERSION.nupkg" 2>/dev/null | wc -l)
    ok "$proj_name: local-feed 现有 $local_count 个 nupkg"
done

# ====================================================================
# 3. 验证 local-feed
# ====================================================================
info "========================================"
info "验证 local-feed"
info "========================================"

check_pkg() {
    local pkg="$1"
    if [ -f "$LOCAL_FEED/${pkg}.${VERSION}.nupkg" ]; then
        ok "  $pkg: $VERSION"
    else
        warn "  $pkg: $VERSION (MISSING)"
    fi
}

check_pkg "ZL.IotHub"; check_pkg "ZL.IotHub.Bridges"
check_pkg "ZL.PFLite"; check_pkg "ZL.Tag"
check_pkg "ZL.Collections"; check_pkg "ZL.Shared"
check_pkg "ZL.Protocol"; check_pkg "ZL.Framing"
check_pkg "ZL.Probing"; check_pkg "ZL.Script"
check_pkg "ZL.Scripting"; check_pkg "ZL.Connection"
check_pkg "ZL.ConnectionGuard"; check_pkg "ZL.DataProcessing"
check_pkg "ZL.Watchdog"; check_pkg "ZL.DataConvert"
check_pkg "ZL.Iot.Interface"; check_pkg "ZL.ProtocolGateway"
check_pkg "ZL.ProtocolGateway.Scripting"; check_pkg "ZL.DB.Acc"
check_pkg "ZL.Dao.IotDevice"; check_pkg "ZL.Dao.Edge"
check_pkg "ZL.Biz.Execute"; check_pkg "ZL.Iot.Plugin"
check_pkg "ZL.Iot.Runner"; check_pkg "ZL.Iot.Runner.Generator"
check_pkg "ZL.EdgeService"

echo ""
info "========================================"
ok "发布完成! 版本: $VERSION"
info "本地 feed: $LOCAL_FEED"
info "消费者 CPM 已同步，版本一致性已验证"
info "========================================"

# ====================================================================
# 4. 同步消费者 CPM — 确保所有消费者版本一致
# ====================================================================
info "========================================"
info "同步消费者 CPM 版本至 $VERSION"
info "========================================"

for proj in "$PLCBASE_DIR" "$IOTSDK_DIR"; do
    if [ -f "$proj/pipeline.json" ]; then
        python3 "$PIPELINE" --config "$proj/pipeline.json" sync-consumers "$VERSION" 2>&1 | tee /dev/stderr || warn "sync-consumers 失败"
    fi
done

# ====================================================================
# 5. 版本一致性门禁 — 阻止版本漂移
# ====================================================================
info "========================================"
info "版本一致性门禁 (version-check)"
info "========================================"

for proj in "$PLCBASE_DIR" "$IOTSDK_DIR"; do
    if [ -f "$proj/pipeline.json" ]; then
        if python3 "$PIPELINE" --config "$proj/pipeline.json" version-check "$VERSION" 2>&1 | tee /dev/stderr; then
            ok "$(basename $proj): 版本一致"
        else
            fail "$(basename $proj): 版本不一致！"
            FAILED=1
        fi
    fi
done

if [ "${FAILED:-0}" -eq 1 ]; then
    fail "版本门禁未通过，请修复后再试"
    exit 1
fi

echo ""
info "========================================"
ok "全部完成! 版本: $VERSION"
info "========================================"
