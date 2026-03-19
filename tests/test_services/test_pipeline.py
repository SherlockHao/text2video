"""Tests for PipelineOrchestrator."""

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from app.ai.pipeline import PipelineOrchestrator, PipelineStage, StageStatus


def test_from_project_data_empty():
    """Orchestrator with no shots should have no stage data."""
    orch = PipelineOrchestrator.from_project_data(
        project_id="test-id", shots=[], tasks=[]
    )
    assert orch.get_overall_progress() == 0.0
    assert not orch.is_complete()
    assert orch.get_failed_stages() == []
    # With no stages set, script_breakdown should be the first ready stage
    assert PipelineStage.SCRIPT_BREAKDOWN in orch.get_next_stages()


def test_from_project_data_partial():
    """Orchestrator with partially completed shots."""
    # Create mock shots
    shots = [
        MagicMock(image_status="completed", tts_status="completed", video_status="pending"),
        MagicMock(image_status="completed", tts_status="failed", video_status="pending"),
    ]
    tasks = []

    orch = PipelineOrchestrator.from_project_data(
        project_id="test-id", shots=shots, tasks=tasks
    )

    assert not orch.is_complete()
    assert orch.get_overall_progress() > 0.0

    pipeline = orch.get_pipeline_dict()

    # Script breakdown is complete (we have shots)
    assert pipeline["script_breakdown"]["is_complete"] is True

    # Image generation: 2/2 completed
    assert pipeline["image_generation"]["completed"] == 2
    assert pipeline["image_generation"]["is_complete"] is True

    # TTS: 1/2 completed, 1 failed
    assert pipeline["tts_generation"]["completed"] == 1
    assert pipeline["tts_generation"]["failed"] == 1
    assert pipeline["tts_generation"]["is_complete"] is False

    # Video: 0/2 completed
    assert pipeline["video_generation"]["completed"] == 0
    assert pipeline["video_generation"]["is_complete"] is False

    # Assembly: not started
    assert pipeline["assembly"]["total"] == 0

    # TTS should be in failed stages
    failed = orch.get_failed_stages()
    assert PipelineStage.TTS_GENERATION in failed


def test_from_project_data_complete():
    """Orchestrator with all stages complete."""
    shots = [
        MagicMock(
            image_status="completed", tts_status="completed", video_status="completed"
        ),
        MagicMock(
            image_status="completed", tts_status="completed", video_status="completed"
        ),
    ]
    tasks = [
        MagicMock(task_type="assembly", status="completed"),
    ]

    orch = PipelineOrchestrator.from_project_data(
        project_id="test-id", shots=shots, tasks=tasks
    )

    assert orch.is_complete()
    assert orch.get_overall_progress() == 1.0
    assert orch.get_failed_stages() == []

    pipeline = orch.get_pipeline_dict()
    for stage_name, stage_info in pipeline.items():
        assert stage_info["is_complete"] is True


def test_can_start_stage_dependencies():
    """can_start_stage should respect the dependency graph."""
    orch = PipelineOrchestrator("test-id")

    # Script breakdown has no deps, always startable
    assert orch.can_start_stage(PipelineStage.SCRIPT_BREAKDOWN) is True

    # Image gen depends on script breakdown — not started yet
    assert orch.can_start_stage(PipelineStage.IMAGE_GENERATION) is False

    # Complete script breakdown
    orch.update_stage(PipelineStage.SCRIPT_BREAKDOWN, StageStatus(
        stage=PipelineStage.SCRIPT_BREAKDOWN,
        total_tasks=1, completed_tasks=1, is_complete=True,
    ))

    # Now image gen should be startable
    assert orch.can_start_stage(PipelineStage.IMAGE_GENERATION) is True
    # TTS also depends only on script breakdown
    assert orch.can_start_stage(PipelineStage.TTS_GENERATION) is True

    # Video gen depends on image gen — not started
    assert orch.can_start_stage(PipelineStage.VIDEO_GENERATION) is False

    # Assembly depends on video + TTS — neither complete
    assert orch.can_start_stage(PipelineStage.ASSEMBLY) is False

    # Complete image gen
    orch.update_stage(PipelineStage.IMAGE_GENERATION, StageStatus(
        stage=PipelineStage.IMAGE_GENERATION,
        total_tasks=2, completed_tasks=2, is_complete=True,
    ))
    assert orch.can_start_stage(PipelineStage.VIDEO_GENERATION) is True

    # Still can't start assembly (TTS not done, video not done)
    assert orch.can_start_stage(PipelineStage.ASSEMBLY) is False

    # Complete TTS and video
    orch.update_stage(PipelineStage.TTS_GENERATION, StageStatus(
        stage=PipelineStage.TTS_GENERATION,
        total_tasks=2, completed_tasks=2, is_complete=True,
    ))
    orch.update_stage(PipelineStage.VIDEO_GENERATION, StageStatus(
        stage=PipelineStage.VIDEO_GENERATION,
        total_tasks=2, completed_tasks=2, is_complete=True,
    ))
    assert orch.can_start_stage(PipelineStage.ASSEMBLY) is True


def test_is_complete():
    """is_complete should only be True when all stages are complete."""
    orch = PipelineOrchestrator("test-id")

    assert not orch.is_complete()

    # Complete all stages
    for stage in PipelineStage:
        orch.update_stage(stage, StageStatus(
            stage=stage, total_tasks=1, completed_tasks=1, is_complete=True,
        ))

    assert orch.is_complete()


def test_get_failed_stages():
    """get_failed_stages should return only stages with is_failed=True."""
    orch = PipelineOrchestrator("test-id")

    assert orch.get_failed_stages() == []

    orch.update_stage(PipelineStage.IMAGE_GENERATION, StageStatus(
        stage=PipelineStage.IMAGE_GENERATION,
        total_tasks=2, completed_tasks=1, failed_tasks=1, is_failed=True,
    ))
    orch.update_stage(PipelineStage.TTS_GENERATION, StageStatus(
        stage=PipelineStage.TTS_GENERATION,
        total_tasks=2, completed_tasks=2, is_complete=True,
    ))

    failed = orch.get_failed_stages()
    assert len(failed) == 1
    assert PipelineStage.IMAGE_GENERATION in failed
