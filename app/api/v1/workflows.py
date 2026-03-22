"""
Workflow API — 工作流模板管理和执行
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.workflows.registry import list_workflows, get_workflow

router = APIRouter(prefix="/workflows", tags=["workflows"])


class WorkflowRunRequest(BaseModel):
    workflow: str = "narration_manga"
    input_text: str
    duration: int = 40
    voice: str = "female-shaonv"
    output_dir: str = "e2e_output/default"


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
    ctx = wf.run(
        input_text=req.input_text,
        output_dir=req.output_dir,
        params=params,
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
