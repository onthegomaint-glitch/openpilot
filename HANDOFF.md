# Session handoff — LAN phone control for sunnypilot

Last updated: 2026-04-21 (end of night).

## Current state

- Fork/repo used by installer: `https://github.com/onthegomaint-glitch/openpilot`
- Branch on device and PC: `staging-tici`
- Latest useful commits:
  - `b9a5c067e` Handle non-JSON or error `/offer` responses
  - `5678507a4` Ignore non-JSON WebRTC data-channel frames
  - `8a8e3b1` Fix `Params().get("DongleId")` call on device
  - `e4b8ba1` Core LAN API/UI feature commit
- Device confirmed on latest (`git log` on comma showed `5678507` and `8a8e3b1`; `b9a5c067e` pushed at end of session)

## What works

- Custom installer path works with repo name `openpilot`:
  - `installer.comma.ai/onthegomaint-glitch/staging-tici`
  - short form on device also works: `onthegomaint-glitch/staging-tici`
- `tools/bodyteleop/web.py` runs on comma and serves HTTPS on `:5000`
- LAN token auth works (`X-Local-Token` / UI token box)
- `/api/status` returns JSON correctly

## Known blocker at end of session

Main failure is now audio-related in `webrtcd`, not token/network:

- `OSError: [Errno -9985] Device unavailable` from `system/webrtc/device/audio.py`
- This can break stream session after `/offer`
- Logs showed stream sessions connecting then ending; ALSA/JACK warnings are noisy but expected, the fatal line is `-9985`

## Runbook to resume tomorrow

### 1) SSH into comma

From Windows PowerShell:

```powershell
ssh -i "$env:USERPROFILE\.ssh\id_ed25519" comma@192.168.86.234
```

### 2) Run `webrtcd` and `bodyteleop` in separate terminals

Terminal A (comma shell):

```bash
cd /data/openpilot
PYTHONPATH=/data/openpilot python3 system/webrtc/webrtcd.py --host 0.0.0.0 --port 5001
```

Terminal B (comma shell):

```bash
cd /data/openpilot
PYTHONPATH=/data/openpilot python3 tools/bodyteleop/web.py
```

### 3) Verify ports on comma

```bash
ss -tlnp | grep -E ':5000|:5001'
```

### 4) Browser checks

- Open: `https://192.168.86.234:5000/?v=5` (or increment query to bust cache)
- Use current token from web.py log
- `https://192.168.86.234:5000/ping` should return `pong`

### 5) Likely next fix

Disable audio negotiation for bodyteleop stream to avoid `-9985` device errors, then re-test video and controls.

## Feature summary implemented

- Added LAN-only authenticated API endpoints in `tools/bodyteleop/web.py`:
  - `GET /api/status`
  - `POST /api/command/remote_start`
  - `POST /api/command/charge_start`
  - `POST /api/command/charge_stop`
- Added phone UI controls and token input:
  - `tools/bodyteleop/static/index.html`
  - `tools/bodyteleop/static/js/jsmain.js`
  - `tools/bodyteleop/static/main.css`
- Added param keys:
  - `LanRemoteStartRequested`
  - `LanChargeStartRequested`
  - `LanChargeStopRequested`

Important: these params are only request flags. Vehicle-specific actuator logic is still needed for real remote start/charge control.

## Notes

- Keep Git identity as:
  - `user.name = otg`
  - `user.email = onthegomaint-glitch@users.noreply.github.com`
- `otgpilot` duplicate repo is no longer needed; active remote is `openpilot`

---

Resume point: fix/disable audio path in webrtcd session setup so offer succeeds and video stays up reliably.
