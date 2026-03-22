# 服务端架构文档

> Project: AI Text-to-Video Marketing Production Tool
> Version: v3.0 (Interactive Workflow + Candidate Management)
> Updated: 2026-03-22

## 1. 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│  入口层                                                      │
│  scripts/e2e_v11b.py (CLI)     app/api/v1/workflows.py (API) │
└──────────────┬─────────────────────────┬────────────────────┘
               │                         │
               ▼                         ▼
┌─────────────────────────────────────────────────────────────┐
│  工作流引擎 (app/workflows/)                                  │
│                                                              │
│  registry.py ─── get_workflow("narration_manga")             │
│       ↓                                                      │
│  base.py ─── BaseWorkflow + WorkflowContext                  │
│       ↓                                                      │
│  templates/                                                  │
│    ├── narration_manga.py   (旁白漫剧, 9 Stages)             │
│    └── ...                  (未来模板)                        │
└──────────────┬───────────────────────────────────────────────┘
               │ 各 Stage 按需调用
               ▼
┌─────────────────────────────────────────────────────────────┐
│  能力层（所有模板共享）                                        │
│                                                              │
│  ┌───────────────┐  ┌───────────────┐  ┌─────────────────┐  │
│  │ AI Providers   │  │ AI Tools      │  │ Services        │  │
│  │               │  │               │  │                 │  │
│  │ vendor/qwen/  │  │ duration_     │  │ ffmpeg_utils    │  │
│  │ vendor/jimeng/│  │ planner.py    │  │ narration_utils │  │
│  │ vendor/kling/ │  │               │  │ storage/        │  │
│  │ vendor/sora2/ │  │               │  │                 │  │
│  │ minimax_tts   │  │               │  │                 │  │
│  └───────────────┘  └───────────────┘  └─────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## 2. 目录结构

```
text2video/
├── scripts/
│   └── e2e_v11b.py              # CLI（run/review/edit/reroll/select 子命令）
│
├── app/
│   ├── workflows/               # 工作流引擎
│   │   ├── base.py              # BaseWorkflow 基类 + WorkflowContext 上下文
│   │   ├── registry.py          # 模板注册表（@register_workflow 装饰器）
│   │   ├── candidates.py        # CandidateManager（候选项管理 + 失效级联）
│   │   ├── interactive.py       # InteractiveOpsMixin（review/edit/reroll/select）
│   │   └── templates/
│   │       └── narration_manga.py  # 旁白漫剧模板（9 Stages）
│   │
│   ├── ai/
│   │   ├── pipeline.py          # DAG 编排器（服务端异步任务用）
│   │   ├── duration_planner.py  # TTS 驱动时长规划器（4 Cases）
│   │   ├── prompts/             # Prompt 模板
│   │   ├── providers/           # AI 服务封装（minimax_tts, kling, jimeng 等）
│   │   └── worker.py            # arq 异步任务 worker
│   │
│   ├── api/v1/                  # REST API
│   │   ├── workflows.py         # 工作流 API（列表、执行）
│   │   ├── projects.py          # 项目管理
│   │   ├── storyboards.py       # 分镜管理
│   │   ├── shots.py             # 镜头管理
│   │   ├── tts.py               # TTS
│   │   ├── videos.py            # 视频生成
│   │   └── assembly.py          # 组装
│   │
│   ├── services/                # 通用业务服务
│   │   ├── ffmpeg_utils.py      # FFmpeg 工具（对齐、拼接、字幕、BGM）
│   │   ├── narration_utils.py   # 旁白工具（TTS 时长估算、LLM 压缩）
│   │   └── ...
│   │
│   ├── models/                  # SQLAlchemy 数据模型
│   ├── repositories/            # 数据库 CRUD
│   ├── storage/                 # 文件存储（本地 / OSS）
│   └── main.py                  # FastAPI 入口
│
├── vendor/                      # 外部 AI 服务客户端
│   ├── qwen/                    # 阿里云 Qwen 3.5-Plus（LLM）
│   ├── jimeng/                  # 字节即梦（文生图 T2I）
│   ├── kling/                   # 快手可灵（图生视频 I2V）
│   └── sora2/                   # OpenAI Sora 2（备选视频生成）
│
├── data/
│   ├── test_novel.txt           # 测试小说文本
│   └── bgm/                    # 背景音乐库
│
├── docs/                        # 文档
│   ├── architecture.md          # 本文档
│   └── development-plan.md      # 开发计划
│
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml
```

## 3. 各层职责

