#!/usr/bin/env bash
# PreCompact hook — stabler micro-task protocol
# Writes durable state to disk BEFORE the lossy compaction happens.
set -uo pipefail
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
OUT_DIR="$PROJECT_DIR/.claude/handoff"; OUT="$OUT_DIR/last-handoff.md"
mkdir -p "$OUT_DIR"
PAYLOAD="$(cat 2>/dev/null || true)"
TRIGGER="$(printf '%s' "$PAYLOAD" | sed -n 's/.*"trigger"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"
[ -z "$TRIGGER" ] && TRIGGER="unknown"
cd "$PROJECT_DIR" 2>/dev/null || exit 0
BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
HEAD_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo '?')"
HEAD_MSG="$(git log -1 --pretty=%s 2>/dev/null || echo '?')"
{
  echo "# HANDOFF — written by PreCompact hook"; echo
  echo "- **When:** $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  echo "- **Compaction trigger:** \`$TRIGGER\`"
  echo "- **Branch:** \`$BRANCH\`"
  echo "- **HEAD:** \`$HEAD_SHA\` — $HEAD_MSG"; echo
  echo "## Working tree (uncommitted work — THE thing at risk)"; echo '```'
  git status --porcelain 2>/dev/null | head -60 || echo "(git status unavailable)"; echo '```'; echo
  echo "## Diff stat vs HEAD"; echo '```'
  git diff --stat 2>/dev/null | tail -25 || true; echo '```'; echo
  echo "## Commits on this branch not on main"; echo '```'
  git log --oneline main..HEAD 2>/dev/null | head -20 || echo "(none)"; echo '```'; echo
  echo "## Open beads"; echo '```'
  if command -v bd >/dev/null 2>&1; then
    bd list --status in_progress 2>/dev/null | head -20 || echo "(bd list failed)"
    echo "--- ready ---"; bd ready 2>/dev/null | head -15 || echo "(bd ready failed)"
  else echo "(bd not on PATH)"; fi
  echo '```'; echo
  echo "## Recovery protocol for the next session"; echo
  echo "1. Do NOT trust the compaction summary for facts. Re-read this file."
  echo "2. Re-establish ground truth with ONE command: \`make check\`."
  echo "3. If the working tree above is dirty, that is the in-flight micro-task."
  echo "4. Finish it or commit it as \`wip(<bead-id>): …\`, then \`/clear\` — do not keep compacting."
  echo "5. Do not re-explore files already changed above; read the diff, not the tree."
} > "$OUT" 2>/dev/null
cat <<EOF
CONTEXT-BUDGET NOTICE: auto-compaction fired ($TRIGGER). Under the stabler
micro-task protocol this means the current unit of work was mis-sized.

Durable state has been written to .claude/handoff/last-handoff.md — treat that
file, git, and \`bd\` as ground truth; do NOT treat this summary as authoritative
for file contents, test results, or what has already been committed.

Next actions, in order:
1. Read .claude/handoff/last-handoff.md.
2. Run \`make check\` to re-establish the real state.
3. Close out the in-flight micro-task (finish or wip-commit), then stop and
   suggest \`/clear\` rather than continuing into another compaction.
Do NOT start a new exploration sweep. Do NOT re-read files listed as changed.
EOF
exit 0
