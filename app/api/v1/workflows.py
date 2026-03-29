"""
Workflow API — 工作流模板管理和执行 + 交互操作（review/reroll）
"""

import os

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

from app.workflows.registry import list_workflows, get_workflow

router = APIRouter(prefix="/workflows", tags=["workflows"])


# ================================================================
# Request models
# ================================================================

class WorkflowRunRequest(BaseModel):
    workflow: str = "narration_manga"
    input_text: str
    duration: int = 40
    voice: str = "Serena"
    output_dir: str = "e2e_output/default"
    stop_after_stage: Optional[str] = None
    stop_after_segment: Optional[int] = None


class RerollCharRefRequest(BaseModel):
    char_id: str


class RerollSceneBgRequest(BaseModel):
    scene_id: str


class RerollFrameRequest(BaseModel):
    unit_number: int
    frame_number: int


class RerollVideoSegmentRequest(BaseModel):
    unit_number: int
    segment_number: int


class RerollDialogueTTSRequest(BaseModel):
    unit_number: int
    segment_number: int
    voice_id: Optional[str] = None


class RerollNarrationTTSRequest(BaseModel):
    unit_number: int
    segment_number: int
    voice_id: Optional[str] = None


# ================================================================
# Workflow listing & execution
# ================================================================

@router.get("/")
async def list_available_workflows():
    """列出所有可用的工作流模板。"""
    return {"workflows": list_workflows()}


@router.post("/run")
async def run_workflow(req: WorkflowRunRequest):
    """
    同步执行工作流（适合开发调试）。
    生产环境应改为异步任务。
    """
    try:
        wf = get_workflow(req.workflow)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    params = {"duration": req.duration, "voice": req.voice}
    if req.stop_after_segment is not None:
        params["stop_after_segment"] = req.stop_after_segment

    ctx = wf.run(
        input_text=req.input_text,
        output_dir=req.output_dir,
        params=params,
        stop_after_stage=req.stop_after_stage,
    )

    return {
        "workflow": req.workflow,
        "completed_stages": ctx.completed_stages,
        "final_video": ctx.final_video_path,
        "final_duration": ctx.final_duration,
        "quality_passed": ctx.quality_passed,
        "quality_issues": ctx.quality_issues,
        "stage_timings": ctx.stage_timings,
    }


# ================================================================
# Review endpoints
# ================================================================

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
ALLOWED_OUTPUT_BASE = os.path.join(_PROJECT_ROOT, "e2e_output")


def _get_wf(workflow: str):
    try:
        return get_workflow(workflow)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


def _safe_output_dir(output_dir: str) -> str:
    """校验 output_dir 防止路径遍历，返回安全的绝对路径。"""
    resolved = os.path.abspath(output_dir)
    if not resolved.startswith(ALLOWED_OUTPUT_BASE):
        raise HTTPException(status_code=400, detail=f"output_dir must be under {ALLOWED_OUTPUT_BASE}")
    return resolved


def _require_op(wf, method_name: str):
    """检查 workflow 是否支持指定操作。"""
    if not hasattr(wf, method_name):
        raise HTTPException(status_code=400,
                            detail=f"Workflow '{wf.name}' does not support '{method_name}'")


@router.get("/{workflow}/review/storyboard")
async def review_storyboard(workflow: str,
                             output_dir: str = Query(..., description="工作流输出目录")):
    """返回分镜脚本摘要。"""
    wf = _get_wf(workflow)
    return wf.op_review_storyboard(_safe_output_dir(output_dir))


@router.get("/{workflow}/review/status")
async def review_status(workflow: str,
                        output_dir: str = Query(..., description="工作流输出目录")):
    """返回整体进度状态。"""
    wf = _get_wf(workflow)
    return wf.op_review_status(_safe_output_dir(output_dir))


@router.get("/{workflow}/review/characters")
async def review_characters(workflow: str,
                            output_dir: str = Query(..., description="工作流输出目录")):
    """返回角色资产（参考图 + 音色信息）。"""
    wf = _get_wf(workflow)
    _require_op(wf, "op_review_characters")
    return wf.op_review_characters(_safe_output_dir(output_dir))