### 3.1 入口层

| 入口 | 用途 | 调用方式 |
|---|---|---|
| `scripts/e2e_v11b.py` | 命令行端到端运行 | `python scripts/e2e_v11b.py --workflow narration_manga --output e2e_output/v13` |
| `app/api/v1/workflows.py` | REST API，供 Web UI 调用 | `POST /api/v1/workflows/run` |

### 3.2 工作流引擎层

| 模块 | 职责 |
|---|---|
| `base.py` | 定义 `BaseWorkflow`（Stage 执行框架）和 `WorkflowContext`（Stage 间数据传递） |
| `registry.py` | `@register_workflow` 装饰器 + `get_workflow(name)` 查找 + `list_workflows()` 列表 |
| `templates/*.py` | 具体模板实现，每个模板定义自己的 Stage 序列和每个 Stage 的逻辑 |

**核心设计**: 模板决定"做什么、什么顺序"，能力层提供"怎么做"。

### 3.3 能力层

| 模块 | 能力 | 被哪些模板使用 |
|---|---|---|
| `vendor/qwen/` | LLM（分镜、旁白压缩、单镜头重生成） | 所有需要 LLM 的模板 |
| `vendor/jimeng/` | 文生图 T2I（角色参考、场景、首帧） | narration_manga |
| `vendor/kling/` | 图生视频 I2V（Kling V3, subject_reference） | narration_manga |
| `vendor/sora2/` | 文生视频（Sora 2, 备选） | 可在任何模板中替换 Kling |
| `minimax_tts` | TTS 语音合成（情感标签） | 所有需要旁白的模板 |
| `duration_planner.py` | TTS 驱动子镜头时长规划 | narration_manga |
| `ffmpeg_utils.py` | 视频对齐、拼接、字幕烧录、BGM 叠加 | 所有需要组装的模板 |

## 4. 旁白漫剧模板（narration_manga）

### 4.1 九阶段流程

```
输入: 小说文本 + 参数(duration, voice)
  │
  ▼
Stage 1: storyboard ─── Qwen LLM → 分镜脚本
  │                      输出: segments(含 sub_shots) + characters + scenes
  ▼
Stage 2: tts ────────── MiniMax TTS → 每段旁白音频
  │                      输出: 真实 TTS 时长（秒）
  ▼
Stage 3: duration_plan ─ TTS 时长驱动子镜头时长规划
  │                      Case 1: TTS+1s >= 子镜头总时长 → 不调整
  │                      Case 2: TTS+1s < 总时长 → 等比例缩短(min 3s)
  │                      Case 3: 缩短触及3s下限 → 钉死3s, 缩短其他
  │                      Case 4: 全部3s仍超出 → LLM 重新生成单镜头
  ▼
Stage 4: char_refs ──── Jimeng T2I → 每角色一张参考图(832×1472)
  │
  ▼
Stage 5: scene_bgs ──── Jimeng T2I → 每场景一张背景图(仅审查用)
  │
  ▼
Stage 6: first_frames ─ Jimeng T2I + 末尾帧提取
  │                      场景首段第一个子镜头 → T2I 生成
  │                      其他子镜头 → 上一个子镜头视频的末尾帧
  ▼
Stage 7: video_gen ──── Kling V3 I2V → 每个子镜头视频(动态时长 3-15s)
  │                      输入: 首帧图 + 角色参考图(subject_reference) + motion prompt
  ▼
Stage 8: assembly ───── FFmpeg
  │                      8a: 子镜头拼接 → 段视频
  │                      8b: 段视频 + TTS 对齐
  │                      8c: 所有段拼接
  │                      8d: 字幕烧录
  │                      8e: BGM 叠加
  ▼
Stage 9: quality_gate ─ 检查: 总时长、BGM、视频完整性、场景连续性
  │
  ▼
输出: final_video.mp4
```

### 4.2 数据流（WorkflowContext）

```
storyboard   → ctx.segments, ctx.characters, ctx.scenes
tts          → ctx.tts_paths, ctx.tts_durations
duration_plan → ctx.seg_durations, ctx.all_sub_shots, ctx.all_durations
char_refs    → ctx.char_images
scene_bgs    → ctx.scene_images
first_frames → ctx.sub_shot_plan, ctx.t2i_images
video_gen    → ctx.sub_shot_videos, ctx.total_generated
assembly     → ctx.final_video_path, ctx.final_duration, ctx.final_size_mb
quality_gate → ctx.quality_passed, ctx.quality_issues
```

