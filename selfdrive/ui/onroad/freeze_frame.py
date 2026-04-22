import json
import os
import subprocess
import threading
from datetime import datetime

from openpilot.common.swaglog import cloudlog
from openpilot.common.params import Params
from openpilot.selfdrive.ui.ui_state import ui_state

FREEZE_DIR = "/data/freeze_frames"
_MAX_SECTION = 200_000


def _json_chunk(obj: object) -> str:
  try:
    return json.dumps(obj, default=str, indent=2)[:_MAX_SECTION]
  except TypeError as e:
    return f"<json error: {e}>\n" + str(obj)[:_MAX_SECTION]


def _append_msg(parts: list[str], title: str, name: str) -> None:
  sm = ui_state.sm
  parts.append(f"\n{'='*20} {title} {'='*20}\n")
  if not sm.seen.get(name, False):
    parts.append(f"(not seen yet: {name})\n")
    return
  try:
    msg = sm[name]
    if name == "modelV2":
      parts.append("modelV2 (subset)\n")
      parts.append(
        _json_chunk(
          {
            "frameId": getattr(msg, "frameId", None),
            "frameIdExtra": getattr(msg, "frameIdExtra", None),
            "frameDropPerc": getattr(msg, "frameDropPerc", None),
            "locationMonoTime": getattr(msg, "locationMonoTime", None),
          }
        )
      )
    else:
      d = msg.to_dict()
      parts.append(_json_chunk(d))
  except Exception as e:  # noqa: BLE001
    parts.append(f"dump error: {e}\n")


def _append_params(parts: list[str]) -> None:
  parts.append(f"\n{'='*20} Params (subset) {'='*20}\n")
  p = Params()
  for k, use_bool in (
    ("Version", False),
    ("DongleId", False),
    ("GitCommit", False),
    ("GitBranch", False),
    ("IsMetric", True),
    ("ExperimentalMode", True),
  ):
    try:
      b = p.get_bool(k) if use_bool else p.get(k, return_default=True)
      if isinstance(b, (bytes, bytearray)):
        b = b.decode("utf-8", errors="replace")
      parts.append(f"  {k}: {b!r}\n")
    except Exception as e:  # noqa: BLE001
      parts.append(f"  {k}: <{e}>\n")


def _append_shell(parts: list[str], title: str, args: list[str], timeout: float = 4.0) -> None:
  parts.append(f"\n{title}\n")
  try:
    r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    out = (r.stdout or "") + (r.stderr or "")
    parts.append(out[-_MAX_SECTION:])
  except Exception as e:  # noqa: BLE001
    parts.append(f"error: {e}\n")


def write_freeze_frame_file() -> str:
  os.makedirs(FREEZE_DIR, exist_ok=True)
  ts = datetime.now().strftime("%Y%m%d_%H%M%S")
  path = os.path.join(FREEZE_DIR, f"freeze_{ts}.txt")

  parts: list[str] = [f"user_freeze_frame {ts} (on-demand snapshot)\n"]

  _append_shell(
    parts,
    "GIT (short)",
    [
      "sh",
      "-c",
      "git -C /data/openpilot log -1 --oneline && echo && git -C /data/openpilot status -sb",
    ],
  )
  _append_shell(parts, "DF", ["df", "-h"])
  _append_shell(
    parts,
    "PS (stack)",
    [
      "sh",
      "-c",
      "ps aux | grep -E 'loggerd|encoderd|manager|selfdriv|controlsd|pandad|camerad|modeld' | grep -v grep | head -n 50",
    ],
  )
  dmesg_path = "/data/log/dmesg" if os.path.isfile("/data/log/dmesg") else None
  if dmesg_path:
    _append_shell(parts, "dmesg tail (file)", ["tail", "-n", "80", dmesg_path])
  else:
    _append_shell(parts, "dmesg tail", ["sh", "-c", "dmesg 2>/dev/null | tail -n 80"])

  for title, name in (
    ("carState", "carState"),
    ("controlsState", "controlsState"),
    ("selfdriveState", "selfdriveState"),
    ("deviceState", "deviceState"),
    ("radarState", "radarState"),
    ("liveCalibration", "liveCalibration"),
    ("longitudinalPlan", "longitudinalPlan"),
    ("pandaStates", "pandaStates"),
    ("managerState", "managerState"),
    ("roadCameraState", "roadCameraState"),
    ("wideRoadCameraState", "wideRoadCameraState"),
    ("modelV2", "modelV2"),
  ):
    _append_msg(parts, title, name)

  _append_params(parts)

  with open(path, "w", encoding="utf-8") as f:
    f.write("".join(parts))
  return path


def trigger_freeze_frame_async() -> None:
  def _work() -> None:
    try:
      p = write_freeze_frame_file()
      cloudlog.info("user freeze frame saved %s", p)
    except Exception as e:  # noqa: BLE001
      cloudlog.error("user freeze frame failed: %s", e)

  threading.Thread(target=_work, name="freeze_frame", daemon=True).start()
