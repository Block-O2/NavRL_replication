import argparse
import json
import os
import hydra
import datetime
import wandb
import torch
from omegaconf import DictConfig, OmegaConf
from omni.isaac.kit import SimulationApp
from ppo import PPO
from omni_drones.controllers import LeePositionController
from omni_drones.utils.torchrl.transforms import VelController, ravel_composite
from omni_drones.utils.torchrl import SyncDataCollector, EpisodeStats
from torchrl.envs.transforms import TransformedEnv, Compose
from utils import evaluate
from torchrl.envs.utils import ExplorationType




FILE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cfg")
@hydra.main(config_path=FILE_PATH, config_name="train", version_base=None)
def main(cfg):
    # Simulation App
    sim_app = SimulationApp({"headless": cfg.headless, "anti_aliasing": 1})

    ckpt_dir_cfg = cfg.get("ckpt_dir", None)
    ckpt_dir = (
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "ckpts")
        if ckpt_dir_cfg is None
        else os.path.abspath(os.path.expanduser(str(ckpt_dir_cfg)))
    )
    os.makedirs(ckpt_dir, exist_ok=True)
    print(f"[CKPT] saving to {ckpt_dir}")

    metrics_log_cfg = cfg.get("metrics_log", None)
    metrics_log_path = None
    if metrics_log_cfg is not None:
        metrics_log_path = os.path.abspath(os.path.expanduser(str(metrics_log_cfg)))
        metrics_log_dir = os.path.dirname(metrics_log_path)
        if metrics_log_dir:
            os.makedirs(metrics_log_dir, exist_ok=True)
        print(f"[METRICS] writing jsonl metrics to {metrics_log_path}")

    # Use Wandb to monitor training
    if (cfg.wandb.run_id is None):
        run = wandb.init(
            project=cfg.wandb.project,
            name=f"{cfg.wandb.name}/{datetime.datetime.now().strftime('%m-%d_%H-%M')}",
            entity=cfg.wandb.entity,
            config=cfg,
            mode=cfg.wandb.mode,
            id=wandb.util.generate_id(),
        )
    else:
        run = wandb.init(
            project=cfg.wandb.project,
            name=f"{cfg.wandb.name}/{datetime.datetime.now().strftime('%m-%d_%H-%M')}",
            entity=cfg.wandb.entity,
            config=cfg,
            mode=cfg.wandb.mode,
            id=cfg.wandb.run_id,
            resume="must"
        )

    # Navigation Training Environment
    from env import NavigationEnv
    env = NavigationEnv(cfg)

    # Transformed Environment
    transforms = []
    # transforms.append(ravel_composite(env.observation_spec, ("agents", "intrinsics"), start_dim=-1))
    controller = LeePositionController(9.81, env.drone.params).to(cfg.device)
    vel_transform = VelController(controller, yaw_control=False)
    transforms.append(vel_transform)
    transformed_env = TransformedEnv(env, Compose(*transforms)).train()
    transformed_env.set_seed(cfg.seed)    
    # PPO Policy
    policy = PPO(cfg.algo, transformed_env.observation_spec, transformed_env.action_spec, cfg.device)

    checkpoint_cfg = cfg.get("checkpoint", None)
    if checkpoint_cfg is not None:
        checkpoint_path = os.path.abspath(os.path.expanduser(str(checkpoint_cfg)))
        policy.load_state_dict(torch.load(checkpoint_path, map_location=cfg.device))
        print(f"[CKPT] loaded checkpoint from {checkpoint_path}")
    
    # Episode Stats Collector
    episode_stats_keys = [
        k for k in transformed_env.observation_spec.keys(True, True) 
        if isinstance(k, tuple) and k[0]=="stats"
    ]
    episode_stats = EpisodeStats(episode_stats_keys)

    # RL Data Collector
    collector = SyncDataCollector(
        transformed_env,
        policy=policy, 
        frames_per_batch=cfg.env.num_envs * cfg.algo.training_frame_num, 
        total_frames=cfg.max_frame_num,
        device=cfg.device,
        return_same_td=True, # update the return tensordict inplace (should set to false if we need to use replace buffer)
        exploration_type=ExplorationType.RANDOM, # sample from normal distribution
    )

    # Training Loop
    for i, data in enumerate(collector):
        # print("data: ", data)
        # print("============================")
        # Log Info
        info = {"env_frames": collector._frames, "rollout_fps": collector._fps}

        # Train Policy
        train_loss_stats = policy.train(data)
        info.update(train_loss_stats) # log training loss info

        # Calculate and log training episode stats
        episode_stats.add(data)
        if len(episode_stats) >= transformed_env.num_envs: # evaluate once if all agents finished one episode
            stats = {
                "train/" + (".".join(k) if isinstance(k, tuple) else k): torch.mean(v.float()).item() 
                for k, v in episode_stats.pop().items(True, True)
            }
            info.update(stats)

        # Evaluate policy and log info
        if i > 0 and i % cfg.eval_interval == 0:
            print("[NavRL]: start evaluating policy at training step: ", i)
            env.enable_render(True)
            env.eval()
            eval_info = evaluate(
                env=transformed_env, 
                policy=policy,
                seed=cfg.seed, 
                cfg=cfg,
                exploration_type=ExplorationType.MEAN
            )
            env.enable_render(not cfg.headless)
            env.train()
            env.reset()
            info.update(eval_info)
            print("\n[NavRL]: evaluation done.")
        
        # Update wand info
        run.log(info)

        if metrics_log_path is not None:
            metrics = {
                "step": int(i),
                "env_frames": int(collector._frames),
                "rollout_fps": float(collector._fps),
            }
            for key, value in train_loss_stats.items():
                metrics[f"loss/{key}"] = float(value)
            try:
                next_stats = data.get(("next", "stats"))
                for key, value in next_stats.items():
                    metrics[f"batch/stats.{key}"] = float(value.float().mean().item())
                metrics["batch/done_rate"] = float(data.get(("next", "done")).float().mean().item())
                metrics["batch/terminated_rate"] = float(data.get(("next", "terminated")).float().mean().item())
                metrics["batch/truncated_rate"] = float(data.get(("next", "truncated")).float().mean().item())
            except Exception as exc:
                metrics["metrics_error"] = repr(exc)
            with open(metrics_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(metrics, sort_keys=True) + "\n")


        # Save Model
        if i % cfg.save_interval == 0:
            ckpt_path = os.path.join(ckpt_dir, f"checkpoint_{i}.pt")
            torch.save(policy.state_dict(), ckpt_path)
            print("[NavRL]: model saved at training step: ", i)

    ckpt_path = os.path.join(ckpt_dir, "checkpoint_final.pt")
    torch.save(policy.state_dict(), ckpt_path)
    wandb.finish()
    print("NO_CLOSE_EXIT")

if __name__ == "__main__":
    main()
    
