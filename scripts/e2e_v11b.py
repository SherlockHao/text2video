"""
E2E runner — 工作流执行 + 交互操作（review/edit/reroll/select）

Usage:
  # 执行完整流程
  python scripts/e2e_v11b.py run --duration 40 --output e2e_output/v14

  # 审查
  python scripts/e2e_v11b.py review storyboard --output dir
  python scripts/e2e_v11b.py review tts --output dir
  python scripts/e2e_v11b.py review status --output dir

  # 编辑分镜
  python scripts/e2e_v11b.py edit storyboard --output dir --segment 2 --field narration_text --value "新旁白"

  # 抽卡
  python scripts/e2e_v11b.py reroll char_ref --output dir --char char_001
  python scripts/e2e_v11b.py reroll video --output dir --seg 1 --sub 1

  # 选择候选
  python scripts/e2e_v11b.py select char_ref --output dir --char char_001 --candidate 2

  # 列出候选
  python scripts/e2e_v11b.py list-candidates char_ref --output dir --char char_001
"""

import os
import sys
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.workflows import get_workflow
from app.workflows.registry import list_workflows
from app.ai.novel_splitter import split_novel_to_episodes


def cmd_run(args):
    with open(args.input) as f:
        input_text = f.read()
    wf = get_workflow(args.workflow)
    params = {"duration": args.duration, "voice": args.voice}
    if args.stop_after_segment:
        params["stop_after_segment"] = args.stop_after_segment
    ctx = wf.run(
        input_text=input_text, output_dir=args.output,
        params=params, stop_after_stage=args.stop_after_stage)
    sys.exit(0 if ctx.quality_passed or ctx.final_video_path else 1)


def cmd_review(args):
    wf = get_workflow(args.workflow)
    if args.target == "storyboard":
        result = wf.op_review_storyboard(args.output)
    elif args.target == "tts":
        result = wf.op_review_tts(args.output)
    elif args.target == "status":
        result = wf.op_review_status(args.output)
    elif args.target == "characters":
        result = wf.op_review_characters(args.output)
    elif args.target == "unit":
        if not args.unit:
            result = {"error": "--unit is required for 'review unit'"}
        else:
            result = wf.op_review_unit(args.output, args.unit)
    elif args.target == "assets":
        if not args.asset_type:
            result = {"error": "--asset-type is required for 'review assets'"}
        else:
            result = wf.op_review_assets(args.output, args.asset_type)
    elif args.target in ("char_refs", "scene_bgs", "first_frames", "videos"):
        type_map = {"char_refs": "char_ref", "scene_bgs": "scene_bg",
                     "first_frames": "first_frame", "videos": "video"}
        result = wf.op_review_assets(args.output, type_map[args.target])
    else:
        result = {"error": f"Unknown review target: {args.target}"}
    _output(result, args.json)


def cmd_edit(args):
    wf = get_workflow(args.workflow)
    if args.target == "storyboard":
        sub_idx = (args.sub - 1) if args.sub else None
        result = wf.op_edit_storyboard(
            args.output, args.segment, args.field, args.value, sub_idx)
    else:
        result = {"error": f"Unknown edit target: {args.target}"}
    _output(result, args.json)


def cmd_reroll(args):
    wf = get_workflow(args.workflow)
    if args.target == "char_ref":
        result = wf.op_reroll_char_ref(args.output, args.char)
    elif args.target == "scene_bg":
        result = wf.op_reroll_scene_bg(args.output, args.scene)
    elif args.target == "tts":
        result = wf.op_reroll_tts(args.output, args.seg,
                                   voice=args.voice, emotion=args.emotion)
    elif args.target == "video":
        result = wf.op_reroll_video(args.output, args.seg, args.sub)
    elif args.target == "frame":
        result = wf.op_reroll_frame(args.output, args.unit, args.frame)
    elif args.target == "video_segment":
        result = wf.op_reroll_video_segment(args.output, args.unit, args.seg)
    elif args.target == "dialogue_tts":
        result = wf.op_reroll_dialogue_tts(args.output, args.unit, args.seg,
                                            voice_id=args.voice)
    else:
        result = {"error": f"Unknown reroll target: {args.target}"}
    _output(result, args.json)


