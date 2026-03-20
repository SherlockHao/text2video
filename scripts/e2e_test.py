"""
E2E v4: Complete pipeline with scene backgrounds, BGM fix, and real self-review.

Usage: python scripts/e2e_test.py [--duration 20] [--voice female-shaonv]
"""

import json
import os
import sys
import time
import asyncio
import argparse
import subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

parser = argparse.ArgumentParser()
parser.add_argument("--duration", type=int, default=20)
parser.add_argument("--voice", type=str, default="female-shaonv")
parser.add_argument("--output", type=str, default="e2e_output/v4")
args = parser.parse_args()

DURATION = args.duration
VOICE_ID = args.voice
OUTPUT = args.output
for d in ["images", "scenes", "videos", "audio", "aligned"]:
    os.makedirs(f"{OUTPUT}/{d}", exist_ok=True)

print(f"{'='*60}")
print(f"E2E v4 — {DURATION}s, Voice: {VOICE_ID}")
print(f"{'='*60}\n")

# ============ STEP 1: Storyboard ============
print("[Step 1] Storyboard...")
with open("data/test_novel.txt") as f:
    novel = f.read()

from vendor.qwen.client import chat_with_system, _extract_json
from app.ai.prompts.narration_manga import build_storyboard_prompt

prompts = build_storyboard_prompt(novel, "narration", "manga", DURATION, "normal", "9:16")
raw = chat_with_system(prompts["system_prompt"], prompts["user_prompt"], max_tokens=8192)
sb = json.loads(_extract_json(raw))
shots = sb.get("storyboards", [])

# Shorten narration
from app.services.narration_utils import shorten_narration_via_llm
for s in shots:
    nt = s.get("narration_text", "")
    if len(nt) > 18:
        s["narration_text"] = shorten_narration_via_llm(nt, 18, s.get("scene_description", ""))

with open(f"{OUTPUT}/storyboard.json", "w") as f:
    json.dump(sb, f, ensure_ascii=False, indent=2)

print(f"  Title: {sb.get('title')}")
print(f"  Characters: {[c['name'] for c in sb.get('character_profiles', [])]}")
scenes = sb.get("scene_backgrounds", [])
print(f"  Scenes: {[s['name'] for s in scenes]}")
for s in shots:
    print(f"  Shot {s['shot_number']}: scene={s.get('scene_id','?')} | '{s.get('narration_text','')}'")
print()

# ============ STEP 1b: Generate scene backgrounds ============
print("[Step 1b] Scene backgrounds...")
from vendor.jimeng.t2i import submit_t2i_task, get_t2i_result, save_images

scene_images = {}
for sc in scenes:
    sid = sc["scene_id"]
    desc = sc.get("description_en", "")
    prompt = f"anime style, manga style, cel shading, vibrant colors, masterpiece, best quality, background art, no characters, no people, {desc}"
    print(f"  {sid}: {prompt[:80]}...")
    tid = submit_t2i_task(prompt, width=832, height=1472)
    if tid:
        r = get_t2i_result(tid, max_wait=120)
        if r:
            saved = save_images(r, output_dir=f"{OUTPUT}/scenes", prefix=sid)
            if saved:
                scene_images[sid] = saved[0]
                print(f"  {sid}: ✓")
    time.sleep(3)
print()

# ============ STEP 2: Shot images ============
print("[Step 2] Shot images...")
shot_images = {}
for s in shots:
    sn = s["shot_number"]
    prompt = s.get("image_prompt", "")
    if not prompt:
        continue
    tid = submit_t2i_task(prompt, width=832, height=1472)
    if tid:
        r = get_t2i_result(tid, max_wait=120)
        if r:
            saved = save_images(r, output_dir=f"{OUTPUT}/images", prefix=f"shot_{sn:02d}")
            if saved:
                shot_images[sn] = saved[0]
                print(f"  Shot {sn}: ✓")
    time.sleep(3)
print(f"  {len(shot_images)}/{len(shots)} images\n")

# ============ STEP 3: Videos (I2V 720P) ============
print("[Step 3] Videos (I2V 720P)...")
from vendor.jimeng.i2v import submit_i2v_task, get_i2v_result, save_video
from app.ai.prompts.video_motion import build_video_motion_prompt

shot_videos = {}
for s in shots:
    sn = s["shot_number"]
    if sn not in shot_images:
        continue
    motion = build_video_motion_prompt(
        s.get("scene_description", ""), s.get("camera_movement", "static"), "manga"
    )
    tid = submit_i2v_task(shot_images[sn], prompt=motion, frames=121)
    if tid:
        r = get_i2v_result(tid, max_wait=300)
        if r:
            saved = save_video(r, output_dir=f"{OUTPUT}/videos", prefix=f"shot_{sn:02d}")
            if saved:
                shot_videos[sn] = saved[0]
                print(f"  Shot {sn}: ✓")
    time.sleep(10)
