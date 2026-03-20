"""
即梦AI - 视频生成 3.0 720P (文生视频)
Action: JimengT2VV30SubmitTask / JimengT2VV30GetResult
req_key: jimeng_t2v_v30
Version: 2024-06-06

支持直接用文本描述生成视频，无需先生成图片。
aspect_ratio: "16:9", "4:3", "1:1", "3:4", "9:16", "21:9"
frames: 121 (~5s) 或 241 (~10s)
"""

import json

from .service import call_api, create_service, poll_result

ACTIONS = ["JimengT2VV30SubmitTask", "JimengT2VV30GetResult"]
REQ_KEY = "jimeng_t2v_v30"


def submit_t2v_task(
    prompt: str,
    aspect_ratio: str = "9:16",
    seed: int = -1,
    frames: int = 121,
) -> str | None:
    """提交文生视频任务，返回 task_id"""
    vs = create_service(ACTIONS)
    form = {
        "req_key": REQ_KEY,
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "seed": seed,
        "frames": frames,
    }

    print(f"提交文生视频任务 (3.0 720P)...")
    print(f"  prompt: {prompt[:80]}...")
    print(f"  比例: {aspect_ratio}, 帧数: {frames} (~{frames / 24:.1f}s)")

    result = call_api(vs, "JimengT2VV30SubmitTask", form)
    code = result.get("code", -1)
    print(f"  code={code}, message={result.get('message', '')}")

    if code != 10000:
        print(f"  错误: {json.dumps(result, ensure_ascii=False)[:300]}")
        return None

    task_id = result.get("data", {}).get("task_id")
    print(f"  task_id: {task_id}")
    return task_id


def get_t2v_result(task_id: str, max_wait: int = 600) -> dict | None:
    """轮询获取文生视频结果"""
    vs = create_service(ACTIONS)
    form = {"req_key": REQ_KEY, "task_id": task_id}

    def check_done(data):
        has_video = bool(data.get("video_url", ""))
        has_binary = any(b for b in data.get("binary_data_base64", []) if b)
        return has_video or has_binary or data.get("status") == "done"

    return poll_result(vs, "JimengT2VV30GetResult", form, max_wait=max_wait, check_done=check_done)
