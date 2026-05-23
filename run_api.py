import asyncio
import signal
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

import uvicorn


def main():
    print("=" * 55)
    print("   LEAD EXTRACTION API SERVER")
    print("=" * 55)
    host = input("Host (default 127.0.0.1): ").strip() or "127.0.0.1"
    port_str = input("Port (default 8000): ").strip()
    port = int(port_str) if port_str.isdigit() else 8000
    print(f"\nStarting API server at http://{host}:{port}")
    print("Press Ctrl+C to stop.\n")

    cfg = {"host": host, "port": port, "use_reloader": False}
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    uvicorn.run(
        "api.server:app",
        host=cfg["host"],
        port=cfg["port"],
        reload=False,
    )


if __name__ == "__main__":
    main()
