# WSL + TextWorld 环境设置

## 环境概览

| 组件 | 版本/状态 |
|------|-----------|
| WSL 版本 | 2 |
| Ubuntu 版本 | 22.04 |
| Python | 3.10.12 |
| TextWorld | 1.7.0 |
| 虚拟环境 | ~/tw-env |
| 项目路径 (WSL) | /mnt/c/Users/micha/PycharmProjects/cognitive-agent |

## WSL 操作

### 启动 WSL

```bash
# 从 Windows PowerShell / CMD 进入 WSL
wsl

# 或单条命令执行
wsl <command>
```

### 激活 TextWorld 环境

```bash
source ~/tw-env/bin/activate
```

退出环境：`deactivate`

### 项目目录对应

```
Windows: C:\Users\micha\PycharmProjects\cognitive-agent\
WSL:     /mnt/c/Users/micha/PycharmProjects/cognitive-agent/
```

## 运行流程

### 1. 激活环境并进入项目目录

```bash
wsl
source ~/tw-env/bin/activate
cd /mnt/c/Users/micha/PycharmProjects/cognitive-agent
```

### 2. 运行测试

```bash
cd /mnt/c/Users/micha/PycharmProjects/cognitive-agent
source ~/tw-env/bin/activate
python -m pytest tests/ -v          # 全部测试
python -m pytest tests/ -v -k test_agent  # 按名称过滤
```

### 3. 运行 Agent

```bash
cd /mnt/c/Users/micha/PycharmProjects/cognitive-agent
source ~/tw-env/bin/activate
python main.py                          # 启动并打印各层状态
python main.py "你的问题"               # 执行任务
```

### 4. 单条命令模式（无需进入交互式 shell）

```bash
wsl bash -c "cd /mnt/c/Users/micha/PycharmProjects/cognitive-agent && source ~/tw-env/bin/activate && python -m pytest tests/ -v"
```

## TextWorld 使用

### 生成游戏

```bash
source ~/tw-env/bin/activate
tw-make custom --world-size 5 --nb-objects 10 --quest-length 5 --seed 1234 --output tw_games/custom_game.z8
```

### 终端中游玩

```bash
tw-play tw_games/custom_game.z8
```

### Python Gym 接口

```python
import textworld.gym

env_id = textworld.gym.register_game("tw_games/custom_game.z8", max_episode_steps=50)
env = textworld.gym.make(env_id)
obs, infos = env.reset()
```

## 重新安装

如需从头重建环境，运行项目中的一键脚本：

```bash
bash scripts/setup-wsl-env.sh
```

## 常见问题

### sudo 需要密码

已在 `/etc/sudoers.d/tonyyang-nopasswd` 配置免密 sudo。如需移除：

```bash
sudo rm /etc/sudoers.d/tonyyang-nopasswd
```

### 中文编码问题

WSL 中 UTF-8 编码正常。Windows PowerShell 对中文路径支持差——所有开发操作建议在 WSL 中完成。

### TextWorld 网络安装失败

Repo 默认分支是 `main`。脚本使用 `pip install textworld`（PyPI 包），无需从 GitHub 源码安装。
