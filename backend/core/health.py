import json
import sys
import urllib.error
import urllib.request


def _check(url: str, timeout: int) -> bool:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode())
            data = body.get("data", body)
            status = data.get("status")
            if status != "ok":
                print(f"HEALTHCHECK FAIL: status={status}", file=sys.stderr)
                return False
            print(f"OK | browser={data.get('browser_session', '?')} | tasks={data.get('active_tasks', '?')}")
            return True
    except urllib.error.URLError as e:
        print(f"HEALTHCHECK FAIL: {e}", file=sys.stderr)
        return False
    except (json.JSONDecodeError, KeyError) as e:
        print(f"HEALTHCHECK FAIL: invalid response — {e}", file=sys.stderr)
        return False


def main() -> int:
    url = "http://127.0.0.1:8000/health"
    timeout = 5
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--url" and i + 1 < len(args):
            url = args[i + 1]
        elif arg == "--timeout" and i + 1 < len(args):
            timeout = int(args[i + 1])
    return 0 if _check(url, timeout) else 1


if __name__ == "__main__":
    sys.exit(main())
