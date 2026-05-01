# Session Handoff - sunnypilot LAN control / UI

Last updated: 2026-05-01

## Repo

- GitHub fork: `https://github.com/ravenskys/openpilot`
- Branch: `staging-tici`
- Push remote: `fork` -> `https://github.com/ravenskys/openpilot.git`
- `origin` may still point to `sunnypilot/sunnypilot`; use `fork` for this work

## Current status

- LAN control UI is wired up in `tools/bodyteleop/web.py` with auth, command endpoints, and a static phone UI.
- `tools/bodyteleop/lancontrol.py` runs the LAN UI offroad without joystick debug mode.
- Remote-start request plumbing exists end-to-end:
  - `LanRemoteStartConfig` stores A/C, temp C, fan level, and front defrost.
  - `LanRemoteStartRequested` is consumed by `tools/bodyteleop/remote_startd.py`.
  - `LanRemoteStartStatus` is written back for the phone UI.
- `tools/bodyteleop/remote_start_adapters.py` currently stops at a Hyundai Kona EV safety blocker instead of sending unknown CAN.
- `tools/bodyteleop/capture_can_window.py` records timed CAN JSONL captures to `/data/bluelink_captures/`.
- The phone UI includes a `Data Capture` tab for starting labeled capture windows.
- `BLUELINK_CAPTURE_CHECKLIST.md` is the operator guide for capture runs.
- UI changes already added:
  - `FREEZE` diagnostic snapshots to `/data/freeze_frames/`
  - Wide road camera on blinker below about 20 mph
  - Offroad display gestures in `selfdrive/ui/ui_state.py`: 3 taps wake/extend display, 4 taps sleep display
- Loggerd watchdog is present on device under `/data/loggerd_watchdog/`.

## Main blocker

Remote-start UI and daemon work are in place, but actual vehicle actuation is not.

- Device fingerprint found so far: `HYUNDAI_KONA_EV`
- Safety config seen on device: `hyundai`, param `65`
- Stock longitudinal is disabled
- Likely telematics remote-start DBC candidate: `TMU_GW_E_01` (`0x53a`) with `CF_Gway_TeleReqEngineOperate`
- Climate status candidate: `FATC11` (`0x383`)
- Current Hyundai panda safety allowlist appears limited to known openpilot control frames such as `LKAS11` (`0x340`), `CLU11` (`0x4f1`), and `LFAHDA_MFC` (`0x485`)

Bottom line: `TMU_GW_E_01` and HVAC actuation frames are expected to be blocked by normal `sendcan` until we either capture stock Bluelink traffic or add a narrowly reviewed offroad safety path.

## Next session

1. Reconnect to the comma:
   `ssh comma@192.168.86.227`
2. Check whether the LAN UI is already listening:
   `ss -ltnp | grep ':5000'`
3. If not, start it from `/data/openpilot`:
   `VIRTUAL_ENV=/usr/local/venv PYTHONPATH=/data/openpilot PATH=/usr/comma/shims:/usr/local/venv/bin:/usr/local/.cargo/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin python3 -m tools.bodyteleop.lancontrol`
4. Open `http://192.168.86.227:5000`, log in, and use the `Data Capture` tab.
5. Collect initial captures:
   `baseline`, `climate_on`, `climate_off`, `charge_start`, `charge_stop`
6. Copy captures off-device:
   `scp comma@192.168.86.227:/data/bluelink_captures/*.jsonl .`
7. Rebuild or restart UI on the comma before validating:
   - `FREEZE`
   - wide-on-blinker camera switch
   - 3/4-tap display gestures

## Useful paths

- `/data/openpilot/` - repo checkout
- `/data/bluelink_captures/` - raw CAN capture windows
- `/data/freeze_frames/` - user-triggered freeze snapshots
- `/data/loggerd_watchdog/` - loggerd and encoderd health logs
- `/data/media/0/realdata/` - route video and rlogs

## Open issues

- `system/webrtc/webrtcd.py`: bodyteleop audio may still fail with `-9985 Device unavailable`; may need audio disabled in the offer path
- Sentry and device-voltage UI values are still partly placeholder telemetry
- Last known device state: updated bodyteleop files copied and compiled on-device, then SSH and port checks started timing out during banner exchange; likely device busy or in a power-state transition

## Handy commands

- Capture command template:
  `cd /data/openpilot && VIRTUAL_ENV=/usr/local/venv PYTHONPATH=/data/openpilot PATH=/usr/comma/shims:/usr/local/venv/bin:/usr/local/.cargo/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin python3 -m tools.bodyteleop.capture_can_window --seconds 180 --label climate_on`
- Remote-start debug dump:
  `python3 -m tools.bodyteleop.remote_start_debug`

## Git note

- If commit identity matters, set `user.name` and `user.email` on the machine you commit from.