def cmd_select(args):
    wf = get_workflow(args.workflow)
    # 构建 asset_id
    if args.target == "char_ref":
        asset_id = args.char
    elif args.target == "scene_bg":
        asset_id = args.scene
    elif args.target == "tts":
        asset_id = str(args.seg)
    elif args.target in ("first_frame", "video"):
        asset_id = f"seg{args.seg:02d}_sub{args.sub:02d}"
    else:
        _output({"error": f"Unknown select target: {args.target}"}, args.json)
        return
    result = wf.op_select(args.output, args.target, asset_id, args.candidate)
    _output(result, args.json)


def cmd_list_candidates(args):
    wf = get_workflow(args.workflow)
    if args.target == "char_ref":
        asset_id = args.char
    elif args.target == "scene_bg":
        asset_id = args.scene
    elif args.target == "tts":
        asset_id = str(args.seg)
    elif args.target in ("first_frame", "video"):
        asset_id = f"seg{args.seg:02d}_sub{args.sub:02d}"
    else:
        _output({"error": f"Unknown target: {args.target}"}, args.json)
        return
    result = wf.op_list_candidates(args.output, args.target, asset_id)
    _output(result, args.json)


def cmd_split(args):
    """将长篇小说拆分为多集，每集对应一个短视频。"""
    import logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    with open(args.input) as f:
        full_text = f.read()
    episodes = split_novel_to_episodes(
        full_text,
        output_dir=args.output,
        chars_per_episode=args.chars_per_episode,
    )
    print(f"\n{'='*50}")
    print(f"拆分完成: {len(full_text)} 字 → {len(episodes)} 集")
    print(f"{'='*50}")
    for ep in episodes:
        match_icon = {"exact": "✓", "fuzzy": "~", "fallback": "✗"}[ep["anchor_match"]]
        print(f"  Ep{ep['episode_number']:02d} [{match_icon}] "
              f"{ep['episode_title']} ({len(ep['raw_text'])} 字)")
    if args.output:
        print(f"\n输出目录: {args.output}/")
        print(f"  novel_blueprint.json   — LLM 蓝图")
        print(f"  episodes_summary.json  — 集摘要")
        print(f"  episodes/ep_001.txt    — 每集原文（供分镜 LLM 使用）")


def cmd_list_workflows(args):
    for wf in list_workflows():
        print(f"  {wf['name']:20s} {wf['display_name']}")
        print(f"    stages: {' → '.join(wf['stages'])}")


def _output(result, as_json=False):
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        if "error" in result:
            print(f"Error: {result['error']}")
            sys.exit(1)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


# ================================================================
# Argparse
# ================================================================
parser = argparse.ArgumentParser(description="E2E Video Generation CLI")
subparsers = parser.add_subparsers(dest="command")

# 共享参数（加到每个子命令）
def _add_common(p):
    p.add_argument("--workflow", type=str, default="narration_manga")
    p.add_argument("--output", type=str, default="e2e_output/v11b")
    p.add_argument("--json", action="store_true", help="JSON output for agent")

# --- run ---
p_run = subparsers.add_parser("run", help="Execute full pipeline")
_add_common(p_run)
p_run.add_argument("--duration", type=int, default=40)
p_run.add_argument("--voice", type=str, default="female-shaonv")
p_run.add_argument("--input", type=str, default="data/test_novel.txt")
p_run.add_argument("--stop-after-stage", type=str, default=None)
p_run.add_argument("--stop-after-segment", type=int, default=None)

