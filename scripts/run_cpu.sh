#!/usr/bin/env bash
set -u

container="${1:-}"
workers="${2:-1}"
proc_root="${CPU_PROC_ROOT:-/proc}"
sample_seconds="${CPU_SAMPLE_SECONDS:-1}"

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

read_cpu_total() {
  awk '/^cpu / {
    total = 0
    for (i = 2; i <= NF; i++) total += $i
    print total
    exit
  }' "$proc_root/stat" 2>/dev/null
}

read_cpu_count() {
  awk '/^cpu[0-9][0-9]*[[:space:]]/ { count++ } END { print (count > 0 ? count : 1) }' "$proc_root/stat" 2>/dev/null
}

read_pid_ticks() {
  local pid="$1"
  awk '
    {
      line = $0
      if (!sub(/^.*\) /, "", line)) exit
      n = split(line, fields, /[[:space:]]+/)
      if (n < 13) exit
      print fields[12] + fields[13]
    }
  ' "$proc_root/$pid/stat" 2>/dev/null
}

sample_cpu_ticks() {
  local total cpu_count
  total="$(read_cpu_total)"
  [ -z "$total" ] && return 1
  cpu_count="$(read_cpu_count)"
  printf 'total %s\n' "$total"
  printf 'cpus %s\n' "${cpu_count:-1}"
  printf '%s\n' "$worker_pids" | awk 'NF {print $1}' | while read -r pid; do
    ticks="$(read_pid_ticks "$pid")"
    [ -n "$ticks" ] && printf 'pid %s %s\n' "$pid" "$ticks"
  done
}

first_sample="$(sample_cpu_ticks || true)"
sleep "$sample_seconds"
second_sample="$(sample_cpu_ticks || true)"

max_cpu="$(awk '
  $1 == "total" && phase == 0 { total1 = $2; next }
  $1 == "cpus" && phase == 0 { cpu_count = $2; next }
  $1 == "pid" && phase == 0 { pid1[$2] = $3; next }
  $1 == "---" { phase = 1; next }
  $1 == "total" && phase == 1 { total2 = $2; next }
  $1 == "pid" && phase == 1 { pid2[$2] = $3; next }
  END {
    total_delta = total2 - total1
    if (total_delta <= 0) {
      printf "%.2f\n", 0
      exit
    }
    if (cpu_count <= 0) cpu_count = 1
    per_cpu_delta = total_delta / cpu_count
    if (per_cpu_delta <= 0) {
      printf "%.2f\n", 0
      exit
    }
    for (pid in pid2) {
      if (!(pid in pid1)) continue
      pid_delta = pid2[pid] - pid1[pid]
      if (pid_delta < 0) continue
      value = (pid_delta / per_cpu_delta) * 100
      if (value > max) max = value
    }
    printf "%.2f\n", max + 0
  }
' <<EOF
$first_sample
---
$second_sample
EOF
)"

if [ -z "$max_cpu" ]; then echo 0; exit 0; fi
echo "$max_cpu"