### 4.3 TTS 驱动时长规划（duration_planner.py）

解决的问题：之前用估算 TTS 时长决定视频时长，实际 TTS 比估算短 2-4s，造成视频浪费。

现在 TTS 先生成，用真实时长反推：

```
target = real_tts_duration + 1.0s（前后各 0.5s 缓冲）

Case 1: target >= N×5s     → 保持原时长（极少出现）
Case 2: target < N×5s      → 等比例缩短，每个子镜头 >= 3s
Case 3: 等比例缩短后有 < 3s → 钉死 3s，缩短其余
Case 4: 全部 3s 仍 > target → 重新生成为单镜头，时长 = target
```

节省约 30% 视频生成量。

## 5. 外部服务

| 服务 | 提供商 | 用途 | 配置位置 |
|---|---|---|---|
| LLM | 阿里云 Qwen 3.5-Plus | 分镜生成、旁白压缩 | `vendor/qwen/config.py` |
| T2I | 字节即梦 | 角色图、场景图、首帧图 | `vendor/jimeng/config.py` |
| I2V（主力） | 快手 Kling V3 | 图生视频，支持 subject_reference | `vendor/kling/config.py` |
| I2V（备选） | OpenAI Sora 2 | 图生视频，支持 4/8/12s | `vendor/sora2/config.py` |
| TTS | MiniMax | 情感旁白语音合成 | `app/ai/providers/minimax_tts.py` |
| 视频处理 | FFmpeg（本地） | 对齐、拼接、字幕、BGM | 无需配置 |

> 注意: 所有 `vendor/*/config.py` 包含 API Key，已在 `.gitignore` 中排除。

## 6. 如何增加新模板

以"口播解说短视频"为例，只需 3 步：

### Step 1: 创建模板文件

```python
# app/workflows/templates/talking_head.py

from app.workflows.base import BaseWorkflow, WorkflowContext, StageResult
from app.workflows.registry import register_workflow

@register_workflow
class TalkingHeadWorkflow(BaseWorkflow):
    name = "talking_head"
    display_name = "口播解说"
    stages = [
        "script",        # LLM 生成解说稿
        "avatar_gen",    # 数字人形象生成
        "tts",           # TTS 语音合成
        "lipsync",       # 口型同步视频
        "assembly",      # 组装
    ]

    def stage_script(self, ctx: WorkflowContext) -> StageResult:
        # 调用 vendor/qwen，用不同的 Prompt 生成解说稿
        ...
        return StageResult(success=True)

    def stage_avatar_gen(self, ctx: WorkflowContext) -> StageResult:
        ...
        return StageResult(success=True)

    def stage_tts(self, ctx: WorkflowContext) -> StageResult:
        # 复用 minimax_tts
        ...
        return StageResult(success=True)

    def stage_lipsync(self, ctx: WorkflowContext) -> StageResult:
        ...
        return StageResult(success=True)

    def stage_assembly(self, ctx: WorkflowContext) -> StageResult:
        # 复用 ffmpeg_utils
        ...
        return StageResult(success=True)
```

### Step 2: 注册（添加一行 import）

```python
# app/workflows/__init__.py
from .templates import narration_manga  # 已有
from .templates import talking_head     # 新增
```

### Step 3: 使用

```bash
# CLI
python scripts/e2e_v11b.py --workflow talking_head --input data/script.txt

# API（自动可用）
# GET  /api/v1/workflows/     → 列出所有模板
# POST /api/v1/workflows/run  → {"workflow": "talking_head", ...}
```

不需要改动 base.py、registry.py、e2e_v11b.py、router.py 或任何 vendor/service 代码。

## 7. 交互操作（Review / Edit / Reroll / Select）

### 7.1 架构

```
Agent / Web UI
    ↓ CLI 子命令 或 REST API
┌─────────────────────────────────┐
│ InteractiveOpsMixin             │
│  op_review_*  → 读取状态        │
│  op_edit_*    → 编辑分镜        │
│  op_reroll_*  → 生成新候选项    │
│  op_select    → 选择候选项      │
└──────────┬──────────────────────┘
           ↓
┌─────────────────────────────────┐
│ CandidateManager                │
│  candidates.json                │
│  - 每个资产多个候选项           │
│  - 当前选择跟踪                 │
│  - 失效级联                     │
└─────────────────────────────────┘
```

### 7.2 candidates.json 结构

