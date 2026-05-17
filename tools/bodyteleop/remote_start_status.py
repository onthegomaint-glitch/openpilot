from __future__ import annotations

import json
import os
from typing import Any

try:
  from openpilot.common.params import Params
except ModuleNotFoundError:
  try:
    from common.params import Params
  except ModuleNotFoundError:
    Params = None


CONFIG_PARAM = "LanRemoteStartConfig"
REQUEST_PARAM = "LanRemoteStartRequested"
STATUS_PARAM = "LanRemoteStartStatus"
CONFIG_FALLBACK_PATH = "/data/lan_remote_start_config.json"
REQUEST_FALLBACK_PATH = "/data/lan_remote_start_requested"
STATUS_FALLBACK_PATH = "/data/lan_remote_start_status.json"


def _read_json_path(path: str) -> dict[str, Any]:
  try:
    with open(path, encoding="utf-8") as f:
      value = json.load(f)
      if isinstance(value, dict):
        return value
  except (FileNotFoundError, OSError, json.JSONDecodeError):
    pass
  return {}


def _write_json_path(path: str, value: dict[str, Any]) -> None:
  tmp_path = f"{path}.tmp"
  os.makedirs(os.path.dirname(path), exist_ok=True)
  with open(tmp_path, "w", encoding="utf-8") as f:
    json.dump(value, f, separators=(",", ":"), sort_keys=True)
  os.replace(tmp_path, path)


def read_remote_start_config(params: Params | None) -> dict[str, Any]:
  if params is not None:
    try:
      config = params.get(CONFIG_PARAM, return_default=True)
      if isinstance(config, dict):
        return config
    except Exception:
      pass
  return _read_json_path(CONFIG_FALLBACK_PATH)


def write_remote_start_config(params: Params | None, config: dict[str, Any]) -> None:
  if params is not None:
    try:
      params.put(CONFIG_PARAM, config)
      return
    except Exception:
      pass
  _write_json_path(CONFIG_FALLBACK_PATH, config)


def read_remote_start_status(params: Params | None) -> dict[str, Any]:
  if params is not None:
    try:
      status = params.get(STATUS_PARAM, return_default=True)
      if isinstance(status, dict):
        return status
    except Exception:
      pass
  return _read_json_path(STATUS_FALLBACK_PATH)


def write_remote_start_status(params: Params | None, status: dict[str, Any]) -> None:
  if params is not None:
    try:
      params.put(STATUS_PARAM, status)
      return
    except Exception:
      pass
  _write_json_path(STATUS_FALLBACK_PATH, status)


def consume_remote_start_request(params: Params | None) -> bool:
  if params is not None:
    try:
      requested = bool(params.get_bool(REQUEST_PARAM))
      if requested:
        params.put_bool(REQUEST_PARAM, False)
      return requested
    except Exception:
      pass

  try:
    with open(REQUEST_FALLBACK_PATH, encoding="utf-8") as f:
      requested = f.read().strip() == "1"
  except FileNotFoundError:
    return False
  except OSError:
    return False

  if requested:
    try:
      os.remove(REQUEST_FALLBACK_PATH)
    except FileNotFoundError:
      pass
  return requested


def trigger_remote_start_request(params: Params | None) -> None:
  if params is not None:
    try:
      params.put_bool(REQUEST_PARAM, False)
      params.put_bool(REQUEST_PARAM, True)
      return
    except Exception:
      pass

  os.makedirs(os.path.dirname(REQUEST_FALLBACK_PATH), exist_ok=True)
  with open(REQUEST_FALLBACK_PATH, "w", encoding="utf-8") as f:
    f.write("1")
