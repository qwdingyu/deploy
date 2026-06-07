#!/usr/bin/env bash
# local-pack — 通用本地打包推送工具
# 将任意 .NET 项目打包并推送到本地 NuGet feed，用于快速迭代开发
#
# 用法:
#   local-pack [选项] [项目路径]
#
# 示例:
#   local-pack .                                    # 打包当前目录
#   local-pack /path/to/project                     # 打包指定项目
#   local-pack /path/to/project -p MyLib            # 只打单个项目
#   local-pack /path/to/project -v 2.0.0-alpha      # 指定版本
#   local-pack /path/to/project --restore           # 先 restore 再 pack
#
# 选项:
#   -v, --version VERSION    指定版本号（默认自动检测）
#   -p, --project NAME       只打包指定项目名（多项目时使用）
#   -o, --output DIR         输出目录（默认: artifacts）
#   --restore                打包前先执行 dotnet restore
#   --force                  强制覆盖已存在的包
#   --feed PATH              指定本地 feed 路径（默认: ~/.nuget/local-feed）
#   -h, --help               显示帮助

set -euo pipefail

# --- 可配置默认值（可通过环境变量或命令行参数覆盖）---
LOCAL_FEED="${NUGET_LOCAL_FEED:-$HOME/.nuget/local-feed}"
OUTPUT_DIR="artifacts"
NEED_RESTORE=false

# --- 依赖检查 ---
check_deps() {
    local missing=0
    for cmd in dotnet find grep sed awk sort; do
        if ! command -v "$cmd" &>/dev/null; then
            echo "错误: 缺少必需命令: $cmd"
            missing=1
        fi
    done
    if [[ $missing -eq 1 ]]; then
        exit 1
    fi
}

usage() {
    cat << 'EOF'
local-pack — 将 .NET 项目打包推送到本地 NuGet feed

用法: local-pack [选项] [项目路径]

选项:
  -v, --version VERSION    指定版本号（默认自动检测）
  -p, --project NAME       只打包指定项目（多项目时使用）
  -o, --output DIR         输出目录（默认: artifacts）
  --restore                打包前先执行 dotnet restore
  --force                  强制覆盖已存在的包
  --feed PATH              指定本地 feed 路径（默认: ~/.nuget/local-feed）
  -h, --help               显示此帮助

项目路径:
  必须指定。使用 . 表示当前目录。
  不带路径参数时会报错。

示例:
  local-pack .                                     # 打包当前目录
  local-pack /path/to/project                      # 打包指定项目
  local-pack . -p MyLib                             # 只打当前项目中的 MyLib
  local-pack /path/to/project -v 2.0.0-alpha       # 指定版本
  local-pack . --restore                            # 先 restore 再 pack

环境变量:
  NUGET_LOCAL_FEED   覆盖默认本地 feed 路径

本地 feed 位置: ~/.nuget/local-feed/
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
        --restore)    NEED_RESTORE=true; shift ;;
        --force)      FORCE=true; shift ;;
        --feed)       LOCAL_FEED="$2"; shift 2 ;;
        -*) echo "未知参数: $1"; usage ;;
        *)  PROJ_DIR="$1"; shift ;;
    esac
done

# 必须指定项目路径
if [[ -z "$PROJ_DIR" ]]; then
    echo "错误: 未指定项目路径"
    echo ""
    echo "用法:"
    echo "  local-pack .                              # 打包当前目录"
    echo "  local-pack /path/to/project               # 打包指定项目"
    echo ""
    echo "运行 local-pack --help 查看完整帮助"
    exit 1
fi

# Resolve to absolute path
if ! PROJ_DIR=$(cd "$PROJ_DIR" && pwd) 2>/dev/null; then
    echo "错误: 目录不存在: $PROJ_DIR"
    exit 1
fi