print(f"  {len(shot_videos)}/{len(shots)} videos\n")

# ============ STEP 4: TTS ============
print(f"[Step 4] TTS ({VOICE_ID})...")

async def gen_tts():
    from app.ai.providers.minimax_tts import MiniMaxTTSProvider
    provider = MiniMaxTTSProvider()
    paths = {}
    for s in shots:
        sn = s["shot_number"]
        text = s.get("narration_text", "")
        if not text:
            continue
        job_id = await provider.submit_job({
            "text": text, "voice_id": VOICE_ID,
            "speed": 0.9, "emotion": "happy",
        })
        status = await provider.poll_job(job_id)
        if status.result_data:
            path = f"{OUTPUT}/audio/shot_{sn:02d}.mp3"
            with open(path, "wb") as f:
                f.write(status.result_data)
            paths[sn] = path
            print(f"  Shot {sn}: ✓")
        time.sleep(1)
    return paths

tts_paths = asyncio.run(gen_tts())
print(f"  {len(tts_paths)}/{len(shots)} TTS\n")

# ============ STEP 5: Assembly ============
print("[Step 5] Assembly...")
from app.services.ffmpeg_utils import (
    align_video_to_audio, concatenate_clips, overlay_bgm, get_media_duration
)

aligned = []
for s in shots:
    sn = s["shot_number"]
    if sn not in shot_videos or sn not in tts_paths:
        continue
    out = f"{OUTPUT}/aligned/shot_{sn:02d}.mp4"
    ok = align_video_to_audio(shot_videos[sn], tts_paths[sn], out)
    if ok:
        vd = get_media_duration(shot_videos[sn])
        ad = get_media_duration(tts_paths[sn])
        fd = get_media_duration(out)
        print(f"  Shot {sn}: v={vd:.1f}s a={ad:.1f}s → {fd:.1f}s ✓")
        aligned.append(os.path.abspath(out))

concat = os.path.abspath(f"{OUTPUT}/concat_no_bgm.mp4")
concatenate_clips(aligned, concat)

final = os.path.abspath(f"{OUTPUT}/final_video.mp4")
bgm = os.path.abspath("data/bgm/romantic_sweet.mp3")
overlay_bgm(concat, bgm, final, bgm_volume=0.35)

dur = get_media_duration(final)
size = os.path.getsize(final) / 1024 / 1024
print(f"\n  ★ Final: {dur:.1f}s, {size:.1f}MB")

# ============ STEP 6: REAL Self-review ============
print(f"\n{'='*60}")
print("[Step 6] Self-review...")
issues = []

# 6a. Duration check
if dur < DURATION * 0.6:
    issues.append(f"Duration {dur:.0f}s < 60% of target {DURATION}s")

# 6b. Freeze frame check
for s in shots:
    sn = s["shot_number"]
    if sn in shot_videos and sn in tts_paths:
        vd = get_media_duration(shot_videos[sn])
        ad = get_media_duration(tts_paths[sn])
        if ad > vd + 0.5:
            issues.append(f"Shot {sn}: freeze frames (audio {ad:.1f}s > video {vd:.1f}s)")

# 6c. BGM actually present — compare audio levels
r_concat = subprocess.run(
    ["ffmpeg", "-i", concat, "-af", "volumedetect", "-f", "null", "-"],
    capture_output=True, text=True, timeout=10
)
r_final = subprocess.run(
    ["ffmpeg", "-i", final, "-af", "volumedetect", "-f", "null", "-"],
    capture_output=True, text=True, timeout=10
)
concat_vol = None
final_vol = None
for line in r_concat.stderr.split("\n"):
    if "mean_volume" in line:
        concat_vol = float(line.split("mean_volume:")[1].split("dB")[0].strip())
for line in r_final.stderr.split("\n"):
    if "mean_volume" in line:
        final_vol = float(line.split("mean_volume:")[1].split("dB")[0].strip())

print(f"  Audio level - concat: {concat_vol}dB, final: {final_vol}dB")
if concat_vol and final_vol and abs(concat_vol - final_vol) < 0.5:
    issues.append(f"BGM not audible (volume diff only {abs(concat_vol-final_vol):.1f}dB)")
else:
    print(f"  BGM mixed in: volume diff {abs(concat_vol-final_vol):.1f}dB ✓")

# 6d. File integrity
if os.path.getsize(final) < 100 * 1024:
    issues.append("File too small (<100KB)")

# 6e. Check completeness
if len(shot_videos) < len(shots):
    issues.append(f"Only {len(shot_videos)}/{len(shots)} videos generated")

if issues:
    print(f"\n  ⚠ Issues ({len(issues)}):")
    for i in issues:
        print(f"    - {i}")
else:
    print(f"\n  ✓ All checks passed!")

print(f"\n{'='*60}")
print(f"Output: {OUTPUT}/final_video.mp4")
print(f"{'='*60}")
