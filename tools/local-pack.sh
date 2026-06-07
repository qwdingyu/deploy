#!/usr/bin/env bash
# local-pack — 通用本地打包推送工具
# 将任意 .NET 项目打包并推送到本地 NuGet feed，用于快速迭代开发
#
# 用法: local-pack [选项] [项目路径]
#
# 示例:
#   local-pack .                                    # 打包当前目录
#   local-pack                                      # 打包当前目录（省略 .）
#   local-pack /path/to/project                     # 打包指定项目
#   local-pack -p ZL.Watchdog                       # 只打当前目录中的 ZL.Watchdog
#   local-pack /path/to/project -p MyLib            # 只打指定项目中的 MyLib
#   local-pack -v 2.0.0-alpha                       # 指定版本打包当前目录

set -euo pipefail

LOCAL_FEED="$HOME/.nuget/local-feed"
OUTPUT_DIR="artifacts"

usage() {
    cat << 'EOF'
local-pack — 将 .NET 项目打包推送到本地 NuGet feed

用法: local-pack [选项] [项目路径]

选项:
  -v, --version VERSION    指定版本号（默认自动检测）
  -p, --project NAME       只打包指定项目（多项目时使用）
  -o, --output DIR         输出目录（默认: artifacts）
  --force                  强制覆盖已存在的包
  -h, --help               显示此帮助

项目路径:
  可选。省略时默认为当前目录。
  使用 . 表示当前目录。

示例:
  local-pack                                     # 打包当前目录
  local-pack .                                   # 同上
  local-pack /path/to/project                    # 打包指定项目
  local-pack -p ZL.Watchdog                      # 只打当前目录中的 ZL.Watchdog
  local-pack /path/to/project -v 2.0.0-alpha     # 指定项目 + 指定版本
  local-pack -p MyLib -v 3.0.0                   # 当前目录 + 指定项目 + 指定版本

依赖:
  - dotnet SDK
  - ~/.nuget/local-feed/ 目录存在
  - ~/.nuget/NuGet/NuGet.Config 中配置了 local-feed 源

EOF
    exit 0
}

# --- Parse args ---
VERSION=""
PROJECT=""
FORCE=false
PROJ_DIR=""

while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help) usage ;;
        -v|--version) VERSION="$2"; shift 2 ;;
        -p|--project) PROJECT="$2"; shift 2 ;;
        -o|--output)  OUTPUT_DIR="$2"; shift 2 ;;
        --force)      FORCE=true; shift ;;
        -*) echo "未知参数: $1"; usage ;;
        *)  PROJ_DIR="$1"; shift ;;
    esac
done

# Default: current directory
if [[ -z "$PROJ_DIR" ]]; then
    PROJ_DIR="."
fi

# Resolve to absolute path
_resolved=$(cd "$PROJ_DIR" 2>/dev/null && pwd) || {
    echo "错误: 目录不存在: $PROJ_DIR"
    exit 1
}
PROJ_DIR="$_resolved"

# Check local-feed directory exists
if [[ ! -d "$LOCAL_FEED" ]]; then
    echo "错误: 本地 feed 目录不存在: $LOCAL_FEED"
    echo "   请先创建: mkdir -p $LOCAL_FEED"
    exit 1
fi

# --- Find solution or csproj ---
SOLUTION=""
if [[ -n "$PROJECT" ]]; then
    # 单个项目模式：直接找 csproj，不走 sln（否则会打包整个解决方案）
    csproj=$(find "$PROJ_DIR" -maxdepth 5 -name "${PROJECT}.csproj" \
        -not -path "*/obj/*" -not -path "*/bin/*" 2>/dev/null | head -1)
    if [[ -z "$csproj" ]]; then
        echo "错误: 未找到项目 '$PROJECT'"
        exit 1
    fi
    SOLUTION="$csproj"
fi

