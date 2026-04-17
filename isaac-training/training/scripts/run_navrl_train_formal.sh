#!/usr/bin/env bash
set -e

export ISAACSIM_PATH=$HOME/.local/share/ov/pkg
export CARB_APP_PATH=$ISAACSIM_PATH/kit
source $ISAACSIM_PATH/setup_conda_env.sh

cd ~/projects/NavRL/isaac-training

$HOME/miniconda3/envs/NavRL/bin/python training/scripts/train_noclose.py \
  headless=True \
  env.num_envs=8 \
  algo.training_frame_num=32 \
  max_frame_num=5000000 \
  eval_interval=500 \
  save_interval=500 \
  wandb.mode=disabled
