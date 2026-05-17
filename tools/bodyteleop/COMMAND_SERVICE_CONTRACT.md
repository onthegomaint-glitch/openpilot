# Command Service Contract Draft

This is the Milestone 1 internal contract for the teleop command layer. It is intentionally backend-focused and keeps the current HTTP API and UI payloads stable.

## Goals

- One internal entrypoint for teleop commands behind `web.py`
- Typed request normalization for current commands
- Explicit accepted/result state even before `cereal` transport exists
- Easy migration path to Milestone 2

## Non-Goals

- Changing the current browser payloads
- Replacing `Params` transport in this phase
- Splitting `web.py` into separate services in this phase

## Internal Model

Suggested implementation module:

- `tools/bodyteleop/command_service.py`

Suggested internal types:

```python
from dataclasses import dataclass, field
from typing import Any, Literal

CommandName = Literal["remote_start", "charge_start", "charge_stop", "sentry_toggle"]
CommandState = Literal["accepted", "rejected", "requested", "completed", "noop"]

@dataclass(slots=True)
class RemoteStartConfig:
  enabled: bool = True
  temperature_c: float = 21.0
  fan_level: int = 2
  front_defrost: bool = False

@dataclass(slots=True)
class CommandRequest:
  command: CommandName
  requested_at: int
  source: str = "lan_web"
  payload: dict[str, Any] = field(default_factory=dict)

@dataclass(slots=True)
class CommandResult:
  ok: bool
  command: CommandName
  state: CommandState
  reason: str
  requested_at: int
  details: dict[str, Any] = field(default_factory=dict)
```

## HTTP Compatibility Rule

The browser can keep sending:

- `POST /api/command/remote_start` with `body.ac`
- `POST /api/command/charge_start` with `{}`
- `POST /api/command/charge_stop` with `{}`
- `POST /api/command/sentry_toggle` with `{}`

`web.py` should parse HTTP, then hand a typed request to `command_service`.

## Command Normalization Rules

### `remote_start`

Incoming browser payload today:

```json
{
  "ac": {
    "enabled": true,
    "temperatureC": 21,
    "fanLevel": 2,
    "frontDefrost": false
  }
}
```

Normalized internal shape:

```python
RemoteStartConfig(
  enabled=bool(ac.enabled),
  temperature_c=float(ac.temperatureC),
  fan_level=int(ac.fanLevel),
  front_defrost=bool(ac.frontDefrost),
)
```

Milestone 1 backend behavior:

- write normalized config
- write explicit `"requested"` status
- trigger existing request transport
- return `CommandResult(ok=True, state="requested", ...)`

### `charge_start`

Incoming browser payload today:

```json
{}
```

Milestone 1 backend behavior:

- trigger existing request transport
- return `CommandResult(ok=True, state="requested", ...)`

### `charge_stop`

Incoming browser payload today:

```json
{}
```

Milestone 1 backend behavior:

- trigger existing request transport
- return `CommandResult(ok=True, state="requested", ...)`

### `sentry_toggle`

Incoming browser payload today:

```json
{}
```

Milestone 1 backend behavior:

- read current sentry state
- write the toggled value
- return `CommandResult(ok=True, state="completed", ...)`

Suggested `details` payload:

```python
{"enabled": new_value}
```

## Error Rules

Suggested cases:

- unknown command -> `ok=False`, `state="rejected"`, reason `"unknown command"`
- params unavailable -> `ok=False`, `state="rejected"`, reason `"params backend unavailable"`
- invalid payload -> `ok=False`, `state="rejected"`, reason `"invalid payload"`

HTTP can continue to map these into current response semantics while the UI stays unchanged.

## Service Entrypoint

Suggested function shape:

```python
def execute_command(command: str, payload: dict[str, Any], params: Params | None, now: int) -> CommandResult:
  ...
```

Optional helper split:

```python
def normalize_remote_start_payload(payload: dict[str, Any]) -> RemoteStartConfig:
  ...

def trigger_param_command(params: Params, param_name: str) -> None:
  ...
```

## Response Mapping Back To HTTP

Milestone 1 does not need to expose the full internal model directly to the browser, but `api_command` should map from `CommandResult` consistently.

Suggested HTTP response body:

```json
{
  "ok": true,
  "requested": "remote_start",
  "state": "requested",
  "reason": "waiting for vehicle-side worker",
  "details": {}
}
```

For sentry toggle:

```json
{
  "ok": true,
  "requested": "sentry_toggle",
  "state": "completed",
  "reason": "sentry state updated",
  "details": {
    "enabled": true
  }
}
```

This keeps the current UI working while giving us a better internal contract.

## Status Surfacing Rule

Milestone 1 should keep using `/api/status`, but the command service should make command outcomes explicit enough to surface there later.

For now:

- remote start already has `remoteStartStatus`
- sentry already has `sentryEnabled`
- charge commands need a future status/result field in Milestone 2

## Milestone 2 Mapping

This contract is intentionally shaped so it can become `cereal` messages later:

- `CommandRequest` -> future `TeleopCommand`
- `CommandResult` -> future `TeleopCommandAck` or `TeleopCommandResult`
- normalized payload objects -> future typed message payloads

That lets us swap transport without changing command semantics again.
