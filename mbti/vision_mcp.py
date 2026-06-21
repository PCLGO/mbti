#!/usr/bin/env python3
"""
MCP server — Qwen vision model for analyzing screenshots/UI.
Uses qwen3.5-omni-plus via DashScope API.
"""
import json
import sys
import base64
import os
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

API_KEY = os.environ.get("QWEN_API_KEY") or os.environ.get("DASHSCOPE_API_KEY") or ""
MODEL = "qwen3.5-omni-plus-2026-03-15"
API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"

MIME_MAP = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}


def log(msg):
    print(f"[vision_mcp] {msg}", file=sys.stderr, flush=True)


def respond(msg):
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle_analyze(args):
    path = args.get("path", "")
    prompt = args.get("prompt", "请详细描述这张图片中的内容，包括布局、颜色、文字、元素位置等。")

    if not Path(path).exists():
        return {"content": [{"type": "text", "text": f"文件不存在: {path}"}], "isError": True}

    if not API_KEY:
        return {"content": [{"type": "text", "text": "Qwen Vision API key is not configured. Set QWEN_API_KEY or DASHSCOPE_API_KEY."}], "isError": True}

    ext = Path(path).suffix.lower()
    mime = MIME_MAP.get(ext, "image/png")

    with open(path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

    payload = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_b64}"}}
        ]}],
        "max_tokens": 2048,
    }).encode()

    req = Request(API_URL, data=payload)
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {API_KEY}")

    try:
        with urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read())
        text = result["choices"][0]["message"]["content"]
        return {"content": [{"type": "text", "text": text}]}
    except URLError as e:
        return {"content": [{"type": "text", "text": f"API 请求失败: {e}"}], "isError": True}
    except Exception as e:
        return {"content": [{"type": "text", "text": f"错误: {e}"}], "isError": True}


def main():
    log("Starting Qwen Vision MCP server...")
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        msg_id = msg.get("id")
        method = msg.get("method")

        if method == "initialize":
            respond({
                "jsonrpc": "2.0", "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "qwen-vision", "version": "1.0.0"}
                }
            })
            log("Initialized")

        elif method == "notifications/initialized":
            pass

        elif method == "tools/list":
            respond({
                "jsonrpc": "2.0", "id": msg_id,
                "result": {
                    "tools": [{
                        "name": "analyze_image",
                        "description": "使用 Qwen 视觉模型分析图片内容（UI 截图、设计稿等）。支持 PNG/JPG。",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string", "description": "图片文件的完整路径"},
                                "prompt": {"type": "string", "description": "对图片的具体提问，如'这个页面的布局和颜色有什么问题？'"}
                            },
                            "required": ["path"]
                        }
                    }]
                }
            })

        elif method == "tools/call":
            result = handle_analyze(msg["params"]["arguments"])
            respond({"jsonrpc": "2.0", "id": msg_id, "result": result})

        elif method == "shutdown":
            respond({"jsonrpc": "2.0", "id": msg_id, "result": None})
            break

        else:
            respond({
                "jsonrpc": "2.0", "id": msg_id,
                "error": {"code": -32601, "message": f"未知方法: {method}"}
            })

    log("Shutdown")


if __name__ == "__main__":
    main()
