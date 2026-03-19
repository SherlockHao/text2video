"""
即梦AI - 视频生成 3.0 1080P (图生视频_首帧)
API Explorer: https://api.volcengine.com/api-docs/view?serviceCode=cv&version=2024-06-06&action=JimengI2VFirstV301080SubmitTask

异步调用流程:
1. JimengI2VFirstV301080SubmitTask 提交任务 → 获取 task_id
2. JimengI2VFirstV301080GetResult  轮询结果 → 获取生成的视频
"""

import base64
import json
import os

import requests

from .service import call_api, create_service, poll_result

ACTIONS = ["JimengI2VFirstV301080SubmitTask", "JimengI2VFirstV301080GetResult"]


def submit_i2v_task(
    image_path: str,
    prompt: str = "",
    seed: int = -1,
    frames: int = 121,
) -> str | None:
    """提交图生视频任务，返回 task_id"""
    vs = create_service(ACTIONS)

    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

    form = {
        "req_key": "jimeng_i2v_first_v30_1080",
        "binary_data_base64": [img_b64],
        "prompt": prompt,
        "seed": seed,
        "frames": frames,
    }

    print(f"提交图生视频任务...")
    print(f"  首帧图片: {image_path}")
    print(f"  prompt: {prompt or '(无)'}")
    print(f"  帧数: {frames} (~{frames / 24:.1f}s @24fps)")

    result = call_api(vs, "JimengI2VFirstV301080SubmitTask", form)
    code = result.get("code", -1)
    print(f"  code={code}, message={result.get('message', '')}")

    if code != 10000:
        print(f"  错误: {json.dumps(result, ensure_ascii=False, indent=2)[:500]}")
        return None

    task_id = result.get("data", {}).get("task_id")
    print(f"  task_id: {task_id}")
    return task_id


def get_i2v_result(task_id: str, max_wait: int = 600) -> dict | None:
    """轮询获取视频生成结果（1080P较慢，默认等待10分钟）"""
    vs = create_service(ACTIONS)
    form = {"req_key": "jimeng_i2v_first_v30_1080", "task_id": task_id}
    return poll_result(vs, "JimengI2VFirstV301080GetResult", form, max_wait=max_wait)


def save_video(data: dict, output_dir: str = ".", prefix: str = "jimeng_video") -> list[str]:
    """保存生成的视频，返回文件路径列表"""
    saved = []

    for i, b64 in enumerate(data.get("binary_data_base64", [])):
        if b64:
            path = os.path.join(output_dir, f"{prefix}_{i}.mp4")
            with open(path, "wb") as f:
                f.write(base64.b64decode(b64))
            saved.append(path)
            print(f"  已保存: {path}")

    if not saved:
        video_url = data.get("video_url", "")
        if video_url:
            path = os.path.join(output_dir, f"{prefix}_0.mp4")
            print(f"  下载视频中...")
            r = requests.get(video_url, timeout=120)
            with open(path, "wb") as f:
                f.write(r.content)
            saved.append(path)
            print(f"  已下载: {path} ({len(r.content) / 1024 / 1024:.1f}MB)")

    return saved


def generate_video(
    image_path: str,
    prompt: str = "",
    frames: int = 121,
    output_dir: str = ".",
    prefix: str = "jimeng_video",
) -> list[str]:
    """一站式图生视频：提交 -> 轮询 -> 保存"""
    task_id = submit_i2v_task(image_path, prompt=prompt, frames=frames)
    if not task_id:
        return []

    data = get_i2v_result(task_id)
    if not data:
        print("获取结果失败")
        return []

    return save_video(data, output_dir=output_dir, prefix=prefix)
