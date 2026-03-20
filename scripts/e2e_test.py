"""
E2E v5: 40s video, 10s per shot, real BGM, auto-rework.

Usage: python scripts/e2e_test.py [--duration 40] [--voice female-shaonv]
"""

import json, os, sys, time, asyncio, argparse, subprocess, shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

parser = argparse.ArgumentParser()
parser.add_argument("--duration", type=int, default=40)
parser.add_argument("--voice", type=str, default="female-shaonv")
parser.add_argument("--output", type=str, default="e2e_output/v5")
args = parser.parse_args()

DURATION, VOICE_ID, OUTPUT = args.duration, args.voice, args.output
FRAMES = 241  # ~10s per video clip
MAX_NARRATION = 35
MIN_NARRATION = 20
for d in ["images", "scenes", "videos", "audio", "aligned"]:
    os.makedirs(f"{OUTPUT}/{d}", exist_ok=True)

from app.services.ffmpeg_utils import (
    align_video_to_audio, concatenate_clips, overlay_bgm, get_media_duration
)

def log(msg): print(msg, flush=True)

# ============ STEP 1: Storyboard ============
log(f"\n{'='*60}\n[Step 1] Storyboard ({DURATION}s target)...")
with open("data/test_novel.txt") as f:
    novel = f.read()

from vendor.qwen.client import chat_with_system, _extract_json
from app.ai.prompts.narration_manga import build_storyboard_prompt
from app.services.narration_utils import shorten_narration_via_llm

prompts = build_storyboard_prompt(novel, "narration", "manga", DURATION, "normal", "9:16")
raw = chat_with_system(prompts["system_prompt"], prompts["user_prompt"], max_tokens=8192)
sb = json.loads(_extract_json(raw))
shots = sb.get("storyboards", [])

# Adjust narration lengths
for s in shots:
    nt = s.get("narration_text", "")
    if len(nt) > MAX_NARRATION:
        s["narration_text"] = shorten_narration_via_llm(nt, MAX_NARRATION, s.get("scene_description", ""))

with open(f"{OUTPUT}/storyboard.json", "w") as f:
    json.dump(sb, f, ensure_ascii=False, indent=2)

scenes = sb.get("scene_backgrounds", [])
log(f"  {len(shots)} shots, {len(scenes)} scenes")
for s in shots:
    log(f"  Shot {s['shot_number']}: {len(s.get('narration_text',''))}字 | '{s.get('narration_text','')}'")

# ============ STEP 1b: Scene backgrounds ============
log(f"\n[Step 1b] Scene backgrounds...")
from vendor.jimeng.t2i import submit_t2i_task, get_t2i_result, save_images

scene_images = {}
for sc in scenes:
    sid = sc["scene_id"]
    prompt = f"anime style, manga style, cel shading, vibrant colors, masterpiece, best quality, background art, no characters, no people, {sc.get('description_en', '')}"
    tid = submit_t2i_task(prompt, width=832, height=1472)
    if tid:
        r = get_t2i_result(tid, max_wait=120)
        if r:
            saved = save_images(r, output_dir=f"{OUTPUT}/scenes", prefix=sid)
            if saved: scene_images[sid] = saved[0]; log(f"  {sid}: ✓")
    time.sleep(3)

# Build scene description lookup
scene_desc_map = {}
for sc in scenes:
    scene_desc_map[sc["scene_id"]] = sc.get("description_en", "")

# ============ STEP 2: Shot images (with scene context) ============
log(f"\n[Step 2] Shot images (with scene context)...")
shot_images = {}
for s in shots:
    sn = s["shot_number"]
    prompt = s.get("image_prompt", "")
    if not prompt: continue

    # Inject scene background description into prompt for location consistency
    scene_id = s.get("scene_id", "")
    scene_desc = scene_desc_map.get(scene_id, "")
    if scene_desc and scene_desc.lower()[:20] not in prompt.lower():
        prompt = f"{prompt}, background: {scene_desc}"

    log(f"  Shot {sn} (scene={scene_id}): {prompt[:80]}...")
    tid = submit_t2i_task(prompt, width=832, height=1472)
    if tid:
        r = get_t2i_result(tid, max_wait=120)
        if r:
            saved = save_images(r, output_dir=f"{OUTPUT}/images", prefix=f"shot_{sn:02d}")
            if saved: shot_images[sn] = saved[0]; log(f"  Shot {sn}: ✓")
    time.sleep(3)
log(f"  {len(shot_images)}/{len(shots)} images")

# ============ STEP 3: Videos (I2V 720P, 10s) ============
log(f"\n[Step 3] Videos (I2V 720P, {FRAMES} frames ≈ {FRAMES/24:.0f}s)...")
from vendor.jimeng.i2v import submit_i2v_task, get_i2v_result, save_video
from app.ai.prompts.video_motion import build_video_motion_prompt

