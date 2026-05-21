#!/usr/bin/env bash
set -u

container="${1:-}"
workers="${2:-1}"

if [ -z "$container" ]; then echo 0; exit 0; fi

worker_pids="$(docker top "$container" 2>/dev/null | awk -v limit="$workers" '
  NR > 1 {
    if (($4 + 0) <= 0) next
    split($7, t, ":")
    sec = t[1] * 3600 + t[2] * 60 + t[3]
    print $2, sec
  }
' | sort -k2 -nr | head -n "$workers" | awk '{print $1}')"

if [ -z "$worker_pids" ]; then
  root_pid="$(docker inspect -f '{{.State.Pid}}' "$container" 2>/dev/null || true)"
  if [[ "$root_pid" =~ ^[0-9]+$ ]] && [ "$root_pid" -gt 0 ]; then
    worker_pids="$(pgrep -P "$root_pid" 2>/dev/null | head -n "$workers")"
  fi
fi

max_mem_gb="$(printf '%s\n' "$worker_pids" | awk 'NF {print $1}' | awk '
  { pids[$1] = 1 }
  END {
    for (pid in pids) {
      cmd = "ps -p " pid " -o rss= 2>/dev/null"
      if ((cmd | getline rss_kb) > 0) {
        mem_gb = rss_kb / 1024 / 1024
        if (mem_gb > max) max = mem_gb
      }
      close(cmd)
    }
    printf "%.4f\n", max + 0
  }
')"

if [ -z "$max_mem_gb" ]; then echo 0; exit 0; fi
echo "$max_mem_gb"
