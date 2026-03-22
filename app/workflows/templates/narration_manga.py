"""
旁白漫剧工作流模板 — Narration-driven manga drama

9 Stages:
  1. storyboard     — LLM 分镜（Qwen）
  2. tts            — TTS 生成 → 真实时长（MiniMax）
  3. duration_plan  — 时长规划（4 Cases）
  4. char_refs      — 角色参考图（Jimeng T2I）
  5. scene_bgs      — 场景背景图（Jimeng T2I）
  6. first_frames   — 首帧图（Jimeng T2I + last-frame）
  7. video_gen      — 视频生成（Kling V3 I2V, 动态时长）
  8. assembly       — 组装（FFmpeg）
  9. quality_gate   — 质量检测
"""

import json
import os
import sys
import time
import asyncio
import subprocess
import base64
import math
import re

from app.workflows.base import BaseWorkflow, WorkflowContext, StageResult
from app.workflows.registry import register_workflow
from app.ai.duration_planner import (
    plan_sub_shot_durations, get_single_shot_duration,
    DEFAULT_SUB_SHOT_DURATION, KLING_MIN_DURATION, KLING_MAX_DURATION,
)
from vendor.qwen.client import chat_with_system, _extract_json
from vendor.jimeng.t2i import generate_image
from vendor.kling.client import KlingClient
from app.services.ffmpeg_utils import (
    align_video_to_audio, concatenate_clips, overlay_bgm, get_media_duration,
)
from app.services.narration_utils import shorten_narration_via_llm
import requests as http_requests

NEGATIVE_PROMPT = (
    "模糊, 低质量, 面部扭曲, 多余手指, 变形, 形变, "
    "闪烁, 突然切换场景, 真人实拍, 写实风格, "
    "文字, 水印, 签名, 边框, "
    "风格突变, 色彩偏移, 角色不一致, 多余肢体"
)

CAMERA_MAP = {
    "static": "镜头保持不动", "pan_left": "镜头缓慢向左平移",
    "pan_right": "镜头缓慢向右平移", "zoom_in": "镜头缓慢推近",
    "zoom_out": "镜头缓慢拉远", "tilt_up": "镜头缓慢上摇",
    "tilt_down": "镜头缓慢下摇", "tracking": "镜头跟随主体移动",
    "dolly_in": "镜头平滑向前推进", "orbit": "镜头缓慢环绕",
}


def _img_to_b64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def _extract_last_frame(video_path, output_path):
    r = subprocess.run(
        ["ffmpeg", "-y", "-sseof", "-0.1", "-i", video_path, "-frames:v", "1", output_path],
        capture_output=True, timeout=10)
    return r.returncode == 0 and os.path.exists(output_path)


