"""阿里云盘 MCP 连接自检

用法: python test_connection.py

作用: 以真实 MCP stdio 方式启动 server.py，跑一遍只读工具，
      确认「token 有效 + API 路径正确 + 工具可用」。
      MCP 面板报 Connection closed 时，先跑这个定位是 token 问题还是代码问题。
"""
import json
import os
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
SERVER = os.path.join(BASE_DIR, "server.py")
TOKEN = os.environ.get("ALIPAN_TOKEN_FILE") or os.path.join(BASE_DIR, "token.json")

if not os.path.exists(TOKEN):
    print(f"[FAIL] 未找到 token 文件: {TOKEN}")
    print("       请先运行: python auth.py <refresh_token>")
    sys.exit(1)

p = subprocess.Popen([PY, "-u", SERVER], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                     stderr=subprocess.DEVNULL, text=True, encoding="utf-8", bufsize=1,
                     env={"ALIPAN_TOKEN_FILE": TOKEN, "PATH": "", "SYSTEMROOT": "C:\\Windows"})


def rpc(payload):
    p.stdin.write(json.dumps(payload) + "\n")
    p.stdin.flush()
    return json.loads(p.stdout.readline())


def tool(name, args=None):
    r = rpc({"jsonrpc": "2.0", "id": 99, "method": "tools/call",
             "params": {"name": name, "arguments": args or {}}})
    if "error" in r:
        return {"__error__": r["error"].get("message", str(r["error"]))}
    txt = r["result"]["content"][0]["text"]
    try:
        return json.loads(txt)
    except ValueError:
        return txt


fails = []


def check(label, res):
    ok = not (isinstance(res, dict) and "__error__" in res)
    print(f"[{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        fails.append(label)
        print("      ", res.get("__error__"))
    return res


try:
    r = rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                        "clientInfo": {"name": "selfcheck", "version": "1"}}})
    print(f"server -> {r['result']['serverInfo']['name']} v{r['result']['serverInfo']['version']}")
    p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
    p.stdin.flush()

    r = rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    print(f"tools  -> {len(r['result']['tools'])} 个\n")

    info = check("get_user_info (账号+容量)", tool("get_user_info"))
    if isinstance(info, dict) and "user_name" in info:
        print(f"        {info['user_name']} | {info.get('used_gb')} GB / {info.get('total_gb')} GB")

    files = check("list_files (根目录)", tool("list_files", {"limit": 3}))
    if isinstance(files, list):
        for i in files[:3]:
            print(f"        [{i['type']}] {i['name']}")

    check("search_files (搜索)", tool("search_files", {"query": "e", "limit": 1}))
finally:
    p.terminate()

print("\n" + "=" * 44)
if fails:
    print(f"自检失败: {', '.join(fails)}")
    sys.exit(1)
print("自检通过：token 有效，MCP 可正常连接。")
