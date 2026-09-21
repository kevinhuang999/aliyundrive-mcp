"""阿里云盘 MCP 授权工具

用法:
    python auth.py                 # 打印授权页链接与步骤说明
    python auth.py <refresh_token> # 换取 access_token 写入 token.json，并验证连通性

注意: refresh_token 约 30 天失效，失效后需重新扫码授权。
"""
import os
import sys
import json
import time

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.environ.get("ALIPAN_TOKEN_FILE") or os.path.join(BASE_DIR, "token.json")
TOKEN_FILE = os.path.abspath(TOKEN_FILE)
OAUTH_TOKEN_URL = os.environ.get("ALIPAN_OAUTH_TOKEN_URL") or "https://api.alistgo.com/alist/ali_open/token"
API_BASE = "https://openapi.alipan.com"
AUTH_PAGE = "https://alistgo.com/tool/aliyundrive/request"


def usage() -> None:
    print("=" * 60)
    print("阿里云盘 MCP 授权")
    print("=" * 60)
    print(f"\n1. 浏览器打开授权页:\n   {AUTH_PAGE}")
    print("\n2. 页面上有两种方式（任选其一）:")
    print("   - 桌面浏览器: 点「前往登录」-> 阿里云盘扫码/登录")
    print("   - 手机 APP:   点「扫描二维码」-> 阿里云盘 APP 扫")
    print("\n3. 授权成功后页面会显示一串 refresh_token，复制它")
    print("\n4. 回到这里执行:")
    print("   python auth.py <粘贴的 refresh_token>")
    print(f"\nToken 将保存到: {TOKEN_FILE}")
    print("注意: refresh_token 约 30 天失效，失效后需重新走一遍上面的流程。")
    print("=" * 60)


def exchange(refresh_token: str) -> dict:
    """用 refresh_token 换 access_token。

    注意: 阿里云盘 refresh_token 一次性消耗，试错须按概率排序，成功即止。
    社区代理端点(api.alistgo.com)对字段名敏感: 传 code=authorization_code 模式，
    传 refresh_token=续期模式。用错会报 Incorrect GrantType。
    """
    attempts = [
        {"refresh_token": refresh_token},
        {"code": refresh_token},
        {"grant_type": "refresh_token", "refresh_token": refresh_token},
    ]
    last_err = ""
    for payload in attempts:
        field = ",".join(payload.keys())
        r = requests.post(OAUTH_TOKEN_URL, json=payload, timeout=30)
        if r.status_code < 400:
            body = r.json()
            if body.get("access_token"):
                print(f"  (成功字段格式: {field})")
                return body
            last_err = f"返回异常[{field}]: {json.dumps(body, ensure_ascii=False)[:300]}"
        else:
            last_err = f"HTTP {r.status_code}[{field}]: {r.text[:300]}"
        # 只在"字段不被认识"类错误时继续尝试，避免误耗 token
        if "GrantType" not in last_err and "Invalid request" not in last_err:
            break
    raise RuntimeError(f"换取 token 失败。最后一次: {last_err}")


def _call(access_token: str, path: str) -> dict:
    r = requests.post(
        f"{API_BASE}/adrive/v1.0/{path.lstrip('/')}",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json={},
        timeout=30,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"连通性验证失败 ({path} HTTP {r.status_code}): {r.text[:400]}")
    return r.json()


def verify(access_token: str):
    return _call(access_token, "user/getDriveInfo"), _call(access_token, "user/getSpaceInfo")


def main() -> int:
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        usage()
        return 0

    refresh_token = sys.argv[1].strip().strip('"').strip("'")
    print("正在换取 access_token ...")
    body = exchange(refresh_token)

    data = {
        "access_token": body["access_token"],
        "refresh_token": body.get("refresh_token") or refresh_token,
        "expires_in": body.get("expires_in", 7200),
        "expires_at": time.time() + int(body.get("expires_in", 7200)) - 300,
    }
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"已保存: {TOKEN_FILE}")

    print("正在验证连通性 ...")
    info, space = verify(data["access_token"])
    sp = space.get("personal_space_info") or {}
    gb = 1024 ** 3
    used, total = sp.get("used_size") or 0, sp.get("total_size") or 0
    print("\n授权成功:")
    print(f"  用户:   {info.get('nick_name') or info.get('user_name')}")
    print(f"  drive_id: {info.get('default_drive_id')}")
    print(f"  容量:   {used / gb:.2f} GB / {total / gb:.2f} GB"
          + (f"  ({used / total * 100:.1f}%)" if total else ""))
    print("\n现在可以在 MCP 里重新连接 aliyundrive-mcp 了。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"\n[失败] {e}", file=sys.stderr)
        sys.exit(1)
