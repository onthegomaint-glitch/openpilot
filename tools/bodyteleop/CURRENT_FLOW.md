# Current Teleop Command And Status Flow

This document captures the current command and status behavior before Milestone 1 changes runtime structure.

## Command Entry Points

Frontend commands are sent from [tools/bodyteleop/static/js/jsmain.js](/C:/Users/msher/OneDrive/Desktop/Cursor projects/sunnypilot-clean/tools/bodyteleop/static/js/jsmain.js:114) through:

- `POST /api/command/remote_start`
- `POST /api/command/charge_start`
- `POST /api/command/charge_stop`
- `POST /api/command/sentry_toggle`

The backend entry point is [api_command in tools/bodyteleop/web.py](/C:/Users/msher/OneDrive/Desktop/Cursor projects/sunnypilot-clean/tools/bodyteleop/web.py:281).

## Status Entry Points

The current UI polls:

- `GET /api/status`
- `GET /api/auth/status`
- `GET /api/capture/status`

Relevant frontend readers live in:

- [refreshVehicleStatus in jsmain.js](/C:/Users/msher/OneDrive/Desktop/Cursor projects/sunnypilot-clean/tools/bodyteleop/static/js/jsmain.js:91)
- [refreshAuthStatus in jsmain.js](/C:/Users/msher/OneDrive/Desktop/Cursor projects/sunnypilot-clean/tools/bodyteleop/static/js/jsmain.js:238)
- [refreshCaptureStatus in jsmain.js](/C:/Users/msher/OneDrive/Desktop/Cursor projects/sunnypilot-clean/tools/bodyteleop/static/js/jsmain.js:164)

## Current Command Matrix

| Command | HTTP payload today | Backend behavior today | Params touched | UI result path |
|---|---|---|---|---|
| `remote_start` | `{ ac: { enabled, temperatureC, fanLevel, frontDefrost } }` | Writes remote-start config, writes initial remote-start status, then toggles request flag | `LanRemoteStartConfig`, `LanRemoteStartStatus`, `LanRemoteStartRequested` | Immediate `Requested: remote_start`, then async polling from `/api/status` via `remoteStartStatus` |
| `charge_start` | `{}` | Sets request param false then true | `LanChargeStartRequested` | Immediate `Requested: charge_start` only |
| `charge_stop` | `{}` | Sets request param false then true | `LanChargeStopRequested` | Immediate `Requested: charge_stop` only |
| `sentry_toggle` | `{}` | Reads current bool and writes opposite value | `LanSentryModeEnabled` | Immediate `Requested: sentry_toggle`, plus `/api/status` updates `sentryEnabled` |

## Current Status Matrix

`GET /api/status` currently returns a structure built by [_read_vehicle_status in tools/bodyteleop/web.py](/C:/Users/msher/OneDrive/Desktop/Cursor projects/sunnypilot-clean/tools/bodyteleop/web.py:169).

Fields currently used by the UI:

| Status field | Source today | UI usage |
|---|---|---|
| `batteryPercent` | `carState.fuelGauge` | Main command result line |
| `charging` | `carState.charging` | Main command result line |
| `deviceVoltage` | `Params().get("CarBatteryCapacity")` | Device voltage text |
| `sentryEnabled` | `Params().get_bool("LanSentryModeEnabled")` | Sentry result line |
| `remoteStartStatus` | `read_remote_start_status(params)` | Remote-start progress/reason text |

Status fields returned but not clearly used by the current UI:

- `ignitionOn`
- `standstill`
- `gear`
- `updated`
- `valid`
- `logMonoTime`
- `remoteStartConfig`
- `statusAvailable`

## Current Auth Behavior

Auth endpoints exist but are effectively placeholders:

- [api_auth_status](/C:/Users/msher/OneDrive/Desktop/Cursor projects/sunnypilot-clean/tools/bodyteleop/web.py:245) always returns authenticated
- [api_auth_setup](/C:/Users/msher/OneDrive/Desktop/Cursor projects/sunnypilot-clean/tools/bodyteleop/web.py:253) always returns ok
- [api_auth_login](/C:/Users/msher/OneDrive/Desktop/Cursor projects/sunnypilot-clean/tools/bodyteleop/web.py:257) always returns ok
- [api_auth_logout](/C:/Users/msher/OneDrive/Desktop/Cursor projects/sunnypilot-clean/tools/bodyteleop/web.py:261) always returns ok
- [refreshAuthStatus](/C:/Users/msher/OneDrive/Desktop/Cursor projects/sunnypilot-clean/tools/bodyteleop/static/js/jsmain.js:238) hardcodes `isAuthenticated = true`

Real access control today is only:

- local/private-network check in [_verify_access](/C:/Users/msher/OneDrive/Desktop/Cursor projects/sunnypilot-clean/tools/bodyteleop/web.py:90)

## Remote Start Flow Today

Current request path:

1. UI sends `POST /api/command/remote_start`.
2. `api_command` normalizes the AC payload.
3. `api_command` writes `LanRemoteStartConfig`.
4. `api_command` writes a `"requested"` object into `LanRemoteStartStatus`.
5. `api_command` toggles `LanRemoteStartRequested`.
6. [remote_startd.py](/C:/Users/msher/OneDrive/Desktop/Cursor projects/sunnypilot-clean/tools/bodyteleop/remote_startd.py:1) polls for the request.
7. Worker consumes the request flag, reads config, runs prechecks, executes adapter logic, and writes final status.
8. UI learns the outcome later through `GET /api/status`.

Current shape weakness:

- HTTP submission and worker transport are tightly coupled to `Params`.
- Result reporting is half immediate and half inferred from later polling.

## Charge Flow Today

Current request path:

1. UI sends `POST /api/command/charge_start` or `charge_stop`.
2. `api_command` toggles the associated request flag.
3. UI gets an immediate `"Requested: ..."` message.
4. There is no equivalent typed result object surfaced through `/api/status` today.

Current shape weakness:

- Request accepted is not the same as request completed.
- The UI has no explicit charge command outcome object.

## Sentry Flow Today

Current request path:

1. UI sends `POST /api/command/sentry_toggle`.
2. `api_command` flips `LanSentryModeEnabled`.
3. Response immediately returns the new boolean.
4. UI also refreshes `/api/status` and reads `sentryEnabled`.

Current shape weakness:

- Sentry is treated more like direct state mutation than a command contract.
- Its response shape differs from the request-flag commands.

## Milestone 1 Implications

This is why Milestone 1 should focus on a typed internal `command_service` first:

- keep the current UI untouched
- standardize command submission in one place
- standardize accepted/result state before changing transport
- make later cleanup measurable
