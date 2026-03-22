"""
Sora 2 (OpenAI) API 客户端
支持文生视频、图生视频，作为 Kling V3 的备选方案

API 参数:
  model: "sora-2" | "sora-2-pro"
  seconds: "4" | "8" | "12"
  size: "720x1280" (竖屏) | "1280x720" (横屏) | "1024x1792" | "1792x1024"
  input_reference: 参考图文件 (可选)

注意: prompt 必须使用英文，中文会被 moderation 拦截
"""

import os
import time

from openai import OpenAI

from .config import API_KEY


class Sora2Client:
    """Sora 2 API 客户端"""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or API_KEY
        self.client = OpenAI(api_key=self.api_key)

    def generate_video(
        self,
        prompt: str,
        model_name: str = "sora-2",
        seconds: str = "4",
        size: str = "720x1280",
        input_reference: str = None,
    ) -> dict:
        """
        生成视频 (文生视频 / 图生视频)

        Args:
            prompt: 视频描述 (必须英文)
            model_name: "sora-2" 或 "sora-2-pro"
            seconds: "4", "8", "12"
            size: "720x1280" (竖屏9:16), "1280x720" (横屏16:9),
                  "1024x1792" (竖屏窄), "1792x1024" (横屏窄)
            input_reference: 参考图文件路径 (可选, 用于图生视频)

        Returns:
            {"status": "completed"/"failed", "id": video_id, "error": ...}
        """
        kwargs = {
            "model": model_name,
            "prompt": prompt,
            "seconds": seconds,
            "size": size,
        }

        # 图生视频: 传入参考图
        if input_reference and os.path.exists(input_reference):
            # OpenAI 需要上传文件
            with open(input_reference, "rb") as f:
                kwargs["input_reference"] = f
                response = self.client.videos.create_and_poll(**kwargs)
        else:
            response = self.client.videos.create_and_poll(**kwargs)

        return {
            "status": response.status,
            "id": response.id,
            "error": str(response.error) if response.error else None,
            "model": response.model,
            "seconds": response.seconds,
            "size": response.size,
        }

    def download_video(self, video_id: str, output_path: str) -> bool:
        """
        下载已完成的视频

        Args:
            video_id: 视频任务 ID
            output_path: 保存路径

        Returns:
            True if successful
        """
        try:
            content = self.client.videos.download_content(video_id)
            content.stream_to_file(output_path)
            return os.path.exists(output_path) and os.path.getsize(output_path) > 0
        except Exception as e:
            print(f"  Sora2 download error: {e}")
            return False

    def generate_and_download(
        self,
        prompt: str,
        output_path: str,
        model_name: str = "sora-2",
        seconds: str = "4",
        size: str = "720x1280",
        input_reference: str = None,
    ) -> dict:
        """
        一站式: 生成视频 + 下载到本地

        Returns:
            {"ok": bool, "path": str, "id": str, "error": str|None}
        """
        print(f"  Sora2: generating ({seconds}s, {size})...")
        start = time.time()

        result = self.generate_video(
            prompt=prompt,
            model_name=model_name,
            seconds=seconds,
            size=size,
            input_reference=input_reference,
        )

        if result["status"] != "completed":
            print(f"  Sora2 failed: {result['error']}")
            return {"ok": False, "path": None, "id": result["id"], "error": result["error"]}

        elapsed = int(time.time() - start)
        print(f"  Sora2: completed ({elapsed}s), downloading...")

        ok = self.download_video(result["id"], output_path)
        if ok:
            sz = os.path.getsize(output_path) / 1024 / 1024
            print(f"  ✓ Sora2: {output_path} ({sz:.1f}MB)")
        else:
            print(f"  ✗ Sora2: download failed")

        return {"ok": ok, "path": output_path if ok else None, "id": result["id"], "error": None}
