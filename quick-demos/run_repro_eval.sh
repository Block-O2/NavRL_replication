#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-/home/ubuntu/miniconda3/envs/NavRL/bin/python}"
OUT_DIR="${OUT_DIR:-$ROOT_DIR/quick-demos/eval_outputs}"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT_FILE="$OUT_DIR/repro_eval_$STAMP.log"

mkdir -p "$OUT_DIR"

AUTHOR="$ROOT_DIR/quick-demos/ckpts/navrl_checkpoint.pt"
OWN1000="$ROOT_DIR/isaac-training/runs/navrl_1024_50m_20260417_policy_retry1/ckpts/checkpoint_1000.pt"
OWN1500="$ROOT_DIR/isaac-training/runs/navrl_1024_50m_20260417_policy_retry1/ckpts/checkpoint_1500.pt"
OWNFINAL="$ROOT_DIR/isaac-training/runs/navrl_1024_50m_20260417_policy_retry1/ckpts/checkpoint_final.pt"
DYNSTOP150="$ROOT_DIR/isaac-training/runs/navrl_1024_ablate_dynstop_5m_20260418/ckpts/checkpoint_150.pt"
DYNSTOPFINAL="$ROOT_DIR/isaac-training/runs/navrl_1024_ablate_dynstop_5m_20260418/ckpts/checkpoint_final.pt"

run_eval() {
  local title="$1"
  shift
  {
    echo
    echo "===== $title ====="
    echo "command: $*"
  } | tee -a "$OUT_FILE"
  "$@" 2>&1 | tee -a "$OUT_FILE"
}

echo "[NavRL repro eval] output: $OUT_FILE" | tee "$OUT_FILE"
echo "[NavRL repro eval] python: $PYTHON_BIN" | tee -a "$OUT_FILE"

COMMON_POLICIES=(
  --policy "author=$AUTHOR"
  --policy "own1000=$OWN1000"
  --policy "own1500=$OWN1500"
  --policy "ownfinal=$OWNFINAL"
)

if [[ -f "$DYNSTOP150" ]]; then
  COMMON_POLICIES+=(--policy "dynstop150=$DYNSTOP150")
fi

if [[ -f "$DYNSTOPFINAL" ]]; then
  COMMON_POLICIES+=(--policy "dynstopfinal=$DYNSTOPFINAL")
fi

SAFE_POLICIES=(
  --policy "author=$AUTHOR"
  --policy "own1500=$OWN1500"
  --policy "ownfinal=$OWNFINAL"
)

if [[ -f "$DYNSTOP150" ]]; then
  SAFE_POLICIES+=(--policy "dynstop150=$DYNSTOP150")
fi

if [[ -f "$DYNSTOPFINAL" ]]; then
  SAFE_POLICIES+=(--policy "dynstopfinal=$DYNSTOPFINAL")
fi

run_eval "ROS2-style mixed, no safe_action" \
  "$PYTHON_BIN" "$ROOT_DIR/quick-demos/policy_ros2_style_compare.py" \
  --seeds 20 \
  --frames 300 \
  --device cpu \
  "${COMMON_POLICIES[@]}"

run_eval "ROS2-style mixed, safe_action approximation" \
  "$PYTHON_BIN" "$ROOT_DIR/quick-demos/policy_ros2_style_compare.py" \
  --safe-action \
  --seeds 10 \
  --frames 300 \
  --device cpu \
  "${SAFE_POLICIES[@]}"

run_eval "ROS2-style dynamic path-crossing, no safe_action" \
  "$PYTHON_BIN" "$ROOT_DIR/quick-demos/policy_ros2_style_compare.py" \
  --seeds 20 \
  --frames 300 \
  --device cpu \
  --static-grid-div 0 \
  --dynamic-count 5 \
  --dynamic-layout path-crossing \
  --route corridor \
  "${COMMON_POLICIES[@]}"

run_eval "ROS2-style dynamic path-crossing, safe_action approximation" \
  "$PYTHON_BIN" "$ROOT_DIR/quick-demos/policy_ros2_style_compare.py" \
  --safe-action \
  --seeds 20 \
  --frames 300 \
  --device cpu \
  --static-grid-div 0 \
  --dynamic-count 5 \
  --dynamic-layout path-crossing \
  --route corridor \
  "${SAFE_POLICIES[@]}"

echo
echo "[NavRL repro eval] done: $OUT_FILE"