# --- Helpers ---
# 从 XML 中提取 Version/VersionPrefix 的值，同时支持两种写法：
#   属性式: <Version="1.0.0" />
#   元素式: <VersionPrefix>1.0.0</VersionPrefix>
extract_xml_version() {
    local file="$1"
    local ver=""
    # 先试属性式: <Version="x.y.z" />
    ver=$(grep -oE '<Version="[^"]*"' "$file" 2>/dev/null | head -1 | sed 's/.*="//;s/"//') || true
    if [[ -n "$ver" ]]; then echo "$ver"; return; fi
    # 再试元素式: <Version>x.y.z</Version> 或 <VersionPrefix>x.y.z</VersionPrefix>
    ver=$(grep -oE '<Version(?:Prefix)?>[^<]*<' "$file" 2>/dev/null | head -1 | sed 's/^<[^>]*>//;s/<.*//') || true
    if [[ -n "$ver" ]]; then echo "$ver"; return; fi
}

# --- Detect version ---
# 优先级:
# 1. Directory.Build.props 中的 <Version> 或 <VersionPrefix>
# 2. 指定 -p 时，从 CPM 查找该项目的 PackageVersion
# 3. 未指定 -p 时，从 CPM 取出现最多的版本号（众数）
# 4. 指定 -p 时，从目标 .csproj 中查找 <Version>
# 5. 兜底: 1.0.0
detect_version() {
    local dir="$1"
    local target_project="$2"

    # 1. Directory.Build.props
    if [[ -f "$dir/Directory.Build.props" ]]; then
        local ver
        ver=$(extract_xml_version "$dir/Directory.Build.props")
        if [[ -n "$ver" ]]; then
            echo "$ver"; return
        fi
    fi

    # 2/3. CPM (Directory.Packages.props)
    if [[ -f "$dir/Directory.Packages.props" ]]; then
        if [[ -n "$target_project" ]]; then
            local ver
            # 使用 grep -F（固定字符串匹配），避免正则注入，无需转义
            ver=$(grep -F "Include=\"${target_project}\"" "$dir/Directory.Packages.props" 2>/dev/null \
                | grep 'PackageVersion' \
                | grep -o 'Version="[^"]*"' | head -1 | sed 's/Version="//;s/"//') || true
            if [[ -n "$ver" ]]; then
                echo "$ver"; return
            fi
        fi
        # 众数版本
        local ver
        ver=$(grep -o 'Version="[^"]*"' "$dir/Directory.Packages.props" 2>/dev/null \
            | sed 's/Version="//;s/"//' | sort | uniq -c | sort -rn | head -1 | awk '{print $2}') || true
        if [[ -n "$ver" ]]; then
            echo "$ver"; return
        fi
    fi

    # 4. Target csproj
    if [[ -n "$target_project" ]]; then
        local tcsproj
        tcsproj=$(find "$dir" -maxdepth 5 -name "${target_project}.csproj" \
            -not -path "*/obj/*" -not -path "*/bin/*" 2>/dev/null | head -1)
        if [[ -n "$tcsproj" && -f "$tcsproj" ]]; then
            local ver
            ver=$(extract_xml_version "$tcsproj")
            if [[ -n "$ver" ]]; then
                echo "$ver"; return
            fi
        fi
    fi

    # 5. Fallback
    echo "1.0.0"
}

if [[ -z "$VERSION" ]]; then
    VERSION=$(detect_version "$PROJ_DIR" "$PROJECT")
fi

# --- Banner ---
echo "======================================"
echo "  local-pack"
echo "  项目:   $PROJ_DIR"
echo "  Feed:   $LOCAL_FEED"
echo "  版本:   $VERSION"
echo "  输出:   $OUTPUT_DIR"
if [[ -n "$PROJECT" ]]; then
    echo "  目标:   $PROJECT"
fi
echo "======================================"

cd "$PROJ_DIR"

