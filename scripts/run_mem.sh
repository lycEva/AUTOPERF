#!/usr/bin/env bash
set -u
set -o pipefail

container="${1:-}"
workers="${2:-1}"

fail() {
  printf 'run_mem.sh: %s\n' "$*" >&2
  exit 1
}

[ -n "$container" ] || fail "container is required"
command -v npu-smi >/dev/null 2>&1 || fail "npu-smi not found"

worker_pids="$(printf '%s\n' "${AUTOPERF_MONITOR_PIDS:-}" | tr ',' '\n' | awk 'NF {print $1}')"

if [ -z "$worker_pids" ]; then
worker_pids="$(docker top "$container" 2>/dev/null | awk -v limit="$workers" '
  NR > 1 {
    if (($4 + 0) <= 0) next
    split($7, t, ":")
    sec = t[1] * 3600 + t[2] * 60 + t[3]
    print $2, sec
  }
' | sort -k2 -nr | head -n "$workers" | awk '{print $1}')"
fi

if [ -z "$worker_pids" ]; then
  root_pid="$(docker inspect -f '{{.State.Pid}}' "$container" 2>/dev/null || true)"
  if [[ "$root_pid" =~ ^[0-9]+$ ]] && [ "$root_pid" -gt 0 ]; then
    worker_pids="$(pgrep -P "$root_pid" 2>/dev/null | head -n "$workers")"
  fi
fi

# Keep the NPU-process-only accounting, using host PIDs from both sources.
container_pids="${AUTOPERF_MONITOR_RELATED_PIDS:-$worker_pids}"
npu_snapshot="$(npu-smi info)" || fail "npu-smi info failed"
npu_pids="$(printf '%s\n' "$npu_snapshot" | awk -F '[|]' '
  NF >= 5 {
    pid = $3
    gsub(/^[[:space:]]+|[[:space:]]+$/, "", pid)
    if (pid ~ /^[0-9]+$/) print pid
  }
')" || fail "failed to parse NPU process IDs"
# An awk set intersection avoids comm's lexicographic-sort requirement.
worker_pids="$(printf '%s\n---\n%s\n' "$container_pids" "$npu_pids" | tr ',' '\n' | awk '
  $0 == "---" { npu = 1; next }
  /^[0-9]+$/ {
    if (!npu) wanted[$0] = 1
    else if (wanted[$0] && !seen[$0]++) print $0
  }
')" || fail "failed to match NPU process IDs"
if [ -z "$worker_pids" ]; then echo 0; exit 0; fi

total_mem_gb="$(printf '%s\n' "$worker_pids" | awk 'NF {print $1}' | awk '
  { pids[$1] = 1 }
  END {
    for (pid in pids) {
      cmd = "ps -p " pid " -o rss= 2>/dev/null"
      if ((cmd | getline rss_kb) > 0) {
        mem_gb = rss_kb / 1024 / 1024
      total += mem_gb
      }
      close(cmd)
    }
    printf "%.4f\n", total + 0
  }
')"

if [ -z "$total_mem_gb" ]; then echo 0; exit 0; fi
echo "$total_mem_gb"
