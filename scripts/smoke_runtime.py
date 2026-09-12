"""Exercise the installed package with a real store and a local test embedder."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import select
import socket
import subprocess
import sys
from threading import Thread
import time
from urllib.request import Request, urlopen


EXISTING = "An existing memory must survive package upgrades.\n"


class TestEmbedder(BaseHTTPRequestHandler):
    """Transport fixture only: finite vectors, no semantic quality claims."""

    def reply(self, data: dict) -> None:
        payload = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        self.reply({"models": [{"name": "bge-m3"}], "version": "0.0.0-test"})

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        if self.path == "/api/show":
            self.reply({"model_info": {"bert.context_length": 8192, "bert.embedding_length": 1024}})
        elif self.path == "/api/embed":
            inputs = body.get("input", "")
            count = len(inputs) if isinstance(inputs, list) else 1
            self.reply({"embeddings": [[1.0] + [0.0] * 1023 for _ in range(count)]})
        else:
            self.send_error(404)

    def log_message(self, format: str, *args) -> None:
        pass


def git(store: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(store), *args], text=True).strip()


def seed(store: Path) -> None:
    store.mkdir(parents=True, exist_ok=True)
    git(store, "init", "-q")
    git(store, "config", "user.name", "Package smoke test")
    git(store, "config", "user.email", "smoke@example.com")
    (store / "insights").mkdir(exist_ok=True)
    (store / "insights/existing.md").write_text(EXISTING)
    (store / ".gitignore").write_text("*.db*\n.palinode/\nlogs/\n.audit/\n")
    git(store, "add", "insights/existing.md", ".gitignore")
    git(store, "commit", "-qm", "Seed existing memory before package installation")
    (store.parent / f"{store.name}-original-commit.txt").write_text(git(store, "rev-parse", "HEAD"))
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("PALINODE_", "OLLAMA_", "EMBEDDING_"))}
    env.update(PALINODE_DIR=str(store), PALINODE_ALLOW_FRESH_DB="1",
               OLLAMA_URL=f"http://127.0.0.1:{unused_port()}")
    subprocess.run([sys.executable, "-c", "from palinode.core.store import init_db; init_db()"],
                   env=env, cwd=store, check=True)


def unused_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def request(base: str, path: str, data: dict | None = None):
    req = Request(base + path, data=json.dumps(data).encode() if data is not None else None,
                  headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=30) as response:
        return json.load(response)


def rpc(process: subprocess.Popen, message: dict) -> dict:
    process.stdin.write(json.dumps(message) + "\n")
    process.stdin.flush()
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(f"MCP exited with code {process.returncode}")
        if select.select([process.stdout], [], [], 1)[0]:
            line = process.stdout.readline()
            if line:
                response = json.loads(line)
                if response.get("id") == message["id"]:
                    assert "error" not in response, response
                    return response["result"]
    raise AssertionError("MCP response timed out")


def stop(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def smoke(bin_dir: Path, store: Path) -> None:
    assert (store / "insights/existing.md").read_text() == EXISTING
    original = (store.parent / f"{store.name}-original-commit.txt").read_text()
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("PALINODE_", "OLLAMA_", "EMBEDDING_"))}
    port = unused_port()
    embedder = ThreadingHTTPServer(("127.0.0.1", 0), TestEmbedder)
    Thread(target=embedder.serve_forever, daemon=True).start()
    env.update(PALINODE_DIR=str(store), PALINODE_API_HOST="127.0.0.1", PALINODE_API_PORT=str(port),
               OLLAMA_URL=f"http://127.0.0.1:{embedder.server_port}", PYTHONUNBUFFERED="1")
    base = f"http://127.0.0.1:{port}"
    with open(store.parent / f"{store.name}-api.log", "w") as log:
        api = subprocess.Popen([str(bin_dir / "palinode-api")], cwd=store, env=env, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 45
            while True:
                if api.poll() is not None:
                    raise AssertionError(f"API exited with {api.returncode}; see API log")
                try:
                    request(base, "/health")
                    break
                except OSError as error:
                    if time.monotonic() > deadline:
                        raise AssertionError("API did not become ready") from error
                    time.sleep(0.25)
            request(base, "/save", {"content": "The copper lantern is the release-test decision. Keep this rationale.",
                                    "type": "Insight", "slug": "homebrew-smoke"})
            memory = request(base, "/read?file_path=insights/homebrew-smoke.md")
            assert "copper lantern" in json.dumps(memory), memory
            hits = request(base, "/search", {"query": "copper lantern", "limit": 5, "threshold": 0.0})
            assert "copper lantern" in json.dumps(hits), hits
            with urlopen(base + "/ui/", timeout=30) as response:
                assert response.status == 200
            with open(store.parent / f"{store.name}-mcp.log", "w") as mcp_log:
                mcp = subprocess.Popen([str(bin_dir / "palinode-mcp")], cwd=store, env=env,
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=mcp_log,
                                       text=True, bufsize=1)
                try:
                    rpc(mcp, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                        "protocolVersion": "2025-03-26", "capabilities": {},
                        "clientInfo": {"name": "homebrew-smoke", "version": "1.0"}}})
                    mcp.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
                    mcp.stdin.flush()
                    tools = rpc(mcp, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
                    assert any(tool["name"] == "palinode_status" for tool in tools["tools"])
                    status = rpc(mcp, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                       "params": {"name": "palinode_status", "arguments": {}}})
                    assert not status.get("isError"), status
                finally:
                    stop(mcp)
        finally:
            stop(api)
            embedder.shutdown()
            embedder.server_close()
    assert (store / "insights/existing.md").read_text() == EXISTING
    git(store, "merge-base", "--is-ancestor", original, "HEAD")
    print(json.dumps({"store": str(store), "original_commit": original, "save": "pass", "read": "pass",
                      "search": "pass", "embedder": "local transport fixture", "ui": "pass", "mcp": "pass",
                      "existing_memory": "preserved"}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--bin", type=Path)
    parser.add_argument("--seed", action="store_true")
    args = parser.parse_args()
    if args.seed:
        seed(args.store.resolve())
    else:
        if args.bin is None:
            parser.error("--bin is required unless --seed is used")
        smoke(args.bin.resolve(), args.store.resolve())