# --- Pack & push ---
if [[ -n "$PROJECT" ]]; then
    # === 单个项目模式 ===
    echo ""
    echo ">>> 打包: $PROJECT"

    mkdir -p "$OUTPUT_DIR"

    dotnet pack "$SOLUTION" -c Release -o "$OUTPUT_DIR" -p:Version="$VERSION" --nologo 2>&1

    # Find nupkg (exact version match)
    nupkg=$(find "$OUTPUT_DIR" -maxdepth 1 -name "${PROJECT}.${VERSION}.nupkg" 2>/dev/null | head -1)
    if [[ -z "$nupkg" || ! -f "$nupkg" ]]; then
        nupkg=$(find "$OUTPUT_DIR" -maxdepth 1 -name "${PROJECT}.${VERSION}-*.nupkg" 2>/dev/null | head -1)
    fi

    if [[ -z "$nupkg" || ! -f "$nupkg" ]]; then
        echo "❌ 未找到 $PROJECT 的 nupkg（版本: $VERSION）"
        ls -1 "$OUTPUT_DIR"/*.nupkg 2>/dev/null && echo "   以上为实际生成的包" || echo "   artifacts/ 目录为空"
        exit 1
    fi

    if $FORCE; then
        dotnet nuget push "$nupkg" --source "local-feed" --no-service-endpoint 2>&1
    else
        dotnet nuget push "$nupkg" --source "local-feed" --no-service-endpoint 2>&1 || true
    fi
    echo "✅ $(basename "$nupkg") 已推送到本地 feed"

else
    # === 全量打包模式 ===
    echo ""
    echo ">>> 全量打包..."

    mkdir -p "$OUTPUT_DIR"
    rm -f "$OUTPUT_DIR"/*.nupkg 2>/dev/null || true

    sln_file=$(find "$PROJ_DIR" -maxdepth 3 -name "*.sln" \
        -not -path "*/obj/*" -not -path "*/bin/*" 2>/dev/null | head -1)
    if [[ -n "$sln_file" ]]; then
        dotnet pack "$sln_file" -c Release -o "$OUTPUT_DIR" -p:Version="$VERSION" --nologo 2>&1
    else
        # No sln — pack each .csproj, skip non-library projects
        found=0
        packed=0
        skipped=0
        for csproj in $(find "$PROJ_DIR" -maxdepth 5 -name "*.csproj" \
            -not -path "*/obj/*" -not -path "*/bin/*" 2>/dev/null | sort); do
            stem=$(basename "$csproj" .csproj)
            stem_lower=$(echo "$stem" | tr '[:upper:]' '[:lower:]')

            # Skip test/bench/demo/sample/perf projects
            case "$stem_lower" in
                *test*|*bench*|*benchmark*|*demo*|*sample*|*perf*|*e2e*)
                    skipped=$((skipped+1)); continue ;;
            esac

            # Skip Exe/WinExe projects
            if grep -q '<OutputType>' "$csproj" 2>/dev/null; then
                if grep '<OutputType>' "$csproj" 2>/dev/null | grep -qE '(Exe|WinExe)'; then
                    skipped=$((skipped+1)); continue
                fi
            fi

            echo "  pack: $stem"
            found=$((found+1))
            result=$(dotnet pack "$csproj" -c Release -o "$OUTPUT_DIR" -p:Version="$VERSION" --nologo 2>&1) || true
            if echo "$result" | grep -qiE 'succeeded|成功|created.*nupkg|已创建'; then
                packed=$((packed+1))
            fi
        done
        if [[ $found -eq 0 ]]; then
            echo "❌ 未找到任何可打包的 .csproj 文件"
            exit 1
        fi
        echo "  (打包 $found 个项目, 成功 $packed 个, 跳过 $skipped 个)"
    fi

    echo ""
    echo ">>> 推送到本地 feed..."
    count=0
    for nupkg in "$OUTPUT_DIR"/*.nupkg; do
        [[ -f "$nupkg" ]] || continue
        name=$(basename "$nupkg")
        dotnet nuget push "$nupkg" --source "local-feed" --no-service-endpoint 2>&1 || true
        count=$((count+1))
        echo "  [$count] $name"
    done

    if [[ $count -eq 0 ]]; then
        echo "❌ $OUTPUT_DIR/ 目录下没有 nupkg 文件"
        exit 1
    fi

    echo ""
    echo "✅ 完成! $count 个包已推送到本地 feed"
    echo "   消费者执行: dotnet restore"
fi
