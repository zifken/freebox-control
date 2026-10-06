# freebox-control

Scripts and lessons learned for driving a Freebox (Free's French ISP router) through
its HTTP API: listing LAN hosts, Wake-on-LAN, and Wi-Fi AP configuration — including
the three gotchas that make real control painful in practice.

This is the sanitized companion to an operations case study: everything here runs
against **placeholder or dummy credentials** by default, and documents the failure
modes we hit, not just the happy path.

> Nothing in this repo contains a real `app_token`, password, or personal hostname.
> `demo.py` will not reach any router until you set the environment variables
> yourself and authorize the app from the box's LCD screen.

## What's inside

| File | Purpose |
|---|---|
| `README.md` | Auth flow, session/CSRF gotchas, full-record PUT recipe, DFS diagnosis |
| `demo.py` | Runnable demo (stdlib only): auth handshake, LAN listing, WoL, Wi-Fi AP put |
| `LICENSE` | MIT |

## The auth flow (official app-token path)

The Freebox API (base URL is typically `http://mafreebox.freebox.fr` on the LAN,
HTTPS with a self-signed cert) uses a two-step app authorization:

1. **Request an app token** — `POST /api/vX/login/authorize/` with your app's
   name, version, device name, and an empty object. The router asks its owner to
   press the right-arrow button on the box's LCD. The response gives you
   `app_token` (store it safely — this repo never will) and a `track_id`.
2. **Poll the challenge** — `GET /api/vX/login/authorize/<track_id>` until
   `status` is `granted` (or `timeout`/`denied`). The response carries a
   `challenge` value that rotates on every session and must accompany each login.
3. **Open a session** — `POST /api/vX/login/session/` with the `app_id`,
   the stored `app_token` (HMAC of the password) and the current `challenge`.
   You get a `session_token` to send as the `X-Fbx-App-Auth` header.
4. **Logout** — `POST /api/vX/login/logout/` to close the session cleanly.

`demo.py` implements exactly this, with a dummy `app_token` placeholder, so you
can run it end-to-end against `example.invalid` and watch the error handling
without touching a real box.

## Gotchas learned the hard way

### 1. POSTs and CSRF

Session-authenticated **POSTs** on the web-app path are CSRF-protected, and the
documented workarounds (`X-Fbx-Csrf-Token` header, or `csrf_token` in the JSON
body) both fail. The reliable path used by the router's own web UI is issuing the
request **through the in-page `Ext.Ajax` stack** — i.e. the same request the UI
itself makes. If you drive the web session programmatically (browser automation
instead of the app-token flow), that's the shape to imitate:

```js
new Promise(res => Ext.Ajax.request({
  url: FbxConf.apiBaseUrl + 'lan/wol/pub/',
  method: 'POST',
  jsonData: {mac: 'aa:bb:cc:dd:ee:ff', password: ''},
  success: r => res(r.responseText),
  failure: r => res('FAIL ' + r.status + ' ' + r.responseText)
}));
```

Also note: the web session expires within minutes; re-login before every batch
of calls. A `200` response with `error_code: "invalid_request"` (or
`invalid_api_version`) usually means the **path** is wrong, not the auth.

### 2. Full-record PUTs

Updating a Wi-Fi AP requires a **full record**: GET the AP object
(`GET /api/vX/wifi/ap/`), patch only the `config` fields you need, and PUT the
*entire* object (`capabilities`, `name`, `id`, `config`, `status`) to
`PUT /api/vX/wifi/ap/<id>` — **no trailing slash**.

A PUT containing only the changed config fields returns `success: true` but
**silently does not persist**. The omitted fields get reset. Always GET → patch
→ PUT the whole record.

### 3. DFS: invisible 5 GHz after a reboot

After a reboot the 5 GHz SSID can be missing. It's usually not broken: the AP
picked a DFS channel (100–144) and is running the Dynamic Frequency Selection
radar check, which can hold the radio silent for up to 600 s. Diagnose with:

```
GET /api/vX/wifi/ap/  →  status.state == "dfs"
                        status.dfs_cac_remaining_time (seconds, up to 600)
```

If you don't want the wait, force a non-DFS channel via the full-record PUT
above (e.g. `primary_channel: 36`, `secondary_channel: 40`, `dfs_enabled: false`).

### 4. Finding the real endpoints

The public docs drift from the firmware. The router's own web app is the ground
truth: grep its bundled JavaScript (`freeboxos.min.js`) for `apiBaseUrl+"..."`
patterns to discover the actual API version and endpoint paths your firmware
serves. `GET /api_version` (no auth) is always the first call to make.

## Running the demo

```bash
# Dummy run (no router): shows the flow and exits gracefully
python3 demo.py

# Real run: set your own values, press the LCD button when asked
export FBX_BASE_URL="http://mafreebox.freebox.fr"   # or your box's LAN address
export FBX_APP_ID="fr.example.myfreeboxapp"
export FBX_APP_TOKEN=""                              # from a first authorize call
python3 demo.py lan
python3 demo.py wol aa:bb:cc:dd:ee:ff
```

The API major version is auto-discovered from `/api_version` at startup.

## Lessons

- **Document the failure, then the command.** "CSRF headers don't work — use the
  in-page request path" outlives any single working command.
- **PUT semantics bite.** Partial-record PUTs that return `success: true` while
  dropping your changes are worse than an error.
- **The firmware is the API reference.** When docs and the box disagree, trust
  the JavaScript shipped in the web UI.
- **Radar-awareness is a feature.** Reading `dfs_cac` status turns "my Wi-Fi is
  broken" into "the channel is in its check window".

## License

MIT — see [LICENSE](LICENSE).
