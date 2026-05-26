import asyncio
import sys

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

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    uvicorn.run(
        "backend.core.server:app",
        host=host,
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()