```json
{
  "assets": {
    "char_ref:char_001": {
      "candidates": [
        {"version": 1, "path": "characters/charref_char_001_v1_0.png"},
        {"version": 2, "path": "characters/charref_char_001_v2_0.png"}
      ],
      "selected": 2
    },
    "video:seg01_sub01": { ... },
    "tts:1": { ... }
  },
  "invalidated": ["tts:2", "video:seg02_sub01"]
}
```

### 7.3 CLI 子命令

```bash
# 执行流程
e2e_v11b.py run --output dir --duration 40
e2e_v11b.py run --output dir --stop-after-stage storyboard

# 审查
e2e_v11b.py review storyboard --output dir --json
e2e_v11b.py review tts --output dir --json
e2e_v11b.py review char_refs --output dir --json
e2e_v11b.py review videos --output dir --json
e2e_v11b.py review status --output dir --json

# 编辑分镜
e2e_v11b.py edit storyboard --output dir --segment 2 --field narration_text --value "新旁白"
e2e_v11b.py edit storyboard --output dir --segment 1 --field video_prompt --sub 2 --value "新动作"

# 抽卡（生成新候选项）
e2e_v11b.py reroll char_ref --output dir --char char_001
e2e_v11b.py reroll video --output dir --seg 1 --sub 1
e2e_v11b.py reroll tts --output dir --seg 2 --emotion angry

# 选择候选项
e2e_v11b.py select char_ref --output dir --char char_001 --candidate 2
e2e_v11b.py select video --output dir --seg 1 --sub 1 --candidate 2

# 列出候选项
e2e_v11b.py list-candidates char_ref --output dir --char char_001 --json
```

所有命令加 `--json` 输出 JSON（供 Agent 消费）。

### 7.4 编辑后的失效级联

| 编辑内容 | 自动失效的下游资产 |
|---|---|
| `narration_text` | 该段 TTS + 该段所有视频 |
| `emotion` | 该段 TTS |
| `image_prompt` | 该段首帧图 |
| `video_prompt`（子镜头） | 对应视频 |
| `appearance_prompt` | 角色参考图 + 引用该角色的所有视频 |
| 选择新角色参考图 | 引用该角色的所有视频 |
| 选择新首帧图 | 对应视频 |

失效资产在下次 `run` 时自动重新生成。

### 7.5 Agent 工作流示例

```bash
# 1. 跑到分镜
e2e_v11b.py run --output dir --stop-after-stage storyboard

# 2. Agent 审查
e2e_v11b.py review storyboard --output dir --json

# 3. Agent 改旁白
e2e_v11b.py edit storyboard --output dir --segment 2 --field narration_text --value "更好的旁白"

# 4. 继续跑到图片
e2e_v11b.py run --output dir --stop-after-stage char_refs

# 5. Agent 抽卡
e2e_v11b.py reroll char_ref --output dir --char char_002
e2e_v11b.py reroll char_ref --output dir --char char_002

# 6. Agent 选择
e2e_v11b.py list-candidates char_ref --output dir --char char_002 --json
e2e_v11b.py select char_ref --output dir --char char_002 --candidate 2

# 7. 跑完
e2e_v11b.py run --output dir
```

## 8. 设计原则

1. **模板决定"做什么"，能力层提供"怎么做"** — 不同模板可以有完全不同的 Stage 序列，但复用相同的 AI 服务和工具函数
2. **WorkflowContext 是唯一的数据通道** — Stage 之间不通过全局变量或文件约定传递数据，全部通过 Context 对象
3. **Stage 方法可独立测试** — 每个 `stage_xxx` 接收 Context、返回 StageResult，可以单独 mock 测试
4. **注册即可用** — `@register_workflow` 装饰器 + 一行 import，CLI 和 API 都自动识别新模板
5. **TTS 驱动时长** — 真实音频时长决定视频时长，而非估算值，避免资源浪费
6. **断点恢复** — 每个 Stage 检查已有输出（通过 CandidateManager），跳过已完成部分，崩溃后重跑不浪费
7. **run 是批量，ops 是交互** — `run` 自动执行全流程，交互操作是独立子命令，不互相干扰
8. **候选项持久化** — 所有抽卡结果保留，不覆盖，用户可以随时切换选择

## 8. 技术栈

| 层 | 技术 |
|---|---|
| 语言 | Python 3.11+ |
| Web 框架 | FastAPI (async) |
| 数据库 | PostgreSQL 15 (JSONB) |
| 任务队列 | Redis 7 + arq |
| 存储 | 本地文件系统 / 阿里云 OSS |
| 容器化 | Docker + docker-compose |
| 视频处理 | FFmpeg |
