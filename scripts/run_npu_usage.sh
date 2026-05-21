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

top_pids="$(docker top "$container" 2>/dev/null | awk -v limit="$workers" '
  NR > 1 {
    if (($4 + 0) <= 0) next
    split($7, t, ":")
    sec = t[1] * 3600 + t[2] * 60 + t[3]
    print $2, sec
  }
' | sort -k2 -nr | head -n "$workers" | awk '{print $1}')"

if [ -z "$top_pids" ]; then
  root_pid="$(docker inspect -f '{{.State.Pid}}' "$container" 2>/dev/null || true)"
  if [[ "$root_pid" =~ ^[0-9]+$ ]] && [ "$root_pid" -gt 0 ]; then
    top_pids="$(pgrep -P "$root_pid" 2>/dev/null | head -n "$workers")"
  fi
fi
log "top_pids=$(printf '%s' "$top_pids" | tr '\n' ',' | sed 's/,$//')"
if [ -z "$top_pids" ]; then echo 0; exit 0; fi

match_pids="$top_pids"
for pid in $top_pids; do
  descendants="$(collect_descendants "$pid")"
  if [ -n "$descendants" ]; then
    match_pids="$(printf '%s\n%s\n' "$match_pids" "$descendants")"
  fi
done
match_pids="$(printf '%s\n' "$match_pids" | awk 'NF {print $1}' | sort -n | uniq)"
log "match_pids=$(printf '%s' "$match_pids" | tr '\n' ',' | sed 's/,$//')"

top_pids_csv="$(printf '%s\n' "$match_pids" | awk 'NF {print $1}' | paste -sd, -)"
pairs="$(printf '%s\n' "$device_info" | tr ',' '\n' | awk -F: 'NF >= 2 && $1 ~ /^[0-9]+$/ && $2 ~ /^[0-9]+$/ { print $1 ":" $2 }' | sort -t: -k1,1n -k2,2n | uniq)"

if [ -z "$pairs" ]; then
  pairs="$(discover_pairs_from_info "$top_pids_csv")"
fi
log "pairs=$(printf '%s' "$pairs" | tr '\n' ',' | sed 's/,$//')"

card_rows="$(printf '%s\n' "$pairs" | tr ',' '\n' | awk -F: '
  NF >= 2 && $1 ~ /^[0-9]+$/ && $2 ~ /^[0-9]+$/ { pairs[$1 ":" $2] = 1 }
  END {
    for (pair in pairs) {
      split(pair, items, ":")
      chips[items[1]]++
    }
    for (card in chips) {
      print card, chips[card]
    }
  }
' | sort -n -k1,1)"

if [ -z "$card_rows" ]; then
card_rows="$(npu-smi info -l 2>/dev/null | awk '
  /NPU[[:space:]_-]*ID/ { next }
  {
    line = $0
    gsub(/[|]/, " ", line)
    n = split(line, fields, /[[:space:]]+/)
    card = ""
    chips = ""
    for (i = 1; i <= n; i++) {
      if (fields[i] ~ /^[0-9]+$/) {
        if (card == "") card = fields[i]
        else if (chips == "") chips = fields[i]
      }
    }
    if (card != "") {
      if (chips == "") chips = 1
      print card, chips
    }
  }
' | sort -n -k1,1 | uniq)"
fi

log "card_rows=$(printf '%s' "$card_rows" | tr '\n' ';' | sed 's/;$//')"
if [ -z "$card_rows" ]; then echo 0; exit 0; fi

extract_usage() {
  awk '
    {
      line = $0
      if (tolower(line) !~ /aicore[[:space:]]+usage[[:space:]]+rate/) next
      gsub(/[|:%]/, " ", line)
      n = split(line, fields, /[[:space:]]+/)
      for (i = 1; i <= n; i++) {
        if (fields[i] ~ /^[0-9]+(\.[0-9]+)?$/ && fields[i] <= 100) value = fields[i]
      }
    }
    END { if (value != "") print value }
  '
}

max="0"
while read -r card chip_count; do
  [ -z "$card" ] && continue
  snapshot="$(npu-smi info -t proc-mem -i "$card" 2>/dev/null || true)"
  log "card=$card chip_count=$chip_count snapshot_lines=$(printf '%s\n' "$snapshot" | wc -l | awk '{print $1}')"
  active_chips=""
  if [ -n "$snapshot" ]; then
    for pid in $match_pids; do
      chips="$(printf '%s\n' "$snapshot" | awk -v pid="$pid" '
        /^[[:space:]]*Chip ID[[:space:]]*:/ {
          line = $0
          sub(/.*:/, "", line)
          gsub(/[^0-9]/, "", line)
          if (line != "") {
            chip_at[NR] = line
            chip_lines[++chip_count] = NR
          }
          next
        }
        {
          line = $0
          gsub(/[|,:]/, " ", line)
          n = split(line, fields, /[[:space:]]+/)
          for (i = 1; i <= n; i++) {
            if (fields[i] == pid) hit_lines[++hit_count] = NR
          }
        }
        END {
          for (h = 1; h <= hit_count; h++) {
            best = ""
            best_distance = 0
            for (c = 1; c <= chip_count; c++) {
              distance = chip_lines[c] - hit_lines[h]
              if (distance < 0) distance = -distance
              if (best == "" || distance < best_distance) {
                best = chip_at[chip_lines[c]]
                best_distance = distance
              }
            }
            if (best != "") print best
          }
        }
      ')"
      active_chips="$active_chips $chips"
    done
  fi
  active_chips="$(printf '%s\n' $active_chips | awk 'NF {print $1}' | sort -n | uniq)"

  if [ -n "$pairs" ]; then
    active_chips="$(printf '%s\n' "$pairs" | tr ',' '\n' | awk -F: -v card="$card" '$1 == card && $2 ~ /^[0-9]+$/ { print $2 }' | sort -n | uniq)"
  fi
  log "card=$card active_chips=$(printf '%s' "$active_chips" | tr '\n' ',' | sed 's/,$//')"

  if [ -z "$active_chips" ]; then
    active_chips="$(awk -v count="${chip_count:-1}" 'BEGIN { for (i = 0; i < count; i++) print i }')"
  fi

  for chip in $active_chips; do
    snapshot="$(npu-smi info -t usages -i "$card" -c "$chip" 2>/dev/null || true)"
    value="$(printf '%s\n' "$snapshot" | extract_usage | tail -n 1)"
    if [ -z "$value" ]; then
      snapshot="$(npu-smi info -t usages -i "$card" 2>/dev/null || true)"
      value="$(printf '%s\n' "$snapshot" | extract_usage | tail -n 1)"
    fi
    log "card=$card chip=$chip npu_usage_value=${value:-<empty>}"
    if [ -n "$value" ]; then
      max="$(awk -v a="$max" -v b="$value" 'BEGIN { print (b > a ? b : a) }')"
    fi
  done
done <<EOF
$card_rows
EOF

log "final_npu_usage=$max"
printf "%.2f\n" "$max"
