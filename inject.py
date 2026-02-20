"""Inject a message into a running Cowork Dash session."""

import httpx
import sys

BASE = "http://localhost:8050"


def main():
    message = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Hello from the outside!"

    # Find connected sessions
    resp = httpx.get(f"{BASE}/api/sessions")
    resp.raise_for_status()
    sessions = [s for s in resp.json() if s["connected"]]

    if not sessions:
        print("No connected sessions found.")
        return

    session_id = sessions[0]["session_id"]
    print(f"Injecting into session {session_id}...")

    resp = httpx.post(
        f"{BASE}/api/session/{session_id}/inject",
        json={"content": message},
    )
    resp.raise_for_status()
    print(f"Response ({resp.status_code}): {resp.json()}")


if __name__ == "__main__":
    main()
