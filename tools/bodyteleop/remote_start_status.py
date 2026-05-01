from __future__ import annotations

import json
import os
from typing import Any

from openpilot.common.params import Params


STATUS_PARAM = "LanRemoteStartStatus"
STATUS_FALLBACK_PATH = "/data/lan_remote_start_status.json"


def read_remote_start_status(params: Params | None) -> dict[str, Any]:
  if params is not None:
    try:
      status = params.get(STATUS_PARAM, return_default=True)
      if isinstance(status, dict):
        return status
    except Exception:
      pass

  try:
    with open(STATUS_FALLBACK_PATH, encoding="utf-8") as f:
      status = json.load(f)
      if isinstance(status, dict):
        return status
  except (FileNotFoundError, OSError, json.JSONDecodeError):
    pass
  return {}


def write_remote_start_status(params: Params | None, status: dict[str, Any]) -> None:
  if params is not None:
    try:
      params.put(STATUS_PARAM, status)
      return
    except Exception:
      pass

  tmp_path = f"{STATUS_FALLBACK_PATH}.tmp"
  os.makedirs(os.path.dirname(STATUS_FALLBACK_PATH), exist_ok=True)
  with open(tmp_path, "w", encoding="utf-8") as f:
    json.dump(status, f, separators=(",", ":"), sort_keys=True)
  os.replace(tmp_path, STATUS_FALLBACK_PATH)
