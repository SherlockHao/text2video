"""
Gemini API 客户端 — 图片生成（支持参考图输入 + 4K 输出）
"""

from pathlib import Path

from google import genai
from google.genai import types

from .config import API_KEY, MODEL_IMAGE


def _get_client() -> genai.Client:
    return genai.Client(api_key=API_KEY)


def generate_image_with_refs(
    prompt: str,
    ref_images: list[str | bytes] | None = None,
    ref_labels: list[str] | None = None,
    output_path: str = "/tmp/gemini_output.png",
    model: str | None = None,
    image_size: str | None = None,
) -> str | None:
    """用 Gemini 生成图片，支持多张参考图和 4K 输出。

    Args:
        prompt: 图片生成 prompt
        ref_images: 参考图列表，每项可以是文件路径(str)或图片bytes
        ref_labels: 每张参考图的标签说明（与 ref_images 一一对应）
        output_path: 输出文件路径
        model: 模型名，默认 gemini-3.1-flash-image-preview
        image_size: 图片尺寸，"1K"/"2K"/"4K"（大写），None 为默认

    Returns:
        输出文件路径，失败返回 None
    """
    client = _get_client()
    model = model or MODEL_IMAGE

    # 构建 contents: [ref_img1, label1, ref_img2, label2, ..., prompt]
    contents = []

    if ref_images:
        labels = ref_labels or [f"Reference image {i+1}" for i in range(len(ref_images))]
        for img, label in zip(ref_images, labels):
            if isinstance(img, (str, Path)):
                img_bytes = Path(img).read_bytes()
            else:
                img_bytes = img
            # 判断 mime type
            if isinstance(img, str) and img.endswith(".jpg"):
                mime = "image/jpeg"
            else:
                mime = "image/png"
            contents.append(types.Part.from_bytes(data=img_bytes, mime_type=mime))
            contents.append(label)

    contents.append(prompt)

    # 构建 config
    config_kwargs = {
        "response_modalities": ["TEXT", "IMAGE"],
    }
    if image_size:
        config_kwargs["image_config"] = types.ImageConfig(image_size=image_size)

    try:
        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(**config_kwargs),
        )

        for part in response.candidates[0].content.parts:
            if part.inline_data:
                with open(output_path, "wb") as f:
                    f.write(part.inline_data.data)
                return output_path

        print(f"  Gemini: 无图片输出")
        return None

    except Exception as e:
        print(f"  Gemini error: {e}")
        return None
