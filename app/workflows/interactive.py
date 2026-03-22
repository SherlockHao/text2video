"""
InteractiveOpsMixin — 交互操作（review/edit/reroll/select）

提供给 CLI 和 Agent 使用的操作方法。
每个方法从磁盘加载状态、执行操作、写回磁盘。
"""

import json
import os
import time
import asyncio
import base64

from .base import BaseWorkflow, WorkflowContext
from .candidates import CandidateManager


class InteractiveOpsMixin:
    """交互操作混入类，NarrationMangaWorkflow 继承此类。"""

    # ================================================================
    # Review 操作
    # ================================================================

    def op_review_storyboard(self, output_dir: str) -> dict:
        sb_path = os.path.join(output_dir, "storyboard.json")
        if not os.path.exists(sb_path):
            return {"error": "storyboard.json not found"}
        with open(sb_path) as f:
            return json.load(f)

    def op_review_tts(self, output_dir: str) -> dict:
        ctx = BaseWorkflow.load_context_from_disk(output_dir)
        result = []
        for seg in ctx.segments:
            sn = seg["segment_number"]
            cm = ctx.candidates
            candidates = cm.list_candidates(f"tts:{sn}")
            entry = {
                "segment": sn,
                "narration": seg.get("narration_text", ""),
                "emotion": seg.get("emotion", ""),
                "candidates": candidates,
            }
            # 添加时长
            sel = cm.get_selected_path(f"tts:{sn}")
            if sel and os.path.exists(sel):
                from app.services.ffmpeg_utils import get_media_duration
                entry["duration"] = get_media_duration(sel)
                entry["selected_path"] = sel
            result.append(entry)
        return {"segments": result}

    def op_review_assets(self, output_dir: str, asset_type: str) -> dict:
        cm = CandidateManager(output_dir)
        cm.migrate_from_existing(output_dir)
        all_assets = cm.get_all_for_type(asset_type)
        result = {}
        for key, entry in all_assets.items():
            candidates = cm.list_candidates(key)
            result[key] = candidates
        return {"type": asset_type, "assets": result}

    def op_review_status(self, output_dir: str) -> dict:
        """返回整体流水线状态。"""
        sb_exists = os.path.exists(os.path.join(output_dir, "storyboard.json"))
        cm = CandidateManager(output_dir)
        cm.migrate_from_existing(output_dir)
        data = cm.load()

        # 统计各类资产
        counts = {}
        for key in data.get("assets", {}):
            atype = key.split(":")[0]
            counts[atype] = counts.get(atype, 0) + 1

        final = os.path.join(output_dir, "final_video.mp4")
        return {
            "storyboard": "ready" if sb_exists else "pending",
            "asset_counts": counts,
            "invalidated": data.get("invalidated", []),
            "final_video": final if os.path.exists(final) else None,
        }

    # ================================================================
    # Edit 操作
    # ================================================================

    def op_edit_storyboard(self, output_dir: str, segment: int,
                           field: str, value: str, sub_idx: int = None) -> dict:
        sb_path = os.path.join(output_dir, "storyboard.json")
        if not os.path.exists(sb_path):
            return {"error": "storyboard.json not found"}

        with open(sb_path) as f:
            sb = json.load(f)

        # 找到目标 segment
        target = None
        for seg in sb.get("segments", []):
            if seg.get("segment_number") == segment:
                target = seg
                break
        if not target:
            return {"error": f"Segment {segment} not found"}

        old_value = None
        if sub_idx is not None:
            # 编辑子镜头字段
            subs = target.get("sub_shots", [])
            if sub_idx < 0 or sub_idx >= len(subs):
                return {"error": f"Sub-shot index {sub_idx} out of range"}
            old_value = subs[sub_idx].get(field)
            subs[sub_idx][field] = value
        else:
            old_value = target.get(field)
            target[field] = value

        with open(sb_path, "w") as f:
            json.dump(sb, f, ensure_ascii=False, indent=2)

        # 级联失效
        cm = CandidateManager(output_dir)
        cm.migrate_from_existing(output_dir)
        cm.invalidate_cascade(
            edit_type=field, seg_num=segment, sub_idx=sub_idx,
            storyboard=sb
        )

        return {
            "segment": segment,
            "field": field,
            "old_value": old_value,
            "new_value": value,
            "invalidated": cm.load().get("invalidated", []),
        }

    # ================================================================
    # Reroll 操作
    # ================================================================

    def op_reroll_char_ref(self, output_dir: str, char_id: str) -> dict:
        ctx = BaseWorkflow.load_context_from_disk(output_dir)
        cm = ctx.candidates
        char = None
        for c in ctx.characters:
            if c["char_id"] == char_id:
                char = c
                break
        if not char:
            return {"error": f"Character {char_id} not found"}

        version = cm.next_version(f"char_ref:{char_id}")
        gender = char.get("gender", "female")
        appearance = char.get("appearance_prompt", "")
        pose = ("面无表情，笔直站立，四分之三侧面，双臂自然放松，自信姿态"
                if gender == "male" else
                "面无表情，笔直站立，四分之三侧面，双手交叠，优雅姿态")
        prompt = (
            "杰作, 最高质量, 高度精细, 4K, "
            "动漫风格, 漫画风格, 赛璐璐上色, 鲜艳色彩, 全彩插画, 色彩丰富, "
            "精细插画, 角色设定图, 上半身肖像, 腰部以上, "
            f"{appearance}, {pose}, "
            "纯净浅灰色背景, 摄影棚灯光, "
            "无文字, 无水印, 高清锐利, 无其他角色, 单人"
        )

        from vendor.jimeng.t2i import generate_image
        paths = generate_image(prompt, width=832, height=1472,
                               output_dir=f"{output_dir}/characters",
                               prefix=f"charref_{char_id}_v{version}")
        if not paths:
            return {"error": "Image generation failed"}

        rel_path = os.path.relpath(paths[0], output_dir)
        cm.register(f"char_ref:{char_id}", rel_path)

        # 选新角色图会影响视频
        cm.invalidate_cascade("select_char_ref", char_id=char_id, storyboard=ctx.storyboard)

        return {"char_id": char_id, "version": version, "path": paths[0],
                "candidates": cm.list_candidates(f"char_ref:{char_id}")}

    def op_reroll_scene_bg(self, output_dir: str, scene_id: str) -> dict:
        ctx = BaseWorkflow.load_context_from_disk(output_dir)
        cm = ctx.candidates
        scene = None
        for s in ctx.scenes:
            if s["scene_id"] == scene_id:
                scene = s
                break
        if not scene:
            return {"error": f"Scene {scene_id} not found"}

        version = cm.next_version(f"scene_bg:{scene_id}")
        desc = scene.get("scene_prompt", "")
        if "无人物" not in desc:
            desc += ", 漫画风格, 动漫背景, 无人物, 无角色"
        prompt = (
            "杰作, 最高质量, 高度精细, 4K, "
            "动漫风格, 漫画风格, 鲜艳色彩, 精细插画, "
            f"远景全景, {desc}, "
            "空气透视, 精细环境, 无文字, 无水印"
        )
        from vendor.jimeng.t2i import generate_image
        paths = generate_image(prompt, width=832, height=1472,
                               output_dir=f"{output_dir}/scenes",
                               prefix=f"scenebg_{scene_id}_v{version}")
        if not paths:
            return {"error": "Image generation failed"}

        rel_path = os.path.relpath(paths[0], output_dir)
        cm.register(f"scene_bg:{scene_id}", rel_path)
        return {"scene_id": scene_id, "version": version, "path": paths[0],
                "candidates": cm.list_candidates(f"scene_bg:{scene_id}")}

    def op_reroll_tts(self, output_dir: str, segment: int,
                      voice: str = None, emotion: str = None) -> dict:
        ctx = BaseWorkflow.load_context_from_disk(output_dir)
        cm = ctx.candidates
        seg = None
        for s in ctx.segments:
            if s["segment_number"] == segment:
                seg = s
                break
        if not seg:
            return {"error": f"Segment {segment} not found"}

        version = cm.next_version(f"tts:{segment}")
        text = seg.get("narration_text", "")
        emo = emotion or seg.get("emotion", "calm")
        valid = {"happy", "sad", "angry", "fearful", "disgusted", "surprised", "calm", "fluent"}
        if emo == "whisper":
            emo = "calm"
        if emo not in valid:
            emo = "calm"
        voice_id = voice or "female-shaonv"

        async def _gen():
            from app.ai.providers.minimax_tts import MiniMaxTTSProvider
            provider = MiniMaxTTSProvider()
            job_id = await provider.submit_job({
                "text": text, "voice_id": voice_id, "speed": 0.9, "emotion": emo,
            })
            status = await provider.poll_job(job_id)
            return status.result_data

        data = asyncio.run(_gen())
        if not data:
            return {"error": "TTS generation failed"}

        path = f"{output_dir}/audio/seg_{segment:02d}_v{version}.mp3"
        with open(path, "wb") as f:
            f.write(data)

        rel_path = os.path.relpath(path, output_dir)
        cm.register(f"tts:{segment}", rel_path)

        from app.services.ffmpeg_utils import get_media_duration
        dur = get_media_duration(path)
        return {"segment": segment, "version": version, "path": path,
                "duration": dur, "emotion": emo,
                "candidates": cm.list_candidates(f"tts:{segment}")}

    def op_reroll_video(self, output_dir: str, seg: int, sub: int) -> dict:
        ctx = BaseWorkflow.load_context_from_disk(output_dir)
        cm = ctx.candidates
        asset_key = f"video:seg{seg:02d}_sub{sub:02d}"
        version = cm.next_version(asset_key)

        # 找到对应的 segment 和 sub_shot
        target_seg = None
        for s in ctx.segments:
            if s["segment_number"] == seg:
                target_seg = s
                break
        if not target_seg:
            return {"error": f"Segment {seg} not found"}
        subs = target_seg.get("sub_shots", [])
        if sub < 1 or sub > len(subs):
            return {"error": f"Sub-shot {sub} out of range (1-{len(subs)})"}
        target_sub = subs[sub - 1]

        # 找首帧（优先用上一个子镜头的末帧，或 T2I 首帧）
        first_frame = None
        if sub == 1:
            sel = cm.get_selected_path(f"first_frame:seg{seg:02d}_sub01")
            if sel and os.path.exists(sel):
                first_frame = sel
        if not first_frame:
            # 尝试找前一个子镜头的末帧
            prev_lf = f"{output_dir}/frames/seg{seg:02d}_sub{sub-1:02d}_lastframe.png"
            if sub > 1 and os.path.exists(prev_lf):
                first_frame = prev_lf
        if not first_frame:
            # fallback: 用段的 image_prompt 生成
            return {"error": "No first frame available. Run pipeline first."}

        # 角色参考图
        chars_in = target_seg.get("characters_in_shot", [])
        subject_ref = []
        for cid in chars_in:
            sel = cm.get_selected_path(f"char_ref:{cid}")
            if sel and os.path.exists(sel):
                with open(sel, "rb") as f:
                    subject_ref.append({"image": base64.b64encode(f.read()).decode()})

        # Motion prompt
        from app.workflows.templates.narration_manga import CAMERA_MAP, NEGATIVE_PROMPT
        vp = target_sub.get("video_prompt", "")
        cam = target_sub.get("camera_movement", "static")
        parts = [vp or "角色微妙动态, 轻微呼吸"]
        if "镜头" not in vp:
            parts.append(CAMERA_MAP.get(cam, "镜头保持不动"))
        parts.append("发丝轻轻飘动, 衣物物理效果, 动漫风格, 流畅动画")
        motion = ", ".join(parts)

        # Duration (从 storyboard 读取或默认5s)
        duration = "5"  # 默认，实际应从 duration_plan 读取

        with open(first_frame, "rb") as f:
            first_b64 = base64.b64encode(f.read()).decode()

        from vendor.kling.client import KlingClient
        kling = KlingClient()
        resp = kling.generate_video(
            image=first_b64, prompt=motion, model_name="kling-v3", mode="std",
            duration=duration, aspect_ratio="9:16", negative_prompt=NEGATIVE_PROMPT,
            cfg_scale=0.5, subject_reference=subject_ref if subject_ref else None)

        if not resp or resp.get("code") != 0:
            return {"error": f"Video generation failed: {resp}"}

        task_id = resp["data"]["task_id"]
        data = kling.poll_task(task_id, task_type="video", max_wait=600, interval=10)
        if not data:
            return {"error": "Video poll failed"}

        videos = data.get("task_result", {}).get("videos", [])
        if not videos or not videos[0].get("url"):
            return {"error": "No video URL"}

        video_path = f"{output_dir}/videos/seg{seg:02d}_sub{sub:02d}_v{version}.mp4"
        import requests
        from app.workflows.templates.narration_manga import _download_with_retry
        if not _download_with_retry(videos[0]["url"], video_path):
            return {"error": "Download failed"}

        rel_path = os.path.relpath(video_path, output_dir)
        cm.register(asset_key, rel_path)

        from app.services.ffmpeg_utils import get_media_duration
        dur = get_media_duration(video_path)
        sz = os.path.getsize(video_path) / 1024 / 1024
        return {"seg": seg, "sub": sub, "version": version, "path": video_path,
                "duration": dur, "size_mb": round(sz, 1),
                "candidates": cm.list_candidates(asset_key)}

    # ================================================================
    # Select 操作
    # ================================================================

    def op_select(self, output_dir: str, asset_type: str, asset_id: str,
                  candidate: int) -> dict:
        cm = CandidateManager(output_dir)
        cm.migrate_from_existing(output_dir)
        asset_key = f"{asset_type}:{asset_id}"
        ok = cm.select(asset_key, candidate)
        if not ok:
            return {"error": f"Cannot select candidate {candidate} for {asset_key}"}

        # 级联失效
        sb_path = os.path.join(output_dir, "storyboard.json")
        storyboard = None
        if os.path.exists(sb_path):
            with open(sb_path) as f:
                storyboard = json.load(f)

        if asset_type == "char_ref":
            cm.invalidate_cascade("select_char_ref", char_id=asset_id, storyboard=storyboard)
        elif asset_type == "first_frame":
            # seg01_sub01 → seg=1, sub_idx=0
            parts = asset_id.replace("seg", "").replace("sub", "_").split("_")
            if len(parts) >= 2:
                seg_num = int(parts[0])
                sub_idx = int(parts[1]) - 1
                cm.invalidate_cascade("select_first_frame", seg_num=seg_num,
                                      sub_idx=sub_idx, storyboard=storyboard)

        selected = cm.get_selected_path(asset_key)
        return {"asset_key": asset_key, "selected_candidate": candidate,
                "selected_path": selected,
                "invalidated": cm.load().get("invalidated", [])}

    # ================================================================
    # List candidates
    # ================================================================

    def op_list_candidates(self, output_dir: str, asset_type: str,
                           asset_id: str) -> dict:
        cm = CandidateManager(output_dir)
        cm.migrate_from_existing(output_dir)
        asset_key = f"{asset_type}:{asset_id}"
        return {"asset_key": asset_key, "candidates": cm.list_candidates(asset_key)}
