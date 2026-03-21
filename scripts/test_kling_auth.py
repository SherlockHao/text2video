"""
可灵 API 认证测试脚本 v2
测试多个可能的 API 端点和参数组合
用法: python scripts/test_kling_auth.py
"""
import time
import jwt
import requests

ACCESS_KEY = "AkLTCfEDbAdBgafkAbJhyHNHGaGB4yNe"
SECRET_KEY = "PQPFrhTr8d9kEy3yDLRYYBYfy9YNbmhm"

# 可能的 API 端点
BASE_URLS = [
    "https://api.klingai.com",
    "https://api-global.klingai.com",
    "https://api.klingai.cn",
    "https://api-cn.klingai.com",
]

# 可能的图片生成路径
ENDPOINTS = [
    "/v1/images/generations",
    "/v2/images/generations",
]

# 可能的模型名
MODELS = ["kling-v1", "kling-v1-5", "kling-v2"]


def generate_token():
    headers = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "iss": ACCESS_KEY,
        "exp": int(time.time()) + 1800,
        "nbf": int(time.time()) - 5,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256", headers=headers)


def test_endpoint(base_url, endpoint, model, token):
    req_headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.post(
            f"{base_url}{endpoint}",
            headers=req_headers,
            json={
                "model_name": model,
                "prompt": "a cute cat",
                "n": 1,
                "aspect_ratio": "1:1",
            },
            timeout=10,
        )
        data = resp.json()
        code = data.get("code", "")
        msg = data.get("message", "")
        return resp.status_code, code, msg
    except requests.exceptions.ConnectionError:
        return None, None, "连接失败(域名不存在)"
    except requests.exceptions.Timeout:
        return None, None, "超时"
    except Exception as e:
        return None, None, str(e)


def main():
    print("=" * 60)
    print("可灵 API 认证排查 v2")
    print("=" * 60)

    # 1. IP
    try:
        ip = requests.get("https://httpbin.org/ip", timeout=10).json().get("origin", "未知")
        print(f"\n当前 IP: {ip}")
    except:
        print("\n当前 IP: 获取失败")

    # 2. Token
    token = generate_token()
    print(f"JWT Token: {token[:50]}...\n")

    # 3. 逐一测试
    print(f"{'Base URL':<35} {'Endpoint':<28} {'Model':<12} {'HTTP':>4} {'Code':>6} Message")
    print("-" * 120)

    for base_url in BASE_URLS:
        for endpoint in ENDPOINTS:
            for model in MODELS:
                http_status, code, msg = test_endpoint(base_url, endpoint, model, token)
                status_str = str(http_status) if http_status else " -  "
                code_str = str(code) if code is not None else "  -  "
                print(f"{base_url:<35} {endpoint:<28} {model:<12} {status_str:>4} {code_str:>6} {msg}")
            # 只测第一个模型如果域名都不通
            if http_status is None:
                break
        if http_status is None:
            continue

    # 4. 额外测试：用 Authorization 头的不同格式
    print(f"\n--- 测试不同 Authorization 格式 ---")
    base = "https://api.klingai.com"
    ep = "/v1/images/generations"
    body = {"model_name": "kling-v1", "prompt": "a cute cat", "n": 1, "aspect_ratio": "1:1"}

    formats = [
        ("Bearer {token}", f"Bearer {token}"),
        ("bearer {token}", f"bearer {token}"),
        ("Token {token}", f"Token {token}"),
        ("{token} (no prefix)", token),
    ]
    for label, auth_value in formats:
        try:
            resp = requests.post(
                f"{base}{ep}",
                headers={"Authorization": auth_value, "Content-Type": "application/json"},
                json=body,
                timeout=10,
            )
            d = resp.json()
            print(f"  {label[:30]:<32} → {resp.status_code} code={d.get('code')} {d.get('message')}")
        except Exception as e:
            print(f"  {label[:30]:<32} → Error: {e}")

    print("\n" + "=" * 60)
    print("如果所有组合都是 1002，请检查:")
    print("  1. 平台上 API 密钥旁边的开关是否为绿色(已启用)")
    print("  2. 是否在'用量查询'中能看到已购买的资源包")
    print("  3. 尝试删除当前密钥，重新创建一个新的密钥对")
    print("=" * 60)


if __name__ == "__main__":
    main()
