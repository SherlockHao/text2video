"""
工作流基类 — 定义 Stage 接口和执行框架
"""

import json
import os
import time
import logging
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .candidates import CandidateManager

logger = logging.getLogger(__name__)


@dataclass
class StageResult:
    """单个 Stage 的执行结果。"""
    success: bool
    message: str = ""
    data: dict = field(default_factory=dict)


@dataclass
class WorkflowContext:
    """
    工作流上下文 — 在 Stage 之间传递数据。
    每个 Stage 读取并写入 context，下一个 Stage 可以使用前面的输出。
    """
    # 输入
    input_text: str = ""
    params: dict = field(default_factory=dict)
    output_dir: str = ""

    # Stage 1: LLM 分镜输出
    storyboard: dict = field(default_factory=dict)
    segments: list = field(default_factory=list)
    characters: list = field(default_factory=list)
    scenes: list = field(default_factory=list)

    # Stage 2: TTS
    tts_paths: dict = field(default_factory=dict)       # seg_number → audio path
    tts_durations: dict = field(default_factory=dict)    # seg_number → duration (seconds)

    # Stage 3: Duration planning
    seg_durations: dict = field(default_factory=dict)    # seg_number → [sub_shot_dur, ...]
    all_sub_shots: list = field(default_factory=list)    # [(seg_idx, sub_idx, seg, sub)]
    all_durations: list = field(default_factory=list)    # 与 all_sub_shots 对应的时长

    # Stage 4-5: 图片
    char_images: dict = field(default_factory=dict)      # char_id → image path
    scene_images: dict = field(default_factory=dict)     # scene_id → image path

    # Stage 6: 首帧
    sub_shot_plan: list = field(default_factory=list)    # "t2i" or "last_frame"
    t2i_images: dict = field(default_factory=dict)       # global_index → image path

    # Stage 7: 视频
    sub_shot_videos: dict = field(default_factory=dict)  # global_index → video path
    total_generated: int = 0

    # Stage 8: 组装
    final_video_path: str = ""
    final_duration: float = 0.0
    final_size_mb: float = 0.0

    # Stage 9: 质量检测
    quality_issues: list = field(default_factory=list)
    quality_passed: bool = False

    # 候选项管理
    candidates: Any = None  # CandidateManager instance

    # 执行状态
    current_stage: str = ""
    completed_stages: list = field(default_factory=list)
    stage_timings: dict = field(default_factory=dict)    # stage_name → seconds

    def log(self, msg):
        print(msg, flush=True)
        logger.info(msg)


class BaseWorkflow:
    """
    工作流基类。

    子类需要:
    1. 设置 name, display_name, stages
    2. 实现每个 stage_xxx 方法
    """

    name: str = "base"
    display_name: str = "Base Workflow"
    stages: list[str] = []

    def __init__(self):
        self._stage_methods = {}
        # 自动注册以 stage_ 开头的方法
        for attr_name in dir(self):
            if attr_name.startswith("stage_"):
                stage_name = attr_name[6:]  # 去掉 "stage_" 前缀
                self._stage_methods[stage_name] = getattr(self, attr_name)

    def run(self, input_text: str, output_dir: str, params: dict = None,
            stop_after_stage: str = None) -> WorkflowContext:
        """
        执行完整工作流。

        Args:
            input_text: 输入文本（小说、脚本等）
            output_dir: 输出目录
            params: 参数（duration, voice 等）
            stop_after_stage: 在指定 stage 后停止

        Returns:
            WorkflowContext: 最终上下文
        """
        from .candidates import CandidateManager

        params = params or {}
        ctx = WorkflowContext(
            input_text=input_text,
            params=params,
            output_dir=output_dir,
        )

        # 创建输出子目录
        for d in self.get_output_subdirs():
            os.makedirs(f"{output_dir}/{d}", exist_ok=True)

        # 初始化候选项管理器
        ctx.candidates = CandidateManager(output_dir)
        ctx.candidates.migrate_from_existing(output_dir)

        ctx.log(f"\n{'='*60}")
        ctx.log(f"Workflow: {self.display_name} ({self.name})")
        ctx.log(f"Output: {output_dir}")
        ctx.log(f"Stages: {' → '.join(self.stages)}")
        ctx.log(f"{'='*60}")

        for i, stage_name in enumerate(self.stages):
            method = self._stage_methods.get(stage_name)
            if method is None:
                ctx.log(f"\n⚠ Stage '{stage_name}' not implemented, skipping")
                continue

            ctx.current_stage = stage_name
            ctx.log(f"\n[Stage {i+1}/{len(self.stages)}] {stage_name}...")
            start = time.time()

            try:
                result = method(ctx)
                elapsed = time.time() - start
                ctx.stage_timings[stage_name] = elapsed

                if result and not result.success:
                    ctx.log(f"  ✗ Stage '{stage_name}' failed: {result.message}")
                    break

                ctx.completed_stages.append(stage_name)
                ctx.log(f"  Stage '{stage_name}' completed ({elapsed:.1f}s)")

            except Exception as e:
                elapsed = time.time() - start
                ctx.stage_timings[stage_name] = elapsed
                ctx.log(f"  ✗ Stage '{stage_name}' exception: {e}")
                logger.exception(f"Stage {stage_name} failed")
                break

            if stop_after_stage and stage_name == stop_after_stage:
                ctx.log(f"\n★ Stopped after stage '{stage_name}'")
                break

        # 输出总结
        total_time = sum(ctx.stage_timings.values())
        ctx.log(f"\n{'='*60}")
        ctx.log(f"Completed {len(ctx.completed_stages)}/{len(self.stages)} stages in {total_time:.0f}s")
        if ctx.final_video_path:
            ctx.log(f"★ {ctx.final_video_path} ({ctx.final_duration:.1f}s, {ctx.final_size_mb:.1f}MB)")
        ctx.log(f"{'='*60}")

        return ctx

    def get_output_subdirs(self) -> list[str]:
        """子类可覆写以定义输出子目录。"""
        return ["images", "scenes", "characters", "videos", "audio",
                "aligned", "frames", "segments"]

    @staticmethod
    def load_context_from_disk(output_dir: str, params: dict = None) -> WorkflowContext:
        """从磁盘重建 WorkflowContext，用于交互操作。"""
        from .candidates import CandidateManager

        ctx = WorkflowContext(output_dir=output_dir, params=params or {})
        ctx.candidates = CandidateManager(output_dir)
        ctx.candidates.migrate_from_existing(output_dir)

        sb_path = os.path.join(output_dir, "storyboard.json")
        if os.path.exists(sb_path):
            with open(sb_path) as f:
                sb = json.load(f)
            ctx.storyboard = sb
            ctx.segments = sb.get("segments", [])
            ctx.characters = sb.get("character_profiles", [])
            ctx.scenes = sb.get("scene_backgrounds", [])

        # 加载 TTS
        for seg in ctx.segments:
            sn = seg["segment_number"]
            p = os.path.join(output_dir, f"audio/seg_{sn:02d}.mp3")
            if os.path.exists(p) and os.path.getsize(p) > 100:
                ctx.tts_paths[sn] = p

        # 加载角色图
        for c in ctx.characters:
            cid = c["char_id"]
            sel = ctx.candidates.get_selected_path(f"char_ref:{cid}")
            if sel and os.path.exists(sel):
                ctx.char_images[cid] = sel

        # 加载场景图
        for sc in ctx.scenes:
            sid = sc["scene_id"]
            sel = ctx.candidates.get_selected_path(f"scene_bg:{sid}")
            if sel and os.path.exists(sel):
                ctx.scene_images[sid] = sel

        return ctx
