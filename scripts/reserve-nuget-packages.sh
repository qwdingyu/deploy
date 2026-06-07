#!/usr/bin/env bash
# ============================================================
# 有思智联 UseThink NuGet 包名批量占位脚本(风控安全版）
# ============================================================
# 风控策略：
#   1. 每个 push 间隔 15 秒(nuget.org 限流 300次/小时，15秒间隔远低于阈值）
#   2. 每批最多 30 个包，批间暂停 60 秒
#   3. 失败自动重试 1 次(间隔 30 秒）
#   4. 只 push P0 优先级的包(最关键的 14 个）
#   5. --skip-duplicate 防止重复推送已注册包
#   6. 记录日志到 scripts/nuget-reserve-log.txt
#
# 使用方法：
#   bash scripts/reserve-nuget-p0.sh          # 占位 P0 优先级
#   bash scripts/reserve-nuget-p1.sh          # 占位 P1 优先级
#   bash scripts/reserve-nuget-p2.sh          # 占位 P2 优先级
#   bash scripts/reserve-nuget-p0.sh --dry-run # 仅预览不推送
# ============================================================
set -euo pipefail

PRIORITY="${1:-P0}"
PRIORITY="${PRIORITY#--}"  # 去掉可能的 -- 前缀
DRY_RUN=false
if [[ "$*" == *"--dry-run"* ]]; then DRY_RUN=true; fi

# 风控参数
INTERVAL=15       # 每个 push 之间的间隔秒数
BATCH_SIZE=30     # 每批最多推送的包数
BATCH_PAUSE=60    # 批间暂停秒数
MAX_RETRY=1       # 最大重试次数
RETRY_INTERVAL=30 # 重试间隔秒数

# 颜色
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

# 配置文件
CONFIG_FILE="scripts/nuget-packages.txt"
LOG_FILE="scripts/nuget-reserve-log.txt"
CACHE_FILE="scripts/.nuget-reserved-cache.txt"  # 本地缓存: 我已 push 成功过的包 ID
CACHE_VERSION=1                                  # 缓存格式版本号,未来结构变更时便于迁移

