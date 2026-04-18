# NavRL Reproduction Policies

This directory stores selected policy checkpoints from the reproduction work.

## Current Candidates

| Directory | File | Role | SHA256 |
| --- | --- | --- | --- |
| `dynstopfinal_20260418` | `checkpoint_final.pt` | Current strongest self-trained candidate after the 5M `dynamic_stop_penalty` ablation. | `2644f67a3979d42e409090c7935316838cbb7a01f0aa54843e80cdb25dd4907e` |
| `own1500_20260417` | `checkpoint_1500.pt` | Stable no-ablation baseline from the 50M self-training run. | `b40a309fdaa5e1a9e1c1bcd8c0c77ec997428e881aeeab9f86f5ad44b64cc435` |

## Source Runs

- `dynstopfinal_20260418/checkpoint_final.pt`
  - Source: `isaac-training/runs/navrl_1024_ablate_dynstop_5m_20260418/ckpts/checkpoint_final.pt`
  - Notes: started from `own1500`; trained for 5M frames with `reward.dynamic_stop_penalty=1.0`, `reward.dynamic_stop_distance=1.2`, `reward.dynamic_stop_speed=0.2`.

- `own1500_20260417/checkpoint_1500.pt`
  - Source: `isaac-training/runs/navrl_1024_50m_20260417_policy_retry1/ckpts/checkpoint_1500.pt`
  - Notes: stable baseline from the 1024 / 350 / 80 GPU noeval0 50M run.

## Important Caveat

These checkpoints are reproduction artifacts, not proof of full paper reproduction.
Current evidence shows they can load in the ROS2 `navigation_node.py` path and produce commands in controlled text-based tests.
They still need broader ROS2/Isaac validation before any real robot use.
