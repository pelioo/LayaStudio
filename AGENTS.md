# LayaStudio / System One Studio — 项目指令

## 项目概述

本地微调 Laya typed-decision 模型的 Studio 平台（Windows/Linux 用 PyTorch，macOS Apple Silicon 用 MLX）。原名 Laya Studio，2026 年 9 月更名为 System One Studio，但命令名和文件夹名保留了历史名称。

- **仓库**：`biplovgautam/LayaStudio`
- **主入口**：`layastudio.server:main`（`layastudio` 命令）
- **运行时选择**：`layastudio/runtime.py` 根据平台自动选择 MLX 或 PyTorch 引擎

## 目录结构

```
LayaStudio/
├── layastudio/            # 核心 Python 包
│   ├── __init__.py        # 包初始化
│   ├── __main__.py        # python -m layastudio 入口（server.main）
│   ├── engine.py          # MLX 微调引擎 + 共享逻辑（数据集、校准、指标）
│   ├── torch_engine.py    # PyTorch 微调引擎（Windows/Linux GPU/CPU）
│   ├── runtime.py         # 运行时检测与选择
│   ├── server.py          # Web UI 服务器
│   ├── families.py        # 模型目录与兼容性检测
│   ├── snake.py           # 内置 Snake 对比测试
│   ├── export.py          # 导出 ONNX / Core ML
│   ├── publish.py         # 发布到 HuggingFace
│   ├── publish_systemone.py # 发布到 System One
│   ├── account.py         # 账户管理
│   ├── bootstrap.py       # 启动引导
│   └── examples.py        # 示例数据集
├── tests/                 # pytest 测试
├── docs/                  # 文档资源
└── workspace/             # 用户数据（数据集、runs、模型）由 WORKSPACE 管理
```

## 关键边界

- **engine.py**：MLX 微调核心 + 所有平台共享的数据集处理、校准、指标计算
- **torch_engine.py**：PyTorch 微调引擎，由 engine.py 的 `run_via_torch()` 调用
- **runtime.py**：根据 `platform.system()` 和 `platform.machine()` 判断是否为 Apple Silicon，返回 `'mlx'` 或 `'torch'`
- **server.py**：所有 HTTP/WebSocket 逻辑，运行重任务为子进程，不会因 OOM 拖垮 UI

## 工作区路径（WORKSPACE）

工作区用于存储数据集、训练 runs 和模型检查点，**不纳入版本控制**（`.gitignore` 已排除）。

```
WORKSPACE = default_workspace()
  → $LAYASTUDIO_HOME（优先）
  → checkout/workspace/  （git clone 场景）
  → ~/.layastudio/workspace  （pip 安装场景）
```

可通过环境变量 `$LAYASTUDIO_HOME` 自定义位置。

## 常用命令

```bash
# 开发运行（推荐，自动创建 .venv）
uv run layastudio

# 运行测试
uv run pytest

# 模块级入口
uv run python -m layastudio.engine run <job_dir>   # 微调任务
uv run python -m layastudio.snake dataset          # 生成 Snake 训练数据
uv run python -m layastudio.snake bench --model run:<id>  # 对比基准测试

# 导出（使用 uv，自动处理多索引）
uv sync --extra torch --extra export
uv run python -m layastudio.export run:<id> --target onnx
```

## 重要默认参数（HYPERPARAMETERS）

在 `layastudio/engine.py` 的 `HYPERPARAMETERS` 字典中定义，包括：
- LoRA rank / alpha / dropout
- 训练轮次、学习率、batch size
- 早停 patience
- 目标函数（`proper` / `rlcd` / `ce`）
- 精度配置（梯度检查点、混合精度阈值）

## 模型家族

- `laya` / `laya-mlx`：English · ModernBERT-large · 421M · 512 tokens
- `laya-multilingual-mlx`：Multilingual · mmBERT-base · 322M · 1024 tokens
- `laya-typed-decisions-mlx`：Typed-decisions · ModernBERT-large · 421M · 1024 tokens

## 测试注意

- `laya_mlx` 仅在 macOS ARM64 上可用；Windows/Linux 测试依赖 `torch_engine`
- `test_engine.py` 需要 `laya_mlx`，在 Windows 上会跳过或报错（预期行为）
- `test_families.py` 可在所有平台运行，测试模型目录逻辑

## 安全与隐私

- 服务器绑定 `127.0.0.1`，不暴露公网
- 训练任务以子进程运行，`HF_HUB_OFFLINE=1` 防止意外下载
- 不向外部发送用户数据
- `.workbuddy/` 目录（Agent 工作区）纳入 `.gitignore`，本地记忆和技能库不会被提交

## 完成标准

- 修改代码后：`uv run pytest` 通过
- 功能变更：对应模块有测试覆盖或 README 文档说明
- 新增导出格式：在 `export.py` 中添加目标并通过 `uv run python -m layastudio.export --help` 验证

## 生产接入

训练完成后，加载微调模型并推理（README.md 有完整示例）：

```python
import json, platform

# 自动选择运行时：macOS ARM64 用 laya_mlx，其余平台用 laya
if platform.system() == "Darwin" and platform.machine() == "arm64":
    import laya_mlx as laya
else:
    import laya as laya

agent = laya.load("workspace/runs/<run>/model")
questions = json.load(open("workspace/runs/<run>/model/questions.json"))
agent.predict("your text", questions)
```
