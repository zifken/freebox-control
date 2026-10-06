#!/usr/bin/env python3
"""freebox-control demo: Freebox OS API auth + a few read/write recipes.

Standard library only. Ships with DUMMY credentials so it is safe to run
anywhere: set FBX_BASE_URL / FBX_APP_ID / FBX_APP_TOKEN in your environment
to talk to a real box, and press the LCD right-arrow button when the box
asks for authorization.

Usage:
    python3 demo.py            # show auth handshake against configured target
    python3 demo.py lan        # list LAN hosts
    python3 demo.py wol AA:BB:CC:DD:EE:FF
    python3 demo.py wifi 36    # set 5GHz AP to non-DFS channel 36 (full-record PUT)
"""

import hashlib
import hmac
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

# --- dummy placeholders (no secrets in this repo) ---------------------------
BASE_URL = os.environ.get("FBX_BASE_URL", "https://example.invalid")
APP_ID = os.environ.get("FBX_APP_ID", "fr.example.freebox-control-demo")
APP_NAME = os.environ.get("FBX_APP_NAME", "freebox-control-demo")
APP_VERSION = os.environ.get("FBX_APP_VERSION", "0.1.0")
DEVICE_NAME = os.environ.get("FBX_DEVICE_NAME", "demo-host")
APP_TOKEN = os.environ.get("FBX_APP_TOKEN", "")  # dummy: never commit a real one

API = "api"  # version is discovered at runtime, e.g. /api/v12


def request(method, path, payload=None, session_token=None):
    """Minimal HTTPS/JSON client; ignores the box's self-signed cert."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    url = BASE_URL.rstrip("/") + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if session_token:
        req.add_header("X-Fbx-App-Auth", session_token)
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"http_status": e.code}
    except Exception as e:  # dummy creds / unreachable host land here
        return {"http_status": None, "error": str(e)}


def discover_api_version():
    """GET /api_version -> '12.1' -> we use the major, /api/v12."""
    meta = request("GET", "/api_version")
    version = str(meta.get("api_version", "")) if isinstance(meta, dict) else ""
    major = version.split(".")[0] if version else "12"
    return f"/{API}/v{major}"


def authorize():
    """Step 1+2: request an app token and poll until granted."""
    res = request("POST", f"{discover_api_version()}/login/authorize/", {
        "app_id": APP_ID, "app_name": APP_NAME, "app_version": APP_VERSION,
        "device_name": DEVICE_NAME,
    })
    if not res.get("success"):
        return None
    token, track_id = res["result"]["app_token"], res["result"]["track_id"]
    print(f"Press the right-arrow on the Freebox LCD to authorize '{APP_NAME}'...")
    while True:
        poll = request("GET", f"{discover_api_version()}/login/authorize/{track_id}")
        status = poll.get("result", {}).get("status")
        if status in ("granted", "denied", "timeout", "unknown"):
            return token if status == "granted" else None


def open_session(app_token):
    """Step 3: exchange challenge + app token for a session token."""
    challenge = request("GET", f"{discover_api_version()}/login/")["result"]["challenge"]
    password = hmac.new(app_token.encode(), challenge.encode(), hashlib.sha1).hexdigest()
    res = request("POST", f"{discover_api_version()}/login/session/", {
        "app_id": APP_ID, "password": password,
    })
    if res.get("success"):
        return res["result"]["session_token"]
    return None


# --- recipes ----------------------------------------------------------------

def list_lan(session_token):
    """GET /lan/browser/pub/ -> hosts with name, MAC, reachability, IPs."""
    res = request("GET", f"{discover_api_version()}/lan/browser/pub/", session_token=session_token)
    for host in res.get("result", []):
        mac = host.get("l2ident", {}).get("id", "?")
        ips = [c["addr"] for c in host.get("l3connectivities", []) if c.get("addr")]
        print(f"{host.get('primary_name', '?'):30} {mac} "
              f"{'up' if host.get('reachable') else 'down':5} {', '.join(ips)}")


def wake_on_lan(session_token, mac):
    """POST /lan/wol/pub/ with {mac, password: ''}. MACs like 'ether-<mac>' ids work too."""
    res = request("POST", f"{discover_api_version()}/lan/wol/pub/",
                  payload={"mac": mac.lower(), "password": ""},
                  session_token=session_token)
    print("WoL:", "sent" if res.get("success") else res)


def wifi_set_channel(session_token, channel):
    """Full-record PUT on /wifi/ap/<id>: GET, patch config, PUT the WHOLE object.

    A PUT with only the changed config fields returns success:true but
    silently does not persist. Always send the full record back.
    """
    base = f"{discover_api_version()}/wifi/ap"
    aps = request("GET", base + "/", session_token=session_token).get("result", [])
    for ap in aps:
        if not ap.get("config", {}).get("band_5GHz"):
            continue
        full = dict(ap)  # capabilities/name/id/config/status — everything
        full["config"]["primary_channel"] = int(channel)
        full["config"]["secondary_channel"] = int(channel) + 4
        full["config"]["dfs_enabled"] = False
        res = request("PUT", f"{base}/{ap['id']}", payload=full, session_token=session_token)
        print(f"AP {ap.get('name')}: {'ok' if res.get('success') else res}")


def main():
    if "example.invalid" in BASE_URL or not APP_TOKEN:
        print("No real Freebox configured (FBX_BASE_URL/FBX_APP_TOKEN unset) — "
              "demo mode. Set them, then re-run; press the LCD button when asked.")
        print(f"Would start auth against {BASE_URL} as app '{APP_NAME}' "
              f"({APP_ID}). See README for the full flow.")
        return 0
    token = authorize()
    if not token:
        print("Authorization not granted.")
        return 1
    session = open_session(token)
    if not session:
        print("Session open failed.")
        return 1
    cmd = sys.argv[1] if len(sys.argv) > 1 else "lan"
    if cmd == "lan":
        list_lan(session)
    elif cmd == "wol":
        wake_on_lan(session, sys.argv[2])
    elif cmd == "wifi":
        wifi_set_channel(session, sys.argv[2] if len(sys.argv) > 2 else 36)
    request("POST", f"{discover_api_version()}/login/logout/", payload={},
            session_token=session)
    return 0


if __name__ == "__main__":
    sys.exit(main())
