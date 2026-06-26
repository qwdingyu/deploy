#!/usr/bin/env bash
# ============================================================
# nuget.org 上传测试脚本（极简版）
# 用法:
#   export NUGET_API_KEY=oy2...
#   bash test-nuget-push.sh ZL.Test.Package
# ============================================================
set -euo pipefail

PKG_ID="${1:?错误: 请指定包名, 如 bash test-nuget-push.sh ZL.MyTest}"

if [ -z "${NUGET_API_KEY:-}" ]; then
  echo "错误: 需要设置 NUGET_API_KEY 环境变量"
  exit 1
fi

WORK_DIR=$(mktemp -d)
trap "rm -rf $WORK_DIR" EXIT

echo "=== 创建占位包: $PKG_ID ==="

cat > "$WORK_DIR/$PKG_ID.csproj" <<EOF
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>netstandard2.0</TargetFramework>
    <PackageId>$PKG_ID</PackageId>
    <Version>0.0.1-test</Version>
    <Description>Test push - can be deleted later.</Description>
    <Authors>Test</Authors>
    <IsPackable>true</IsPackable>
  </PropertyGroup>
</Project>
EOF

echo "=== 打包 ==="
dotnet pack "$WORK_DIR/$PKG_ID.csproj" -c Release -o "$WORK_DIR/out" --nologo -v q

NUPKG=$(ls "$WORK_DIR/out/$PKG_ID."*".nupkg" | head -1)
echo "=== 推送: $NUPKG ==="
dotnet nuget push "$NUPKG" \
  --source "https://api.nuget.org/v3/index.json" \
  --api-key "$NUGET_API_KEY" \
  --skip-duplicate

echo ""
echo "=== 完成 ==="
