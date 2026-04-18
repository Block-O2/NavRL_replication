import json
import os

import hydra
import torch
from omni.isaac.kit import SimulationApp
from omni_drones.controllers import LeePositionController
from omni_drones.utils.torchrl.transforms import VelController
from omegaconf import OmegaConf
from ppo import PPO
from torchrl.envs.transforms import Compose, TransformedEnv
from torchrl.envs.utils import ExplorationType
from utils import evaluate


FILE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cfg")


@hydra.main(config_path=FILE_PATH, config_name="train", version_base=None)
def main(cfg):
    sim_app = SimulationApp({"headless": cfg.headless, "anti_aliasing": 1})

    checkpoint_cfg = cfg.get("checkpoint", None)
    if checkpoint_cfg is None:
        raise ValueError("Pass checkpoint=/abs/path/to/checkpoint.pt")
    checkpoint_path = os.path.abspath(os.path.expanduser(str(checkpoint_cfg)))

    print("[EVAL-CFG]")
    print(OmegaConf.to_yaml(cfg))
    print(f"[EVAL-CKPT] loading {checkpoint_path}", flush=True)

    from env import NavigationEnv

    env = NavigationEnv(cfg)
    controller = LeePositionController(9.81, env.drone.params).to(cfg.device)
    transformed_env = TransformedEnv(env, Compose(VelController(controller, yaw_control=False))).eval()
    transformed_env.set_seed(cfg.seed)

    policy = PPO(cfg.algo, transformed_env.observation_spec, transformed_env.action_spec, cfg.device)
    policy.load_state_dict(torch.load(checkpoint_path, map_location=cfg.device))
    print("[EVAL-CKPT] loaded", flush=True)

    eval_info = evaluate(
        env=transformed_env,
        policy=policy,
        seed=cfg.seed,
        cfg=cfg,
        exploration_type=ExplorationType.MEAN,
    )

    scalar_info = {
        key: float(value)
        for key, value in eval_info.items()
        if key != "recording"
    }
    print("[EVAL-JSON] " + json.dumps(scalar_info, sort_keys=True), flush=True)
    print("NO_CLOSE_EXIT")


if __name__ == "__main__":
    main()
