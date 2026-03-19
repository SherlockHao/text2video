"""
Pipeline orchestrator for video production workflow.

Manages the DAG of tasks for a project:
  ScriptBreakdown -> (ImageGen || TTS) -> VideoGen -> Assembly

Phase 0: Skeleton only. Full implementation in Phase 7.
"""

import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class PipelineStage(str, Enum):
    SCRIPT_BREAKDOWN = "script_breakdown"
    IMAGE_GENERATION = "image_generation"
    TTS_GENERATION = "tts_generation"
    VIDEO_GENERATION = "video_generation"
    ASSEMBLY = "assembly"


# Stage dependency graph
STAGE_DEPENDENCIES: dict[PipelineStage, list[PipelineStage]] = {
    PipelineStage.SCRIPT_BREAKDOWN: [],
    PipelineStage.IMAGE_GENERATION: [PipelineStage.SCRIPT_BREAKDOWN],
    PipelineStage.TTS_GENERATION: [PipelineStage.SCRIPT_BREAKDOWN],
    PipelineStage.VIDEO_GENERATION: [PipelineStage.IMAGE_GENERATION],
    PipelineStage.ASSEMBLY: [PipelineStage.VIDEO_GENERATION, PipelineStage.TTS_GENERATION],
}


@dataclass
class StageStatus:
    stage: PipelineStage
    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    is_complete: bool = False
    is_failed: bool = False

    @property
    def progress(self) -> float:
        if self.total_tasks == 0:
            return 0.0
        return self.completed_tasks / self.total_tasks


class PipelineOrchestrator:
    """
    Orchestrates the video production pipeline for a project.

    Skeleton implementation — will be fully built in Phase 7.
    """

    def __init__(self, project_id: str):
        self.project_id = project_id
        self._stages: dict[PipelineStage, StageStatus] = {}

    def can_start_stage(self, stage: PipelineStage) -> bool:
        """Check if all dependencies for a stage are completed."""
        deps = STAGE_DEPENDENCIES.get(stage, [])
        return all(
            self._stages.get(dep, StageStatus(stage=dep)).is_complete
            for dep in deps
        )

    def get_next_stages(self) -> list[PipelineStage]:
        """Get stages that are ready to start."""
        ready = []
        for stage in PipelineStage:
            status = self._stages.get(stage)
            if status is None and self.can_start_stage(stage):
                ready.append(stage)
            elif status and not status.is_complete and not status.is_failed:
                # Stage in progress, don't start new ones in same track
                pass
        return ready

    def get_overall_progress(self) -> float:
        """Get overall pipeline progress (0.0 to 1.0)."""
        if not self._stages:
            return 0.0
        total_weight = len(PipelineStage)
        completed_weight = sum(
            1 for s in self._stages.values() if s.is_complete
        )
        return completed_weight / total_weight
