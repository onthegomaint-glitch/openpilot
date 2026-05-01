from __future__ import annotations

import time
from typing import Any

from cereal import car, messaging
from openpilot.common.params import Params
from openpilot.common.realtime import Ratekeeper
from openpilot.common.swaglog import cloudlog
from openpilot.tools.bodyteleop.remote_start_adapters import RemoteStartRequest, adapter_for_car
from openpilot.tools.bodyteleop.remote_start_status import (
  consume_remote_start_request,
  read_remote_start_config,
  write_remote_start_status,
)


REQUEST_PARAM = "LanRemoteStartRequested"
CONFIG_PARAM = "LanRemoteStartConfig"
STATUS_PARAM = "LanRemoteStartStatus"
MIN_REQUEST_INTERVAL_S = 30.0


def _now() -> int:
  return int(time.time())


def _put_status(params: Params, state: str, reason: str, **extra: Any) -> None:
  status = {
    "state": state,
    "reason": reason,
    "updatedAt": _now(),
    **extra,
  }
  write_remote_start_status(params, status)
  cloudlog.event("lan_remote_start_status", **status)


def _read_car_params(params: Params) -> car.CarParams:
  for key in ("CarParams", "CarParamsPersistent", "CarParamsCache"):
    raw = params.get(key)
    if raw:
      return messaging.log_from_bytes(raw, car.CarParams)
  return car.CarParams.new_message()


def _read_config(params: Params) -> RemoteStartRequest:
  cfg = read_remote_start_config(params)
  return RemoteStartRequest(
    enabled=bool(cfg.get("enabled", True)),
    temperature_c=max(16.0, min(30.0, float(cfg.get("temperatureC", 21.0)))),
    fan_level=max(0, min(5, int(cfg.get("fanLevel", 2)))),
    front_defrost=bool(cfg.get("frontDefrost", False)),
  )


def _safe_to_attempt(sm: messaging.SubMaster) -> tuple[bool, str]:
  sm.update(0)
  if not sm.alive["carState"]:
    return True, "carState not live offroad; relying on manager offroad gating"
  if not sm.valid["carState"]:
    return False, "carState invalid"

  cs = sm["carState"]
  ignition_on = bool(cs.ignitionLine or cs.ignitionCan)
  moving = abs(cs.vEgo) > 0.1 or not bool(cs.standstill)
  if ignition_on:
    return False, "ignition already on"
  if moving:
    return False, "vehicle is not standstill"
  return True, "safe precheck passed"


def _handle_request(params: Params, sm: messaging.SubMaster, last_attempt: float) -> float:
  now = time.monotonic()
  cfg = _read_config(params)
  CP = _read_car_params(params)
  car_fingerprint = str(CP.carFingerprint or "unknown")
  adapter = adapter_for_car(CP)

  if now - last_attempt < MIN_REQUEST_INTERVAL_S:
    _put_status(params, "rejected", "rate limited", carFingerprint=car_fingerprint, adapter=adapter.name, config=cfg.as_dict())
    return last_attempt

  safe, safety_reason = _safe_to_attempt(sm)
  if not safe:
    _put_status(params, "rejected", safety_reason, carFingerprint=car_fingerprint, adapter=adapter.name, config=cfg.as_dict())
    return now

  result = adapter.execute(cfg)
  _put_status(
    params,
    result.state,
    result.reason,
    carFingerprint=car_fingerprint,
    adapter=adapter.name,
    safety=safety_reason,
    config=cfg.as_dict(),
    details=result.details or {},
  )
  return now


def main() -> None:
  params = Params()
  sm = messaging.SubMaster(["carState"])
  rk = Ratekeeper(1.0, print_delay_threshold=None)
  last_attempt = 0.0

  _put_status(params, "idle", "waiting for LAN remote start request")
  while True:
    if consume_remote_start_request(params):
      last_attempt = _handle_request(params, sm, last_attempt)
    rk.keep_time()


if __name__ == "__main__":
  main()
