#!/usr/bin/env bash
# Start/status/tail/stop wrapper for the resumable follow-up pipeline.
set -Eeuo pipefail

ACTION="${1:-start}"
PROJECT="${PROJECT:-/home/hyan/LyricAlignment}"
DATA_ROOT="${DATA_ROOT:-/home/hyan/Data/lyricalign}"
LOG_ROOT="${LOG_ROOT:-$DATA_ROOT/logs}"
STATE_ROOT="${STATE_ROOT:-$DATA_ROOT/runs/20260724_qwen_fa_followup_overnight}"
POINTER="$LOG_ROOT/qwen_fa_followup_latest"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python)}"
PIPELINE="$PROJECT/scripts/training/run_qwen_fa_followup_overnight.sh"

mkdir -p "$LOG_ROOT" "$STATE_ROOT"

read_pointer() {
  [ -f "${POINTER}.pid" ] || return 1
  PID="$(cat "${POINTER}.pid")"
  LOG="$(cat "${POINTER}.log")"
  RCFILE="$(cat "${POINTER}.rc")"
}

running() {
  read_pointer || return 1
  kill -0 "$PID" 2>/dev/null
}

case "$ACTION" in
  start|resume)
    if running; then
      echo "already_running PID=$PID"
      echo "LOG=$LOG"
      exit 1
    fi
    [ -x "$PIPELINE" ] || { echo "missing executable: $PIPELINE" >&2; exit 1; }
    STAMP="$(date +%Y%m%d_%H%M%S)"
    LOG="$LOG_ROOT/qwen_fa_followup_${STAMP}.log"
    PIDFILE="$LOG_ROOT/qwen_fa_followup_${STAMP}.pid"
    RCFILE="$LOG_ROOT/qwen_fa_followup_${STAMP}.return_code"
    LAUNCHER="$LOG_ROOT/qwen_fa_followup_${STAMP}.launcher.sh"
    cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
set +e
cd "$PROJECT"
export PYTHON_BIN="$PYTHON_BIN"
export PATH="$(dirname "$PYTHON_BIN"):\$PATH"
export HF_HUB_CACHE="${HF_HUB_CACHE:-$DATA_ROOT/models/hf_cache}"
export HF_HUB_OFFLINE=1
export PYTHONUNBUFFERED=1
export AUTO_RUN_FULL_SEED2="${AUTO_RUN_FULL_SEED2:-0}"
export SECOND_SEED="${SECOND_SEED:-20260724}"
export STATE_ROOT="$STATE_ROOT"
"$PIPELINE" resume
rc=\$?
printf '%s\n' "\$rc" > "$RCFILE"
echo "finished_at=\$(date -Is)"
echo "return_code=\$rc"
exit "\$rc"
EOF
    chmod +x "$LAUNCHER"
    nohup setsid "$LAUNCHER" > "$LOG" 2>&1 < /dev/null &
    PID=$!
    printf '%s\n' "$PID" > "$PIDFILE"
    printf '%s\n' "$PID" > "${POINTER}.pid"
    printf '%s\n' "$LOG" > "${POINTER}.log"
    printf '%s\n' "$RCFILE" > "${POINTER}.rc"
    printf '%s\n' "$LAUNCHER" > "${POINTER}.launcher"
    disown "$PID" 2>/dev/null || true
    echo "PID=$PID"
    echo "LOG=$LOG"
    echo "RCFILE=$RCFILE"
    echo "STATE_ROOT=$STATE_ROOT"
    ;;
  status)
    if ! read_pointer; then
      echo "no_previous_launch"
      "$PIPELINE" status || true
      exit 0
    fi
    if kill -0 "$PID" 2>/dev/null; then echo "process=running"; else echo "process=stopped"; fi
    echo "PID=$PID"
    echo "LOG=$LOG"
    [ -f "$RCFILE" ] && echo "return_code=$(cat "$RCFILE")" || echo "return_code=not_written"
    ps -o pid,ppid,sid,pgid,stat,etime,cmd -p "$PID" || true
    "$PIPELINE" status || true
    ;;
  tail)
    read_pointer || { echo "no_previous_launch" >&2; exit 1; }
    tail -f "$LOG"
    ;;
  stop)
    running || { echo "not_running"; exit 0; }
    kill -INT -- "-$PID"
    echo "sent_SIGINT_to_process_group=-$PID"
    ;;
  *)
    echo "usage: $0 [start|resume|status|tail|stop]" >&2
    exit 2
    ;;
esac
