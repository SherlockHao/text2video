"""
可灵 (Kling) API 客户端
基于 JWT 认证，支持文生图、图生视频、角色参考绑定
API文档: https://app.klingai.com/global/dev/document-api
"""

import base64
import json
import time
import jwt
import requests

from .config import ACCESS_KEY, SECRET_KEY, BASE_URL


def _generate_jwt_token(access_key: str = None, secret_key: str = None) -> str:
    """生成 Kling API JWT Token (有效期30分钟)"""
    ak = access_key or ACCESS_KEY
    sk = secret_key or SECRET_KEY

    headers = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "iss": ak,
        "exp": int(time.time()) + 1800,  # 30 min
        "nbf": int(time.time()) - 5,
    }
    return jwt.encode(payload, sk, algorithm="HS256", headers=headers)


class KlingClient:
    """可灵 API 客户端"""

    def __init__(self, access_key: str = None, secret_key: str = None):
        self.access_key = access_key or ACCESS_KEY
        self.secret_key = secret_key or SECRET_KEY
        self.base_url = BASE_URL
        self._token = None
        self._token_exp = 0

    def _get_token(self) -> str:
        if self._token is None or time.time() > self._token_exp - 60:
            self._token = _generate_jwt_token(self.access_key, self.secret_key)
            self._token_exp = time.time() + 1800
        return self._token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
        }

    def _post(self, endpoint: str, data: dict) -> dict:
        url = f"{self.base_url}{endpoint}"
        resp = requests.post(url, headers=self._headers(), json=data, timeout=120)
        if resp.status_code != 200:
            try:
                err = resp.json()
                print(f"  Kling API error: {resp.status_code} code={err.get('code')} msg={err.get('message')}")
            except Exception:
                print(f"  Kling API error: {resp.status_code} {resp.text[:200]}")
        resp.raise_for_status()
        return resp.json()

    def _get(self, endpoint: str, retries: int = 3) -> dict:
        url = f"{self.base_url}{endpoint}"
        for attempt in range(retries):
            try:
                resp = requests.get(url, headers=self._headers(), timeout=30)
                resp.raise_for_status()
                return resp.json()
            except (requests.exceptions.SSLError, requests.exceptions.ConnectionError) as e:
                if attempt < retries - 1:
                    import time as _t
                    _t.sleep(5)
                    continue
                raise

    # ========== 图片生成 (T2I + I2I with reference) ==========

    def generate_image(
        self,
        prompt: str,
        model_name: str = "kling-v1-5",
        aspect_ratio: str = "9:16",
        n: int = 1,
        image: str = None,
        image_reference: str = None,  # "face" or "subject"
        image_fidelity: float = 0.5,
        negative_prompt: str = "",
    ) -> dict:
        """
        生成图片 (支持参考图)

        Args:
            prompt: 文本描述
            model_name: 模型 (kling-v1, kling-v1-5, kling-v2)
            image: 参考图 (base64 或 URL)
            image_reference: "face" (面部匹配) 或 "subject" (主体特征匹配)
            image_fidelity: 参考图相似度 0-1
        """
        data = {
            "model_name": model_name,
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "n": n,
        }
        if negative_prompt:
            data["negative_prompt"] = negative_prompt
        if image:
            data["image"] = image
        if image_reference:
            data["image_reference"] = image_reference
        if image is not None:
            data["image_fidelity"] = image_fidelity

        return self._post("/v1/images/generations", data)

    def get_image_result(self, task_id: str) -> dict:
        """查询图片生成结果"""
        return self._get(f"/v1/images/generations/{task_id}")

    # ========== 视频生成 (I2V with subject reference) ==========

    def generate_video(
        self,
        image: str,
        prompt: str = "",
        model_name: str = "kling-v1-6",
        mode: str = "std",  # "std" or "pro"
        duration: str = "5",  # v1-6: "5"/"10", v3: "3"-"15"
        aspect_ratio: str = "9:16",
        negative_prompt: str = "",
        cfg_scale: float = 0.5,
        subject_reference: list = None,  # [{"image": base64}, ...]
        image_tail: str = None,  # 尾帧图 base64 (仅 v3 支持)
    ) -> dict:
        """
        图生视频

        Args:
            image: 首帧图 (base64 或 URL)
            prompt: 运动描述
            model_name: kling-v1, kling-v1-6, kling-v3
            mode: "std" (标准) 或 "pro" (专业)
            duration: v1-6 仅 "5"/"10", v3 支持 "3"-"15"
            subject_reference: 角色/场景参考图数组 [{"image": b64}, ...]
            image_tail: 尾帧图 base64 (v3 支持首尾帧控制)
        """
        data = {
            "model_name": model_name,
            "image": image,
            "mode": mode,
            "duration": duration,
            "aspect_ratio": aspect_ratio,
            "cfg_scale": cfg_scale,
        }
        if prompt:
            data["prompt"] = prompt
        if negative_prompt:
            data["negative_prompt"] = negative_prompt
        if subject_reference:
            data["subject_reference"] = subject_reference
        if image_tail:
            data["image_tail"] = image_tail

        return self._post("/v1/videos/image2video", data)

    def get_video_result(self, task_id: str) -> dict:
        """查询视频生成结果"""
        return self._get(f"/v1/videos/image2video/{task_id}")

    # ========== 工具方法 ==========

    def poll_task(
        self,
        task_id: str,
        task_type: str = "video",  # "video" or "image"
        max_wait: int = 600,
        interval: int = 5,
    ) -> dict | None:
        """轮询任务直到完成"""
        get_fn = self.get_video_result if task_type == "video" else self.get_image_result
        start = time.time()

        while time.time() - start < max_wait:
            result = get_fn(task_id)
            data = result.get("data", {})
            status = data.get("task_status", "")

            if status == "succeed":
                print(f"  任务完成! ({int(time.time()-start)}s)")
                return data
            elif status == "failed":
                print(f"  任务失败: {data.get('task_status_msg', '')}")
                return None
            else:
                elapsed = int(time.time() - start)
                print(f"  生成中... ({elapsed}s)", end="\r")

            time.sleep(interval)

        print(f"  超时 ({max_wait}s)")
        return None

    @staticmethod
    def encode_image(image_path: str) -> str:
        """读取图片文件并转为 base64"""
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode()