# Check that local-feed directory exists
if [[ ! -d "$LOCAL_FEED" ]]; then
    echo "错误: 本地 feed 目录不存在: $LOCAL_FEED"
    echo "   请先创建: mkdir -p $LOCAL_FEED"
    echo "   并确保 ~/.nuget/NuGet/NuGet.Config 中已配置 local-feed 源"
    exit 1
fi

# --- Find solution or csproj for single project mode ---
SOLUTION=""
if [[ -n "$PROJECT" ]]; then
    # Search deeper for sln (up to 3 levels)
    sln=$(find "$PROJ_DIR" -maxdepth 3 -name "*.sln" | head -1)
    if [[ -n "$sln" ]]; then
        SOLUTION="$sln"
    else
        # Try to find a csproj directly
        csproj=$(find "$PROJ_DIR" -maxdepth 5 -name "${PROJECT}.csproj" | head -1)
        if [[ -z "$csproj" ]]; then
            echo "错误: 未找到项目 '$PROJECT'"
            echo "   搜索范围: $PROJ_DIR (maxdepth 5)"
            exit 1
        fi
        SOLUTION="$csproj"
    fi
fi

# --- Detect version ---
# 优先级:
# 1. 如果项目有 Directory.Build.props 中的 Version/VersionPrefix → 使用
# 2. 如果项目有单个 csproj 中的 Version/VersionPrefix → 使用
# 3. 如果有 CPM 且指定了 -p → 查找该项目的 PackageVersion
# 4. 如果有 CPM 且未指定 -p → 使用众数版本
# 5. 使用 dotnet 自身计算: dotnet build -p:ShowVersion=true
# 6. 兜底: 1.0.0
detect_version() {
    local dir="$1"
    local target_project="${2:-}"

    # 1. Try Directory.Build.props for Version/VersionPrefix
    local dbp="$dir/Directory.Build.props"
    if [[ -f "$dbp" ]]; then
        local ver
        ver=$(grep -oE '(?:^|\s)<(?:Version|VersionPrefix)\s*=\s*"[^"]*"' "$dbp" 2>/dev/null | head -1 | sed 's/.*="//;s/"//')
        if [[ -n "$ver" ]]; then
            echo "$ver"
            return
        fi
    fi

    # 2. If single project mode, try that project's csproj for Version/VersionPrefix
    if [[ -n "$target_project" ]]; then
        local target_csproj
        target_csproj=$(find "$dir" -maxdepth 5 -name "${target_project}.csproj" 2>/dev/null | head -1)
        if [[ -n "$target_csproj" && -f "$target_csproj" ]]; then
            local ver
            ver=$(grep -oE '(?:^|\s)<(?:Version|VersionPrefix)\s*=\s*"[^"]*"' "$target_csproj" 2>/dev/null | head -1 | sed 's/.*="//;s/"//')
            if [[ -n "$ver" ]]; then
                echo "$ver"
                return
            fi
        fi
    fi

    # 3. Try CPM (Directory.Packages.props)
    local cpm="$dir/Directory.Packages.props"
    if [[ -f "$cpm" ]]; then
        if [[ -n "$target_project" ]]; then
            # Find the exact project's version in CPM
            local ver
            ver=$(grep "PackageVersion.*Include=\"${target_project}\"" "$cpm" 2>/dev/null | grep -o 'Version="[^"]*"' | head -1 | sed 's/Version="//;s/"//')
            if [[ -n "$ver" ]]; then
                echo "$ver"
                return
            fi
        fi
        # Fallback: find most common version among PackageVersion entries
        local ver
        ver=$(grep -o 'Version="[^"]*"' "$cpm" 2>/dev/null | sed 's/Version="//;s/"//' | sort | uniq -c | sort -rn | head -1 | awk '{print $2}')
        if [[ -n "$ver" ]]; then
            echo "$ver"
            return
        fi
    fi

    # 4. Ask dotnet to compute the version (for first library csproj found)
    local first_lib_csproj
    first_lib_csproj=$(find "$dir" -maxdepth 4 -name "*.csproj" 2>/dev/null | while read f; do
        # Skip test/demo/bench projects
        local stem
        stem=$(basename "$f" .csproj)
        local stem_lower
        stem_lower=$(echo "$stem" | tr '[:upper:]' '[:lower:]')
        case "$stem_lower" in
            *test*|*bench*|*demo*|*sample*|*perf*) continue ;;
        esac
        # Skip Exe projects
        if grep -q '<OutputType>.*E' "$f" 2>/dev/null; then
            continue
        fi
        echo "$f"
        break
    done)
    if [[ -n "$first_lib_csproj" && -f "$first_lib_csproj" ]]; then
        local dotnet_ver
        dotnet_ver=$(dotnet build "$first_lib_csproj" --no-build -v:q --nologo 2>/dev/null \
            | grep -i "Version:" | head -1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+[^ ]*' | head -1) || true
        if [[ -z "$dotnet_ver" ]]; then
            # Try reading Version property directly
            dotnet_ver=$(dotnet msbuild "$first_lib_csproj" -getProperty:Version -nologo 2>/dev/null | tail -1) || true
        fi
        if [[ -n "$dotnet_ver" && "$dotnet_ver" != "0.1.0" ]]; then
            echo "$dotnet_ver"
            return
        fi
    fi

    # 5. Ultimate fallback
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
if [[ "$NEED_RESTORE" == "true" ]]; then
    echo "  Restore: yes"
fi
echo "======================================"

cd "$PROJ_DIR"

# --- Restore (optional) ---
if [[ "$NEED_RESTORE" == "true" ]]; then
    echo ""
    echo ">>> 还原依赖..."
    sln_for_restore=$(find "$PROJ_DIR" -maxdepth 3 -name "*.sln" | head -1)
    if [[ -n "$sln_for_restore" ]]; then
        dotnet restore "$sln_for_restore" --nologo 2>&1 | tail -5
    else
        # Restore each csproj
        for csproj in $(find "$PROJ_DIR" -maxdepth 4 -name "*.csproj" | sort); do
            dotnet restore "$csproj" --nologo -v:q 2>&1 | tail -2 || true
        done
    fi
    echo ">>> 还原完成"
fi

# --- Helper: filter dotnet output for key lines (language-agnostic) ---
filter_dotnet() {
    grep -iE "succeeded|failed|error |warning |restored|created|pack" || true
}

# --- Pack & push ---
if [[ -n "$PROJECT" ]]; then
    # Single project mode
    echo ""
    echo ">>> 打包: $PROJECT"

    mkdir -p "$OUTPUT_DIR"

    if [[ "$SOLUTION" == *.csproj ]]; then
        # Direct csproj path — pack just this project
        dotnet pack "$SOLUTION" \
            -c Release \
            -o "$OUTPUT_DIR" \
            -p:Version="$VERSION" \
            --nologo \
            2>&1 | filter_dotnet | tail -5

        nupkg=$(find "$OUTPUT_DIR" -maxdepth 1 -name "${PROJECT}.${VERSION}.nupkg" 2>/dev/null | head -1)
        if [[ -z "$nupkg" || ! -f "$nupkg" ]]; then
            nupkg=$(find "$OUTPUT_DIR" -maxdepth 1 -name "${PROJECT}.${VERSION}-*.nupkg" 2>/dev/null | head -1)
        fi
    else
        # Pack via sln — dotnet will pack all packable projects in the sln
        dotnet pack "$SOLUTION" \
            -c Release \
            -o "$OUTPUT_DIR" \
            -p:Version="$VERSION" \
            --nologo \
            2>&1 | filter_dotnet | tail -10

        nupkg=$(find "$OUTPUT_DIR" -maxdepth 1 -name "${PROJECT}.${VERSION}.nupkg" 2>/dev/null | head -1)
        if [[ -z "$nupkg" || ! -f "$nupkg" ]]; then
            nupkg=$(find "$OUTPUT_DIR" -maxdepth 1 -name "${PROJECT}.${VERSION}-*.nupkg" 2>/dev/null | head -1)
        fi
    fi

    if [[ -z "$nupkg" || ! -f "$nupkg" ]]; then
        echo "❌ 未找到 $PROJECT 的 nupkg（版本: $VERSION，输出目录: $OUTPUT_DIR/）"
        echo "   输出目录内容:"
        ls -1 "$OUTPUT_DIR"/*.nupkg 2>/dev/null || echo "   (无 nupkg 文件)"
        exit 1
    fi

    if $FORCE; then
        dotnet nuget push "$nupkg" --source "local-feed" --no-service-endpoint 2>&1
    else
        dotnet nuget push "$nupkg" --source "local-feed" --skip-duplicate 2>&1 || true
    fi
    echo "✅ $(basename "$nupkg") 已推送到本地 feed"

else
    # Full pack — all library projects
    echo ""
    echo ">>> 全量打包..."

    mkdir -p "$OUTPUT_DIR"
    rm -f "$OUTPUT_DIR"/*.nupkg 2>/dev/null || true

    # Find solution (search up to 3 levels)
    sln_file=$(find "$PROJ_DIR" -maxdepth 3 -name "*.sln" | head -1)
    if [[ -n "$sln_file" ]]; then
        dotnet pack "$sln_file" \
            -c Release \
            -o "$OUTPUT_DIR" \
            -p:Version="$VERSION" \
            --nologo \
            2>&1 | filter_dotnet | tail -15
    else
        # No sln — pack each .csproj individually, skipping non-library projects
        found=0
        packed=0
        for csproj in $(find "$PROJ_DIR" -maxdepth 5 -name "*.csproj" | sort); do
            stem=$(basename "$csproj" .csproj)
            stem_lower=$(echo "$stem" | tr '[:upper:]' '[:lower:]')

            # Skip test/bench/demo/sample/perf projects
            case "$stem_lower" in
                *test*|*bench*|*benchmark*|*demo*|*sample*|*perf*|*e2e*) continue ;;
            esac

            # Skip Exe/WinExe projects (they're apps, not packable libraries)
            if grep -q '<OutputType>\s*\(Exe\|WinExe\)' "$csproj" 2>/dev/null; then
                continue
            fi

            # Skip projects without <GeneratePackageOnBuild> or that are content projects
            # (most library projects are fine to pack)

            echo "  pack: $stem"
            found=$((found+1))
            result=$(dotnet pack "$csproj" \
                -c Release \
                -o "$OUTPUT_DIR" \
                -p:Version="$VERSION" \
                --nologo \
                2>&1) || true
            if echo "$result" | grep -qi "succeeded\|created.*nupkg"; then
                packed=$((packed+1))
            fi
            echo "$result" | filter_dotnet | tail -2
        done
        if [[ $found -eq 0 ]]; then
            echo "❌ 未找到任何可打包的 .csproj 文件"
            exit 1
        fi
        echo "  (扫描 $found 个项目, 成功 $packed 个)"
    fi

    echo ">>> 推送到本地 feed..."
    count=0
    for nupkg in "$OUTPUT_DIR"/*.nupkg; do
        [[ -f "$nupkg" ]] || continue
        name=$(basename "$nupkg")
        if $FORCE; then
            dotnet nuget push "$nupkg" --source "local-feed" --no-service-endpoint 2>&1 || true
        else
            dotnet nuget push "$nupkg" --source "local-feed" --skip-duplicate 2>&1 || true
        fi
        count=$((count+1))
        echo "  [$count] $name"
    done

    if [[ $count -eq 0 ]]; then
        echo "❌ $OUTPUT_DIR/ 目录下没有 nupkg 文件，打包可能全部失败"
        exit 1
    fi

    echo ""
    echo "✅ 完成! $count 个包已推送到本地 feed"
    echo "   消费者执行: dotnet restore"
fi
