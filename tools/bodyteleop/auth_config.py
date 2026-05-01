from __future__ import annotations

import json
import os

from openpilot.common.params import Params


AUTH_CONFIG_PARAM = "LanAuthConfig"
AUTH_CONFIG_FALLBACK_PATH = "/data/lan_auth_config.json"


def _read_json_path(path: str) -> dict:
  try:
    with open(path, encoding="utf-8") as f:
      value = json.load(f)
      if isinstance(value, dict):
        return value
  except (FileNotFoundError, OSError, json.JSONDecodeError):
    pass
  return {}


def _write_json_path(path: str, value: dict) -> None:
  tmp_path = f"{path}.tmp"
  os.makedirs(os.path.dirname(path), exist_ok=True)
  with open(tmp_path, "w", encoding="utf-8") as f:
    json.dump(value, f, separators=(",", ":"), sort_keys=True)
  os.replace(tmp_path, path)


def read_auth_config(params: Params | None) -> dict:
  if params is not None:
    try:
      cfg = params.get(AUTH_CONFIG_PARAM, return_default=True)
      if isinstance(cfg, dict):
        return cfg
    except Exception:
      pass
  return _read_json_path(AUTH_CONFIG_FALLBACK_PATH)


def write_auth_config(params: Params | None, cfg: dict) -> None:
  if params is not None:
    try:
      params.put(AUTH_CONFIG_PARAM, cfg)
      return
    except Exception:
      pass
  _write_json_path(AUTH_CONFIG_FALLBACK_PATH, cfg)
