#!/usr/bin/env bash
set -euo pipefail
MODE="${1:-formal}"; shift || true
case "$MODE" in smoke|formal) ;; *) echo "usage: $0 smoke|formal [extra args]" >&2; exit 2;; esac
D="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SESSION="${SESSION:-lyricalign-rv6-$MODE}"
RUNNER="$D/run_research_v6_${MODE}.sh"
command -v tmux >/dev/null || { echo "ERROR: tmux not installed" >&2; exit 2; }
if tmux has-session -t "$SESSION" 2>/dev/null; then echo "ERROR: tmux session exists: $SESSION" >&2; exit 2; fi
printf -v CMD '%q ' "$RUNNER" "$@"
tmux new-session -d -s "$SESSION" "bash -lc '$CMD'"
echo "started: $SESSION"
echo "attach: tmux attach -t $SESSION"
echo "detach: Ctrl-b then d"
echo "status: tmux capture-pane -pt $SESSION -S -80"
