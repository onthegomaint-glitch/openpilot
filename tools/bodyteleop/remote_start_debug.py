#!/usr/bin/env python3
from __future__ import annotations

from cereal import car, messaging
from openpilot.common.params import Params
from openpilot.tools.bodyteleop.remote_start_status import (
  consume_remote_start_request,
  read_remote_start_config,
  read_remote_start_status,
  trigger_remote_start_request,
)


def _print_car_params(params: Params) -> None:
  for key in ("CarParams", "CarParamsPersistent", "CarParamsCache"):
    raw = params.get(key)
    print(f"{key}: {'present' if raw else 'missing'} {len(raw) if raw else 0}")
    if raw:
      CP = messaging.log_from_bytes(raw, car.CarParams)
      print(f"  carFingerprint: {CP.carFingerprint}")
      print(f"  carName: {CP.carName}")
      print(f"  carVin: {CP.carVin}")
      print(f"  notCar: {CP.notCar}")
      print(f"  dashcamOnly: {CP.dashcamOnly}")
      print(f"  openpilotLongitudinalControl: {CP.openpilotLongitudinalControl}")
      print(f"  safetyConfigs: {[(str(c.safetyModel), c.safetyParam) for c in CP.safetyConfigs]}")
      return


def _print_json_param(params: Params, key: str) -> None:
  value = params.get(key, return_default=True)
  print(f"{key}: {value if value is not None else 'missing'}")


def main() -> None:
  params = Params()
  _print_car_params(params)
  requested = consume_remote_start_request(params)
  if requested:
    trigger_remote_start_request(params)
  print(f"LanRemoteStartRequested: {requested}")
  print(f"LanRemoteStartConfig: {read_remote_start_config(params) or 'missing'}")
  print(f"LanRemoteStartStatus: {read_remote_start_status(params) or 'missing'}")


if __name__ == "__main__":
  main()
