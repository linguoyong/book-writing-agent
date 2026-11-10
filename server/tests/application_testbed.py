"""Isolated real application + deterministic OpenAI-compatible service for integration tests.

Run manually with ``uv run python -m tests.application_testbed --port 18879``.
Only the model service is simulated; agents, tools, approvals, persistence and HTTP are real.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import tempfile
import threading
import time
from contextlib import asynccontextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TOKEN = "application-integration-test-token"
BODY = "林昭站在雨中的青石桥上，握紧了手中的旧剑。远处传来一声钟鸣。"


def model_response(payload):
    messages = payload.get("messages", [])
    last_user = max((i for i, m in enumerate(messages) if m["role"] == "user"), default=-1)
    prompt = str(messages[last_user].get("content", "")) if last_user >= 0 else ""
    if prompt.startswith("TEST_TOOL "):
        spec = json.loads(prompt.removeprefix("TEST_TOOL "))
        if not any(m["role"] == "tool" for m in messages[last_user + 1 :]):
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_integration",
                        "type": "function",
                        "function": {
                            "name": spec["name"],
                            "arguments": json.dumps(spec["args"], ensure_ascii=False),
                        },
                    }
                ],
            }
        return {"role": "assistant", "content": "操作已完成，请查看实际工具结果。"}
    if '"dimensions"' in prompt:
        content = json.dumps(
            {
                "dimensions": dict.fromkeys(
                    ["consistency", "structure", "pacing", "voice", "hook", "redundancy"], 4
                ),
                "issues": [],
                "summary": "测试审稿：各项满足要求。",
                "verdict": "pass",
            },
            ensure_ascii=False,
        )
    elif "为一部小说建立设定库" in prompt:
        content = json.dumps(
            {
                "characters": [
                    {
                        "name": "林昭",
                        "aliases": ["小昭"],
                        "role": "主角",
                        "note": "携带旧剑",
                        "confidence": 0.95,
                    },
                    {"name": "神秘来客", "note": "身份待确认", "confidence": 0.3},
                ],
                "events": [
                    {"summary": "林昭在桥上听到钟声", "characters": ["林昭"], "importance": "major"}
                ],
            },
            ensure_ascii=False,
        )
    elif '"techniques"' in prompt and '"structure"' in prompt:
        content = json.dumps(
            {
                "summary": "人物在雨中等待，钟声留下悬念。",
                "structure": {"goal": "等待"},
                "techniques": [
                    {"name": "声音留悬念", "how": "以远方钟声结束场景", "when": "章节收尾"}
                ],
                "entities": {
                    "characters": [{"name": "林昭", "note": "携带旧剑", "confidence": 0.95}]
                },
            },
            ensure_ascii=False,
        )
    elif "创建两个东西" in prompt or "风格分析师" in prompt:
        content = json.dumps(
            {
                "expert": {
                    "id": "rain-expert",
                    "name": "雨夜风格",
                    "prompt": "节奏克制",
                    "body": "以具体细节写场景。",
                },
                "skill": {
                    "id": "rain-skill",
                    "name": "测试悬念技法",
                    "description": "章末技法",
                    "body": "用声音留悬念。",
                },
            },
            ensure_ascii=False,
        )
    elif "改写" in prompt and not payload.get("tools"):
        content = "雨落青石桥，林昭握紧旧剑，远处钟声缓缓传来。"
    elif "长期保留" in prompt:
        content = "- 用户偏好克制的文字。"
    else:
        content = (
            ("测试流式回复。" * 120)
            if prompt.startswith("TEST_SLOW")
            else "测试回复：已收到请求，历史记录将被保留。"
        )
    return {"role": "assistant", "content": content}


class ModelService(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path.endswith("/embeddings"):
            texts = payload["input"]
            texts = [texts] if isinstance(texts, str) else texts
            data = [
                {
                    "object": "embedding",
                    "index": index,
                    "embedding": [
                        value / 255 for value in hashlib.sha256(text.encode()).digest()[:8]
                    ],
                }
                for index, text in enumerate(texts)
            ]
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "object": "list",
                        "data": data,
                        "model": payload["model"],
                        "usage": {"prompt_tokens": 10, "total_tokens": 10},
                    }
                ).encode()
            )
            return
        messages = payload.get("messages", [])
        prompt = str(
            next((m.get("content", "") for m in reversed(messages) if m["role"] == "user"), "")
        )
        if prompt.startswith("TEST_ERROR"):
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                b'{"error":{"message":"integration model error","type":"invalid_request_error"}}'
            )
            return
        message = model_response(payload)
        common = {
            "id": "chatcmpl-integration",
            "created": int(time.time()),
            "model": "integration-model",
        }
        usage = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}
        self.send_response(200)
        self.send_header(
            "Content-Type", "text/event-stream" if payload.get("stream") else "application/json"
        )
        self.end_headers()
        if not payload.get("stream"):
            self.wfile.write(
                json.dumps(
                    {
                        **common,
                        "object": "chat.completion",
                        "usage": usage,
                        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
                    },
                    ensure_ascii=False,
                ).encode()
            )
            return

        def emit(delta, finish=None):
            item = {
                **common,
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
            }
            self.wfile.write(("data: " + json.dumps(item, ensure_ascii=False) + "\n\n").encode())
            self.wfile.flush()

        try:
            emit({"role": "assistant"})
            if message.get("tool_calls"):
                emit({"tool_calls": [{"index": 0, **message["tool_calls"][0]}]})
                emit({}, "tool_calls")
            else:
                content = message["content"]
                for start in range(0, len(content), 8):
                    emit({"content": content[start : start + 8]})
                    if prompt.startswith("TEST_SLOW"):
                        time.sleep(0.12)
                emit({}, "stop")
            self.wfile.write(
                (
                    "data: "
                    + json.dumps(
                        {**common, "object": "chat.completion.chunk", "choices": [], "usage": usage}
                    )
                    + "\n\ndata: [DONE]\n\n"
                ).encode()
            )
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass


def serve(port, model_port, home):
    os.environ["BOOK_AGENT_HOME"] = str(home)
    os.environ["BOOK_AGENT_TOKEN"] = TOKEN
    os.environ.pop("BOOK_AGENT_DISABLE_AUTH", None)

    import uvicorn
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse
    from fastapi.staticfiles import StaticFiles

    from app.config import EmbeddingSettings, ModelSettings, Settings, save_settings
    from app.main import app as backend

    service = ThreadingHTTPServer(("127.0.0.1", model_port), ModelService)
    model = ModelSettings(
        base_url=f"http://127.0.0.1:{service.server_port}/v1",
        api_key="test-only-key",
        model="integration-model",
    )
    save_settings(
        Settings(
            writer=model,
            extractor=model,
            reviewer=model,
            embedding=EmbeddingSettings(provider="none"),
        )
    )
    threading.Thread(target=service.serve_forever, daemon=True).start()

    @asynccontextmanager
    async def lifespan(_):
        async with backend.router.lifespan_context(backend):
            yield
        await asyncio.to_thread(service.shutdown)
        service.server_close()

    frontend = FastAPI(lifespan=lifespan)
    assets = Path(__file__).resolve().parents[2] / "apps/desktop/out/renderer"
    if assets.exists():
        frontend.mount("/assets", StaticFiles(directory=assets / "assets"))

        @frontend.get("/", response_class=HTMLResponse)
        def index():
            html = (assets / "index.html").read_text(encoding="utf-8")
            script = f"""<script>window.desktop={{backendInfo:async()=>({{port:{port},ready:true}})}};
            const originalFetch=window.fetch;
            window.fetch=(url,init={{}})=>{{const headers=new Headers(init.headers);
            if(String(url).startsWith('http://127.0.0.1:{port}/api/')) headers.set('X-Book-Agent-Token','{TOKEN}');
            return originalFetch(url,{{...init,headers}})}};</script>"""
            return html.replace("<head>", "<head>" + script)

    frontend.mount("/", backend)
    print(json.dumps({"home": str(home), "url": f"http://127.0.0.1:{port}"}), flush=True)
    uvicorn.run(frontend, host="127.0.0.1", port=port, access_log=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18879)
    parser.add_argument("--model-port", type=int, default=0)
    parser.add_argument("--home", type=Path)
    args = parser.parse_args()
    serve(
        args.port,
        args.model_port,
        args.home or Path(tempfile.mkdtemp(prefix="book-app-integration-")),
    )
