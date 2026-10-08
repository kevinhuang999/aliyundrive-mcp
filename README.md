# aliyundrive-mcp

[中文](#中文) | [English](#english)

---

<a id="中文"></a>
# 中文

> **一句话结论**：把阿里云盘接进 AI 的 MCP 服务器——9 个工具，覆盖「看账号 / 列目录 / 搜文件 / 改名 / 移动 / 建文件夹 / 回收站 / 取下载链接」，让模型用大白话直接操作你的网盘。

基于 [FastMCP](https://github.com/jlowin/fastmcp) 实现，走 **stdio** 协议，可直接挂到任意支持 MCP 的客户端（WorkBuddy、Claude Desktop、Cherry Studio 等）。

---

## 目录

- [它能做什么](#它能做什么)
- [快速开始](#快速开始)
- [工具清单](#工具清单)
- [接进 MCP 客户端](#接进-mcp-客户端)
- [为什么走社区托管端点](#为什么走社区托管端点)
- [token 是怎么管的](#token-是怎么管的)
- [故障排查](#故障排查)
- [安全须知](#安全须知)
- [已知限制](#已知限制)

---

## 它能做什么

| 场景 | 对应的工具 |
|---|---|
| 「我网盘还剩多少空间？」 | `get_user_info` |
| 「根目录下有什么？」 | `list_files` |
| 「帮我找找那份报告在哪」 | `search_files` |
| 「新建一个 2026 项目 文件夹」 | `create_folder` |
| 「把这个文件改名叫 xxx」 | `rename_file` |
| 「把这几份文件挪到归档目录」 | `move_files` |
| 「删掉这个」 | `delete_file`（进回收站，**可恢复**） |
| 「给我这个文件的下载链接」 | `get_download_url` |

**只读 + 有限写**：没有上传、没有真删除、没有分享外链。动到的都是元数据与回收站。

---

## 快速开始

### 1. 装依赖

```bash
pip install fastmcp requests
```

（`test_connection.py` 只用标准库，不需要额外依赖。）

### 2. 授权拿 token

**第一步——扫码取 refresh_token：**

浏览器打开 **https://alistgo.com/tool/aliyundrive/request**

- 桌面浏览器：点「前往登录」→ 阿里云盘扫码 / 登录
- 手机：点「扫描二维码」→ 用阿里云盘 APP 扫

授权成功后页面会显示一串 `refresh_token`，复制它。

**第二步——换成 token.json：**

```bash
python auth.py <粘贴的 refresh_token>
```

脚本会自动完成三件事：换 `access_token` → 写入 `token.json` → **验证连通性**（打印用户昵称、drive_id、容量占用）。看到「授权成功」就通了。

> 只想看授权步骤说明，直接跑 `python auth.py`（不带参数）即可。

### 3. 自检

```bash
python test_connection.py
```

它会**以真实 MCP stdio 方式启动 `server.py`**，跑一遍只读工具，确认「token 有效 + API 路径正确 + 工具可用」：

```
server -> aliyundrive-mcp vX.Y
tools  -> 9 个

[PASS] get_user_info (账号+容量)
[PASS] list_files (根目录)
[PASS] search_files (搜索)

自检通过：token 有效，MCP 可正常连接。
```

MCP 面板报 `Connection closed` 时，**先跑这个**——能立刻分清是 token 问题还是代码问题。

### 4. 挂进客户端

见下一节。

---

## 工具清单

| 工具 | 作用 | 主要参数 |
|---|---|---|
| `get_user_info` | 账号信息：昵称、user_id、drive_id、容量占用 | — |
| `list_files` | 列出目录内容 | `parent_file_id`（默认 `root`）、`limit`（1–200）、`order_by`、`order_direction` |
| `search_files` | 按文件名关键词搜索 | `query`、`limit`（1–100） |
| `get_file_info` | 单个文件/文件夹详情 | `file_id` |
| `create_folder` | 新建文件夹 | `name`、`parent_file_id`（默认 `root`） |
| `rename_file` | 重命名 | `file_id`、`new_name` |
| `move_files` | **批量**移动（不是复制） | `file_ids`（数组）、`target_parent_id` |
| `delete_file` | 移入回收站（可恢复） | `file_id` |
| `get_download_url` | 取临时下载链接 | `file_id`、`expire_sec`（默认 3600 秒） |

几个实现上的小设计：

- **`limit` 会夹取**：`list_files` 夹到 1–200，`search_files` 夹到 1–100，防止模型传个离谱数字把接口打挂。
- **`move_files` 逐个搬、不整体失败**：返回 `{"moved": [...], "failed": [...]}`，一批里坏一个不影响其余的，还能看清是哪个坏。
- **`drive_id` 带缓存**：第一次调 `user/getDriveInfo` 拿到后缓存在进程里，不给每个工具都重复请求一次。
- **`get_download_url` 会挡文件夹**：文件夹没有下载链接，直接返回明确错误提示，而不是抛一个看不懂的 API 报错。
- **文件列表统一瘦身**：`_fmt_item` 只返回 `file_id / name / type / size / updated_at / parent_file_id`，不把接口的一大坨原始字段全塞给模型（省 token）。

---

## 接进 MCP 客户端

在客户端的 MCP 配置里加一段（**路径换成你自己的绝对路径**）：

```json
{
  "mcpServers": {
    "aliyundrive": {
      "command": "python",
      "args": ["/绝对路径/aliyundrive-mcp/server.py"],
      "env": {
        "ALIPAN_TOKEN_FILE": "/绝对路径/aliyundrive-mcp/token.json"
      }
    }
  }
}
```

Windows 下 `command` 建议写 `python` 的完整路径（如 `C:\\Python313\\python.exe`），避免客户端拿不到 PATH。

**两个环境变量（都可选）：**

| 变量 | 默认值 | 用途 |
|---|---|---|
| `ALIPAN_TOKEN_FILE` | 脚本同目录下的 `token.json` | 换 token 存放位置（多账号可共存） |
| `ALIPAN_OAUTH_TOKEN_URL` | `https://api.alistgo.com/alist/ali_open/token` | 换刷新端点（自建代理时改这个） |

---

## 为什么走社区托管端点

这是本项目最需要说明的一处设计取舍。

阿里云盘官方的 OAuth 刷新端点 `api.nn.ci` **已被阻断**，而**官方个人开发者申请自 2025-07 起暂停**——也就是说，官方路线对个人用户实际已关闭。

因此本项目走 AList 社区托管的刷新端点 `api.alistgo.com`。代价是**依赖第三方服务可用性**：这个端点哪天停了，本项目就需要改 `ALIPAN_OAUTH_TOKEN_URL` 或自建代理。

好消息是它与你的网盘数据无关——**它只负责把 `refresh_token` 换成 `access_token`**，真正的文件操作全部直连官方 `openapi.alipan.com`。

---

## token 是怎么管的

```
refresh_token（约 30 天失效）
      │  auth.py 换取
      ▼
token.json  ──  access_token（约 2 小时）+ refresh_token + expires_at
      │
      │  expires_at 到了 / 接口返回 401·403
      ▼
自动刷新（提前 5 分钟续期，无需人工干预）
```

- **提前 5 分钟刷新**：`expires_at = now + expires_in - 300`，避开边界时刻的偶发失败。
- **401/403 自动重试一次**：先强制刷新 token，再重放原请求；只重试一次，不会死循环。
- **写回失败不阻断**：token.json 没写权限时只打警告，内存里的 token 仍能用到过期。
- **⚠️ refresh_token 约 30 天失效**，届时需要重新扫码授权（见快速开始第 2 步）。

---

## 故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| `未找到 token 文件` | 还没授权，或 `ALIPAN_TOKEN_FILE` 指错 | 跑 `python auth.py <refresh_token>` |
| `刷新 token 失败 (400) Incorrect GrantType` | 刷新端点的字段格式不对 | `auth.py` 已内置三种格式回退；若仍失败，说明端点有变，改 `ALIPAN_OAUTH_TOKEN_URL` |
| `未被授权 (401/403)` 反复出现 | refresh_token 已过期（约 30 天） | 重新扫码授权 |
| `未能获取 drive_id，账号可能未开通开放平台权限` | 该账号没开通阿里云盘开放平台 | 换账号或先在阿里云盘侧确认开放平台权限 |
| MCP 面板 `Connection closed` | token 问题 或 代码问题 | **先跑 `python test_connection.py`** 定位 |
| 客户端连不上、日志空白 | 客户端拿不到 PATH | `command` 写 python 完整路径 |
| 文件夹取下载链接报错 | 文件夹本来就没有下载链接 | 传具体文件的 `file_id` |

> **Windows 小坑**：`test_connection.py` 启动子进程时传了 `PATH=""` + `SYSTEMROOT=C:\Windows`，是为了隔离环境、避免父进程的环境变量干扰自检结果。这不是 bug。

---

## 安全须知

**`token.json` 含 `refresh_token`，等同于你网盘的长期钥匙。**

仓库的 `.gitignore` 已把它排除在外：

```gitignore
# 运行时凭据与缓存——不要提交
token.json
__pycache__/
*.pyc
.env
```

**自己动手前请再确认一次**：

```bash
git ls-files | grep -i token    # 应无输出
git log --all --name-only | grep -i token   # 应无输出
```

第一条查「当前是否被跟踪」，第二条查「历史里是否出现过」——**第二条更重要**，被跟踪过又删掉的文件仍留在历史里。

另外两条：

- 复制本仓库给别人之前，先确认 `token.json` **没有被一起打包**。
- 令牌一旦外泄，立即到授权页重新授权（旧 refresh_token 会失效）。

---

## 已知限制

- **无上传 / 下载文件本体**：只处理元数据与链接。要落地文件请用 `get_download_url` 拿链接后自行下载。
- **无分享外链 / 无批量删除**：`delete_file` 一次一个；批量删除请循环调用。
- **`search_files` 是文件名匹配**，不做全文检索（阿里云盘开放接口本身也没有）。
- **单账号**：一套 `token.json` 对应一个账号；多账号靠 `ALIPAN_TOKEN_FILE` 开多个 server 实例。
- **依赖社区端点**：见上文「为什么走社区托管端点」。

---

## 声明

本项目为个人自用工具，按现状提供。阿里云盘开放平台接口的可用性、配额与条款以其官方规定为准；使用前请确认你的用法符合相关服务条款。

---

<a id="english"></a>
# English

> **In one sentence**: an MCP server that plugs Aliyun Drive (Alipan) into AI — 9 tools covering "check account / list directory / search files / rename / move / create folder / recycle bin / get download link", letting the model operate your cloud drive in plain language.

Built on [FastMCP](https://github.com/jlowin/fastmcp) over the **stdio** protocol, it can be attached to any MCP-capable client (WorkBuddy, Claude Desktop, Cherry Studio, etc.).

---

## Table of Contents

- [What It Can Do](#what-it-can-do)
- [Quick Start](#quick-start)
- [Tool Reference](#tool-reference)
- [Connecting to an MCP Client](#connecting-to-an-mcp-client)
- [Why a Community-Hosted Endpoint](#why-a-community-hosted-endpoint)
- [How Tokens Are Managed](#how-tokens-are-managed)
- [Troubleshooting](#troubleshooting)
- [Security Notes](#security-notes)
- [Known Limitations](#known-limitations)

---

## What It Can Do

| Scenario | Tool |
|---|---|
| "How much space is left on my drive?" | `get_user_info` |
| "What's in the root directory?" | `list_files` |
| "Help me find that report" | `search_files` |
| "Create a folder called 2026 Project" | `create_folder` |
| "Rename this file to xxx" | `rename_file` |
| "Move these files to the archive folder" | `move_files` |
| "Delete this" | `delete_file` (moves to recycle bin — **recoverable**) |
| "Give me a download link for this file" | `get_download_url` |

**Read-only + limited write**: no uploads, no permanent deletes, no share links. Only metadata and the recycle bin are touched.

---

## Quick Start

### 1. Install dependencies

```bash
pip install fastmcp requests
```

(`test_connection.py` uses only the standard library and needs no extra dependencies.)

### 2. Authorize and obtain a token

**Step one — scan the QR code to get a `refresh_token`:**

Open **https://alistgo.com/tool/aliyundrive/request** in a browser.

- Desktop browser: click "Go to login" → scan / log in with Aliyun Drive
- Mobile: click "Scan QR code" → scan with the Aliyun Drive app

On success the page displays a `refresh_token` string — copy it.

**Step two — exchange it for `token.json`:**

```bash
python auth.py <pasted refresh_token>
```

The script does three things automatically: exchanges for an `access_token` → writes `token.json` → **verifies connectivity** (prints the user nickname, drive_id, and capacity usage). Seeing "authorization successful" means you're good.

> To just read the authorization instructions, run `python auth.py` with no arguments.

### 3. Self-check

```bash
python test_connection.py
```

It **launches `server.py` over real MCP stdio**, exercises the read-only tools, and confirms "token valid + API paths correct + tools usable":

```
server -> aliyundrive-mcp vX.Y
tools  -> 9

[PASS] get_user_info (account + capacity)
[PASS] list_files (root)
[PASS] search_files (search)

Self-check passed: token valid, MCP connects normally.
```

When the MCP panel reports `Connection closed`, **run this first** — it immediately distinguishes a token problem from a code problem.

### 4. Connect to a client

See the next section.

---

## Tool Reference

| Tool | Purpose | Main parameters |
|---|---|---|
| `get_user_info` | Account info: nickname, user_id, drive_id, capacity usage | — |
| `list_files` | List directory contents | `parent_file_id` (default `root`), `limit` (1–200), `order_by`, `order_direction` |
| `search_files` | Search by filename keyword | `query`, `limit` (1–100) |
| `get_file_info` | Details for a single file/folder | `file_id` |
| `create_folder` | Create a folder | `name`, `parent_file_id` (default `root`) |
| `rename_file` | Rename | `file_id`, `new_name` |
| `move_files` | **Batch** move (not copy) | `file_ids` (array), `target_parent_id` |
| `delete_file` | Move to recycle bin (recoverable) | `file_id` |
| `get_download_url` | Get a temporary download link | `file_id`, `expire_sec` (default 3600 s) |

A few design details:

- **`limit` is clamped**: `list_files` to 1–200, `search_files` to 1–100, so the model can't pass an absurd number and break the API.
- **`move_files` moves one by one without failing wholesale**: returns `{"moved": [...], "failed": [...]}` — one bad item in a batch doesn't block the rest, and you can see exactly which failed.
- **`drive_id` is cached**: fetched once via `user/getDriveInfo` and cached in the process rather than re-requested by every tool.
- **`get_download_url` blocks folders**: folders have no download link, so it returns a clear error instead of an incomprehensible API failure.
- **File listings are slimmed uniformly**: `_fmt_item` returns only `file_id / name / type / size / updated_at / parent_file_id`, rather than dumping the API's full raw payload on the model (saves tokens).

---

## Connecting to an MCP Client

Add this block to your client's MCP config (**replace the paths with your own absolute paths**):

```json
{
  "mcpServers": {
    "aliyundrive": {
      "command": "python",
      "args": ["/absolute/path/aliyundrive-mcp/server.py"],
      "env": {
        "ALIPAN_TOKEN_FILE": "/absolute/path/aliyundrive-mcp/token.json"
      }
    }
  }
}
```

On Windows, use the full path to `python` for `command` (e.g. `C:\\Python313\\python.exe`) so the client doesn't fail to resolve PATH.

**Two environment variables (both optional):**

| Variable | Default | Purpose |
|---|---|---|
| `ALIPAN_TOKEN_FILE` | `token.json` next to the script | Change where the token is stored (supports multiple accounts) |
| `ALIPAN_OAUTH_TOKEN_URL` | `https://api.alistgo.com/alist/ali_open/token` | Change the refresh endpoint (for a self-hosted proxy) |

---

## Why a Community-Hosted Endpoint

This is the design trade-off that most needs explaining.

Aliyun Drive's official OAuth refresh endpoint `api.nn.ci` **has been blocked**, and **official individual-developer applications have been suspended since July 2025** — meaning the official route is effectively closed to individual users.

This project therefore uses the AList community-hosted refresh endpoint `api.alistgo.com`. The cost is **dependence on a third-party service's availability**: if that endpoint goes down, this project needs `ALIPAN_OAUTH_TOKEN_URL` changed or a self-hosted proxy.

The good news is that it has nothing to do with your drive data — **it only exchanges a `refresh_token` for an `access_token`**; all actual file operations connect directly to the official `openapi.alipan.com`.

---

## How Tokens Are Managed

```
refresh_token (expires in ~30 days)
      │  exchanged by auth.py
      ▼
token.json  ──  access_token (~2 hours) + refresh_token + expires_at
      │
      │  expires_at reached / API returns 401·403
      ▼
Auto-refresh (renews 5 minutes early, no manual intervention)
```

- **Refreshes 5 minutes early**: `expires_at = now + expires_in - 300`, avoiding occasional failures at the boundary.
- **Auto-retries once on 401/403**: force-refresh the token, then replay the original request — only once, so no infinite loop.
- **Write-back failure doesn't block**: if `token.json` isn't writable it only warns; the in-memory token still works until it expires.
- **⚠️ The `refresh_token` expires in about 30 days**, at which point you need to rescan and reauthorize (see Quick Start step 2).

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `未找到 token 文件` (token file not found) | Not yet authorized, or `ALIPAN_TOKEN_FILE` points wrong | Run `python auth.py <refresh_token>` |
| `刷新 token 失败 (400) Incorrect GrantType` | Wrong field format for the refresh endpoint | `auth.py` has three built-in format fallbacks; if it still fails the endpoint has changed — update `ALIPAN_OAUTH_TOKEN_URL` |
| `未被授权 (401/403)` repeatedly | The refresh_token has expired (~30 days) | Rescan and reauthorize |
| `未能获取 drive_id，账号可能未开通开放平台权限` | The account hasn't enabled the Aliyun Drive open platform | Use another account, or verify open-platform access on the Aliyun Drive side |
| MCP panel shows `Connection closed` | Either a token problem or a code problem | **Run `python test_connection.py` first** to localize it |
| Client can't connect, logs are blank | Client can't resolve PATH | Put the full python path in `command` |
| Error when getting a download link for a folder | Folders simply have no download link | Pass the `file_id` of an actual file |

> **Windows footnote**: `test_connection.py` passes `PATH=""` + `SYSTEMROOT=C:\Windows` when spawning the subprocess, to isolate the environment and prevent parent-process variables from skewing the self-check. This is not a bug.

---

## Security Notes

**`token.json` contains a `refresh_token`, which is equivalent to a long-term key to your cloud drive.**

The repo's `.gitignore` already excludes it:

```gitignore
# Runtime credentials and caches — do not commit
token.json
__pycache__/
*.pyc
.env
```

**Double-check before you push:**

```bash
git ls-files | grep -i token    # should output nothing
git log --all --name-only | grep -i token   # should output nothing
```

The first checks "is it currently tracked"; the second checks "has it ever appeared in history" — **the second matters more**, since a file that was tracked once and deleted still lives on in history.

Two more points:

- Before copying this repo to someone else, confirm `token.json` **wasn't included**.
- If a token leaks, reauthorize immediately at the authorization page (the old refresh_token becomes invalid).

---

## Known Limitations

- **No upload / no downloading file bodies**: only metadata and links. To fetch a file, use `get_download_url` and download it yourself.
- **No share links / no batch delete**: `delete_file` handles one at a time; loop for bulk deletion.
- **`search_files` matches filenames**, not full text (the Aliyun Drive open API doesn't offer full-text search either).
- **Single account**: one `token.json` per account; use `ALIPAN_TOKEN_FILE` to run multiple server instances for multiple accounts.
- **Depends on a community endpoint**: see "Why a Community-Hosted Endpoint" above.

---

## Disclaimer

This is a personal-use tool, provided as is. The availability, quotas, and terms of the Aliyun Drive open platform API are governed by its official policies; please confirm your usage complies with the relevant terms of service before use.