@router.get("/{workflow}/review/unit/{unit_number}")
async def review_unit(workflow: str, unit_number: int,
                      output_dir: str = Query(..., description="工作流输出目录")):
    """返回某个 unit 的详细信息。"""
    wf = _get_wf(workflow)
    _require_op(wf, "op_review_unit")
    return wf.op_review_unit(_safe_output_dir(output_dir), unit_number)


@router.get("/{workflow}/review/assets")
async def review_assets(workflow: str,
                        asset_type: str = Query(..., description="资产类型: scene_refs/grids/frames/videos"),
                        output_dir: str = Query(..., description="工作流输出目录")):
    """返回指定类型的资产列表。"""
    wf = _get_wf(workflow)
    return wf.op_review_assets(_safe_output_dir(output_dir), asset_type)


# ================================================================
# Reroll endpoints — 对话漫剧特有
# ================================================================

@router.post("/{workflow}/reroll/frame")
async def reroll_frame(workflow: str, req: RerollFrameRequest,
                       output_dir: str = Query(..., description="工作流输出目录")):
    """重新生成单个宫格帧。"""
    wf = _get_wf(workflow)
    if not hasattr(wf, "op_reroll_frame"):
        raise HTTPException(status_code=400, detail=f"Workflow {workflow} does not support frame reroll")
    return wf.op_reroll_frame(_safe_output_dir(output_dir), req.unit_number, req.frame_number)


@router.post("/{workflow}/reroll/video-segment")
async def reroll_video_segment(workflow: str, req: RerollVideoSegmentRequest,
                               output_dir: str = Query(..., description="工作流输出目录")):
    """重新生成视频段。"""
    wf = _get_wf(workflow)
    if not hasattr(wf, "op_reroll_video_segment"):
        raise HTTPException(status_code=400, detail=f"Workflow {workflow} does not support video-segment reroll")
    return wf.op_reroll_video_segment(_safe_output_dir(output_dir), req.unit_number, req.segment_number)


@router.post("/{workflow}/reroll/dialogue-tts")
async def reroll_dialogue_tts(workflow: str, req: RerollDialogueTTSRequest,
                              output_dir: str = Query(..., description="工作流输出目录")):
    """重新生成对话 TTS。"""
    wf = _get_wf(workflow)
    if not hasattr(wf, "op_reroll_dialogue_tts"):
        raise HTTPException(status_code=400, detail=f"Workflow {workflow} does not support dialogue-tts reroll")
    return wf.op_reroll_dialogue_tts(_safe_output_dir(output_dir), req.unit_number, req.segment_number,
                                     voice_id=req.voice_id)


@router.post("/{workflow}/reroll/narration-tts")
async def reroll_narration_tts(workflow: str, req: RerollNarrationTTSRequest,
                               output_dir: str = Query(..., description="工作流输出目录")):
    """重新生成旁白 TTS。"""
    wf = _get_wf(workflow)
    if not hasattr(wf, "op_reroll_narration_tts"):
        raise HTTPException(status_code=400, detail=f"Workflow {workflow} does not support narration-tts reroll")
    return wf.op_reroll_narration_tts(_safe_output_dir(output_dir), req.unit_number, req.segment_number,
                                      voice_id=req.voice_id)


# ================================================================
# Reroll endpoints — 通用（兼容旁白漫剧 + 对话漫剧）
# ================================================================

@router.post("/{workflow}/reroll/char-ref")
async def reroll_char_ref(workflow: str, req: RerollCharRefRequest,
                          output_dir: str = Query(..., description="工作流输出目录")):
    """重新生成角色参考图。"""
    wf = _get_wf(workflow)
    return wf.op_reroll_char_ref(_safe_output_dir(output_dir), req.char_id)


@router.post("/{workflow}/reroll/scene-bg")
async def reroll_scene_bg(workflow: str, req: RerollSceneBgRequest,
                          output_dir: str = Query(..., description="工作流输出目录")):
    """重新生成场景背景图。"""
    wf = _get_wf(workflow)
    return wf.op_reroll_scene_bg(_safe_output_dir(output_dir), req.scene_id)
