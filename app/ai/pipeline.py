"""
Pipeline orchestrator for video production workflow.

Manages the DAG of tasks for a project:
  ScriptBreakdown -> (ImageGen || TTS) -> VideoGen -> Assembly
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
    """Orchestrates the video production pipeline for a project."""

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

    def update_stage(self, stage: PipelineStage, status: StageStatus) -> None:
        """Update a stage's status."""
        self._stages[stage] = status

    def is_complete(self) -> bool:
        """True if all stages are complete."""
        return all(
            self._stages.get(s, StageStatus(stage=s)).is_complete
            for s in PipelineStage
        )

    def get_failed_stages(self) -> list[PipelineStage]:
        """Get stages that have failed tasks."""
        return [
            s for s, st in self._stages.items() if st.is_failed
        ]

    def get_pipeline_dict(self) -> dict:
        """Return pipeline state as a serializable dict."""
        result = {}
        for stage in PipelineStage:
            status = self._stages.get(stage, StageStatus(stage=stage))
            result[stage.value] = {
                "total": status.total_tasks,
                "completed": status.completed_tasks,
                "failed": status.failed_tasks,
                "progress": status.progress,
                "is_complete": status.is_complete,
            }
        return result

    @classmethod
    def from_project_data(
        cls, project_id: str, shots: list, tasks: list
    ) -> "PipelineOrchestrator":
        """Build orchestrator state from DB data (shots + tasks).

        Analyzes shot statuses and task statuses to reconstruct pipeline state.
        """
        orch = cls(project_id)

        if not shots:
            return orch

        total_shots = len(shots)

        # Script breakdown — complete if we have shots at all
        orch.update_stage(PipelineStage.SCRIPT_BREAKDOWN, StageStatus(
            stage=PipelineStage.SCRIPT_BREAKDOWN,
            total_tasks=1, completed_tasks=1, is_complete=True,
        ))

        # Image generation
        img_completed = sum(1 for s in shots if s.image_status == "completed")
        img_failed = sum(1 for s in shots if s.image_status == "failed")
        orch.update_stage(PipelineStage.IMAGE_GENERATION, StageStatus(
            stage=PipelineStage.IMAGE_GENERATION,
            total_tasks=total_shots,
            completed_tasks=img_completed,
            failed_tasks=img_failed,
            is_complete=img_completed == total_shots,
            is_failed=img_failed > 0,
        ))

        # TTS generation
        tts_completed = sum(1 for s in shots if s.tts_status == "completed")
        tts_failed = sum(1 for s in shots if s.tts_status == "failed")
        orch.update_stage(PipelineStage.TTS_GENERATION, StageStatus(
            stage=PipelineStage.TTS_GENERATION,
            total_tasks=total_shots,
            completed_tasks=tts_completed,
            failed_tasks=tts_failed,
            is_complete=tts_completed == total_shots,
            is_failed=tts_failed > 0,
        ))

        # Video generation
        vid_completed = sum(1 for s in shots if s.video_status == "completed")
        vid_failed = sum(1 for s in shots if s.video_status == "failed")
        orch.update_stage(PipelineStage.VIDEO_GENERATION, StageStatus(
            stage=PipelineStage.VIDEO_GENERATION,
            total_tasks=total_shots,
            completed_tasks=vid_completed,
            failed_tasks=vid_failed,
            is_complete=vid_completed == total_shots,
            is_failed=vid_failed > 0,
        ))

        # Assembly — check from tasks
        assembly_tasks = [t for t in tasks if t.task_type == "assembly"]
        asm_complete = any(t.status == "completed" for t in assembly_tasks)
        asm_failed = any(t.status == "failed" for t in assembly_tasks)
        orch.update_stage(PipelineStage.ASSEMBLY, StageStatus(
            stage=PipelineStage.ASSEMBLY,
            total_tasks=1 if assembly_tasks else 0,
            completed_tasks=1 if asm_complete else 0,
            failed_tasks=1 if asm_failed else 0,
            is_complete=asm_complete,
            is_failed=asm_failed and not asm_complete,
        ))

        return orch