# --- review ---
p_review = subparsers.add_parser("review", help="Review current state")
_add_common(p_review)
p_review.add_argument("target", choices=["storyboard", "tts", "char_refs", "scene_bgs",
                                          "first_frames", "videos", "status",
                                          "characters", "unit", "assets"])
p_review.add_argument("--unit", type=int, default=None, help="Unit number (for dialogue_manga)")
p_review.add_argument("--asset-type", type=str, default=None,
                       help="Asset type: scene_refs/grids/frames/videos (for 'review assets')")

# --- edit ---
p_edit = subparsers.add_parser("edit", help="Edit storyboard")
_add_common(p_edit)
p_edit.add_argument("target", choices=["storyboard"])
p_edit.add_argument("--segment", type=int, required=True)
p_edit.add_argument("--field", type=str, required=True)
p_edit.add_argument("--value", type=str, required=True)
p_edit.add_argument("--sub", type=int, default=None, help="Sub-shot index (1-based)")

# --- reroll ---
p_reroll = subparsers.add_parser("reroll", help="Generate new candidate")
_add_common(p_reroll)
p_reroll.add_argument("target", choices=["char_ref", "scene_bg", "tts", "first_frame", "video",
                                        "frame", "video_segment", "dialogue_tts"])
p_reroll.add_argument("--char", type=str, help="Character ID")
p_reroll.add_argument("--scene", type=str, help="Scene ID")
p_reroll.add_argument("--seg", type=int, help="Segment number")
p_reroll.add_argument("--sub", type=int, help="Sub-shot number (1-based)")
p_reroll.add_argument("--unit", type=int, help="Unit number (for dialogue_manga)")
p_reroll.add_argument("--frame", type=int, help="Frame number (1-16, for frame reroll)")
p_reroll.add_argument("--voice", type=str, help="TTS voice override")
p_reroll.add_argument("--emotion", type=str, help="TTS emotion override")

# --- select ---
p_select = subparsers.add_parser("select", help="Select a candidate")
_add_common(p_select)
p_select.add_argument("target", choices=["char_ref", "scene_bg", "tts", "first_frame", "video"])
p_select.add_argument("--char", type=str, help="Character ID")
p_select.add_argument("--scene", type=str, help="Scene ID")
p_select.add_argument("--seg", type=int, help="Segment number")
p_select.add_argument("--sub", type=int, help="Sub-shot number (1-based)")
p_select.add_argument("--candidate", type=int, required=True, help="Candidate version to select")

# --- list-candidates ---
p_list = subparsers.add_parser("list-candidates", help="List candidates for an asset")
_add_common(p_list)
p_list.add_argument("target", choices=["char_ref", "scene_bg", "tts", "first_frame", "video"])
p_list.add_argument("--char", type=str)
p_list.add_argument("--scene", type=str)
p_list.add_argument("--seg", type=int)
p_list.add_argument("--sub", type=int)

# --- split ---
p_split = subparsers.add_parser("split", help="Split novel into episodes")
p_split.add_argument("--input", type=str, default="data/test_novel.txt")
p_split.add_argument("--output", type=str, default="e2e_output/split")
p_split.add_argument("--chars-per-episode", type=int, default=600)
p_split.add_argument("--verbose", action="store_true")

# --- list-workflows ---
p_lw = subparsers.add_parser("list-workflows", help="List available workflows")
_add_common(p_lw)

args = parser.parse_args()

if args.command == "run":
    cmd_run(args)
elif args.command == "review":
    cmd_review(args)
elif args.command == "edit":
    cmd_edit(args)
elif args.command == "reroll":
    cmd_reroll(args)
elif args.command == "select":
    cmd_select(args)
elif args.command == "list-candidates":
    cmd_list_candidates(args)
elif args.command == "split":
    cmd_split(args)
elif args.command == "list-workflows":
    cmd_list_workflows(args)
elif args.command is None:
    parser.print_help()
else:
    parser.print_help()
