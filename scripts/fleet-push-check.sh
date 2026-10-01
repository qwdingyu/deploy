#!/usr/bin/env bash
# ==============================================================================
# fleet-push-check.sh —— 批量盘点：哪些本地仓库在当前 gh 活动账号下推不动
# ==============================================================================
#
# 【为什么需要它】
# 2026-10-01 的推送事故中，我一度以为是"仓库被删"。事后发现整个
# `qwdingyu` 组织下有 40+ 个仓库同时不可达——**如果当时有批量盘点，
# 几秒就能看出"是全部都推不动"，指向身份问题，而不是某个仓库出问题。**
#
# 【踩过的坑，勿重犯】
# 初版用 `basename $d`（**目录名**）当仓库名，结果 4 个仓库误报：
#     目录 iot-sdk   → 实际仓库 ZL.Iot.Sdk
#     目录 AGV       → 实际仓库 SyncBus
#     目录 go_plugin → 实际仓库 growthkit
#     目录 shop      → 实际仓库 vibox-shop
# **必须从 remote URL 解析真实仓库名**，不能拿目录名凑。
#
# 【用法】
#   ./fleet-push-check.sh --owner qwdingyu          # 只盘自己名下的仓（推荐）
#   ./fleet-push-check.sh /path/to/dir             # 指定扫描根目录
#
# 强烈建议总是带 --owner：本机 ~/0-X 下有 140+ 个仓库，其中绝大多数是
# 他人的开源项目。盘进来只会让真故障被噪音淹没，且每个仓一次 API 调用、很慢。
# ==============================================================================
set -uo pipefail
ROOT="$HOME/0-X"
OWNER_FILTER=""
while [ $# -gt 0 ]; do
  case "$1" in
    --owner) shift; OWNER_FILTER="${1:-}" ;;
    *) ROOT="$1" ;;
  esac
  shift
done
PREFLIGHT="$(cd "$(dirname "$0")" && pwd)/git-push-preflight.sh"

[ -f "$PREFLIGHT" ] || { echo "找不到 $PREFLIGHT" >&2; exit 2; }

printf '\n批量盘点：%s\n' "$ROOT"
printf '当前活动账号：%s\n\n' "$(gh api user --jq .login 2>/dev/null || echo 未登录)"

OK=0; NG=0; declare -a FAILED

while IFS= read -r d; do
  # find 命中的是 <repo>/.git，仓库根要取它的上一级
  dir="$(dirname "${d%/}")"
  u="$(git -C "$dir" remote get-url origin 2>/dev/null)" || continue
  case "$u" in
    *github.com/*) ;;
    *) continue ;;
  esac
  # 从 remote 解析 owner/repo（不用目录名——目录名可能与仓库名不同）
  full="$(printf '%s' "$u" | sed -E 's#^(https?://)?[^/]+/##; s#^git@([^:]+):##; s#\.git$##; s#/$##')"
  case "$full" in */*) ;; *) continue ;; esac
  owner="${full%%/*}"; repo="${full##*/}"
  # 只盘自己名下的仓：他人仓库推不动是正常的，算进来只会淹没真故障
  [ -n "$OWNER_FILTER" ] && [ "$owner" != "$OWNER_FILTER" ] && continue

  if "$PREFLIGHT" --repo "$owner/$repo" >/dev/null 2>&1; then
    OK=$((OK+1))
  else
    NG=$((NG+1))
    FAILED+=("${owner}/${repo}  （目录：$(basename "$dir")）")
  fi
done < <(find "$ROOT" -maxdepth 3 -name .git -type d 2>/dev/null)

printf '可推送：%d    推不动：%d\n' "$OK" "$NG"
if [ "$NG" -gt 0 ]; then
  printf '\n推不动的仓库：\n'
  printf '  - %s\n' "${FAILED[@]}"
  printf '\n逐个排查：\n'
  printf '  gh repo view <OWNER/REPO>          # 确认仓库是否真的存在\n'
  printf '  gh auth status                     # 确认活动账号\n'
  printf '  %s --repo <OWNER/REPO>            # 跑本脚本的核验\n' "$(basename "$PREFLIGHT")"
  exit 1
fi
printf '\n全部可推送。\n'
