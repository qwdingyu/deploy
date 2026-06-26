#!/usr/bin/env bash
set -euo pipefail
#
# deploy-local.sh — 发布过渡期包到本地 NuGet 全局缓存
#
# 用法:
#   ./deploy-local.sh              # 发布所有项目，版本从 args 获取
#   ./deploy-local.sh 2.1.1        # 指定版本号
#
# 作用:
#   1. 编译 + 打包 ZL.PlcBase 和 iot-sdk
#   2. 复制 nupkg 到本地 nuget 全局缓存 (~/.nuget/packages/)
#   3. 不上传到 nuget.org

# ====================================================================
# 配置
# ====================================================================
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECTS_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"  # tools -> deploy -> 0-X
PLCBASE_DIR="$PROJECTS_DIR/ZL.PlcBase"
IOTSDK_DIR="$PROJECTS_DIR/iot-sdk"
PIPELINE="$SCRIPT_DIR/ZL.Pipeline.Cli/zl-pipeline.py"
NUGET_CACHE="$HOME/.nuget/packages"

# 版本号: 从参数获取，或从上一个版本递增
VERSION="${1:-}"

# ====================================================================
# 颜色输出
# ====================================================================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[ OK ]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail()  { echo -e "${RED}[FAIL]${NC}  $*" >&2; }

# ====================================================================
# 前置检查
# ====================================================================
info "检查前置依赖..."

if ! command -v python3 &>/dev/null; then
    fail "python3 未安装"
    exit 1
fi

if ! command -v dotnet &>/dev/null; then
    fail "dotnet SDK 未安装"
    exit 1
fi

if [ ! -f "$PIPELINE" ]; then
    fail "pipeline 脚本不存在: $PIPELINE"
    exit 1
fi

if [ ! -d "$PLCBASE_DIR" ]; then
    fail "ZL.PlcBase 目录不存在: $PLCBASE_DIR"
    exit 1
fi

if [ ! -d "$IOTSDK_DIR" ]; then
    fail "iot-sdk 目录不存在: $IOTSDK_DIR"
    exit 1
fi

