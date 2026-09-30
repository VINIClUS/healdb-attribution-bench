#!/usr/bin/env bash
# Launch a detached headless Opus lead session in a worktree.
# usage: launch_lead.sh <name> <worktree_dir> <prompt_file> [extra claude args, e.g. --resume <session_id>]
# Output: $HAB_DATA_DIR/orchestration/<name>.{json,err,pid}
set -euo pipefail
name=$1; wt=$2; prompt_file=$3; shift 3
logdir=/home/vinicius/hab-data/orchestration
mkdir -p "$logdir"
allowed=(Read Write Edit Glob Grep Agent
  "Bash(uv:*)" "Bash(rtk uv:*)" "Bash(git:*)" "Bash(rtk git:*)" "Bash(rtk proxy git:*)" "Bash(rtk proxy uv:*)"
  "Bash(flock:*)" "Bash(ls:*)" "Bash(rtk ls:*)" "Bash(cat:*)" "Bash(rtk read:*)" "Bash(head:*)" "Bash(tail:*)"
  "Bash(wc:*)" "Bash(find:*)" "Bash(rtk find:*)" "Bash(grep:*)" "Bash(rtk grep:*)" "Bash(sha256sum:*)"
  "Bash(md5sum:*)" "Bash(mkdir:*)" "Bash(cp:*)" "Bash(mv:*)" "Bash(diff:*)" "Bash(rtk diff:*)" "Bash(sort:*)"
  "Bash(python3:*)" "Bash(unzip -l:*)" "Bash(unzip -p:*)" "Bash(date:*)" "Bash(echo:*)" "Bash(pdftotext:*)"
  "Bash(touch:*)" "Bash(rm:*)")
cd "$wt"
setsid nohup env AWS_SHARED_CREDENTIALS_FILE=/dev/null AWS_CONFIG_FILE=/dev/null AWS_EC2_METADATA_DISABLED=true \
  claude -p "$(cat "$prompt_file")" "$@" --model claude-opus-5-5 --permission-mode acceptEdits \
  --allowedTools "${allowed[@]}" \
  --add-dir /home/vinicius/hab-data --add-dir /home/vinicius/healdb-reconstrucao --add-dir /home/vinicius/code/HealDB \
  --output-format json > "$logdir/$name.json" 2> "$logdir/$name.err" < /dev/null &
echo $! > "$logdir/$name.pid"
echo "launched $name pid $(cat "$logdir/$name.pid")"
