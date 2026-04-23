# Session handoff — sunnypilot / LAN control / UI

Last updated: 2026-04-22.

## Repos and branch

- **Active fork (GitHub):** `https://github.com/ravenskys/openpilot` (transferred from `onthegomaint-glitch/openpilot`)
- **Branch:** `staging-tici`
- **Local remote name:** `fork` → `https://github.com/ravenskys/openpilot.git`
- **Upstream in clone:** `origin` may still point at `sunnypilot/sunnypilot` for merges; use `fork` to push this work

## Recent commits (landscape)

- On-road **FREEZE** diagnostic snapshot button → `/data/freeze_frames/freeze_*.txt` (`selfdrive/ui/onroad/freeze_frame*.py`, `hud_renderer.py`)
- **Wide road camera** when turn signal on and speed under ~20 mph (`augmented_road_view.py`)
- **Loggerd watchdog** on device: `/data/loggerd_watchdog/`, 1 GiB cap, `scripts/loggerd_watchdog.sh`, autostart from `launch_openpilot.sh`
- **LAN auth** + remote start A/C + sentry UI + `future` annotations fix for Windows `web.py` import
- `HANDOFF.md` + bodyteleop / params work as in earlier history

## What works (high level)

- `tools/bodyteleop/web.py` — LAN API, auth, commands, static UI
- Comma installer URL style: `installer.comma.ai/ravenskys/staging-tici` (verify exact path if installer changed)
- Device: pull `staging-tici` from `ravenskys/openpilot`; set `git remote` if you still have old URL

## On-device paths worth knowing

| Path | Purpose |
|------|--------|
| `/data/freeze_frames/` | User-tapped **FREEZE** text snapshots |
| `/data/loggerd_watchdog/` | Auto health + error/freeze logs for loggerd/encoderd |
| `/data/media/0/realdata/` | Route video / rlogs |
| `/data/openpilot/` | Repo checkout |

## Known issues / next steps (from prior sessions)

- **webrtcd / bodyteleop:** audio `-9985 Device unavailable` may still need audio disabled in offer path for reliable streaming
- **Params `Lan*Requested`:** still flags; vehicle-side actuation for remote start / charge is separate work
- **Sentry / device voltage in UI:** partly placeholder telemetry

## Quick SSH (example)

```powershell
ssh comma@192.168.86.234
```

IP may change on LAN; use device’s current address.

## Resume points

1. Rebuild / restart UI on comma after UI pulls so **FREEZE** and **wide-on-blinker** are active
2. Copy diagnostics: `scp comma@<ip>:/data/freeze_frames/freeze_*.txt .` and `.../data/loggerd_watchdog/snapshot_*.log` as needed
3. Continue webrtcd audio hardening if phone camera path still fails

## Git notes

- If commits should show a specific identity, set `user.name` / `user.email` on the machine you commit from; do not commit secrets.
