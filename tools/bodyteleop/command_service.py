from __future__ import annotations

from dataclasses import dataclass, field
import logging
import time
from typing import Any, Literal

try:
  from openpilot.common.params import Params
except ModuleNotFoundError:
  try:
    from common.params import Params
  except ModuleNotFoundError:
    Params = None

try:
  from openpilot.tools.bodyteleop.remote_start_status import (
    trigger_remote_start_request,
    write_remote_start_config,
    write_remote_start_status,
  )
except ModuleNotFoundError:
  from tools.bodyteleop.remote_start_status import (
    trigger_remote_start_request,
    write_remote_start_config,
    write_remote_start_status,
  )


logger = logging.getLogger("bodyteleop.command_service")

CommandName = Literal["remote_start", "charge_start", "charge_stop", "sentry_toggle"]
CommandState = Literal["requested", "completed", "rejected"]

COMMAND_PARAMS: dict[CommandName, str] = {
  "remote_start": "LanRemoteStartRequested",
  "charge_start": "LanChargeStartRequested",
  "charge_stop": "LanChargeStopRequested",
  "sentry_toggle": "LanSentryModeEnabled",
}


@dataclass(slots=True)
class RemoteStartConfig:
  enabled: bool = True
  temperature_c: float = 21.0
  fan_level: int = 2
  front_defrost: bool = False

  def to_param_dict(self) -> dict[str, Any]:
    return {
      "enabled": self.enabled,
      "temperatureC": self.temperature_c,
      "fanLevel": self.fan_level,
      "frontDefrost": self.front_defrost,
    }


@dataclass(slots=True)
class CommandResult:
  ok: bool
  command: CommandName
  state: CommandState
  reason: str
  requested_at: int
  details: dict[str, Any] = field(default_factory=dict)

  def to_response(self) -> dict[str, Any]:
    body = {
      "ok": self.ok,
      "requested": self.command,
      "state": self.state,
      "reason": self.reason,
      "details": self.details,
    }
    if self.command == "sentry_toggle" and "enabled" in self.details:
      body["enabled"] = bool(self.details["enabled"])
    return body


class CommandError(ValueError):
  pass


def _require_params(params: Params | None) -> Params:
  if params is None:
    raise CommandError("Params backend unavailable on this host")
  return params


def normalize_remote_start_payload(payload: dict[str, Any]) -> RemoteStartConfig:
  ac_cfg = payload.get("ac", {})
  if not isinstance(ac_cfg, dict):
    raise CommandError("Invalid remote_start payload")

  return RemoteStartConfig(
    enabled=bool(ac_cfg.get("enabled", True)),
    temperature_c=float(ac_cfg.get("temperatureC", 21.0)),
    fan_level=int(ac_cfg.get("fanLevel", 2)),
    front_defrost=bool(ac_cfg.get("frontDefrost", False)),
  )


def trigger_param_command(params: Params, param_name: str) -> None:
  params.put_bool(param_name, False)
  params.put_bool(param_name, True)


def execute_command(command: str, payload: dict[str, Any] | None, params: Params | None, now: int | None = None) -> CommandResult:
  requested_at = int(time.time()) if now is None else int(now)
  safe_payload = payload if isinstance(payload, dict) else {}

  if command not in COMMAND_PARAMS:
    raise CommandError("Unknown command")

  typed_command = command
  typed_params = _require_params(params)

  logger.info("command submit name=%s payload_keys=%s", typed_command, sorted(safe_payload.keys()))

  if typed_command == "remote_start":
    cfg = normalize_remote_start_payload(safe_payload)
    param_cfg = cfg.to_param_dict()
    write_remote_start_config(typed_params, param_cfg)
    write_remote_start_status(typed_params, {
      "state": "requested",
      "reason": "waiting for vehicle-side worker",
      "updatedAt": requested_at,
      "config": param_cfg,
    })
    trigger_remote_start_request(typed_params)
    result = CommandResult(
      ok=True,
      command="remote_start",
      state="requested",
      reason="waiting for vehicle-side worker",
      requested_at=requested_at,
      details={"config": param_cfg},
    )
    logger.info("command accepted name=%s state=%s", result.command, result.state)
    return result

  if typed_command == "sentry_toggle":
    current = typed_params.get_bool("LanSentryModeEnabled")
    enabled = not current
    typed_params.put_bool("LanSentryModeEnabled", enabled)
    result = CommandResult(
      ok=True,
      command="sentry_toggle",
      state="completed",
      reason="sentry state updated",
      requested_at=requested_at,
      details={"enabled": enabled},
    )
    logger.info("command completed name=%s state=%s enabled=%s", result.command, result.state, enabled)
    return result

  trigger_param_command(typed_params, COMMAND_PARAMS[typed_command])
  result = CommandResult(
    ok=True,
    command=typed_command,
    state="requested",
    reason="request flag updated",
    requested_at=requested_at,
  )
  logger.info("command accepted name=%s state=%s", result.command, result.state)
  return result
