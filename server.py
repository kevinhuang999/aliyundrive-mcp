"""阿里云盘 MCP Server (社区托管路线 - AList OAuth)

授权流程: 浏览器打开 https://alistgo.com/tool/aliyundrive/request 扫码 -> 拿到 refresh_token
         -> python auth.py <refresh_token> -> 换 access_token 写入 token.json

注意: refresh_token 约 30 天失效，失效后需重新扫码授权。
"""
import os
import sys
import json
import time
import threading
from typing import Optional, List, Dict, Any

import requests
from fastmcp import FastMCP

# ---------- 相对独立: 路径不写死，跟随脚本目录 / 环境变量 ----------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.environ.get("ALIPAN_TOKEN_FILE") or os.path.join(BASE_DIR, "token.json")
TOKEN_FILE = os.path.abspath(TOKEN_FILE)

API_BASE = "https://openapi.alipan.com"
# 社区托管刷新端点 (官方 api.nn.ci 已被阻断); 官方个人开发者申请自 2025-07 暂停
OAUTH_TOKEN_URL = os.environ.get("ALIPAN_OAUTH_TOKEN_URL") or "https://api.alistgo.com/alist/ali_open/token"

mcp = FastMCP("aliyundrive-mcp")

_lock = threading.Lock()
_session = requests.Session()


