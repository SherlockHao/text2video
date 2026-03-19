"""
即梦AI - 智能绘图（漫画版）图像风格化
支持: 网红日漫风(吉卜力)、人像保持、AIGC图像风格

参考文档: https://www.volcengine.com/docs/86081/1660199
API Explorer: https://api.volcengine.com/api-docs/view?action=Img2imgGhibliStyleUsage&version=2024-06-06&serviceCode=cv
"""

import base64
import json
import os

import requests

from .service import call_api, create_service

STYLES = {
    "ghibli": {
        "action": "Img2imgGhibliStyleUsage",
        "req_key": "img2img_ghibli_style_usage",
        "name": "网红日漫风（吉卜力风格）",
    },
    "maintain_id": {
        "action": "MaintainIDUsage",
        "req_key": "maintain_id_usage",
        "name": "漫画版-人像保持",
    },
    "aigc_style": {
        "action": "AIGCStylizeImageUsage",
        "req_key": "aigc_stylize_image_usage",
        "name": "AIGC图像风格化",
    },
}


def stylize_image(
    image_path: str,
    style_key: str = "ghibli",
    output_dir: str = ".",
) -> str | None:
    """将图片转换为漫画风格，返回输出文件路径"""
    style = STYLES[style_key]
    vs = create_service([style["action"]])

    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

    form = {
        "req_key": style["req_key"],
        "binary_data_base64": [img_b64],
        "return_url": True,
    }

    print(f"风格: {style['name']}")
    print(f"输入: {image_path}")
    print("生成中...")

    result = call_api(vs, style["action"], form)
    code = result.get("code", -1)
    print(f"  code={code}, message={result.get('message', '')}")

    if code != 10000:
        print(f"  错误: {json.dumps(result, ensure_ascii=False, indent=2)[:300]}")
        return None

    data = result.get("data", {})
    basename = os.path.splitext(os.path.basename(image_path))[0]
    output_path = os.path.join(output_dir, f"{basename}_{style_key}.png")

    b64_list = [b for b in data.get("binary_data_base64", []) if b]
    if b64_list:
        with open(output_path, "wb") as f:
            f.write(base64.b64decode(b64_list[0]))
    elif data.get("image_urls"):
        r = requests.get(data["image_urls"][0], timeout=30)
        with open(output_path, "wb") as f:
            f.write(r.content)
    else:
        print("  无图片数据")
        return None

    print(f"  已保存: {output_path}")
    print(f"  耗时: {result.get('time_elapsed', 'N/A')}")
    return output_path
