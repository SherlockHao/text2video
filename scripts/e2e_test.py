"""
E2E v3: Complete pipeline test with all quality fixes.

Usage: python scripts/e2e_test.py [--duration 20] [--voice female-shaonv]
"""

import json
import os
import sys
import time
import asyncio
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ============ Config ============
parser = argparse.ArgumentParser()
parser.add_argument("--duration", type=int, default=20, help="Target video duration in seconds")
parser.add_argument("--voice", type=str, default="female-shaonv", help="MiniMax TTS voice_id")
parser.add_argument("--output", type=str, default="e2e_output/v3", help="Output directory")
args = parser.parse_args()

DURATION = args.duration
VOICE_ID = args.voice
OUTPUT = args.output
os.makedirs(f"{OUTPUT}/images", exist_ok=True)
os.makedirs(f"{OUTPUT}/videos", exist_ok=True)
os.makedirs(f"{OUTPUT}/audio", exist_ok=True)
os.makedirs(f"{OUTPUT}/aligned", exist_ok=True)

print(f"{'='*60}")
print(f"E2E Test v3 — Target: {DURATION}s, Voice: {VOICE_ID}")
print(f"Output: {OUTPUT}")
print(f"{'='*60}\n")

# ============ STEP 1: Storyboard ============
print("[Step 1] Generating storyboard...")
with open("data/test_novel.txt") as f:
    novel = f.read()

from vendor.qwen.client import chat_with_system, _extract_json
from app.ai.prompts.narration_manga import build_storyboard_prompt

prompts = build_storyboard_prompt(novel, "narration", "manga", DURATION, "normal", "9:16")
raw = chat_with_system(prompts["system_prompt"], prompts["user_prompt"], max_tokens=8192)
sb = json.loads(_extract_json(raw))

shots = sb.get("storyboards", [])
total_dur = sum(s.get("duration_seconds", 0) for s in shots)
print(f"  Title: {sb.get('title')}")
print(f"  Shots: {len(shots)}, Duration: {total_dur}s")
for s in shots:
    nt = s.get("narration_text", "")
    print(f"  Shot {s['shot_number']}: {s.get('duration_seconds')}s | {len(nt)}字 | '{nt}'")

# Auto-shorten any narration > 20 chars
from app.services.narration_utils import shorten_narration_via_llm
MAX_CHARS = 18
for s in shots:
    nt = s.get("narration_text", "")
    if len(nt) > MAX_CHARS:
        shortened = shorten_narration_via_llm(nt, MAX_CHARS, s.get("scene_description", ""))
        print(f"  [Shortened] Shot {s['shot_number']}: {len(nt)}→{len(shortened)} '{shortened}'")
        s["narration_text"] = shortened

with open(f"{OUTPUT}/storyboard.json", "w") as f:
    json.dump(sb, f, ensure_ascii=False, indent=2)
print("[Step 1] DONE ✓\n")

# ============ STEP 2: Images ============
print("[Step 2] Generating images...")
from vendor.jimeng.t2i import submit_t2i_task, get_t2i_result, save_images

shot_images = {}
for s in shots:
    sn = s["shot_number"]
    prompt = s.get("image_prompt", "")
    if not prompt:
        continue
    task_id = submit_t2i_task(prompt, width=832, height=1472)
    if task_id:
        r = get_t2i_result(task_id, max_wait=120)
        if r:
            saved = save_images(r, output_dir=f"{OUTPUT}/images", prefix=f"shot_{sn:02d}")
            if saved:
                shot_images[sn] = saved[0]
                print(f"  Shot {sn}: ✓")
    time.sleep(3)
print(f"[Step 2] {len(shot_images)}/{len(shots)} images ✓\n")

# ============ STEP 3: Videos (I2V 720P) ============
print("[Step 3] Generating videos (I2V 720P)...")
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
    tid = submit_i2v_task(shot_images[sn], prompt=motion, frames=121)  # 5s at 720P
    if tid:
        r = get_i2v_result(tid, max_wait=300)
        if r:
            saved = save_video(r, output_dir=f"{OUTPUT}/videos", prefix=f"shot_{sn:02d}")
            if saved:
                shot_videos[sn] = saved[0]
                print(f"  Shot {sn}: ✓")
    time.sleep(10)  # Rate limit protection
print(f"[Step 3] {len(shot_videos)}/{len(shots)} videos ✓\n")

# ============ STEP 4: TTS ============
print(f"[Step 4] Generating TTS (voice={VOICE_ID})...")

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
            print(f"  Shot {sn}: {len(status.result_data)} bytes ✓")
        time.sleep(1)
    return paths

tts_paths = asyncio.run(gen_tts())
print(f"[Step 4] {len(tts_paths)}/{len(shots)} TTS ✓\n")

# ============ STEP 5: Assembly ============
print("[Step 5] Assembling...")
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
        print(f"  Shot {sn}: video={vd:.1f}s audio={ad:.1f}s → {fd:.1f}s ✓")
        aligned.append(os.path.abspath(out))

if not aligned:
    print("  No clips to assemble!")
    sys.exit(1)

concat_path = os.path.abspath(f"{OUTPUT}/concat_no_bgm.mp4")
concatenate_clips(aligned, concat_path)
print(f"  Concat: {get_media_duration(concat_path):.1f}s ✓")

final_path = os.path.abspath(f"{OUTPUT}/final_video.mp4")
bgm_path = os.path.abspath("data/bgm/romantic_sweet.mp3")
ok = overlay_bgm(concat_path, bgm_path, final_path, bgm_volume=0.25)
if ok:
    dur = get_media_duration(final_path)
    size = os.path.getsize(final_path) / 1024 / 1024
    print(f"  BGM overlay: ✓")
    print(f"\n{'='*60}")
    print(f"★ FINAL: {final_path}")
    print(f"  Duration: {dur:.1f}s | Size: {size:.1f}MB")
    print(f"  Shots: {len(aligned)} | Voice: {VOICE_ID}")
    print(f"{'='*60}")
else:
    print("  BGM failed, using concat version")
    import shutil
    shutil.copy2(concat_path, final_path)

# ============ STEP 6: Self-review ============
print("\n[Step 6] Self-review...")
dur = get_media_duration(final_path)
issues = []
if dur < DURATION * 0.5:
    issues.append(f"Duration {dur:.0f}s is less than 50% of target {DURATION}s")
if not os.path.exists(final_path):
    issues.append("Final video file missing")
if os.path.getsize(final_path) < 100 * 1024:
    issues.append("Final video file too small (<100KB)")

# Check each aligned clip for freeze frames (video shorter than audio)
for s in shots:
    sn = s["shot_number"]
    if sn in shot_videos and sn in tts_paths:
        vd = get_media_duration(shot_videos[sn])
        ad = get_media_duration(tts_paths[sn])
        if ad > vd + 0.5:
            issues.append(f"Shot {sn}: audio ({ad:.1f}s) > video ({vd:.1f}s), freeze frames likely")

if issues:
    print(f"  Issues found ({len(issues)}):")
    for i in issues:
        print(f"    - {i}")
else:
    print("  No issues found ✓")
print("\nDONE.")
