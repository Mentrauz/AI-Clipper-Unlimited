"""OpenAI-compatible bridge: answers PeakCut's AI requests by running `claude -p` (Claude Code, your subscription)."""
import json, os, subprocess, tempfile, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("BRIDGE_PORT", "8790"))
MODELS = ["haiku", "sonnet", "opus"]
CWD = tempfile.mkdtemp(prefix="claude-bridge-")  # empty dir: no project context gets loaded


def ask(model, prompt):
    p = subprocess.run(["claude", "-p", "--model", model, "--no-session-persistence"],
                       input=prompt, capture_output=True, text=True, encoding="utf-8", cwd=CWD, timeout=600, shell=False)
    if p.returncode != 0:
        raise RuntimeError(f"claude exited {p.returncode}: " + (p.stderr or p.stdout or "no output")[:500])
    return p.stdout.strip()


class H(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            return self._send(200, {"data": [{"id": m, "object": "model"} for m in MODELS]})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if not self.path.rstrip("/").endswith("/chat/completions"):
            return self._send(404, {"error": "not found"})
        prompt = "\n\n".join(m["content"] if isinstance(m["content"], str) else "".join(
            c.get("text", "") for c in m["content"]) for m in body.get("messages", []))
        prompt += "\n\nReply with only the requested JSON, no commentary and no code fences."
        try:
            text = ask(body.get("model") or "haiku", prompt)
        except Exception as e:  # noqa: BLE001
            return self._send(500, {"error": {"message": str(e)}})
        self._send(200, {"id": "bridge", "object": "chat.completion", "created": int(time.time()), "model": body.get("model"),
                         "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": text}}],
                         "usage": {"prompt_tokens": 0, "completion_tokens": 0}})

    def log_message(self, *a):
        pass


print(f"Claude Code bridge on http://127.0.0.1:{PORT}/v1", flush=True)
ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