# ---------- token 管理 ----------
def _load_token() -> Dict[str, Any]:
    if not os.path.exists(TOKEN_FILE):
        raise RuntimeError(
            f"未找到 token 文件: {TOKEN_FILE}\n"
            "请先授权: 浏览器打开 https://alistgo.com/tool/aliyundrive/request 扫码拿 refresh_token, "
            "然后运行: python auth.py <refresh_token>"
        )
    with open(TOKEN_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_token(data: Dict[str, Any]) -> None:
    try:
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError as e:
        # 写权限不足时只警告，不阻断 (内存态 token 仍可用到过期)
        print(f"[warn] 无法写回 token 文件 {TOKEN_FILE}: {e}", file=sys.stderr)


def _refresh(refresh_token: str) -> Dict[str, Any]:
    """用 refresh_token 换 access_token。

    实测(2026-08-30): 社区代理端点 api.alistgo.com/alist/ali_open/token 只认
    {"grant_type": "refresh_token", "refresh_token": ...}; 传 {"code": ...} 会被
    判为 authorization_code 模式并报 Incorrect GrantType。
    """
    r = _session.post(
        OAUTH_TOKEN_URL,
        json={"grant_type": "refresh_token", "refresh_token": refresh_token},
        timeout=30,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"刷新 token 失败 ({r.status_code}): {r.text[:300]}")
    body = r.json()
    if not body.get("access_token"):
        raise RuntimeError(f"刷新 token 返回异常: {json.dumps(body, ensure_ascii=False)[:300]}")
    data = _load_token() if os.path.exists(TOKEN_FILE) else {}
    data["access_token"] = body["access_token"]
    data["refresh_token"] = body.get("refresh_token") or refresh_token
    data["expires_in"] = body.get("expires_in", 7200)
    data["expires_at"] = time.time() + int(data["expires_in"]) - 300  # 提前 5 分钟刷新
    _save_token(data)
    return data


def get_token() -> Dict[str, Any]:
    with _lock:
        data = _load_token()
        if data.get("expires_at", 0) < time.time():
            data = _refresh(data.get("refresh_token", ""))
        return data


# ---------- 通用请求 ----------
def api(path: str, payload: Optional[Dict[str, Any]] = None, retry: bool = True) -> Dict[str, Any]:
    tok = get_token()
    url = f"{API_BASE}/adrive/v1.0/{path.lstrip('/')}"
    headers = {
        "Authorization": f"Bearer {tok['access_token']}",
        "Content-Type": "application/json",
    }
    r = _session.post(url, json=payload or {}, headers=headers, timeout=60)
    # 401/403 且未重试过 -> 强制刷新后重试一次
    if r.status_code in (401, 403) and retry:
        with _lock:
            _refresh(_load_token().get("refresh_token", ""))
        return api(path, payload, retry=False)
    if r.status_code >= 400:
        raise RuntimeError(f"阿里网盘 API 错误 ({r.status_code}): {r.text[:500]}")
    if not r.content:
        return {}
    try:
        return r.json()
    except ValueError:
        return {"raw": r.text[:500]}


_drive_id_cache: Optional[str] = None


def drive_id(force: bool = False) -> str:
    """获取默认 drive_id 并缓存，避免每个工具都重复请求用户信息。"""
    global _drive_id_cache
    if _drive_id_cache is None or force:
        d = api("user/getDriveInfo")
        _drive_id_cache = d.get("default_drive_id") or d.get("backup_drive_id")
        if not _drive_id_cache:
            raise RuntimeError("未能获取 drive_id，账号可能未开通开放平台权限")
    return _drive_id_cache


def _fmt_item(it: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "file_id": it.get("file_id"),
        "name": it.get("name"),
        "type": it.get("type"),
        "size": it.get("size"),
        "updated_at": it.get("updated_at"),
        "parent_file_id": it.get("parent_file_id"),
    }


# ---------- 工具 ----------
@mcp.tool()
def get_user_info() -> Dict[str, Any]:
    """获取阿里云盘账号信息（用户昵称、容量使用情况、默认 drive_id）。"""
    d = api("user/getDriveInfo")
    # 容量不在 getDriveInfo 里，需单独查 getSpaceInfo (实测 2026-08-30)
    try:
        sp = api("user/getSpaceInfo").get("personal_space_info") or {}
    except Exception:
        sp = {}
    used, total = sp.get("used_size"), sp.get("total_size")
    gb = 1024 ** 3
    return {
        "user_name": d.get("nick_name") or d.get("user_name"),
        "user_id": d.get("user_id"),
        "default_drive_id": d.get("default_drive_id"),
        "backup_drive_id": d.get("backup_drive_id"),
        "used_size": used,
        "total_size": total,
        "used_gb": round(used / gb, 2) if used else None,
        "total_gb": round(total / gb, 2) if total else None,
        "used_percent": round(used / total * 100, 2) if (used and total) else None,
    }


@mcp.tool()
def list_files(parent_file_id: str = "root", limit: int = 100, order_by: str = "updated_at",
               order_direction: str = "DESC") -> List[Dict[str, Any]]:
    """列出指定目录下的文件和文件夹。parent_file_id 默认为 root（根目录）。"""
    payload = {
        "drive_id": drive_id(),
        "parent_file_id": parent_file_id,
        "limit": min(max(limit, 1), 200),
        "order_by": order_by,
        "order_direction": order_direction,
        "fields": "*",
    }
    d = api("openFile/list", payload)
    return [_fmt_item(i) for i in d.get("items", [])]


@mcp.tool()
def search_files(query: str, limit: int = 50) -> List[Dict[str, Any]]:
    """按文件名关键词搜索阿里云盘文件。"""
    payload = {
        "drive_id": drive_id(),
        "query": f'name match "{query}"',
        "limit": min(max(limit, 1), 100),
        "order_by": "updated_at DESC",
    }
    d = api("openFile/search", payload)
    return [_fmt_item(i) for i in d.get("items", [])]


@mcp.tool()
def get_file_info(file_id: str) -> Dict[str, Any]:
    """获取单个文件或文件夹的详细信息。"""
    d = api("openFile/get", {
        "drive_id": drive_id(),
        "file_id": file_id,
    })
    return d


@mcp.tool()
def create_folder(name: str, parent_file_id: str = "root") -> Dict[str, Any]:
    """在指定目录下新建文件夹，返回新文件夹的 file_id。"""
    d = api("openFile/create", {
        "drive_id": drive_id(),
        "parent_file_id": parent_file_id,
        "name": name,
        "type": "folder",
        "check_name_mode": "refuse",
    })
    return {"file_id": d.get("file_id"), "name": d.get("name"), "type": d.get("type")}


@mcp.tool()
def rename_file(file_id: str, new_name: str) -> Dict[str, Any]:
    """重命名文件或文件夹。"""
    d = api("openFile/update", {
        "drive_id": drive_id(),
        "file_id": file_id,
        "name": new_name,
        "check_name_mode": "refuse",
    })
    return {"file_id": d.get("file_id"), "name": d.get("name"), "updated_at": d.get("updated_at")}


@mcp.tool()
def move_files(file_ids: List[str], target_parent_id: str) -> Dict[str, Any]:
    """批量移动文件/文件夹到目标目录（移动，不是复制）。"""
    drive_id = drive_id()
    results, errors = [], []
    for fid in file_ids:
        try:
            d = api("openFile/update", {
                "drive_id": drive_id,
                "file_id": fid,
                "to_parent_file_id": target_parent_id,
            })
            results.append({"file_id": fid, "ok": True, "name": d.get("name")})
        except Exception as e:
            errors.append({"file_id": fid, "ok": False, "error": str(e)})
    return {"moved": results, "failed": errors}


@mcp.tool()
def delete_file(file_id: str) -> Dict[str, Any]:
    """删除文件或文件夹（移入回收站，可恢复；不是永久销毁）。"""
    api("openFile/recyclebin/trash", {
        "drive_id": drive_id(),
        "file_id": file_id,
    })
    return {"file_id": file_id, "trashed": True}


@mcp.tool()
def get_download_url(file_id: str, expire_sec: int = 3600) -> Dict[str, Any]:
    """获取文件的临时下载链接（默认有效期 1 小时）。文件夹没有下载链接。"""
    info = api("openFile/get", {"drive_id": drive_id(), "file_id": file_id})
    if info.get("type") == "folder":
        return {
            "file_id": file_id,
            "url": None,
            "error": "这是文件夹，没有下载链接。请传入具体文件的 file_id。",
        }
    d = api("openFile/getDownloadUrl", {
        "drive_id": drive_id(),
        "file_id": file_id,
        "expire_sec": expire_sec,
    })
    return {
        "file_id": file_id,
        "name": info.get("name"),
        "url": d.get("url"),
        "expiration": d.get("expiration"),
        "size": info.get("size") or d.get("size"),
    }


if __name__ == "__main__":
    mcp.run()
