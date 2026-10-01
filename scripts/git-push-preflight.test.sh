#!/usr/bin/env bash
# ==============================================================================
# git-push-preflight.test.sh —— 推送前核验脚本的回归测试
# ==============================================================================
#
# 【为什么要写这个测试】
# 本脚本初版有 4 个真实缺陷，全部**只有靠实跑才暴露**：
#   ① probe_as 传了账号参数却没用 —— gh api 永远用活动账号，探测形同虚设
#   ② $VAR 紧跟全角字符 → bash 把全角吞进变量名 → set -u 报 unbound variable
#      （同一个坑本会话在 CI 里已犯过一次，文档 commit 21843af）
#   ③ for + shift 遍历 "$@" 破坏遍历；改用下标后只增 i 却仍引用 ${1}，
#      TARGET 取到 "--repo" 自己
#   ④ --repo 传入的 OWNER/REPO 被 URL 归一化逻辑剥掉 owner
# 而我**第一次写用例时还把期望值写错了**（以为"没有账号能访问"，
# 实际另一个账号有权限）——测试用例本身也必须能被证伪。
#
# 【用法】./git-push-preflight.test.sh
# ==============================================================================
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/git-push-preflight.sh"
PASS=0; FAIL=0
ACC_A="qwdingyu"; ACC_B="usethinklab"     # 有权 / 无权（依本机实际账号调整）

chk() { # chk <描述> <期望退出码> <实际退出码>
  if [ "$2" = "$3" ]; then printf '  \033[32m✓\033[0m %s\n' "$1"; PASS=$((PASS+1))
  else printf '  \033[31m✗\033[0m %s（期望退出码 %s，实际 %s）\n' "$1" "$2" "$3"; FAIL=$((FAIL+1)); fi
}
active() { gh api user --jq .login 2>/dev/null; }

printf '\n== 用例 1：活动账号有权限 → 期望 0，且不得切换 ==\n'
gh auth switch --user "$ACC_A" >/dev/null 2>&1
"$SCRIPT" >/dev/null 2>&1; chk "可推送" 0 $?
[ "$(active)" = "$ACC_A" ] && { printf '  \033[32m✓\033[0m 未发生账号切换\n'; PASS=$((PASS+1)); } \
  || { printf '  \033[31m✗\033[0m 账号被意外切换为 %s\n' "$(active)"; FAIL=$((FAIL+1)); }

printf '\n== 用例 2：活动账号无权限 → 期望自动切换并复验 → 0 ==\n'
gh auth switch --user "$ACC_B" >/dev/null 2>&1
OUT2="$("$SCRIPT" 2>&1)"; RC2=$?
chk "自动纠正后放行" 0 $RC2
printf '%s' "$OUT2" | grep -q '复验通过' \
  && { printf '  \033[32m✓\033[0m 切换后确实执行了复验（未假定切换即成功）\n'; PASS=$((PASS+1)); } \
  || { printf '  \033[31m✗\033[0m 未见复验步骤——跳过复验等于把"切换成功"当假设\n'; FAIL=$((FAIL+1)); }
[ "$(active)" = "$ACC_A" ] && { printf '  \033[32m✓\033[0m 已切回有权账号\n'; PASS=$((PASS+1)); } \
  || { printf '  \033[31m✗\033[0m 未切回，当前 %s\n' "$(active)"; FAIL=$((FAIL+1)); }

printf '\n== 用例 3：两账号都无权限 → 期望 1，且不得乱切 ==\n'
gh auth switch --user "$ACC_B" >/dev/null 2>&1
BEFORE="$(active)"
"$SCRIPT" --repo qwdingyu/__preflight_test_no_such_repo__ >/dev/null 2>&1
chk "拒绝并给出可执行建议" 1 $?
[ "$(active)" = "$BEFORE" ] && { printf '  \033[32m✓\033[0m 未乱切账号\n'; PASS=$((PASS+1)); } \
  || { printf '  \033[31m✗\033[0m 账号被切成了 %s\n' "$(active)"; FAIL=$((FAIL+1)); }

printf '\n== 用例 4：--repo 参数解析（曾经的 bug：TARGET 取到 "--repo"）==\n'
gh auth switch --user "$ACC_A" >/dev/null 2>&1
OUT="$("$SCRIPT" --repo qwdingyu/__preflight_test_no_such_repo__ 2>&1)"
printf '%s' "$OUT" | grep -q 'qwdingyu/__preflight_test_no_such_repo__' \
  && { printf '  \033[32m✓\033[0m 正确解析出目标仓库名\n'; PASS=$((PASS+1)); } \
  || { printf '  \033[31m✗\033[0m 目标解析错误：%s\n' "$(printf '%s' "$OUT" | head -3)"; FAIL=$((FAIL+1)); }
printf '%s' "$OUT" | grep -q '原始值：--repo' \
  && { printf '  \033[31m✗\033[0m 复现了旧 bug（TARGET 被赋成 --repo）\n'; FAIL=$((FAIL+1)); } \
  || { printf '  \033[32m✓\033[0m 未复现 "$VAR+全角" 与参数解析 bug\n'; PASS=$((PASS+1)); }

printf '\n== 用例 5：语法与 set -u 安全性（静态检查）==\n'
bash -n "$SCRIPT" 2>/dev/null && { printf '  \033[32m✓\033[0m bash -n 通过\n'; PASS=$((PASS+1)); } \
  || { printf '  \033[31m✗\033[0m 语法错误\n'; FAIL=$((FAIL+1)); }
# 任何 "$VAR" 紧跟非 ASCII 字符的写法在 set -u 下会报 unbound variable
# 注意：这里**不能**用 grep -P。macOS 自带的是 BSD grep，不支持 -P，
# 会直接以退出码 2 失败；而失败在 if 判断里等于"没发现问题" = 假绿。
# 本测试套件就是这么漏掉过一次变异（实测：grep -P 在本机返回 2）。
RISK="$(python3 - "$SCRIPT" <<'PYEOF'
import re,sys
pat=re.compile(r'\$[A-Za-z_][A-Za-z0-9_]*(?=[^\x00-\x7F])')
hits=[f"{i}:{l.strip()}" for i,l in enumerate(open(sys.argv[1],encoding='utf-8'),1) if pat.search(l)]
print("\n".join(hits))
PYEOF
)"
if [ -n "$RISK" ]; then
  printf '  \033[31m✗\033[0m 仍存在 "$变量+全角字符" 隐患：\n%s\n' "$RISK"; FAIL=$((FAIL+1))
else
  printf '  \033[32m✓\033[0m 无 "$变量+全角字符" 隐患（python3 精确检查）\n'; PASS=$((PASS+1))
fi

printf '\n──────── 结果：通过 %d，失败 %d ────────\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