# ====================================================================
# 确定版本号
# ====================================================================
if [ -z "$VERSION" ]; then
    # 从全局缓存中获取当前最高版本，自动递增
    version_from_cache() {
        local pkg_name="$1"
        local lowest="999"
        for dir in "$NUGET_CACHE/$pkg_name"/*/; do
            if [ -d "$dir" ]; then
                local v=$(basename "$dir")
                if [ "$v" != "$lowest" ] && [ "$v" \< "$lowest" ] 2>/dev/null || [ "$v" \> "$lowest" ] 2>/dev/null; then
                    : # skip
                fi
                # 比较版本号
                if command -v sort &>/dev/null; then
                    echo "$v"
                fi
            fi
        done | sort -V | tail -1
    }

    # 尝试从多个包中取最新版本
    candidate=$(version_from_cache "zl.iothub")
    if [ -z "$candidate" ]; then
        candidate=$(version_from_cache "zl.collections")
    fi

    if [ -n "$candidate" ]; then
        # 递增补丁号 (x.y.Z -> x.y.Z+1)
        IFS='.' read -r major minor patch <<< "$candidate"
        VERSION="$major.$minor.$((patch + 1))"
        info "从全局缓存检测到最新版本: $candidate"
        info "自动递增版本: $VERSION"
    else
        VERSION="2.2.0"
        warn "未检测到已有版本，使用默认版本: $VERSION"
    fi
fi

info "准备发布版本: $VERSION"

# ====================================================================
# 清理旧 artifacts
# ====================================================================
clean_artifacts() {
    local artifacts_dir="$1"
    if [ -d "$artifacts_dir" ]; then
        rm -rf "$artifacts_dir"
    fi
    mkdir -p "$artifacts_dir"
    info "artifacts 目录已清理: $artifacts_dir"
}

# ====================================================================
# 发布项目
# ====================================================================
publish_project() {
    local project_name="$1"
    local project_dir="$2"
    local artifacts_dir="$3"

    info "========================================"
    info "发布 $project_name (版本: $VERSION)"
    info "目录: $project_dir"
    info "========================================"

    cd "$project_dir"

    # 清理 artifacts
    clean_artifacts "$artifacts_dir"

    # 执行 pipeline publish (不推送到 nuget.org)
    if python3 "$PIPELINE" publish "$VERSION" --dry-run 2>&1 | tee /dev/stderr; then
        ok "dry-run 验证通过"
    else
        fail "dry-run 验证失败"
        return 1
    fi

    info "开始打包..."
    if python3 "$PIPELINE" publish "$VERSION" 2>&1 | tee /dev/stderr; then
        ok "$project_name 打包完成"
    else
        fail "$project_name 打包失败"
        return 1
    fi

    # 验证 nupkg 文件
    local count=$(find "$artifacts_dir" -name "*.${VERSION}.nupkg" 2>/dev/null | wc -l)
    if [ "$count" -gt 0 ]; then
        ok "$project_name: 成功打包 $count 个包"
        echo "  包列表:"
        find "$artifacts_dir" -name "*.${VERSION}.nupkg" | xargs -I{} echo "    $(basename {})"
    else
        fail "$project_name: 没有找到 ${VERSION}.nupkg"
        return 1
    fi

    return 0
}

# ====================================================================
# 复制到全局缓存
# ====================================================================
sync_to_cache() {
    local artifacts_dir="$1"
    local project_name="$2"

    info "同步 $project_name 到全局缓存..."

    # 找到该项目的所有包
    local nupkgs=$(find "$artifacts_dir" -name "*.${VERSION}.nupkg" 2>/dev/null | sort)

    if [ -z "$nupkgs" ]; then
        fail "没有找到 ${VERSION}.nupkg 文件"
        return 1
    fi

    local synced=0
    local skipped=0

    while IFS= read -r nupkg; do
        local basename_pkg=$(basename "$nupkg")
        # 提取包名: ZL.IotHub.2.1.0.nupkg -> ZL.IotHub
        local pkg_name=$(echo "$basename_pkg" | sed "s/\\.${VERSION}\\.nupkg\$//")

        # 目标目录
        local dest="$NUGET_CACHE/$pkg_name"

        # 如果是 ZL.PlcBase 中的包，包名可能在缓存中用小写
        # nuget 包名不区分大小写，但目录区分。用包名的原始大小写
        mkdir -p "$dest"

        # 检查是否已有同版本
        if [ -f "$dest/${basename_pkg}" ]; then
            warn "跳过 (已存在): $pkg_name $VERSION"
            skipped=$((skipped + 1))
            continue
        fi

        # 复制
        cp "$nupkg" "$dest/"
        synced=$((synced + 1))
        ok "同步: $pkg_name $VERSION"
    done <<< "$nupkgs"

    info "$project_name: 同步 $synced 个包，跳过 $skipped 个"
    return 0
}

# ====================================================================
# 主流程
# ====================================================================
main() {
    echo ""
    echo "╔══════════════════════════════════════════╗"
    echo "║   NuGet 本地包发布工具 (过渡期)           ║"
    echo "╚══════════════════════════════════════════╝"
    echo ""
    info "版本: $VERSION"
    info "全局缓存: $NUGET_CACHE"
    echo ""

    # 1. 发布 ZL.PlcBase
    if ! publish_project "ZL.PlcBase" "$PLCBASE_DIR" "$PLCBASE_DIR/artifacts"; then
        fail "ZL.PlcBase 发布失败"
        exit 1
    fi

    echo ""

    # 2. 发布 iot-sdk
    if ! publish_project "iot-sdk" "$IOTSDK_DIR" "$IOTSDK_DIR/artifacts"; then
        fail "iot-sdk 发布失败"
        exit 1
    fi

    echo ""

    # 3. 同步到全局缓存
    info "========================================"
    info "同步到全局缓存: $NUGET_CACHE"
    info "========================================"

    sync_to_cache "$PLCBASE_DIR/artifacts" "ZL.PlcBase" || exit 1
    sync_to_cache "$IOTSDK_DIR/artifacts" "iot-sdk" || exit 1

    echo ""

    # 4. 验证
    info "验证全局缓存中的版本..."

    # ZL.PlcBase 包列表
    local plcbase_expected=(
        "zl.iothub"
        "zl.iothub.bridges"
        "zl.pflite"
        "zl.tag"
    )

    for pkg in "${plcbase_expected[@]}"; do
        local dir="$NUGET_CACHE/$pkg/$VERSION"
        if [ -d "$dir" ]; then
            ok "  $pkg: $VERSION ✅"
        else
            warn "  $pkg: $VERSION (未找到)"
        fi
    done

    # iot-sdk 包列表
    local iotsdk_expected=(
        "zl.collections"
        "zl.shared"
        "zl.protocol"
        "zl.framing"
        "zl.probing"
        "zl.script"
        "zl.scripting"
        "zl.connection"
        "zl.connectionguard"
        "zl.dataprocessing"
        "zl.watchdog"
        "zl.dataconvert"
        "zl.iot.interface"
        "zl.protocolgateway"
        "zl.protocolgateway.scripting"
        "zl.db.acc"
        "zl.dao.iotdevice"
        "zl.dao.edge"
        "zl.biz.execute"
        "zl.iot.plugin"
        "zl.iot.runner"
        "zl.iot.runner.generator"
        "zl.edgeservice"
    )

    local iotsdk_ok=0
    local iotsdk_total=${#iotsdk_expected[@]}
    for pkg in "${iotsdk_expected[@]}"; do
        local dir="$NUGET_CACHE/$pkg/$VERSION"
        if [ -d "$dir" ]; then
            iotsdk_ok=$((iotsdk_ok + 1))
        else
            warn "  $pkg: $VERSION (未找到)"
        fi
    done
    if [ "$iotsdk_ok" -eq "$iotsdk_total" ]; then
        ok "  iot-sdk: 全部 $iotsdk_total/$iotsdk_total 已同步 ✅"
    else
        warn "  iot-sdk: $iotsdk_ok/$iotsdk_total 已同步"
    fi

    echo ""
    info "========================================"
    ok "发布完成! 版本: $VERSION"
    info "本地缓存: $NUGET_CACHE"
    info "如需推送到 nuget.org，执行: dotnet nuget push <nupkg> -k <key> -s https://api.nuget.org/v3/index.json"
    info "========================================"
    echo ""
}

main "$@"
