from __future__ import annotations
import json
import logging
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from core.env.base import Environment, EnvState, EnvStep

logger = logging.getLogger(__name__)

TW_GAMES_DIR = Path("tw_games")
TW_BRIDGE_SCRIPT = Path(__file__).resolve().parent.parent.parent / "scripts" / "tw_bridge.py"


class TextWorldError(Exception):
    ...


def is_wsl_available() -> bool:
    if platform.system() != "Windows":
        return False
    try:
        result = subprocess.run(
            ["wsl", "--version"],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def _is_running_in_wsl() -> bool:
    if platform.system() != "Linux":
        return False
    try:
        with open("/proc/version") as f:
            return "microsoft" in f.read().lower() or "wsl" in f.read().lower()
    except Exception:
        return False


def _can_import_textworld() -> bool:
    try:
        import textworld  # noqa
        return True
    except ImportError:
        return False


class WSLBridge:
    def __init__(self, game_path: str, tw_env_path: str = "~/tw-env", max_steps: int = 100):
        self.game_path = game_path
        self.tw_env_path = tw_env_path
        self.max_steps = max_steps
        self._process: subprocess.Popen | None = None

    @staticmethod
    def _make_request(cmd_type: str, **kwargs) -> str:
        data: dict[str, Any] = {"type": cmd_type}
        data.update(kwargs)
        return json.dumps(data, ensure_ascii=False)

    @staticmethod
    def _parse_response(raw: str) -> dict[str, Any]:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise TextWorldError(f"invalid JSON response: {e}") from e
        if "error" in data:
            raise TextWorldError(data["error"])
        return data

    @staticmethod
    def _wsl_path(windows_path: Path) -> str:
        parts = windows_path.resolve().parts
        if len(parts) > 1 and parts[0].endswith(":"):
            drive = parts[0][0].lower()
            rest = "/".join(parts[1:])
            return f"/mnt/{drive}/{rest}"
        return str(windows_path)

    def _start(self):
        bridge_wsl = self._wsl_path(TW_BRIDGE_SCRIPT)
        cmd = [
            "wsl",
            "bash", "-c",
            f"source {self.tw_env_path}/bin/activate && "
            f"python3 {bridge_wsl} {self.game_path} {self.max_steps}",
        ]
        self._process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    def reset(self) -> EnvState:
        if self._process is None:
            self._start()
        req = self._make_request("reset")
        self._write(req)
        raw = self._read()
        data = self._parse_response(raw)
        return EnvState(
            observation=data["observation"],
            info=data.get("infos", {}),
        )

    def step(self, action: str) -> EnvStep:
        if self._process is None:
            raise TextWorldError("bridge not started, call reset() first")
        req = self._make_request("step", action=action)
        self._write(req)
        raw = self._read()
        data = self._parse_response(raw)
        return EnvStep(
            state=EnvState(
                observation=data["observation"],
                info=data.get("infos", {}),
            ),
            reward=data.get("reward", 0.0),
            done=data.get("done", False),
        )

    def close(self):
        if self._process:
            try:
                self._write(self._make_request("close"))
                self._process.wait(timeout=5)
            except Exception:
                self._process.kill()
            self._process = None

    def _write(self, data: str):
        if self._process and self._process.stdin:
            self._process.stdin.write(data + "\n")
            self._process.stdin.flush()

    def _read(self) -> str:
        if self._process and self._process.stdout:
            return self._process.stdout.readline().strip()
        raise TextWorldError("bridge process not running")


class DirectTextWorldBackend:
    def __init__(self, game_path: str, max_steps: int = 100):
        import textworld.gym
        self._env_id = textworld.gym.register_game(game_path, max_episode_steps=max_steps)
        self._env = textworld.gym.make(self._env_id)

    def reset(self) -> EnvState:
        obs, infos = self._env.reset()
        return EnvState(observation=str(obs), info=dict(infos))

    def step(self, action: str) -> EnvStep:
        obs, reward, done, infos = self._env.step(action)
        return EnvStep(
            state=EnvState(observation=str(obs), info=dict(infos)),
            reward=float(reward),
            done=bool(done),
        )

    def close(self):
        self._env.close()


class TextWorldEnv(Environment):
    def __init__(self, game_path: str, max_steps: int = 100):
        self.game_path = str(game_path)
        self.max_steps = max_steps
        self._backend: WSLBridge | DirectTextWorldBackend | None = None

    def reset(self, task_description: str = "") -> EnvState:
        self._init_backend()
        return self._backend.reset()

    def step(self, action: str) -> EnvStep:
        if self._backend is None:
            raise TextWorldError("env not reset, call reset() first")
        return self._backend.step(action)

    def close(self):
        if self._backend:
            self._backend.close()
            self._backend = None

    def _init_backend(self):
        if self._backend is not None:
            return
        if _is_running_in_wsl() and _can_import_textworld():
            logger.info("using native TextWorld backend (WSL)")
            self._backend = DirectTextWorldBackend(self.game_path, self.max_steps)
        elif is_wsl_available():
            logger.info("using WSL subprocess backend")
            self._backend = WSLBridge(self.game_path, max_steps=self.max_steps)
        else:
            raise TextWorldError(
                "TextWorld not available. Either run in WSL with tw-env, "
                "or use --tw-env-path to point to a WSL TextWorld environment."
            )

    @staticmethod
    def generate_game(
        world_size: int = 5,
        nb_objects: int = 10,
        quest_length: int = 5,
        seed: int = 1234,
        output_dir: str | Path | None = None,
    ) -> Path:
        output_dir = Path(output_dir) if output_dir else TW_GAMES_DIR
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"game_s{seed}_w{world_size}_o{nb_objects}_q{quest_length}.z8"
        output_path = output_dir / filename

        if output_path.exists():
            logger.info("game already exists: %s", output_path)
            return output_path

        if is_wsl_available():
            cmd = [
                "wsl",
                "bash", "-c",
                f"source ~/tw-env/bin/activate && "
                f"tw-make custom --world-size {world_size} "
                f"--nb-objects {nb_objects} --quest-length {quest_length} "
                f"--seed {seed} --output \"{output_path}\"",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                raise TextWorldError(
                    f"game generation failed: {result.stderr.strip()}"
                )
        elif _is_running_in_wsl() and _can_import_textworld():
            import textworld
            textworld.make(
                f"custom_game_s{seed}",
                options={
                    "world_size": world_size,
                    "nb_objects": nb_objects,
                    "quest_length": quest_length,
                    "seed": seed,
                },
            )
        else:
            raise TextWorldError(
                "cannot generate game: TextWorld not available in WSL"
            )

        return output_path
