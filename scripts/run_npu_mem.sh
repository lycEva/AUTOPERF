#!/usr/bin/env bash
set -u

container="${1:-}"
workers="${2:-1}"
device_info="${3:-}"
DEBUG="${DEBUG:-0}"

log() {
  if [ "$DEBUG" = "1" ]; then
    printf '[DEBUG] %s\n' "$*" >&2
  fi
}

collect_descendants() {
  local root_pid="$1"
  docker top "$container" 2>/dev/null | awk -v root="$root_pid" '
    NR == 1 { next }
    {
      pid = $2
      ppid = $3
      cmd = ""
      for (i = 8; i <= NF; i++) {
        cmd = cmd (i == 8 ? "" : " ") $i
      }
      if (pid ~ /^[0-9]+$/ && ppid ~ /^[0-9]+$/) {
        parent[pid] = ppid
        command[pid] = cmd
      }
    }
    END {
      for (pid in parent) {
        current = pid
        while (current in parent) {
          if (parent[current] == root) {
            if (command[pid] ~ /gunicorn/) print pid
            break
          }
          current = parent[current]
        }
      }
    }
  ' | sort -n | uniq
}

discover_pairs_from_info() {
  local pids_csv="$1"
  npu-smi info 2>/dev/null | awk -v pids="$pids_csv" '
    BEGIN {
      split(pids, arr, /,/)
      for (i in arr) {
        if (arr[i] != "") wanted[arr[i]] = 1
      }
    }
    /\|/ {
      raw = $0
      count = split(raw, cols, /\|/)
      if (count < 5) next
      left = cols[2]
      pid = cols[3]
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", left)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", pid)
      if (pid !~ /^[0-9]+$/) next
      n = split(left, parts, /[[:space:]]+/)
      if (n < 2) next
      npu = parts[1]
      chip = parts[2]
      if (npu !~ /^[0-9]+$/ || chip !~ /^[0-9]+$/) next
      if (wanted[pid]) {
        pair = npu ":" chip
        if (!seen[pair]) {
          print pair
          seen[pair] = 1
        }
      }
    }
  ' | sort -t: -k1,1n -k2,2n
}

if [ -z "$container" ]; then echo 0; exit 0; fi
if ! command -v npu-smi >/dev/null 2>&1; then echo 0; exit 0; fi

log "container=$container workers=$workers device_info=${device_info:-<empty>}"

top_pids="$(printf '%s\n' "${AUTOPERF_MONITOR_PIDS:-}" | tr ',' '\n' | awk 'NF {print $1}')"

if [ -z "$top_pids" ]; then
top_pids="$(docker top "$container" 2>/dev/null | awk -v limit="$workers" '
  NR > 1 {
    if (($4 + 0) <= 0) next
    split($7, t, ":")
    sec = t[1] * 3600 + t[2] * 60 + t[3]
    print $2, sec
  }
' | sort -k2 -nr | head -n "$workers" | awk '{print $1}')"
fi

if [ -z "$top_pids" ]; then
  root_pid="$(docker inspect -f '{{.State.Pid}}' "$container" 2>/dev/null || true)"
  if [[ "$root_pid" =~ ^[0-9]+$ ]] && [ "$root_pid" -gt 0 ]; then
    top_pids="$(pgrep -P "$root_pid" 2>/dev/null | head -n "$workers")"
  fi
fi
log "top_pids=$(printf '%s' "$top_pids" | tr '\n' ',' | sed 's/,$//')"
if [ -z "$top_pids" ]; then echo 0; exit 0; fi

match_pids="$(printf '%s\n' "${AUTOPERF_MONITOR_RELATED_PIDS:-}" | tr ',' '\n' | awk 'NF {print $1}')"
if [ -z "$match_pids" ]; then
  match_pids="$top_pids"
  for pid in $top_pids; do
    descendants="$(collect_descendants "$pid")"
    if [ -n "$descendants" ]; then
      match_pids="$(printf '%s\n%s\n' "$match_pids" "$descendants")"
    fi
  done
fi
match_pids="$(printf '%s\n' "$match_pids" | awk 'NF {print $1}' | sort -n | uniq)"
log "match_pids=$(printf '%s' "$match_pids" | tr '\n' ',' | sed 's/,$//')"

top_pids_csv="$(printf '%s\n' "$match_pids" | awk 'NF {print $1}' | paste -sd, -)"
pairs="$(printf '%s\n' "$device_info" | tr ',' '\n' | awk -F: 'NF >= 2 && $1 ~ /^[0-9]+$/ && $2 ~ /^[0-9]+$/ { print $1 ":" $2 }' | sort -t: -k1,1n -k2,2n | uniq)"

if [ -z "$pairs" ]; then
  pairs="$(discover_pairs_from_info "$top_pids_csv")"
fi
log "pairs=$(printf '%s' "$pairs" | tr '\n' ',' | sed 's/,$//')"

cards="$(printf '%s\n' "$pairs" | awk -F: 'NF >= 1 && $1 ~ /^[0-9]+$/ { print $1 }' | sort -n | uniq)"

if [ -z "$cards" ]; then
cards="$(npu-smi info -l 2>/dev/null | awk '
  /NPU[[:space:]_-]*ID/ { next }
  {
    line = $0
    gsub(/[|]/, " ", line)
    n = split(line, fields, /[[:space:]]+/)
    for (i = 1; i <= n; i++) {
      if (fields[i] ~ /^[0-9]+$/) {
        print fields[i]
        next
      }
    }
  }
' | sort -n | uniq)"
fi

log "cards=$(printf '%s' "$cards" | tr '\n' ',' | sed 's/,$//')"
if [ -z "$cards" ]; then echo 0; exit 0; fi

max="0"
for card in $cards; do
  snapshot="$(npu-smi info -t proc-mem -i "$card" 2>/dev/null || true)"
  log "card=$card snapshot_lines=$(printf '%s\n' "$snapshot" | wc -l | awk '{print $1}')"
  [ -z "$snapshot" ] && continue
  for pid in $match_pids; do
    value="$(printf '%s\n' "$snapshot" | awk -v pid="$pid" -v wanted="$pairs" -v card="$card" '
      BEGIN {
        use_filter = (wanted != "")
      }
      {
        line = $0
        gsub(/[|,:]/, " ", line)
        n = split(line, fields, /[[:space:]]+/)
        hit = 0
        for (i = 1; i <= n; i++) {
          if (fields[i] == pid) hit = 1
        }
        if (hit) {
          for (i = 1; i <= n; i++) {
            token = fields[i]
            gsub(/[A-Za-z()%]/, "", token)
            if (token ~ /^[0-9]+(\.[0-9]+)?$/) value = token
          }
          if (value != "") print value
        }
      }
    ' | tail -n 1)"
    log "card=$card pid=$pid npu_mem_value=${value:-<empty>}"
    if [ -n "$value" ]; then
      max="$(awk -v a="$max" -v b="$value" 'BEGIN { print (b > a ? b : a) }')"
    fi
  done
done

log "final_npu_mem=$max"
printf "%.2f\n" "$max"
