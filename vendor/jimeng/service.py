"""
即梦AI 火山引擎 VisualService 公共服务层
封装 API 调用、轮询等通用逻辑
"""

import json
import time

from volcengine.ApiInfo import ApiInfo
from volcengine.visual.VisualService import VisualService

from .config import AK, SK


def create_service(actions: list[str]) -> VisualService:
    """创建并注册指定 actions 的 VisualService"""
    vs = VisualService()
    vs.set_ak(AK)
    vs.set_sk(SK)
    for action in actions:
        vs.api_info[action] = ApiInfo(
            "POST", "/",
            {"Action": action, "Version": "2022-08-31"},
            {}, {},
        )
    return vs


def call_api(vs: VisualService, action: str, form: dict) -> dict:
    """调用 API 并解析响应"""
    try:
        res = vs.json(action, {}, json.dumps(form))
        res_str = res if isinstance(res, str) else res.decode("utf-8", "replace")
        j = json.loads(res_str)
        return j.get("Result", j)
    except Exception as e:
        err = e.args[0].decode("utf-8", "replace") if isinstance(e.args[0], bytes) else str(e)
        try:
            j = json.loads(err)
            return j.get("Result", j)
        except Exception:
            return {"code": -1, "message": err[:300]}


def poll_result(
    vs: VisualService,
    action: str,
    form: dict,
    max_wait: int = 300,
    interval: int = 5,
    check_done=None,
) -> dict | None:
    """
    轮询异步任务结果

    check_done: 自定义判断完成的函数 (data) -> bool，默认检查 binary_data_base64/video_url/image_urls
    """
    print(f"等待生成结果 (最多 {max_wait}s)...")
    start = time.time()

    while time.time() - start < max_wait:
        result = call_api(vs, action, form)
        code = result.get("code", -1)
        data = result.get("data", {})

        if code == 10000:
            if check_done:
                if check_done(data):
                    print(f"\n  生成完成! ({int(time.time() - start)}s)")
                    return data
            else:
                # 默认检查
                has_video = bool(data.get("video_url", ""))
                has_binary = any(b for b in data.get("binary_data_base64", []) if b)
                has_images = bool(data.get("image_urls", []))
                if has_video or has_binary or has_images or data.get("status") == "done":
                    print(f"\n  生成完成! ({int(time.time() - start)}s)")
                    return data

            print(f"  生成中... ({int(time.time() - start)}s)", end="\r")
        elif code == 20000:
            print(f"  处理中... ({int(time.time() - start)}s)", end="\r")
        elif code in (50100, 50000):
            print(f"  排队中... ({int(time.time() - start)}s)", end="\r")
        else:
            msg = result.get("message", "")
            print(f"\n  错误 code={code}, message={msg}")
            return None

        time.sleep(interval)

    print(f"\n  超时 ({max_wait}s)")
    return None