# 加载本地缓存(避免重复 HTTP 查询 NuGet)
# 注: 用普通数组而非关联数组,兼容 macOS 默认 bash 3.2 (不支持 declare -A)
declare -a CACHE=()
if [ -f "$CACHE_FILE" ]; then
  while IFS= read -r cached_id || [ -n "$cached_id" ]; do
    [[ "$cached_id" =~ ^[[:space:]]*# ]] && continue
    [[ -z "${cached_id// }" ]] && continue
    cached_id=$(echo "$cached_id" | xargs)
    CACHE+=("$cached_id")
  done < "$CACHE_FILE"
fi

# 检查 pkg_id 是否在缓存中(线性查找,包少时性能可忽略)
in_cache() {
  local target="$1"
  local item
  for item in "${CACHE[@]}"; do
    [ "$item" = "$target" ] && return 0
  done
  return 1
}

# 写入缓存(追加,带锁防并发)
write_cache() {
  local pkg_id="$1"
  # 用 mkdir 实现简易文件锁,避免多进程并发写
  local lock_dir="${CACHE_FILE}.lock"
  local waited=0
  while ! mkdir "$lock_dir" 2>/dev/null; do
    sleep 1
    waited=$((waited + 1))
    [ $waited -ge 30 ] && { rm -rf "$lock_dir"; break; }  # 最多等30秒
  done
  # 写之前再检查一次,避免重复行
  if ! grep -Fxq "$pkg_id" "$CACHE_FILE" 2>/dev/null; then
    echo "$pkg_id" >> "$CACHE_FILE"
  fi
  rmdir "$lock_dir" 2>/dev/null
}

# API Key
if [ -z "${NUGET_API_KEY:-}" ]; then
  echo -e "${RED}错误: 需要设置 NUGET_API_KEY 环境变量${NC}"
  echo "  export NUGET_API_KEY=oy2xxx..."
  echo "  或已在 ~/.zshenv 中配置"
  exit 1
fi

[ ! -f "$CONFIG_FILE" ] && { echo -e "${RED}配置文件不存在: $CONFIG_FILE${NC}"; exit 1; }

echo -e "${BLUE}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  有思智联 NuGet 包名批量占位(风控安全版）                  ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "优先级: ${CYAN}${PRIORITY}${NC}"
echo -e "风控参数: 间隔=${INTERVAL}s / 批次=${BATCH_SIZE} / 批间暂停=${BATCH_PAUSE}s"
echo -e "日志文件: ${CYAN}${LOG_FILE}${NC}"
echo ""

# ── dry-run 模式 ──
if [ "$DRY_RUN" = true ]; then
  echo -e "${YELLOW}=== DRY-RUN 模式(仅预览，不推送） ===${NC}"
  echo ""
fi

# ── 读取配置，筛选指定优先级 ──
declare -a TO_RESERVE=()
declare -a SKIP_REGISTERED=()
declare -a SKIP_CATEGORY=()

while IFS= read -r line || [ -n "$line" ]; do
  [[ "$line" =~ ^[[:space:]]*# ]] && continue
  [[ -z "${line// }" ]] && continue

  IFS='|' read -r pkg_id category obfuscate priority description <<< "$line"
  pkg_id=$(echo "$pkg_id" | xargs)
  category=$(echo "$category" | xargs)
  priority=$(echo "$priority" | xargs)

  [ -z "$pkg_id" ] && continue

  # 只处理指定优先级
  [ "$priority" != "$PRIORITY" ] && continue

  # TMom 和 X 类不推到 nuget.org
  if [ "$category" = "TMom" ] || [ "$category" = "X" ]; then
    SKIP_CATEGORY+=("$pkg_id")
    continue
  fi
  # ① 先查本地缓存(我已 push 成功过的,免 HTTP 查询)
  if in_cache "$pkg_id"; then
    SKIP_REGISTERED+=("$pkg_id")
    continue
  fi

  # ② 缓存没命中,再 HTTP 查 NuGet 是否已被注册
  lower_id=$(echo "$pkg_id" | tr '[:upper:]' '[:lower:]')
  http_code=$(curl -s -o /dev/null -w "%{http_code}" \
    "https://api.nuget.org/v3/registration5-gz-semver2/${lower_id}/index.json" \
    --connect-timeout 5 --max-time 8 2>/dev/null || echo "000")

  if [ "$http_code" = "200" ]; then
    SKIP_REGISTERED+=("$pkg_id")
    # 已被占(可能是我们自己,也可能是别人),写入本地缓存,下次免查
    write_cache "$pkg_id"
    continue
  fi

  TO_RESERVE+=("$pkg_id|$description")
done < "$CONFIG_FILE"

echo -e "${BOLD}预览：${NC}"
echo ""
echo -e "  需要占位: ${GREEN}${#TO_RESERVE[@]}${NC} 个包 (优先级 $PRIORITY)"
echo -e "  已注册跳过: ${YELLOW}${#SKIP_REGISTERED[@]}${NC} 个"
echo -e "  分类跳过: ${YELLOW}${#SKIP_CATEGORY[@]}${NC} 个"

if [ ${#SKIP_REGISTERED[@]} -gt 0 ]; then
  echo ""
  echo -e "  已注册(跳过）:"
  for s in "${SKIP_REGISTERED[@]}"; do echo -e "    ${YELLOW}$s${NC}"; done
fi

echo ""

if [ ${#TO_RESERVE[@]} -eq 0 ]; then
  echo -e "${GREEN}没有需要占位的包。所有 $PRIORITY 优先级的包已注册或被跳过。${NC}"
  exit 0
fi

echo -e "  待占位列表:"
for item in "${TO_RESERVE[@]}"; do
  IFS='|' read -r pid desc <<< "$item"
  echo -e "    ${GREEN}$pid${NC} - $desc"
done
echo ""

# ── dry-run 模式到此结束 ──
if [ "$DRY_RUN" = true ]; then
  echo -e "${YELLOW}DRY-RUN 结束。如需执行，去掉 --dry-run 参数。${NC}"
  exit 0
fi

# ── 确认 ──
echo -e "${YELLOW}即将推送 ${#TO_RESERVE[@]} 个占位包到 nuget.org${NC}"
echo -e "${YELLOW}预计耗时: $(echo "${#TO_RESERVE[@]} * $INTERVAL / 60" | bc) 分钟${NC}"
echo ""
read -p "确认继续？(y/N) " -r confirm
[[ ! "$confirm" =~ ^[Yy]$ ]] && { echo "已取消"; exit 0; }

# ── 日志初始化 ──
echo "# NuGet 占位日志 - $(date '+%Y-%m-%d %H:%M:%S') - 优先级 $PRIORITY" > "$LOG_FILE"
echo "# 格式: PackageId | Status | Time" >> "$LOG_FILE"

# ── 批量推送 ──
SUCCESS=0
FAIL=0
BATCH_NUM=0
TOTAL=${#TO_RESERVE[@]}
COUNT=0

echo ""
echo -e "${CYAN}══════════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}  开始推送${NC}"
echo -e "${CYAN}══════════════════════════════════════════════════════════════${NC}"
echo ""

WORK_DIR=$(mktemp -d)
trap "rm -rf $WORK_DIR" EXIT

for item in "${TO_RESERVE[@]}"; do
  IFS='|' read -r pkg_id description <<< "$item"
  COUNT=$((COUNT + 1))

  # 批次控制
  if [ $((COUNT % BATCH_SIZE)) -eq 1 ] && [ $COUNT -gt 1 ]; then
    BATCH_NUM=$((BATCH_NUM + 1))
    echo ""
    echo -e "${YELLOW}── 批次 $BATCH_NUM 完成，暂停 ${BATCH_PAUSE}s ──${NC}"
    sleep $BATCH_PAUSE
    echo ""
  fi

  # 创建最小占位包
  mkdir -p "$WORK_DIR/$pkg_id"
  safe_desc="${description//\"/\\\"}"
  cat > "$WORK_DIR/$pkg_id/${pkg_id}.csproj" << CSPEOF
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>netstandard2.0</TargetFramework>
    <PackageId>${pkg_id}</PackageId>
    <Version>0.0.1-placeholder</Version>
    <Description>${safe_desc} - Placeholder package. Official release coming soon from UseThink (有思智联).</Description>
    <Authors>UseThink</Authors>
    <Company>UseThink (有思智联)</Company>
    <PackageLicenseExpression>Apache-2.0</PackageLicenseExpression>
    <RepositoryUrl>https://github.com/tmom/tmom</RepositoryUrl>
    <PackageTags>placeholder;iot;plc;mes;industrial;usethink</PackageTags>
    <IsPackable>true</IsPackable>
  </PropertyGroup>
</Project>
CSPEOF

  # 打包
  pack_ok=true
  if ! (cd "$WORK_DIR/$pkg_id" && dotnet pack -c Release -o "$WORK_DIR/out" --nologo -v q 2>/dev/null); then
    echo -e "  [$COUNT/$TOTAL] ${RED}✗ $pkg_id 打包失败${NC}"
    echo "$pkg_id | PACK_FAIL | $(date '+%H:%M:%S')" >> "$LOG_FILE"
    FAIL=$((FAIL + 1))
    pack_ok=false
  fi

  if [ "$pack_ok" = true ]; then
    # 推送
    nupkg=$(ls "$WORK_DIR/out/${pkg_id}."*".nupkg" 2>/dev/null | head -1)
    push_ok=false

    for attempt in 1 $((MAX_RETRY + 1)); do
      [ $attempt -gt $((MAX_RETRY + 1)) ] && break

      if [ $attempt -gt 1 ]; then
        echo -e "    ${YELLOW}重试 #$attempt...${NC}"
        sleep $RETRY_INTERVAL
      fi

      push_result=$(dotnet nuget push "$nupkg" \
        --source "https://api.nuget.org/v3/index.json" \
        --api-key "$NUGET_API_KEY" \
        --skip-duplicate 2>&1)

      if echo "$push_result" | grep -qi "已推送包\|pushed\|Created"; then
        echo -e "  [$COUNT/$TOTAL] ${GREEN}✓ $pkg_id 占位成功${NC}"
        echo "$pkg_id | OK | $(date '+%H:%M:%S')" >> "$LOG_FILE"
        # 写本地缓存: 下次重跑此包时直接跳过,免 HTTP 查询
        write_cache "$pkg_id"
        push_ok=true
        break
      elif echo "$push_result" | grep -qi "skip-duplicate\|already exists\|409"; then
        echo -e "  [$COUNT/$TOTAL] ${YELLOW}⊙ $pkg_id 已存在(跳过）${NC}"
        echo "$pkg_id | EXISTS | $(date '+%H:%M:%S')" >> "$LOG_FILE"
        # 即使是被别人占了,本地也记一下,下次免查
        write_cache "$pkg_id"
        push_ok=true
        break
      else
        echo -e "  [$COUNT/$TOTAL] ⚠ $pkg_id push 响应异常"
        echo "    响应: $push_result" | head -3
      fi
    done

    if [ "$push_ok" = false ]; then
      echo -e "  [$COUNT/$TOTAL] ${RED}✗ $pkg_id 推送失败(重试后仍失败）${NC}"
      echo "$pkg_id | PUSH_FAIL | $(date '+%H:%M:%S')" >> "$LOG_FILE"
      FAIL=$((FAIL + 1))
    else
      SUCCESS=$((SUCCESS + 1))
    fi
  fi

  # 清理该包的 build 产物(避免 out 目录越来越大）
  rm -rf "$WORK_DIR/out" 2>/dev/null

  # 风控间隔
  if [ $COUNT -lt $TOTAL ]; then
    sleep $INTERVAL
  fi

done

# ── 结果汇总 ──
echo ""
echo -e "${CYAN}══════════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}  结果汇总${NC}"
echo -e "${CYAN}══════════════════════════════════════════════════════════════${NC}"
echo ""
printf "  优先级: %s\n" "$PRIORITY"
printf "  成功: %s\n" "$SUCCESS"
printf "  失败: %s\n" "$FAIL"
printf "  跳过(已注册): %s\n" "${#SKIP_REGISTERED[@]}"
printf "  跳过(分类): %s\n" "${#SKIP_CATEGORY[@]}"
printf "  总计: %s\n" "$TOTAL"
echo ""
echo -e "日志已保存: ${CYAN}$LOG_FILE${NC}"

if [ $FAIL -gt 0 ]; then
  echo -e "${RED}有 $FAIL 个包推送失败，请检查日志后手动重试。${NC}"
fi

if [ $SUCCESS -gt 0 ]; then
  echo -e "${GREEN}占位成功！${NC}"
  echo ""
  echo -e "${YELLOW}⚠ 后续步骤：${NC}"
  echo "  1. 等待 30 分钟后，在 nuget.org 上确认包已显示"
  echo "  2. 对已注册的旧包(ZL.* 系列），在 nuget.org 网页上 unlist 旧版本"
  echo "  3. 申请 UseThink.* 和 ZL.* 的 ID 前缀预留"
fi