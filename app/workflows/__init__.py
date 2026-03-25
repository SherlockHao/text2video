"""
Workflow engine — 工作流模板化引擎

每种视频类型（旁白漫剧、口播解说等）是一个 Workflow 模板，
定义自己的 Stage 序列、Prompt 策略和时长规划逻辑。
支持交互操作：review/edit/reroll/select。
"""

from .base import BaseWorkflow, WorkflowContext, StageResult
from .registry import get_workflow, list_workflows
from .candidates import CandidateManager

# 导入模板以触发注册
from .templates import narration_manga  # noqa: F401
from .templates import dialogue_manga   # noqa: F401
