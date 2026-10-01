#!/usr/bin/env bash
# ==============================================================================
# git-push-preflight.sh —— 推送前身份核验（多 gh 账号环境下防"Repository not found"）
# ==============================================================================
#
# 【要解决的问题】
#   本机登录多个 gh 账号时，git 凭据助手**永远服务"活动账号"**。
#   活动账号若无目标仓权限，git 推送会报：
#       remote: Repository not found.
#       fatal: repository 'https://github.com/OWNER/REPO.git/' not found
#
#   **这个报错具有高度歧义**——它同时意味着：
#       ① 仓库不存在        ② 仓库存在但当前账号无权限
#       ③ 活动账号不是 OWNER ④ 网络/DNS 异常
#   本会话（2026-10-01）就因为没先分清 ①③，误以为是"仓库被删"，
#   实际只是 gh 活动账号是 usethinklab 而仓库属于 qwdingyu。
#
# 【已验证的机制事实（勿凭直觉推翻，见 docs/241）】
#   $ printf 'get\nprotocol=https\nhost=github.com\nusername=qwdingyu\n\n' \
#       | gh auth git-credential get
#   → 忽略 username，返回的仍是**活动账号**。
#   gh auth git-credential 也没有任何选账号的参数。
#   结论：**无法按 URL/仓库自动绑定账号**，活动账号是唯一开关。
#   所以唯一可靠的防线是"推送前核验 + 自动纠正"。
#
# 【用法】
#   ./git-push-preflight.sh              # 核验当前仓，必要时自动切换账号
#   ./git-push-preflight.sh --check-only # 只检查，不自动切换
#   ./git-push-preflight.sh --repo OWNER/REPO   # 跨仓核验（盘点用）
#
# 【退出码】
#   0 = 可推送
#   1 = 不可推送（已给出可执行的修复命令）
#   2 = 环境异常（缺 gh / 不在 git 仓内）
# ==============================================================================
set -uo pipefail

CHECK_ONLY=0
TARGET=""
# 参数解析：用 while + 真正 shift。
# 两个坑（都已实测踩过）：
#   ① for a in "$@"; do ... shift ... done —— shift 会破坏遍历
#   ② 只递增 i 却仍引用 ${1} —— 取到的永远是第一个参数（--repo 自己）
while [ $# -gt 0 ]; do
  case "$1" in
    --check-only) CHECK_ONLY=1; shift ;;
    --repo)
      if [ $# -ge 2 ]; then TARGET="$2"; shift 2; else shift; fi ;;
    *) shift ;;
  esac
done

RED=$'\033[31m'; GRN=$'\033[32m'; YLW=$'\033[33m'; DIM=$'\033[2m'; RST=$'\033[0m'
say()  { printf '%s\n' "$*"; }
ok()   { printf '  %s✓%s %s\n' "$GRN" "$RST" "$*"; }
bad()  { printf '  %s✗%s %s\n' "$RED" "$RST" "$*"; }
warn() { printf '  %s!%s %s\n' "$YLW" "$RST" "$*"; }
dim()  { printf '  %s%s%s\n' "$DIM" "$*" "$RST"; }

# ---- 0. 环境检查 -------------------------------------------------------------
command -v gh >/dev/null 2>&1 || { bad "未找到 gh 命令"; exit 2; }

if [ -z "$TARGET" ]; then
  git rev-parse --git-dir >/dev/null 2>&1 || { bad "不在 git 仓库内（可用 --repo OWNER/REPO）"; exit 2; }
  TARGET="$(git remote get-url origin 2>/dev/null)"
  [ -n "$TARGET" ] || { bad "没有 origin 远端"; exit 2; }
fi

