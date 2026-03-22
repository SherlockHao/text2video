"""
E2E runner — 调用 Workflow 模板引擎执行端到端视频生成

Usage:
  python scripts/e2e_v11b.py --duration 40 --output e2e_output/v13
  python scripts/e2e_v11b.py --workflow narration_manga --stop-after-stage tts
"""

import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.workflows import get_workflow

parser = argparse.ArgumentParser(description="E2E Video Generation Runner")
parser.add_argument("--workflow", type=str, default="narration_manga",
                    help="Workflow template name")
parser.add_argument("--duration", type=int, default=40,
                    help="Target video duration in seconds")
parser.add_argument("--voice", type=str, default="female-shaonv",
                    help="TTS voice ID")
parser.add_argument("--output", type=str, default="e2e_output/v11b",
                    help="Output directory")
parser.add_argument("--input", type=str, default="data/test_novel.txt",
                    help="Input text file")
parser.add_argument("--stop-after-stage", type=str, default=None,
                    help="Stop after this stage (e.g. 'tts', 'duration_plan', 'video_gen')")
parser.add_argument("--stop-after-segment", type=int, default=None,
                    help="Stop video_gen after this segment number")
parser.add_argument("--list-workflows", action="store_true",
                    help="List available workflow templates")
args = parser.parse_args()

if args.list_workflows:
    from app.workflows.registry import list_workflows
    for wf in list_workflows():
        print(f"  {wf['name']:20s} {wf['display_name']}")
        print(f"    stages: {' → '.join(wf['stages'])}")
    sys.exit(0)

# 读取输入文本
with open(args.input) as f:
    input_text = f.read()

# 获取工作流
workflow = get_workflow(args.workflow)

# 构建参数
params = {
    "duration": args.duration,
    "voice": args.voice,
}
if args.stop_after_segment:
    params["stop_after_segment"] = args.stop_after_segment

# 执行
ctx = workflow.run(
    input_text=input_text,
    output_dir=args.output,
    params=params,
    stop_after_stage=args.stop_after_stage,
)

# 退出码
sys.exit(0 if ctx.quality_passed or ctx.final_video_path else 1)
