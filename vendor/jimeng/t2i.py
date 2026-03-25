"""
即梦AI - 图片生成 4.0 (文生图)

异步调用流程 (正式版通用异步接口):
1. CVSync2AsyncSubmitTask 提交任务 → 获取 task_id
2. CVSync2AsyncGetResult  轮询结果 → 获取生成的图片

注意: 试用版使用 JimengT2IV40SubmitTask (Version=2024-06-06)，
      正式版使用 CVSync2AsyncSubmitTask (Version=2022-08-31)。
"""

import base64
import json
import os

import requests

from .service import call_api, create_service, poll_result

SUBMIT_ACTION = "CVSync2AsyncSubmitTask"
GET_ACTION = "CVSync2AsyncGetResult"
ACTIONS = [SUBMIT_ACTION, GET_ACTION]


def submit_t2i_task(
    prompt: str,
    width: int = 1024,
    height: int = 1024,
    seed: int = -1,
    scale: float = 0.5,
) -> str | None:
    """提交文生图任务，返回 task_id"""
    vs = create_service(ACTIONS)
    form = {
        "req_key": "jimeng_t2i_v40",
        "prompt": prompt,
        "width": width,
        "height": height,
        "seed": seed,
        "scale": scale,
        "use_sr": True,
        "return_url": True,
    }

    print(f"提交文生图任务...")
    print(f"  prompt: {prompt}")
    print(f"  尺寸: {width}x{height}")

    result = call_api(vs, SUBMIT_ACTION, form)
    code = result.get("code", -1)
    print(f"  code={code}, message={result.get('message', '')}")

    if code != 10000:
        print(f"  错误: {json.dumps(result, ensure_ascii=False, indent=2)[:500]}")
        return None

    task_id = result.get("data", {}).get("task_id")
    print(f"  task_id: {task_id}")
    return task_id


def get_t2i_result(task_id: str, max_wait: int = 120) -> dict | None:
    """轮询获取文生图结果"""
    vs = create_service(ACTIONS)
    form = {"req_key": "jimeng_t2i_v40", "task_id": task_id}

    def check_done(data):
        has_images = bool(data.get("image_urls", []))
        has_binary = any(b for b in data.get("binary_data_base64", []) if b)
        if has_images or has_binary:
            return True
        resp_data = data.get("resp_data")
        if resp_data:
            rd = json.loads(resp_data) if isinstance(resp_data, str) else resp_data
            return bool(rd.get("image_urls") or rd.get("binary_data_base64"))
        return False

    return poll_result(vs, GET_ACTION, form, max_wait=max_wait, check_done=check_done)


def save_images(data: dict, output_dir: str = ".", prefix: str = "jimeng_t2i") -> list[str]:
    """保存生成的图片，返回文件路径列表"""
    saved = []

    for i, b64 in enumerate(data.get("binary_data_base64", [])):
        if b64:
            path = os.path.join(output_dir, f"{prefix}_{i}.png")
            with open(path, "wb") as f:
                f.write(base64.b64decode(b64))
            saved.append(path)
            print(f"  已保存: {path}")

    if not saved:
        for i, url in enumerate(data.get("image_urls", [])):
            if url:
                path = os.path.join(output_dir, f"{prefix}_{i}.png")
                r = requests.get(url, timeout=30)
                with open(path, "wb") as f:
                    f.write(r.content)
                saved.append(path)
                print(f"  已下载: {path}")

    return saved


def generate_image(
    prompt: str,
    width: int = 1024,
    height: int = 1024,
    output_dir: str = ".",
    prefix: str = "jimeng_t2i",
) -> list[str]:
    """一站式文生图：提交 -> 轮询 -> 保存"""
    task_id = submit_t2i_task(prompt, width=width, height=height)
    if not task_id:
        return []

    data = get_t2i_result(task_id)
    if not data:
        print("获取结果失败")
        return []

    return save_images(data, output_dir=output_dir, prefix=prefix)
