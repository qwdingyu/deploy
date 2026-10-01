#!/usr/bin/env bash
# ==============================================================================
# 全局 pre-push hook —— 推送前核验 GitHub 身份
# ==============================================================================
# 通过 `git config --global core.hooksPath ~/.githooks` 对**本机所有仓库**生效，
# 不需要在每个仓库里放任何东西（含那 30 个没有 AGENTS.md 的仓库）。
#
# 【为什么用 hook 而不是写文档】
# 2026-10-01 实测：qwdingyu 名下 13 个仓库都有 AGENTS.md，但内容各不相同，
# 只有 ZL.PlcBase 有 §18，而发版实际发生在 ZL.PlcSimulator——
# 它的 AGENTS.md 是 omx 工具生成的（omx:generated），可能被重新生成覆盖。
# 同一批文档里还躺着一个已经过时的 §17.4（"必须显式传 --protocols"）。
# **结论：文档必然漂移，机械的规则必须由自动化强制。**
#
# -- 输入格式（实测确认，勿凭直觉改）----------------------------------------
#   命令行参数：$1 = 远端名，$2 = 远端 URL
#   stdin      ：待推的 ref 更新，每行 "本地ref 本地sha 远端ref 远端sha"
#   远端名/URL **不在 stdin**，在**参数**里。初版误以为在 stdin，
#   读出来是空串 → case 落到 *) exit 0 → hook 静默变成空壳，
#   而所有"测试"都返回 0，看起来一切正常。
# -----------------------------------------------------------------------------
#
# 【设计要点】
# · 只拦 github.com；本地路径 / 其它远端一律放行（fail open，避免误伤）
# · 有完整核验脚本时优先调用它（含自动切换账号）；否则退化为最小内联检查
# · SKIP_PUSH_PREFLIGHT=1 git push … 可临时跳过（逃生舱，须写进事故报告）
# ==============================================================================
set -uo pipefail

[ -n "${SKIP_PUSH_PREFLIGHT:-}" ] && exit 0

# 远端名与 URL 在**参数**里，不在 stdin
remote_url="${2:-}"

if [ -z "$remote_url" ]; then
  # 拿不到 URL 时不能静默放行——那正是初版失效的路径。
  printf 'pre-push: 未收到远端 URL（$2 为空），已阻止推送。\n' >&2
  printf '  若这是非标准调用，请设 SKIP_PUSH_PREFLIGHT=1 显式跳过。\n' >&2
  exit 1
fi

case "$remote_url" in
  *github.com*) ;;
  *) exit 0 ;;          # 非 GitHub 远端，一律放行
esac

command -v gh >/dev/null 2>&1 || exit 0   # 没装 gh 就别拦，交给 git 自己去失败

repo="$(printf '%s' "$remote_url" \
  | sed -E 's#^(https?://)?[^/]+/##; s#^git@([^:]+):##; s#\.git$##; s#/$##')"
case "$repo" in
  */*) ;;
  *)
    printf 'pre-push: 无法从远端 URL 解析出仓库名：%s\n' "$remote_url" >&2
    exit 1 ;;
esac

# 优先用完整版（含自动纠正 + 复验）
FULL="$HOME/0-X/deploy/scripts/git-push-preflight.sh"
if [ -x "$FULL" ]; then
  exec "$FULL" --repo "$repo"
fi

# 退化为最小检查：只有"能不能推"这一件事
tok="$(gh auth token 2>/dev/null)" || {
  printf 'pre-push: gh 未登录，已阻止推送。请先 gh auth login\n' >&2
  exit 1
}
if [ "$(GH_TOKEN="$tok" gh api "repos/$repo" --jq '.permissions.push' 2>/dev/null)" = "true" ]; then
  exit 0
fi

printf '\npre-push 已阻止推送：当前 gh 活动账号对 %s 没有推送权限。\n' "$repo" >&2
printf '  Repository not found 往往就是这个原因，而非仓库被删。\n' >&2
printf '  修复：gh auth switch --user <有权账号>\n' >&2
printf '  临时跳过：SKIP_PUSH_PREFLIGHT=1 git push\n' >&2
exit 1
