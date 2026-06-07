#!/usr/bin/env bash
# ============================================================================
# 验证 NuGet 包是否包含混淆后的 DLL
# 用途: 下载 nuget.org 上的包，解压 DLL，与本地 obfuscated/ 目录对比 SHA256
#
# 用法:
#   ./scripts/verify-nuget-obfuscation.sh <package-name> <version> [tfmdir]
#   ./scripts/verify-nuget-obfuscation.sh PlcSimulator.Core 1.0.1
#   ./scripts/verify-nuget-obfuscation.sh ZL.PlcBase 2.0.1 net8.0
#
# 示例（批量验证所有包）:
#   for pkg in PlcSimulator.Core PlcSimulator.Grpc ProtocolGateway ProtocolGateway.Scripting; do
#     bash scripts/verify-nuget-obfuscation.sh "$pkg" 1.0.1
#   done
# ============================================================================
set -euo pipefail

PKG_NAME="${1:?Usage: verify-nuget-obfuscation.sh <package-name> <version> [tfmdir]}"
VERSION="${2:?Usage: verify-nuget-obfuscation.sh <package-name> <version> [tfmdir]}"
TFMDIR="${3:-net8.0}"

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOCAL_DLL="$PROJECT_DIR/obfuscated/$PKG_NAME/$PKG_NAME.dll"
TMP_DIR="/tmp/nuget-verify-$$"
NUPKG_FILE="$TMP_DIR/$PKG_NAME.$VERSION.nupkg"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

PASS=0
FAIL=0

log()  { printf "${YELLOW}[INFO]${NC}  $*\n"; }
ok()   { printf "${GREEN}[PASS]${NC}  $*\n"; PASS=$((PASS+1)); }
fail() { printf "${RED}[FAIL]${NC}  $*\n"; FAIL=$((FAIL+1)); }

cleanup() {
    rm -rf "$TMP_DIR" "$NUPKG_FILE"
}

# ============================================================================
log "=== 验证 $PKG_NAME v$VERSION 的混淆状态 ==="
# ============================================================================

# Step 1: 检查本地 obfuscated DLL
if [[ ! -f "$LOCAL_DLL" ]]; then
    fail "本地混淆 DLL 不存在: $LOCAL_DLL"
    log "提示: 先在本地运行 bash scripts/release-verify.sh $VERSION"
    exit 1
fi
LOCAL_SHA=$(sha256sum "$LOCAL_DLL" | cut -d' ' -f1)
log "本地混淆 DLL: $LOCAL_SHA"

# Step 2: 从 NuGet.org 下载包
mkdir -p "$TMP_DIR"
# 尝试多个下载端点（V2 API 有时会重定向为网页）
log "正在从 nuget.org 下载 $PKG_NAME v$VERSION ..."
if curl -sL --connect-timeout 10 --max-time 30 \
    "https://www.nuget.org/api/v2/package/$PKG_NAME/$VERSION" \
    -o "$NUPKG_FILE" 2>/dev/null; then
    
    # 检查是否下载了有效的 ZIP
    FILE_TYPE=$(file "$NUPKG_FILE" 2>/dev/null)
    if echo "$FILE_TYPE" | grep -qi "zip\|archive"; then
        ok "下载成功 (ZIP)"
    else
        # 可能是 NuGet CDN 传播延迟，尝试备用端点
        log "V2 API 返回非 ZIP 内容 (传播中)，尝试 CDN 端点..."
        sleep 3
        curl -sL --connect-timeout 10 --max-time 30 \
            "https://globalcdn.nuget.org/packages/$PKG_NAME.$VERSION.nupkg" \
            -o "$NUPKG_FILE" 2>/dev/null || true
        if ! file "$NUPKG_FILE" 2>/dev/null | grep -qi "zip\|archive"; then
            fail "无法下载有效的 nupkg（CDN 尚未传播，请稍后重试）"
            log "NuGet 推送日志显示包已 Created，但 CDN 需要 1-5 分钟同步"
            cleanup
            exit 1
        fi
    fi
else
    fail "下载失败"
    cleanup
    exit 1
fi

# Step 3: 解压并提取 DLL
unzip -qo "$NUPKG_FILE" -d "$TMP_DIR/extracted/" 2>&1 || {
    fail "解压失败（可能不是有效的 ZIP）"
    file "$NUPKG_FILE"
    cleanup
    exit 1
}

NUGET_DLL="$TMP_DIR/extracted/lib/$TFMDIR/$PKG_NAME.dll"
if [[ ! -f "$NUGET_DLL" ]]; then
    # 尝试模糊匹配
    NUGET_DLL=$(find "$TMP_DIR/extracted" -name "$PKG_NAME.dll" 2>/dev/null | head -1)
fi

if [[ ! -f "$NUGET_DLL" ]]; then
    fail "在 nupkg 中找不到 $PKG_NAME.dll（检查 TFM 路径: lib/$TFMDIR/）"
    log "包内文件列表:"
    unzip -l "$NUPKG_FILE" 2>/dev/null | grep "\.dll" || echo "(无)"
    cleanup
    exit 1
fi

NUGET_SHA=$(sha256sum "$NUGET_DLL" | cut -d' ' -f1)
log "NuGet DLL:       $NUGET_SHA"

# Step 4: SHA256 对比
if [[ "$LOCAL_SHA" == "$NUGET_SHA" ]]; then
    ok "$PKG_NAME: SHA256 完全匹配 — NuGet 包包含混淆版 DLL"
    log "校验: 二进制完全相同 ✅ 混淆版已发布"
else
    fail "$PKG_NAME: SHA256 不匹配"
    log "❌ NuGet 包中的 DLL 与本地混淆版不同"
    log "  可能原因:"
    log "    1. 推送时使用了未混淆的包（版本号错误）"
    log "    2. nuget.org 上的是旧版本（CDN 缓存）"
    log "    3. 本地混淆前后重新 build 过，hash 变化"
fi

# Step 5: 额外验证 — 检查 DLL 中是否有 Unicode 混淆名
log ""
log "--- 额外验证: 检查 Unicode 混淆名（私有方法被混淆的标志）==="
UNICODE_COUNT=$(strings "$NUGET_DLL" 2>/dev/null | grep -c $'[\xc0-\xff][\x80-\xbf]' || true)
if [[ $UNICODE_COUNT -gt 5 ]]; then
    ok "DLL 中包含 $UNICODE_COUNT 个 Unicode 编码名字（混淆生效）"
else
    log "DLL 中包含 $UNICODE_COUNT 个 Unicode 编码名字"
    log "（KeepPublicApi=true 保留公开类型名，Unicode 混淆只影响私有成员）"
fi

# Step 6: 报告
echo ""
echo "========================================================"
echo "  验证结果: $PKG_NAME v$VERSION"
echo "========================================================"
echo "  通过: $PASS  失败: $FAIL"
echo ""

if [[ $FAIL -eq 0 ]]; then
    printf "${GREEN}✅ $PKG_NAME v$VERSION: 混淆版验证通过${NC}\n"
    cleanup
    exit 0
else
    printf "${RED}❌ $PKG_NAME v$VERSION: 验证失败${NC}\n"
    cleanup
    exit 1
fi