@register_workflow
class NarrationMangaWorkflow(BaseWorkflow):
    name = "narration_manga"
    display_name = "旁白漫剧"
    stages = [
        "storyboard",
        "tts",
        "duration_plan",
        "char_refs",
        "scene_bgs",
        "first_frames",
        "video_gen",
        "assembly",
        "quality_gate",
    ]

    # ================================================================
    # Stage 1: LLM Storyboard
    # ================================================================
    def stage_storyboard(self, ctx: WorkflowContext) -> StageResult:
        duration = ctx.params.get("duration", 40)

        system_prompt = self._build_storyboard_prompt(duration)
        user_prompt = f"""请将以下小说改编为解说类漫剧短视频分镜脚本。

【重要】你是顶级导演，旁白要讲好故事。直接输出JSON，回复以 {{ 开头。

文本内容：
{ctx.input_text}"""

        raw = chat_with_system(system_prompt, user_prompt, max_tokens=8192)
        sb = json.loads(_extract_json(raw))
        ctx.storyboard = sb
        ctx.segments = sb.get("segments", [])
        ctx.characters = sb.get("character_profiles", [])
        ctx.scenes = sb.get("scene_backgrounds", [])

        # 旁白超长则压缩
        for seg in ctx.segments:
            nt = seg.get("narration_text", "")
            if len(nt) > 30:
                seg["narration_text"] = shorten_narration_via_llm(
                    nt, 30, seg.get("scene_description", ""))

        with open(f"{ctx.output_dir}/storyboard.json", "w") as f:
            json.dump(sb, f, ensure_ascii=False, indent=2)

        ctx.log(f"  {len(ctx.segments)} segments, {len(ctx.scenes)} scenes, {len(ctx.characters)} chars")
        for c in ctx.characters:
            ctx.log(f"  Char: {c['name']} ({c['char_id']}) {c.get('gender','?')}")
        for seg in ctx.segments:
            sn = seg["segment_number"]
            nt = seg.get("narration_text", "")
            subs = seg.get("sub_shots", [])
            ctx.log(f"  Seg {sn}: {len(subs)}个子镜头 | {len(nt)}字 | emotion={seg.get('emotion','?')}")
            ctx.log(f"    旁白: \"{nt}\"")
            for i, sub in enumerate(subs):
                ctx.log(f"    子镜头{i+1}: {sub.get('shot_type','')} | {sub.get('video_prompt','')[:60]}")

        return StageResult(success=True)

    # ================================================================
    # Stage 2: TTS
    # ================================================================
    def stage_tts(self, ctx: WorkflowContext) -> StageResult:
        voice_id = ctx.params.get("voice", "female-shaonv")

        async def _gen():
            from app.ai.providers.minimax_tts import MiniMaxTTSProvider
            provider = MiniMaxTTSProvider()
            paths = {}
            for seg in ctx.segments:
                sn = seg["segment_number"]
                text = seg.get("narration_text", "")
                if not text:
                    continue
                emotion = seg.get("emotion", "calm")
                valid = {"happy", "sad", "angry", "fearful", "disgusted", "surprised", "calm", "fluent"}
                if emotion == "whisper":
                    emotion = "calm"
                if emotion not in valid:
                    emotion = "calm"
                job_id = await provider.submit_job({
                    "text": text, "voice_id": voice_id, "speed": 0.9, "emotion": emotion,
                })
                status = await provider.poll_job(job_id)
                if status.result_data:
                    path = f"{ctx.output_dir}/audio/seg_{sn:02d}.mp3"
                    with open(path, "wb") as f:
                        f.write(status.result_data)
                    paths[sn] = path
                    ctx.log(f"  Seg {sn}: ✓ (emotion={emotion})")
                await asyncio.sleep(1)
            return paths

        ctx.tts_paths = asyncio.run(_gen())

        for seg in ctx.segments:
            sn = seg["segment_number"]
            if sn in ctx.tts_paths:
                ctx.tts_durations[sn] = get_media_duration(ctx.tts_paths[sn])
                ctx.log(f"  Seg {sn}: TTS = {ctx.tts_durations[sn]:.1f}s")

        return StageResult(success=True)

    # ================================================================
    # Stage 3: Duration Planning
    # ================================================================
    def stage_duration_plan(self, ctx: WorkflowContext) -> StageResult:
        for seg in ctx.segments:
            sn = seg["segment_number"]
            subs = seg.get("sub_shots", [])
            tts_dur = ctx.tts_durations.get(sn, 0)
            if tts_dur <= 0:
                ctx.log(f"  Seg {sn}: no TTS, skip")
                continue

            original_total = len(subs) * DEFAULT_SUB_SHOT_DURATION
            ctx.log(f"  Seg {sn}: TTS={tts_dur:.1f}s, {len(subs)} subs (orig {original_total}s)")

            adjusted, durations = plan_sub_shot_durations(subs, tts_dur)

            if adjusted is None:
                # Case 4: 重新生成单镜头
                target_dur = get_single_shot_duration(tts_dur)
                new_subs = self._regenerate_single_shot(seg, target_dur)
                seg["sub_shots"] = new_subs
                ctx.seg_durations[sn] = [target_dur]
                ctx.log(f"    → Case 4: regenerated 1 sub-shot × {target_dur}s")
            else:
                seg["sub_shots"] = adjusted
                ctx.seg_durations[sn] = durations
                dur_str = "+".join(str(d) for d in durations)
                ctx.log(f"    → {dur_str} = {sum(durations)}s")

        # 保存更新后的 storyboard
        with open(f"{ctx.output_dir}/storyboard.json", "w") as f:
            json.dump(ctx.storyboard, f, ensure_ascii=False, indent=2)

        # 构建全局子镜头列表
        ctx.all_sub_shots = []
        for seg_idx, seg in enumerate(ctx.segments):
            for sub_idx, sub in enumerate(seg.get("sub_shots", [])):
                ctx.all_sub_shots.append((seg_idx, sub_idx, seg, sub))

        ctx.all_durations = []
        for seg in ctx.segments:
            sn = seg["segment_number"]
            durs = ctx.seg_durations.get(sn,
                [DEFAULT_SUB_SHOT_DURATION] * len(seg.get("sub_shots", [])))
            ctx.all_durations.extend(durs)

        total_subs = len(ctx.all_sub_shots)
        total_dur = sum(ctx.all_durations)
        ctx.log(f"  Total: {total_subs} sub-shots, {total_dur}s planned video")

        return StageResult(success=True)

    # ================================================================
    # Stage 4: Character Reference Images
    # ================================================================
    def stage_char_refs(self, ctx: WorkflowContext) -> StageResult:
        for c in ctx.characters:
            cid = c["char_id"]
            gender = c.get("gender", "female")
            appearance = c.get("appearance_prompt", "")
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
            paths = generate_image(prompt, width=832, height=1472,
                                   output_dir=f"{ctx.output_dir}/characters",
                                   prefix=f"charref_{cid}")
            if paths:
                ctx.char_images[cid] = paths[0]
                ctx.log(f"  {c['name']} ({cid}): ✓")
            time.sleep(3)
        return StageResult(success=True)

    # ================================================================
    # Stage 5: Scene Background Images
    # ================================================================
    def stage_scene_bgs(self, ctx: WorkflowContext) -> StageResult:
        for sc in ctx.scenes:
            sid = sc["scene_id"]
            desc = sc.get("scene_prompt", "")
            if "无人物" not in desc:
                desc += ", 漫画风格, 动漫背景, 无人物, 无角色"
            prompt = (
                "杰作, 最高质量, 高度精细, 4K, "
                "动漫风格, 漫画风格, 鲜艳色彩, 精细插画, "
                f"远景全景, {desc}, "
                "空气透视, 精细环境, 无文字, 无水印"
            )
            paths = generate_image(prompt, width=832, height=1472,
                                   output_dir=f"{ctx.output_dir}/scenes",
                                   prefix=f"scenebg_{sid}")
            if paths:
                ctx.scene_images[sid] = paths[0]
                ctx.log(f"  {sid} ({sc['name']}): ✓")
            time.sleep(3)
        return StageResult(success=True)

    # ================================================================
    # Stage 6: First-Frame Generation
    # ================================================================
    def stage_first_frames(self, ctx: WorkflowContext) -> StageResult:
        profiles_map = {c["char_id"]: c for c in ctx.characters}
        scene_desc_map = {s["scene_id"]: s for s in ctx.scenes}

        # 确定首帧策略
        ctx.sub_shot_plan = []
        prev_sid = None
        for seg_idx, sub_idx, seg, sub in ctx.all_sub_shots:
            sid = seg.get("scene_id", "")
            if sub_idx == 0:
                if seg_idx == 0 or sid != prev_sid:
                    ctx.sub_shot_plan.append("t2i")
                else:
                    ctx.sub_shot_plan.append("last_frame")
                prev_sid = sid
            else:
                ctx.sub_shot_plan.append("last_frame")

        for i, (_, sub_idx, seg, _) in enumerate(ctx.all_sub_shots):
            ctx.log(f"  Seg{seg['segment_number']}-Sub{sub_idx+1}: {ctx.sub_shot_plan[i]} ({ctx.all_durations[i]}s)")

        # 生成 T2I 首帧
        for i, (seg_idx, sub_idx, seg, sub) in enumerate(ctx.all_sub_shots):
            if ctx.sub_shot_plan[i] != "t2i":
                continue

            chars_in = seg.get("characters_in_shot", [])
            sid = seg.get("scene_id", "")
            sd = scene_desc_map.get(sid, {}).get("scene_prompt", "")

            if len(chars_in) >= 2:
                main_cid = chars_in[0]
                main_app = profiles_map.get(main_cid, {}).get("appearance_prompt", "")
                scene_brief = sd.replace("无人物, 无角色", "").strip(" ,.")
                prompt = (
                    "杰作, 最高质量, 高度精细, 4K, "
                    "动漫风格, 漫画风格, 赛璐璐上色, 鲜艳色彩, 精细插画, "
                    f"中景, {main_app}, "
                    f"站在门口神情紧张, {scene_brief}, 戏剧性光影"
                )
            else:
                base_prompt = seg.get("image_prompt", "")
                parts = []
                if "杰作" not in base_prompt:
                    parts.append("杰作, 最高质量, 高度精细, 4K")
                if "动漫风格" not in base_prompt:
                    parts.append("动漫风格, 漫画风格, 赛璐璐上色, 鲜艳色彩, 精细插画")
                parts.append(base_prompt)
                for cid in chars_in:
                    app = profiles_map.get(cid, {}).get("appearance_prompt", "")
                    if app and app[:20] not in base_prompt:
                        parts.append(app)
                if sd and sd[:20] not in base_prompt:
                    parts.append(f"背景: {sd.replace('无人物, 无角色', '').strip(' ,.')}")
                prompt = ", ".join(parts)

            sn = seg["segment_number"]
            paths = generate_image(prompt, width=832, height=1472,
                                   output_dir=f"{ctx.output_dir}/images",
                                   prefix=f"seg{sn:02d}_sub{sub_idx+1:02d}")
            if paths:
                ctx.t2i_images[i] = paths[0]
                ctx.log(f"  Seg{sn}-Sub{sub_idx+1} first-frame: ✓")
            time.sleep(3)

        return StageResult(success=True)

    # ================================================================
    # Stage 7: Video Generation
    # ================================================================
    def stage_video_gen(self, ctx: WorkflowContext) -> StageResult:
        kling = KlingClient()
        prev_last_frame = None
        stop_seg = ctx.params.get("stop_after_segment")
        total_subs = len(ctx.all_sub_shots)

        for i, (seg_idx, sub_idx, seg, sub) in enumerate(ctx.all_sub_shots):
            sn = seg["segment_number"]
            chars_in = seg.get("characters_in_shot", [])
            shot_duration = ctx.all_durations[i]

            ctx.log(f"\n  --- Seg{sn}-Sub{sub_idx+1} ({i+1}/{total_subs}) ---")

            # 首帧
            if ctx.sub_shot_plan[i] == "t2i":
                if i not in ctx.t2i_images:
                    ctx.log(f"  SKIP (no first-frame)"); prev_last_frame = None; continue
                first_frame_path = ctx.t2i_images[i]
                ctx.log(f"  First frame: T2I")
            else:
                if prev_last_frame and os.path.exists(prev_last_frame):
                    first_frame_path = prev_last_frame
                    ctx.log(f"  First frame: last-frame continuity")
                else:
                    bp = seg.get("image_prompt", "") or "杰作, 动漫风格, 角色站立"
                    paths = generate_image(bp, width=832, height=1472,
                                           output_dir=f"{ctx.output_dir}/images",
                                           prefix=f"seg{sn:02d}_sub{sub_idx+1:02d}_fb")
                    if not paths:
                        ctx.log(f"  SKIP"); prev_last_frame = None; continue
                    first_frame_path = paths[0]; time.sleep(3)

            # subject_reference
            subject_ref = []
            for cid in chars_in:
                if cid in ctx.char_images:
                    subject_ref.append({"image": _img_to_b64(ctx.char_images[cid])})

            # Motion prompt
            vp = sub.get("video_prompt", "")
            cam = sub.get("camera_movement", "static")
            parts = []
            parts.append(vp or "角色微妙动态, 轻微呼吸, 细微重心转移")
            if "镜头" not in vp:
                parts.append(CAMERA_MAP.get(cam, "镜头保持不动"))
            parts.append("发丝轻轻飘动, 衣物物理效果, 动漫风格, 流畅动画")
            motion_prompt = ", ".join(parts)

            kling_dur = str(max(KLING_MIN_DURATION, min(KLING_MAX_DURATION, shot_duration)))
            ctx.log(f"  Duration: {kling_dur}s | {sub.get('shot_type', '?')}")

            # 调用 Kling V3
            first_b64 = _img_to_b64(first_frame_path)
            resp = None
            for attempt in range(2):
                try:
                    resp = kling.generate_video(
                        image=first_b64, prompt=motion_prompt,
                        model_name="kling-v3", mode="std",
                        duration=kling_dur, aspect_ratio="9:16",
                        negative_prompt=NEGATIVE_PROMPT, cfg_scale=0.5,
                        subject_reference=subject_ref if subject_ref else None,
                    )
                except Exception as e:
                    ctx.log(f"  Attempt {attempt+1} error: {e}")
                    if attempt == 0: time.sleep(10); continue
                    else: break

                code = resp.get("code", -1) if resp else -1
                if code == 1303:
                    ctx.log(f"  Parallel limit, waiting 90s..."); time.sleep(90); continue
                elif code == 0:
                    break
                else:
                    ctx.log(f"  Attempt {attempt+1} failed: code={code}")
                    if attempt == 0: time.sleep(10); continue

            if not resp or resp.get("code") != 0:
                ctx.log(f"  FAILED"); prev_last_frame = None; continue

            task_id = resp["data"]["task_id"]
            ctx.log(f"  Task: {task_id}, polling...")
            data = kling.poll_task(task_id, task_type="video", max_wait=600, interval=10)
            if not data:
                ctx.log(f"  Poll failed"); prev_last_frame = None; continue

            videos = data.get("task_result", {}).get("videos", [])
            if not videos or not videos[0].get("url"):
                ctx.log(f"  No video URL"); prev_last_frame = None; continue

            video_path = f"{ctx.output_dir}/videos/seg{sn:02d}_sub{sub_idx+1:02d}.mp4"
            r = http_requests.get(videos[0]["url"], timeout=120)
            with open(video_path, "wb") as f:
                f.write(r.content)
            ctx.sub_shot_videos[i] = video_path
            ctx.total_generated += 1

            dur_v = get_media_duration(video_path)
            sz = os.path.getsize(video_path) / 1024 / 1024

            lf_path = f"{ctx.output_dir}/frames/seg{sn:02d}_sub{sub_idx+1:02d}_lastframe.png"
            if _extract_last_frame(video_path, lf_path):
                prev_last_frame = lf_path
                ctx.log(f"  ✓ {dur_v:.1f}s, {sz:.1f}MB (last-frame saved)")
            else:
                prev_last_frame = None
                ctx.log(f"  ✓ {dur_v:.1f}s, {sz:.1f}MB")

            # 按段停止
            if stop_seg and sn >= stop_seg:
                is_last = (sub_idx == len(seg.get("sub_shots", [])) - 1)
                if is_last:
                    ctx.log(f"\n★ Stopped after Segment {sn}. Generated {ctx.total_generated} videos.")
                    return StageResult(success=True)

            time.sleep(5)

        ctx.log(f"\n  {ctx.total_generated}/{total_subs} sub-shot videos generated")
        return StageResult(success=True)

    # ================================================================
    # Stage 8: Assembly
    # ================================================================
    def stage_assembly(self, ctx: WorkflowContext) -> StageResult:
        # 8a: 拼接子镜头 → 段视频
        segment_videos = {}
        for seg in ctx.segments:
            sn = seg["segment_number"]
            subs = seg.get("sub_shots", [])
            paths = []
            for sub_idx in range(len(subs)):
                for gi, (si, sbi, s, _) in enumerate(ctx.all_sub_shots):
                    if s["segment_number"] == sn and sbi == sub_idx:
                        if gi in ctx.sub_shot_videos:
                            paths.append(os.path.abspath(ctx.sub_shot_videos[gi]))
                        break

            if not paths:
                ctx.log(f"  Seg {sn}: no videos, skip"); continue

            if len(paths) == 1:
                segment_videos[sn] = paths[0]
                ctx.log(f"  Seg {sn}: 1 sub-shot → {get_media_duration(paths[0]):.1f}s ✓")
            else:
                out = os.path.abspath(f"{ctx.output_dir}/segments/seg_{sn:02d}_concat.mp4")
                concatenate_clips(paths, out)
                segment_videos[sn] = out
                ctx.log(f"  Seg {sn}: {len(paths)} sub-shots → {get_media_duration(out):.1f}s ✓")

        # 8b: 对齐
        aligned = []
        for seg in ctx.segments:
            sn = seg["segment_number"]
            if sn not in segment_videos or sn not in ctx.tts_paths:
                continue
            out = f"{ctx.output_dir}/aligned/seg_{sn:02d}.mp4"
            ok = align_video_to_audio(segment_videos[sn], ctx.tts_paths[sn], out)
            if ok:
                vd = get_media_duration(segment_videos[sn])
                ad = get_media_duration(ctx.tts_paths[sn])
                fd = get_media_duration(out)
                ctx.log(f"  Seg {sn}: v={vd:.1f}s a={ad:.1f}s → {fd:.1f}s ✓")
                aligned.append(os.path.abspath(out))

        if not aligned:
            return StageResult(success=False, message="No aligned segments")

        # 8c: 拼接
        concat = os.path.abspath(f"{ctx.output_dir}/concat_no_bgm.mp4")
        concatenate_clips(aligned, concat)
        ctx.log(f"  Concat: {get_media_duration(concat):.1f}s")

        # 8d: 字幕
        srt_path = os.path.abspath(f"{ctx.output_dir}/subtitles.srt")
        current_time = 0.0
        srt_entries = []
        aligned_segs = set()
        for seg in ctx.segments:
            sn = seg["segment_number"]
            p = f"{ctx.output_dir}/aligned/seg_{sn:02d}.mp4"
            if os.path.abspath(p) in aligned:
                aligned_segs.add(sn)

        for seg in ctx.segments:
            sn = seg["segment_number"]
            if sn not in aligned_segs:
                continue
            ad = get_media_duration(ctx.tts_paths[sn])
            sh, sm = divmod(int(current_time), 3600)
            sm, ss = divmod(sm, 60)
            sms = int((current_time % 1) * 1000)
            et = current_time + ad
            eh, em = divmod(int(et), 3600)
            em, es = divmod(em, 60)
            ems = int((et % 1) * 1000)
            srt_entries.append(
                f"{len(srt_entries)+1}\n"
                f"{sh:02d}:{sm:02d}:{ss:02d},{sms:03d} --> "
                f"{eh:02d}:{em:02d}:{es:02d},{ems:03d}\n"
                f"{seg.get('narration_text', '')}\n"
            )
            current_time = et

        with open(srt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(srt_entries))

        concat_sub = os.path.abspath(f"{ctx.output_dir}/concat_with_sub.mp4")
        r = subprocess.run([
            "ffmpeg", "-y", "-i", concat,
            "-vf", f"subtitles={srt_path}:force_style='FontSize=16,PrimaryColour=&Hffffff,"
                   f"OutlineColour=&H000000,Outline=2,Alignment=2,MarginV=40'",
            "-c:a", "copy", concat_sub
        ], capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            ctx.log(f"  Subtitles failed, using no-subtitle version")
            concat_sub = concat
        else:
            ctx.log(f"  Subtitles: ✓")

        # 8e: BGM
        final = os.path.abspath(f"{ctx.output_dir}/final_video.mp4")
        bgm = os.path.abspath("data/bgm/romantic_sweet.mp3")
        overlay_bgm(concat_sub, bgm, final, bgm_volume=0.25)
        ctx.final_video_path = final
        ctx.final_duration = get_media_duration(final)
        ctx.final_size_mb = os.path.getsize(final) / 1024 / 1024
        ctx.log(f"  Final: {ctx.final_duration:.1f}s, {ctx.final_size_mb:.1f}MB")

        return StageResult(success=True)

    # ================================================================
    # Stage 9: Quality Gate
    # ================================================================
    def stage_quality_gate(self, ctx: WorkflowContext) -> StageResult:
        issues = []
        target = ctx.params.get("duration", 40)

        if ctx.final_duration < target * 0.5:
            issues.append(f"Duration {ctx.final_duration:.0f}s < 50% of target {target}s")

        # BGM check
        concat = os.path.abspath(f"{ctx.output_dir}/concat_no_bgm.mp4")
        final = ctx.final_video_path
        sample = str(min(15, ctx.final_duration / 2))
        vc = vf = -91.0
        for src, var_name in [(concat, "vc"), (final, "vf")]:
            r = subprocess.run(
                ["ffmpeg", "-i", src, "-ss", sample, "-t", "3",
                 "-af", "volumedetect", "-f", "null", "-"],
                capture_output=True, text=True, timeout=10)
            for line in r.stderr.split("\n"):
                if "mean_volume" in line:
                    try:
                        val = float(line.split(":")[1].split("dB")[0])
                        if var_name == "vc": vc = val
                        else: vf = val
                    except: pass

        diff = abs(vc - vf)
        if diff < 1.0:
            issues.append(f"BGM not audible (diff={diff:.1f}dB)")
        else:
            ctx.log(f"  BGM ✓ (diff={diff:.1f}dB)")

        total_subs = len(ctx.all_sub_shots)
        if ctx.total_generated < total_subs:
            issues.append(f"Missing videos: {ctx.total_generated}/{total_subs}")

        # 连续性
        prev_sid = None
        for seg in ctx.segments:
            sn = seg["segment_number"]
            sid = seg.get("scene_id", "")
            if prev_sid and sid == prev_sid:
                ctx.log(f"  Seg {sn-1}→{sn}: same scene ✓")
            elif prev_sid:
                ctx.log(f"  Seg {sn-1}→{sn}: scene change ✓")
            prev_sid = sid

        ctx.quality_issues = issues
        ctx.quality_passed = len(issues) == 0

        if issues:
            ctx.log(f"\n  ⚠ ISSUES ({len(issues)}):")
            for issue in issues:
                ctx.log(f"    - {issue}")
            ctx.log(f"  Quality gate: FAILED")
        else:
            ctx.log(f"\n  ✓ Quality gate: PASSED")

        return StageResult(success=True)

    # ================================================================
    # Internal helpers
    # ================================================================
    def _regenerate_single_shot(self, seg, target_duration):
        """Case 4: 让 LLM 重新生成单镜头。"""
        nt = seg.get("narration_text", "")
        scene_desc = seg.get("scene_description", "")
        chars = seg.get("characters_in_shot", [])

        system = """你是短剧导演，请为以下旁白生成一个单镜头的 video_prompt。
要求：
1. 只输出 JSON: {"shot_type": "...", "video_prompt": "...", "camera_movement": "..."}
2. video_prompt 只描述动作和镜头运动，不包含角色外貌和场景描述
3. 动作幅度要小，适合短时长视频
4. 只输出 JSON"""

        user = f"旁白: \"{nt}\"\n场景: {scene_desc}\n角色数: {len(chars)}\n时长: {int(target_duration)}秒"
        try:
            raw = chat_with_system(system, user, max_tokens=512)
            data = json.loads(_extract_json(raw))
            return [data]
        except Exception:
            return [{"shot_type": "中景", "video_prompt": "角色缓慢动作，镜头缓慢推近",
                     "camera_movement": "zoom_in"}]

    def _build_storyboard_prompt(self, duration):
        """构建 LLM 分镜 system prompt。"""
        return f"""你是一位顶级短剧导演兼编剧，擅长将小说文本改编为"解说类漫剧"短视频分镜。

## 你的任务
将原文改编为一部约 {duration} 秒的竖屏短视频分镜脚本。这是"旁白驱动"的漫剧——观众通过旁白听故事，画面配合营造氛围。

## 核心架构：叙事段 + 子镜头
每个"叙事段"(segment) 包含：
- 一段旁白（20-30字），连续播放
- 2-3个子镜头(sub_shots)，每个子镜头5秒，用不同景别和角度切换

## 旁白写作（最核心）
1. **保留原文精华**：经典对话、内心独白、氛围描写必须保留或改编进旁白
2. **讲故事而非描述画面**：不要"她走进大厅"，要"苏家破产，千金沦为秘书，她低头穿过嘲讽的目光"
3. **融入关键对话**：原文对话自然融入
4. **情感层次丰富**：每段旁白都有明确的情感基调
5. **每段旁白严格控制在20-30个汉字**

## 子镜头规则
1. 子镜头数量 = ceil(估算TTS时长 / 5)，通常2个
2. 估算TTS时长 ≈ ceil(字数/3) + 1
3. 相邻子镜头景别必须不同
4. 每个子镜头只描述5秒能完成的小动作

## 情绪标注
- happy/sad/angry/fearful/surprised/calm/whisper

## 角色设定
1. appearance_prompt: 冻结中文外貌标签（发色+发型+瞳色+肤色+体型+服装+饰品）
2. 色彩丰富，避免全黑灰
3. 男性强调"高大威严的成年男性"

## video_prompt 规则
只描述动作和镜头运动，禁止外貌和场景描述。
- ✅ "女子缓缓转头，眼中泛起泪光，镜头缓慢推近"
- ❌ "长黑发的女子在办公室里转头"

**双人镜头必须描述每个角色的动作。**

## 输出格式
严格JSON，所有prompt字段均使用中文：
{{{{
  "title": "标题",
  "character_profiles": [
    {{{{ "char_id": "char_xxx", "name": "名", "gender": "female",
      "appearance": "概述", "appearance_prompt": "冻结标签" }}}}
  ],
  "scene_backgrounds": [
    {{{{ "scene_id": "scene_xxx", "name": "场景名",
      "scene_prompt": "描述，以'漫画风格，动漫背景，无人物'结尾" }}}}
  ],
  "segments": [
    {{{{
      "segment_number": 1, "scene_id": "scene_xxx",
      "characters_in_shot": ["char_xxx"],
      "narration_text": "20-30字旁白", "emotion": "sad",
      "scene_description": "场景描述",
      "image_prompt": "杰作, 4K, 动漫风格, ...",
      "sub_shots": [
        {{{{"shot_type": "中景", "video_prompt": "...", "camera_movement": "tracking"}}}},
        {{{{"shot_type": "特写", "video_prompt": "...", "camera_movement": "zoom_in"}}}}
      ]
    }}}}
  ]
}}}}

## 约束
1. 4-5个叙事段，每段2-3个子镜头
2. 总子镜头数 × 5秒 ≈ {duration}s
3. 旁白 20-30 字
4. video_prompt 纯动作（中文）
5. 只输出JSON"""