shot_videos = {}
for s in shots:
    sn = s["shot_number"]
    if sn not in shot_images: continue
    motion = build_video_motion_prompt(s.get("scene_description",""), s.get("camera_movement","static"), "manga")
    tid = submit_i2v_task(shot_images[sn], prompt=motion, frames=FRAMES)
    if tid:
        r = get_i2v_result(tid, max_wait=600)
        if r:
            saved = save_video(r, output_dir=f"{OUTPUT}/videos", prefix=f"shot_{sn:02d}")
            if saved: shot_videos[sn] = saved[0]; log(f"  Shot {sn}: ✓")
    time.sleep(10)
log(f"  {len(shot_videos)}/{len(shots)} videos")

# ============ STEP 4: TTS ============
log(f"\n[Step 4] TTS ({VOICE_ID}, emotion=happy, speed=0.9)...")

async def gen_tts():
    from app.ai.providers.minimax_tts import MiniMaxTTSProvider
    provider = MiniMaxTTSProvider()
    paths = {}
    for s in shots:
        sn = s["shot_number"]
        text = s.get("narration_text", "")
        if not text: continue
        job_id = await provider.submit_job({
            "text": text, "voice_id": VOICE_ID, "speed": 0.9, "emotion": "happy",
        })
        status = await provider.poll_job(job_id)
        if status.result_data:
            path = f"{OUTPUT}/audio/shot_{sn:02d}.mp3"
            with open(path, "wb") as f: f.write(status.result_data)
            paths[sn] = path
            log(f"  Shot {sn}: {len(status.result_data)//1024}KB ✓")
        time.sleep(1)
    return paths

tts_paths = asyncio.run(gen_tts())
log(f"  {len(tts_paths)}/{len(shots)} TTS")

# ============ STEP 5: Assembly ============
log(f"\n[Step 5] Assembly...")
aligned = []
for s in shots:
    sn = s["shot_number"]
    if sn not in shot_videos or sn not in tts_paths: continue
    out = f"{OUTPUT}/aligned/shot_{sn:02d}.mp4"
    ok = align_video_to_audio(shot_videos[sn], tts_paths[sn], out)
    if ok:
        vd = get_media_duration(shot_videos[sn])
        ad = get_media_duration(tts_paths[sn])
        fd = get_media_duration(out)
        log(f"  Shot {sn}: v={vd:.1f}s a={ad:.1f}s → {fd:.1f}s ✓")
        aligned.append(os.path.abspath(out))

concat = os.path.abspath(f"{OUTPUT}/concat_no_bgm.mp4")
concatenate_clips(aligned, concat)
log(f"  Concat: {get_media_duration(concat):.1f}s")

final = os.path.abspath(f"{OUTPUT}/final_video.mp4")
bgm = os.path.abspath("data/bgm/romantic_sweet.mp3")
overlay_bgm(concat, bgm, final, bgm_volume=0.25)
dur = get_media_duration(final)
size = os.path.getsize(final) / 1024 / 1024
log(f"  Final: {dur:.1f}s, {size:.1f}MB")

# ============ STEP 6: Self-review ============
log(f"\n{'='*60}\n[Step 6] Self-review...")
issues = []

# Duration
if dur < DURATION * 0.5:
    issues.append(f"Duration {dur:.0f}s < 50% of target {DURATION}s")

# Freeze frames
for s in shots:
    sn = s["shot_number"]
    if sn in shot_videos and sn in tts_paths:
        vd = get_media_duration(shot_videos[sn])
        ad = get_media_duration(tts_paths[sn])
        if ad > vd + 1.0:
            issues.append(f"Shot {sn}: audio ({ad:.1f}s) > video ({vd:.1f}s) → freeze frames")

# BGM
r_c = subprocess.run(["ffmpeg","-i",concat,"-af","volumedetect","-f","null","-"], capture_output=True, text=True, timeout=10)
r_f = subprocess.run(["ffmpeg","-i",final,"-af","volumedetect","-f","null","-"], capture_output=True, text=True, timeout=10)
vc = vf = 0
for l in r_c.stderr.split("\n"):
    if "mean_volume" in l: vc = float(l.split(":")[1].split("dB")[0])
for l in r_f.stderr.split("\n"):
    if "mean_volume" in l: vf = float(l.split(":")[1].split("dB")[0])
diff = abs(vc - vf)
log(f"  BGM: concat={vc:.1f}dB final={vf:.1f}dB diff={diff:.1f}dB {'✓' if diff > 0.5 else '✗'}")
if diff < 0.5:
    issues.append("BGM not audible")

# Completeness
if len(shot_videos) < len(shots):
    issues.append(f"Only {len(shot_videos)}/{len(shots)} videos")

if issues:
    log(f"\n  ⚠ Issues ({len(issues)}):")
    for i in issues: log(f"    - {i}")
else:
    log(f"\n  ✓ All checks passed!")

log(f"\n{'='*60}")
log(f"★ Output: {OUTPUT}/final_video.mp4 ({dur:.1f}s, {size:.1f}MB)")
log(f"{'='*60}")
