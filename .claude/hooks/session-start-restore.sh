#!/usr/bin/env bash
# SessionStart hook (matchers: compact, resume) — stabler micro-task protocol
set -uo pipefail
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
HANDOFF="$PROJECT_DIR/.claude/handoff/last-handoff.md"
[ -f "$HANDOFF" ] || exit 0
if [ "$(find "$HANDOFF" -mmin +720 2>/dev/null | wc -l | tr -d ' ')" != "0" ]; then
  echo "NOTE: a handoff exists at .claude/handoff/last-handoff.md but is >12h old; ignoring."
  echo "Start from \`bd ready\` instead."
  exit 0
fi
echo "=== RESTORED HANDOFF (disk truth, overrides any conversation summary) ==="
cat "$HANDOFF"
echo "=== END HANDOFF ==="
echo
echo "Reminder: one micro-task per session. Delegate exploration to a subagent."
echo "Definition of Done is \`make check\`, not agreement in conversation."
exit 0
