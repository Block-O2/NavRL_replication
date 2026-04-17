#!/usr/bin/env bash
set -e

export ISAACSIM_PATH=$HOME/.local/share/ov/pkg
export CARB_APP_PATH=$ISAACSIM_PATH/kit
source $ISAACSIM_PATH/setup_conda_env.sh

cd $HOME/projects/NavRL/isaac-training

$HOME/miniconda3/envs/NavRL/bin/python training/scripts/train_clean_noclose.py \
  headless=True \
  env.num_envs=1024 \
  env.num_obstacles=350 \
  env_dyn.num_obstacles=80 \
  wandb.mode=disabled
