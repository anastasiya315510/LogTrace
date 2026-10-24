#!/usr/bin/env bash
# Start or stop the full local dev stack.
# Usage: ./scripts/dev.sh start | stop | restart | status | logs [service]

set -euo pipefail

VENV=".venv/bin/activate"
LOG_DIR="/tmp/nemotrace"
mkdir -p "$LOG_DIR"

start_all() {
  echo "── Starting infrastructure ──────────────────────────"
  docker-compose up -d postgres redis
  echo "Waiting for postgres + redis..."
  sleep 4

  echo "── Running migrations ───────────────────────────────"
  source "$VENV" && alembic upgrade head 2>/dev/null || alembic stamp head

  echo "── Starting API ─────────────────────────────────────"
  source "$VENV"
  nohup uvicorn api.main:app --reload --port 8000 > "$LOG_DIR/api.log" 2>&1 &
  echo $! > "$LOG_DIR/api.pid"
  sleep 2

  echo "── Starting Stream Processor ────────────────────────"
  nohup python -m stream_processor.processor > "$LOG_DIR/stream_processor.log" 2>&1 &
  echo $! > "$LOG_DIR/stream_processor.pid"

  echo "── Starting Demo Producers ──────────────────────────"
  nohup env INGEST_URL=http://localhost:8000/api/v1/ingest \
            DEMO_API_KEY=dev-demo-key \
            REDIS_URL=redis://localhost:6379/0 \
        python -m demo.producers.run_demo > "$LOG_DIR/producers.log" 2>&1 &
  echo $! > "$LOG_DIR/producers.pid"

  echo "── Starting Portal (Vite) ───────────────────────────"
  (cd portal && nohup npm run dev -- --port 5173 > "$LOG_DIR/portal.log" 2>&1) &
  echo $! > "$LOG_DIR/portal.pid"

  echo "── Starting Streamlit Portal ────────────────────────"
  nohup streamlit run streamlit_portal/app.py \
        --server.port 8501 \
        --server.headless true \
        > "$LOG_DIR/streamlit.log" 2>&1 &
  echo $! > "$LOG_DIR/streamlit.pid"

  sleep 3
  echo ""
  echo "✓ All services running"
  echo "  React portal:     http://localhost:5173  (API key: dev-demo-key)"
  echo "  Streamlit portal: http://localhost:8501"
  echo "  API docs:         http://localhost:8000/docs"
  echo ""
  echo "Logs: $LOG_DIR/"
}

stop_all() {
  echo "── Stopping services ────────────────────────────────"

  # Kill by PID file first
  for name in api stream_processor producers portal streamlit; do
    pid_file="$LOG_DIR/$name.pid"
    if [ -f "$pid_file" ]; then
      pid=$(cat "$pid_file")
      kill "$pid" 2>/dev/null && echo "  stopped $name (pid $pid)" || true
      rm -f "$pid_file"
    fi
  done

  # Kill ALL orphaned process instances by pattern (handles zombie processes
  # from previous dev sessions that weren't tracked by PID files)
  pkill -f "uvicorn api.main:app" 2>/dev/null && echo "  killed all uvicorn instances" || true
  pkill -f "stream_processor.processor" 2>/dev/null && echo "  killed all stream_processor instances" || true
  pkill -f "demo.producers.run_demo" 2>/dev/null && echo "  killed all producer instances" || true
  pkill -f "streamlit run streamlit_portal" 2>/dev/null && echo "  killed all streamlit instances" || true
  # Portal (vite) — match the specific port to avoid killing unrelated vite servers
  pkill -f "vite.*--port 5173" 2>/dev/null && echo "  killed portal (vite)" || true

  sleep 1
  echo "✓ Done (postgres + redis still running)"
}

status_all() {
  for name in api stream_processor producers portal streamlit; do
    pid_file="$LOG_DIR/$name.pid"
    if [ -f "$pid_file" ] && kill -0 "$(cat $pid_file)" 2>/dev/null; then
      echo "  ✓ $name  (pid $(cat $pid_file))"
    else
      echo "  ✗ $name  (not running)"
    fi
  done
}

show_logs() {
  local service="${2:-}"

  if [ "$service" = "jobs" ]; then
    # Tail all stage1 + stage2 log files (created per-run)
    echo "── Recent stage1/stage2 job logs ────────────────────"
    ls -t "$LOG_DIR"/stage1_*.log "$LOG_DIR"/stage2_*.log 2>/dev/null | head -10 | while read f; do
      echo ""
      echo "=== $f ==="
      cat "$f"
    done
    return
  fi

  if [ -n "$service" ]; then
    local log_file="$LOG_DIR/${service}.log"
    if [ ! -f "$log_file" ]; then
      echo "Unknown service: '$service'"
      echo "Available: api, stream_processor, producers, portal, jobs"
      exit 1
    fi
    tail -n 50 -f "$log_file"
    return
  fi

  # Tail all logs in parallel, each prefixed with a colour label
  tail -n 20 -f "$LOG_DIR/api.log"              | sed -u 's/^/\o033[36m[api]             \o033[0m/' &
  tail -n 20 -f "$LOG_DIR/stream_processor.log" | sed -u 's/^/\o033[33m[stream_processor]\o033[0m/' &
  tail -n 20 -f "$LOG_DIR/producers.log"        | sed -u 's/^/\o033[32m[producers]       \o033[0m/' &
  tail -n 20 -f "$LOG_DIR/portal.log"           | sed -u 's/^/\o033[35m[portal]          \o033[0m/' &
  # Also tail the most recent stage1/stage2 job logs if present
  for f in $(ls -t "$LOG_DIR"/stage1_*.log "$LOG_DIR"/stage2_*.log 2>/dev/null | head -4); do
    name=$(basename "$f" .log)
    tail -n 5 -f "$f" | sed -u "s/^/\o033[90m[$name]\o033[0m/" &
  done

  # Wait and clean up on Ctrl+C
  trap 'kill $(jobs -p) 2>/dev/null; exit 0' INT TERM
  wait
}

clean_start() {
  echo "── Nuclear clean-start ──────────────────────────────"
  stop_all

  echo "── Clearing stale logs ──────────────────────────────"
  rm -f "$LOG_DIR"/stage1_*.log "$LOG_DIR"/stage2_*.log
  rm -f "$LOG_DIR"/*.pid

  echo "── Resetting Redis demo state ───────────────────────"
  source "$VENV"
  python3 - <<'EOF'
import redis, os
r = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
# Clear demo state and stream processor state
for key in r.scan_iter("demo:*"):
    r.delete(key)
for key in r.scan_iter("stream:ingest:*"):
    r.delete(key)
for key in r.scan_iter("stream_processor:*"):
    r.delete(key)
for key in r.scan_iter("sse:*"):
    r.delete(key)
print("  Redis demo state cleared")
EOF

  sleep 1
  start_all
}

case "${1:-start}" in
  start)        source "$VENV" && start_all ;;
  stop)         stop_all ;;
  restart)      stop_all && sleep 1 && source "$VENV" && start_all ;;
  clean-start)  source "$VENV" && clean_start ;;
  status)       status_all ;;
  logs)         show_logs "$@" ;;
  *) echo "Usage: $0 start|stop|restart|clean-start|status|logs [service]" && exit 1 ;;
esac