# 归一化为 OWNER/REPO：兼容 https / ssh / 已是 OWNER/REPO 三种输入
if [[ "$TARGET" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
  OWNER_REPO="$TARGET"                       # 已是 OWNER/REPO
else
  OWNER_REPO="$(printf '%s' "$TARGET" \
    | sed -E 's#^(https?://)?[^/]+/##; s#^git@([^:]+):##; s#\.git$##; s#/$##')"
fi

case "$OWNER_REPO" in
  */*) ;;
  *) bad "无法从远端解析出 OWNER/REPO（原始值：${TARGET}）"; exit 2 ;;
esac

# ---- 1. 探测某账号能否访问某仓库 --------------------------------------------
# 0 = 有推送权限；1 = 无权限或仓库不可见
#
# 【关于"无权限"与"仓库不存在"能否区分】——**不能**，这是 GitHub 的刻意设计：
# 对你无权查看的**私有**仓，API 返回 404 而不是 403，以免泄露私有仓是否存在。
# 本会话实测：usethinklab 查 qwdingyu 私有仓 → 404；
#             查一个确实不存在的仓 → 也是 404。
# 因此本脚本**不**谎称能区分二者；它只回答"能不能推"这个真正的问题，
# 并在失败时把两种可能一并列出，让人去 `gh repo view` 人工确认。
probe_as() {
  local user="$1" repo="$2" tok pushable
  # 关键：gh api 永远用**活动账号**，所以必须用 GH_TOKEN 显式覆盖。
  # 否则探测别的账号时其实还是活动账号在查（本脚本初版就踩了这个坑：
  # 传了 usethinklab/qwdingyu 两个参数，结果两次都是活动账号在问）。
  tok="$(gh auth token --user "$user" 2>/dev/null)" || return 1
  [ -n "$tok" ] || return 1
  pushable="$(GH_TOKEN="$tok" gh api "repos/$repo" --jq '.permissions.push' 2>/dev/null)" || return 1
  [ "$pushable" = "true" ] && return 0 || return 1
}

# ---- 2. 当前活动账号是否可用 -------------------------------------------------
ACTIVE="$(gh api user --jq .login 2>/dev/null || true)"

say ""
say "推送前身份核验  ${OWNER_REPO}"

if [ -z "$ACTIVE" ]; then
  bad "gh 未登录或凭据失效（gh api user 无响应）"
  dim "修复：gh auth login"
  exit 1
fi

dim "活动账号：$ACTIVE"

if probe_as "$ACTIVE" "$OWNER_REPO"; then
  ok "$ACTIVE 对 $OWNER_REPO 有推送权限"
  say ""
  exit 0
fi

# ---- 3. 当前账号不行：区分"没权限"和"仓库不存在" ---------------------------
say ""
warn "$ACTIVE 无 $OWNER_REPO 的访问权限（这就是 'Repository not found' 的真因）"

# ---- 4. 自动寻找可用账号 ----------------------------------------------------
ACCOUNTS="$(gh auth status 2>/dev/null | sed -nE 's/.*account[[:space:]]+([^[:space:]]+)[[:space:]]+\(keyring\).*/\1/p')"
FOUND=""
for a in ${ACCOUNTS}; do
  [ "$a" = "$ACTIVE" ] && continue
  if probe_as "$a" "$OWNER_REPO"; then
    FOUND="$a"; break
  fi
  dim "  试 $a … 无权限"
done

if [ -z "$FOUND" ]; then
  say ""
  bad "本机已登录的账号（${ACCOUNTS}）均无 $OWNER_REPO 的访问权限"
  say ""
  dim "这说明不是账号切换问题。请确认其一："
  dim "  1) 仓库确实存在？→ ${GRN}gh repo view $OWNER_REPO${RST}"
  dim "  2) 账号是否已被移出该组织/仓库？"
  dim "  3) 是否该用另一个 GitHub 账号登录？→ ${GRN}gh auth login${RST}"
  say ""
  exit 1
fi

# ---- 5. 找到可用账号：切换 ---------------------------------------------------
say ""
if [ "$CHECK_ONLY" = "1" ]; then
  warn "可用账号为 ${FOUND}，但 --check-only 模式不自动切换"
  dim "手动切换：gh auth switch --user $FOUND"
  say ""
  exit 1
fi

warn "已自动切换活动账号：$ACTIVE → $FOUND"
if gh auth switch --user "$FOUND" >/dev/null 2>&1; then
  # 切换后必须复验，不能假定成功
  if probe_as "$FOUND" "$OWNER_REPO"; then
    ok "复验通过：$FOUND 可推送 $OWNER_REPO"
    say ""
    dim "提示：gh 活动账号是**全局**设置，会影响所有仓库的推送。"
    dim "     跨组织工作时建议推送前先跑本脚本。"
    say ""
    exit 0
  fi
  bad "切换后复验仍然失败——请手动排查"
  say ""
  exit 1
fi

bad "gh auth switch 执行失败"
say ""
exit 1
