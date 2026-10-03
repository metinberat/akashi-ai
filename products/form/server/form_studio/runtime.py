"""Standalone loopback runtime with OS-held ownership; no AKASHI Core process."""

import json
import os
import socket
from pathlib import Path

import uvicorn
from .api import create_app


def main():
    root = Path(os.environ["FORM_DATA_DIR"]).resolve()
    root.mkdir(parents=True, exist_ok=True)
    lock = (root / "runtime.lock").open("a+b")
    lock.seek(0)
    if os.name == "nt":
        import msvcrt

        if lock.read(1) == b"":
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = None
    app = create_app(
        root,
        os.environ["FORM_RUNTIME_TOKEN"],
        Path(os.environ["FORM_WEB_DIR"]),
        shutdown_callback=lambda: setattr(server, "should_exit", True),
        recover=True,
    )
    server = uvicorn.Server(
        uvicorn.Config(
            app, log_level="warning", access_log=False, timeout_graceful_shutdown=240
        )
    )
    print(json.dumps({"port": sock.getsockname()[1], "product": "FORM"}), flush=True)
    try:
        server.run(sockets=[sock])
    finally:
        sock.close()
        lock.close()


if __name__ == "__main__":
    main()
