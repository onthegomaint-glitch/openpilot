from __future__ import annotations

import asyncio
import dataclasses
import ipaddress
import json
import logging
import os
import re
import ssl
import subprocess
import sys
import time

try:
  import pyaudio
except ModuleNotFoundError:
  pyaudio = None
import wave
from aiohttp import web
from aiohttp import ClientSession

BASEDIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
try:
  from openpilot.common.params import Params
except ModuleNotFoundError:
  try:
    from common.params import Params
  except ModuleNotFoundError:
    Params = None

try:
  from cereal import messaging
except Exception:
  messaging = None

try:
  from openpilot.tools.bodyteleop.remote_start_status import (
    read_remote_start_config,
    read_remote_start_status,
    trigger_remote_start_request,
    write_remote_start_config,
    write_remote_start_status,
  )
except ModuleNotFoundError:
  from tools.bodyteleop.remote_start_status import (
    read_remote_start_config,
    read_remote_start_status,
    trigger_remote_start_request,
    write_remote_start_config,
    write_remote_start_status,
  )

logger = logging.getLogger("bodyteleop")
logging.basicConfig(level=logging.INFO)

TELEOPDIR = f"{BASEDIR}/tools/bodyteleop"
WEBRTCD_HOST, WEBRTCD_PORT = "localhost", 5001
COMMAND_PARAMS = {
  "remote_start": "LanRemoteStartRequested",
  "charge_start": "LanChargeStartRequested",
  "charge_stop": "LanChargeStopRequested",
  "sentry_toggle": "LanSentryModeEnabled",
}
CAPTURE_DIR = "/data/bluelink_captures"
VIDEO_LIBRARY_DIR = "/data/media/0/realdata"
VIDEO_LIBRARY_META_PATH = "/data/media/0/video_library_meta.json"
VIDEO_ROUTE_RE = re.compile(r"^[A-Za-z0-9]{16}\|\d{4}-\d{2}-\d{2}--\d{2}-\d{2}-\d{2}$")
VIDEO_SEGMENT_RE = re.compile(r"^(?P<route>[A-Za-z0-9]{16}\|\d{4}-\d{2}-\d{2}--\d{2}-\d{2}-\d{2})--(?P<segment>\d+)$")
LEGACY_VIDEO_SEGMENT_RE = re.compile(r"^(?P<route>[0-9a-f]{8}--[0-9a-f]{10})--(?P<segment>\d+)$", re.IGNORECASE)
VIDEO_FILE_MAP = {
  "qcamera": ("qcamera.ts", "Q camera"),
  "road": ("fcamera.hevc", "Road"),
  "wide": ("ecamera.hevc", "Wide"),
  "driver": ("dcamera.hevc", "Driver"),
}


@dataclasses.dataclass
class StreamRequestBody:
  sdp: str
  cameras: list[str]
  bridge_services_in: list[str] = dataclasses.field(default_factory=list)
  bridge_services_out: list[str] = dataclasses.field(default_factory=list)


def _is_private_request(request: 'web.Request') -> bool:
  remote = request.remote
  if remote is None:
    return False
  try:
    addr = ipaddress.ip_address(remote)
    return addr.is_private or addr.is_loopback
  except ValueError:
    return False


def _verify_access(request: 'web.Request'):
  if not _is_private_request(request):
    raise web.HTTPForbidden(text="Local network access only")
  return


## UTILS
async def play_sound(sound: str):
  if pyaudio is None:
    logger.warning("Skipping sound playback because pyaudio is unavailable")
    return

  SOUNDS = {
    "engage": "selfdrive/assets/sounds/engage.wav",
    "disengage": "selfdrive/assets/sounds/disengage.wav",
    "error": "selfdrive/assets/sounds/warning_immediate.wav",
  }
  assert sound in SOUNDS

  chunk = 5120
  with wave.open(os.path.join(BASEDIR, SOUNDS[sound]), "rb") as wf:
    def callback(in_data, frame_count, time_info, status):
      data = wf.readframes(frame_count)
      return data, pyaudio.paContinue

    p = pyaudio.PyAudio()
    stream = p.open(format=p.get_format_from_width(wf.getsampwidth()),
                    channels=wf.getnchannels(),
                    rate=wf.getframerate(),
                    output=True,
                    frames_per_buffer=chunk,
                    stream_callback=callback)
    stream.start_stream()
    while stream.is_active():
      await asyncio.sleep(0)
    stream.stop_stream()
    stream.close()
    p.terminate()

## SSL
def create_ssl_cert(cert_path: str, key_path: str):
  try:
    proc = subprocess.run(f'openssl req -x509 -newkey rsa:4096 -nodes -out {cert_path} -keyout {key_path} \
                          -days 365 -subj "/C=US/ST=California/O=commaai/OU=comma body"',
                          capture_output=True, shell=True)
    proc.check_returncode()
  except subprocess.CalledProcessError as ex:
    raise ValueError(f"Error creating SSL certificate:\n[stdout]\n{proc.stdout.decode()}\n[stderr]\n{proc.stderr.decode()}") from ex


def create_ssl_context():
  cert_path = os.path.join(TELEOPDIR, "cert.pem")
  key_path = os.path.join(TELEOPDIR, "key.pem")
  if not os.path.exists(cert_path) or not os.path.exists(key_path):
    logger.info("Creating certificate...")
    try:
      create_ssl_cert(cert_path, key_path)
    except ValueError:
      logger.warning("OpenSSL unavailable, starting HTTP-only server")
      return None
  else:
    logger.info("Certificate exists!")
  ssl_context = ssl.SSLContext(protocol=ssl.PROTOCOL_TLS_SERVER)
  ssl_context.load_cert_chain(cert_path, key_path)

  return ssl_context

## ENDPOINTS
async def index(request: 'web.Request'):
  with open(os.path.join(TELEOPDIR, "static", "index.html")) as f:
    content = f.read()
    return web.Response(content_type="text/html", text=content)


async def ping(request: 'web.Request'):
  return web.Response(text="pong")


async def sound(request: 'web.Request'):
  params = await request.json()
  sound_to_play = params["sound"]

  await play_sound(sound_to_play)
  return web.json_response({"status": "ok"})


def _read_vehicle_status(sm) -> dict:
  fuel_gauge = 0.0
  charging = False
  ignition_on = False
  standstill = False
  gear = "unknown"
  updated = False
  valid = False
  log_mono_time = 0

  if sm is not None:
    sm.update(0)
    car_state = sm["carState"]
    fuel_gauge = float(getattr(car_state, "fuelGauge", 0.0))
    charging = bool(getattr(car_state, "charging", False))
    ignition_on = bool(getattr(car_state, "ignitionLine", False) or getattr(car_state, "ignitionCan", False))
    standstill = bool(getattr(car_state, "standstill", False))
    gear = str(getattr(car_state, "gearShifter", "unknown"))
    updated = bool(sm.updated.get("carState", False))
    valid = bool(sm.valid.get("carState", False))
    log_mono_time = int(sm.logMonoTime.get("carState", 0))

  device_voltage = 0.0
  if Params is not None:
    cap = Params()
    car_batt = cap.get("CarBatteryCapacity", return_default=True)
    if isinstance(car_batt, (int, float)):
      device_voltage = float(car_batt)

  sentry_enabled = False
  remote_start_config = {}
  remote_start_status = {}
  if Params is not None:
    cap = Params()
    sentry_enabled = bool(cap.get_bool("LanSentryModeEnabled"))
    remote_start_config = read_remote_start_config(cap)
    remote_start_status = read_remote_start_status(cap)

  return {
    "batteryPercent": round(fuel_gauge * 100, 1),
    "charging": charging,
    "ignitionOn": ignition_on,
    "standstill": standstill,
    "gear": gear,
    "updated": updated,
    "valid": valid,
    "logMonoTime": log_mono_time,
    "deviceVoltage": round(device_voltage, 2),
    "sentryEnabled": sentry_enabled,
    "remoteStartConfig": remote_start_config,
    "remoteStartStatus": remote_start_status,
  }


async def api_config(request: 'web.Request'):
  _verify_access(request)
  return web.json_response({
    "ok": True,
    "tokenHint": "Use X-Local-Token header with the generated token from logs",
  })


async def api_status(request: 'web.Request'):
  _verify_access(request)
  sm = request.app["status_sm"]
  status = _read_vehicle_status(sm)
  status["statusAvailable"] = True
  return web.json_response({"ok": True, "status": status})


async def api_auth_status(request: 'web.Request'):
  return web.json_response({
    "ok": True,
    "setupRequired": False,
    "authenticated": True,
  })


async def api_auth_setup(request: 'web.Request'):
  return web.json_response({"ok": True})


async def api_auth_login(request: 'web.Request'):
  return web.json_response({"ok": True})


async def api_auth_logout(request: 'web.Request'):
  return web.json_response({"ok": True})


async def api_command(request: 'web.Request'):
  _verify_access(request)
  command = request.match_info["name"]
  if command not in COMMAND_PARAMS:
    raise web.HTTPBadRequest(text="Unknown command")

  params = request.app["params"]
  if params is None:
    return web.json_response({"ok": False, "error": "Params backend unavailable on this host"}, status=503)
  payload = {}
  try:
    payload = await request.json()
  except Exception:
    payload = {}

  if command == "sentry_toggle":
    current = params.get_bool("LanSentryModeEnabled")
    params.put_bool("LanSentryModeEnabled", not current)
    return web.json_response({"ok": True, "requested": command, "enabled": (not current)})

  if command == "remote_start" and isinstance(payload, dict):
    ac_cfg = payload.get("ac", {})
    if isinstance(ac_cfg, dict):
      safe_cfg = {
        "enabled": bool(ac_cfg.get("enabled", True)),
        "temperatureC": float(ac_cfg.get("temperatureC", 21.0)),
        "fanLevel": int(ac_cfg.get("fanLevel", 2)),
        "frontDefrost": bool(ac_cfg.get("frontDefrost", False)),
      }
      write_remote_start_config(params, safe_cfg)
      write_remote_start_status(params, {
        "state": "requested",
        "reason": "waiting for vehicle-side worker",
        "updatedAt": int(time.time()),
        "config": safe_cfg,
      })
      trigger_remote_start_request(params)
      return web.json_response({"ok": True, "requested": command})

  command_param = COMMAND_PARAMS[command]
  params.put_bool(command_param, False)
  params.put_bool(command_param, True)

  return web.json_response({"ok": True, "requested": command})


def _capture_status(app) -> dict:
  proc = app.get("capture_proc")
  meta = app.get("capture_meta", {})
  running = bool(proc is not None and proc.poll() is None)
  if proc is not None and not running:
    log_handle = app.get("capture_log_handle")
    if log_handle is not None:
      log_handle.close()
      app["capture_log_handle"] = None
  status = {
    "running": running,
    **meta,
  }
  if proc is not None and not running:
    status["returnCode"] = proc.returncode
  return status


def _is_safe_video_root(path: str) -> bool:
  try:
    return os.path.commonpath([os.path.realpath(path), os.path.realpath(VIDEO_LIBRARY_DIR)]) == os.path.realpath(VIDEO_LIBRARY_DIR)
  except ValueError:
    return False


def _load_video_library_meta() -> dict:
  try:
    with open(VIDEO_LIBRARY_META_PATH, encoding="utf-8") as f:
      data = json.load(f)
      if isinstance(data, dict):
        return data
  except FileNotFoundError:
    return {}
  except (OSError, json.JSONDecodeError):
    logger.warning("Failed to read video library metadata from %s", VIDEO_LIBRARY_META_PATH)
  return {}


def _save_video_library_meta(meta: dict) -> None:
  parent_dir = os.path.dirname(VIDEO_LIBRARY_META_PATH)
  os.makedirs(parent_dir, exist_ok=True)
  temp_path = f"{VIDEO_LIBRARY_META_PATH}.tmp"
  with open(temp_path, "w", encoding="utf-8") as f:
    json.dump(meta, f, indent=2, sort_keys=True)
  os.replace(temp_path, VIDEO_LIBRARY_META_PATH)


def _video_meta_key(route_name: str, segment_num: int, camera_key: str) -> str:
  return f"{route_name}--{segment_num}/{camera_key}"


def _resolve_video_entry(route_name: str, segment_num: int, camera_key: str) -> tuple[str, str] | tuple[None, None]:
  if not (VIDEO_ROUTE_RE.fullmatch(route_name) or LEGACY_VIDEO_SEGMENT_RE.fullmatch(f"{route_name}--{segment_num}")):
    return None, None
  if camera_key not in VIDEO_FILE_MAP:
    return None, None

  filename = VIDEO_FILE_MAP[camera_key][0]
  candidate_paths = [
    os.path.join(VIDEO_LIBRARY_DIR, f"{route_name}--{segment_num}", filename),
    os.path.join(VIDEO_LIBRARY_DIR, route_name, str(segment_num), filename),
  ]

  for candidate in candidate_paths:
    if os.path.isfile(candidate) and _is_safe_video_root(candidate):
      return candidate, _video_meta_key(route_name, segment_num, camera_key)
  return None, None


def _is_video_protected(meta: dict, route_name: str, segment_num: int, camera_key: str) -> bool:
  entry = meta.get(_video_meta_key(route_name, segment_num, camera_key), {})
  return bool(entry.get("protected", False)) if isinstance(entry, dict) else False


def _set_video_protection(meta: dict, route_name: str, segment_num: int, camera_key: str, protected: bool) -> dict:
  key = _video_meta_key(route_name, segment_num, camera_key)
  existing = meta.get(key, {})
  if not isinstance(existing, dict):
    existing = {}
  if protected:
    existing["protected"] = True
    existing["updatedAt"] = int(time.time())
    meta[key] = existing
  else:
    if key in meta:
      existing.pop("protected", None)
      existing["updatedAt"] = int(time.time())
      if any(v not in (None, False, "", [], {}) for v in existing.values()):
        meta[key] = existing
      else:
        meta.pop(key, None)
  return meta


def _build_segment_video_info(route_name: str, segment_num: int, segment_dir: str, meta: dict) -> dict | None:
  cameras = []
  for camera_key, (filename, label) in VIDEO_FILE_MAP.items():
    full_path = os.path.join(segment_dir, filename)
    if os.path.isfile(full_path):
      cameras.append({
        "key": camera_key,
        "label": label,
        "filename": filename,
        "protected": _is_video_protected(meta, route_name, segment_num, camera_key),
      })

  if not cameras:
    return None

  try:
    modified_at = int(os.path.getmtime(segment_dir))
  except OSError:
    modified_at = 0

  return {
    "routeName": route_name,
    "segmentNum": segment_num,
    "segmentName": f"{route_name}--{segment_num}",
    "modifiedAt": modified_at,
    "cameras": cameras,
  }


def _scan_video_library(query: str = "", limit: int = 60) -> list[dict]:
  if not os.path.isdir(VIDEO_LIBRARY_DIR):
    return []

  query_lower = query.strip().lower()
  meta = _load_video_library_meta()
  routes: dict[str, dict] = {}

  with os.scandir(VIDEO_LIBRARY_DIR) as entries:
    for entry in entries:
      if not entry.is_dir():
        continue

      segment_matches: list[dict] = []
      match = VIDEO_SEGMENT_RE.fullmatch(entry.name)
      if match:
        route_name = match.group("route")
        segment_info = _build_segment_video_info(route_name, int(match.group("segment")), entry.path, meta)
        if segment_info is not None:
          segment_matches.append(segment_info)
      else:
        legacy_match = LEGACY_VIDEO_SEGMENT_RE.fullmatch(entry.name)
        if legacy_match:
          route_name = legacy_match.group("route")
          segment_info = _build_segment_video_info(route_name, int(legacy_match.group("segment")), entry.path, meta)
          if segment_info is not None:
            segment_matches.append(segment_info)
      if not segment_matches and VIDEO_ROUTE_RE.fullmatch(entry.name):
        route_name = entry.name
        try:
          with os.scandir(entry.path) as segment_entries:
            for segment_entry in segment_entries:
              if not segment_entry.is_dir() or not segment_entry.name.isdigit():
                continue
              segment_info = _build_segment_video_info(route_name, int(segment_entry.name), segment_entry.path, meta)
              if segment_info is not None:
                segment_matches.append(segment_info)
        except OSError:
          continue

      if not segment_matches:
        continue

      route_key = segment_matches[0]["routeName"]
      route_bucket = routes.setdefault(route_key, {
        "routeName": route_key,
        "displayName": route_key,
        "modifiedAt": 0,
        "segmentCount": 0,
        "segments": [],
      })
      route_bucket["segments"].extend(segment_matches)
      route_bucket["segmentCount"] = len(route_bucket["segments"])
      route_bucket["modifiedAt"] = max(route_bucket["modifiedAt"], max(seg["modifiedAt"] for seg in segment_matches))

  route_list = list(routes.values())
  for route in route_list:
    route["segments"].sort(key=lambda seg: seg["segmentNum"])

  if query_lower:
    route_list = [
      route for route in route_list
      if query_lower in route["routeName"].lower() or any(query_lower in seg["segmentName"].lower() for seg in route["segments"])
    ]

  route_list.sort(key=lambda route: route["modifiedAt"], reverse=True)
  return route_list[:max(1, limit)]


def _resolve_video_path(route_name: str, segment_num: int, camera_key: str) -> str | None:
  video_path, _meta_key = _resolve_video_entry(route_name, segment_num, camera_key)
  return video_path


async def api_capture_status(request: 'web.Request'):
  _verify_access(request)
  return web.json_response({"ok": True, "capture": _capture_status(request.app)})


async def api_videos_list(request: 'web.Request'):
  _verify_access(request)
  query = str(request.query.get("query", "")).strip()
  try:
    limit = int(request.query.get("limit", "60"))
  except ValueError:
    limit = 60

  routes = _scan_video_library(query=query, limit=max(1, min(limit, 200)))
  return web.json_response({
    "ok": True,
    "libraryRoot": VIDEO_LIBRARY_DIR,
    "routes": routes,
  })


async def api_videos_stream(request: 'web.Request'):
  _verify_access(request)
  route_name = str(request.query.get("route", "")).strip()
  camera_key = str(request.query.get("camera", "qcamera")).strip()
  try:
    segment_num = int(request.query.get("segment", "0"))
  except ValueError as exc:
    raise web.HTTPBadRequest(text="Invalid segment number") from exc

  video_path = _resolve_video_path(route_name, segment_num, camera_key)
  if video_path is None:
    raise web.HTTPNotFound(text="Video not found")

  ffmpeg_cmd = [
    "ffmpeg",
    "-hide_banner",
    "-loglevel",
    "error",
    "-i",
    video_path,
    "-an",
    "-movflags",
    "frag_keyframe+empty_moov+faststart",
    "-pix_fmt",
    "yuv420p",
    "-c:v",
    "libx264",
    "-preset",
    "ultrafast",
    "-f",
    "mp4",
    "pipe:1",
  ]

  try:
    proc = await asyncio.create_subprocess_exec(
      *ffmpeg_cmd,
      stdout=asyncio.subprocess.PIPE,
      stderr=asyncio.subprocess.PIPE,
    )
  except FileNotFoundError as exc:
    raise web.HTTPServiceUnavailable(text="ffmpeg is not installed on this device") from exc

  response = web.StreamResponse(
    status=200,
    headers={
      "Content-Type": "video/mp4",
      "Cache-Control": "no-store",
      "X-Accel-Buffering": "no",
    },
  )
  await response.prepare(request)

  try:
    assert proc.stdout is not None
    while True:
      chunk = await proc.stdout.read(256 * 1024)
      if not chunk:
        break
      await response.write(chunk)

    return_code = await proc.wait()
    if return_code != 0:
      stderr = b""
      if proc.stderr is not None:
        stderr = await proc.stderr.read()
      logger.warning("ffmpeg exited with %s for %s: %s", return_code, video_path, stderr.decode("utf-8", errors="ignore"))
  except (asyncio.CancelledError, ConnectionResetError, BrokenPipeError):
    proc.kill()
    raise
  finally:
    if proc.returncode is None:
      proc.kill()
      await proc.wait()
    try:
      await response.write_eof()
    except (ConnectionResetError, RuntimeError):
      pass

  return response


async def api_videos_protect(request: 'web.Request'):
  _verify_access(request)
  payload = await request.json()
  route_name = str(payload.get("route", "")).strip()
  camera_key = str(payload.get("camera", "")).strip()
  try:
    segment_num = int(payload.get("segment", -1))
  except ValueError as exc:
    raise web.HTTPBadRequest(text="Invalid segment number") from exc
  protected = bool(payload.get("protected", True))

  video_path, meta_key = _resolve_video_entry(route_name, segment_num, camera_key)
  if video_path is None or meta_key is None:
    raise web.HTTPNotFound(text="Video not found")

  meta = _load_video_library_meta()
  _set_video_protection(meta, route_name, segment_num, camera_key, protected)
  _save_video_library_meta(meta)
  return web.json_response({
    "ok": True,
    "route": route_name,
    "segment": segment_num,
    "camera": camera_key,
    "protected": protected,
  })


async def api_videos_delete(request: 'web.Request'):
  _verify_access(request)
  payload = await request.json()
  route_name = str(payload.get("route", "")).strip()
  camera_key = str(payload.get("camera", "")).strip()
  force = bool(payload.get("force", False))
  try:
    segment_num = int(payload.get("segment", -1))
  except ValueError as exc:
    raise web.HTTPBadRequest(text="Invalid segment number") from exc

  video_path, meta_key = _resolve_video_entry(route_name, segment_num, camera_key)
  if video_path is None or meta_key is None:
    raise web.HTTPNotFound(text="Video not found")

  meta = _load_video_library_meta()
  is_protected = _is_video_protected(meta, route_name, segment_num, camera_key)
  if is_protected and not force:
    return web.json_response({
      "ok": False,
      "protected": True,
      "warning": "This video is protected. Confirm again to delete it.",
    }, status=409)

  try:
    os.remove(video_path)
  except FileNotFoundError as exc:
    raise web.HTTPNotFound(text="Video not found") from exc
  except OSError as exc:
    raise web.HTTPInternalServerError(text=f"Failed to delete video: {exc}") from exc

  meta.pop(meta_key, None)
  _save_video_library_meta(meta)
  return web.json_response({
    "ok": True,
    "deleted": True,
    "protected": is_protected,
    "route": route_name,
    "segment": segment_num,
    "camera": camera_key,
  })


async def api_capture_start(request: 'web.Request'):
  _verify_access(request)
  proc = request.app.get("capture_proc")
  if proc is not None and proc.poll() is None:
    return web.json_response({"ok": False, "error": "Capture already running", "capture": _capture_status(request.app)}, status=409)

  payload = await request.json()
  label = str(payload.get("label", "capture")).strip() or "capture"
  seconds = max(10, min(600, int(payload.get("seconds", 180))))
  safe_label = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in label)
  stamp = time.strftime("%Y%m%d-%H%M%S")
  os.makedirs(CAPTURE_DIR, exist_ok=True)
  out_file = os.path.join(CAPTURE_DIR, f"{stamp}_{safe_label}.jsonl")
  log_file = os.path.join(CAPTURE_DIR, f"{stamp}_{safe_label}.out")

  cmd = [
    sys.executable,
    "-m",
    "tools.bodyteleop.capture_can_window",
    "--seconds",
    str(seconds),
    "--label",
    safe_label,
    "--out-file",
    out_file,
  ]
  log_handle = open(log_file, "w", encoding="utf-8")
  proc = subprocess.Popen(cmd, cwd=BASEDIR, stdout=log_handle, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
  request.app["capture_proc"] = proc
  request.app["capture_log_handle"] = log_handle
  request.app["capture_meta"] = {
    "label": safe_label,
    "seconds": seconds,
    "startedAt": int(time.time()),
    "outFile": out_file,
    "logFile": log_file,
  }
  return web.json_response({"ok": True, "capture": _capture_status(request.app)})


async def api_capture_stop(request: 'web.Request'):
  _verify_access(request)
  proc = request.app.get("capture_proc")
  if proc is None or proc.poll() is not None:
    return web.json_response({"ok": True, "capture": _capture_status(request.app)})

  proc.terminate()
  try:
    proc.wait(timeout=5)
  except subprocess.TimeoutExpired:
    proc.kill()
    proc.wait(timeout=5)
  log_handle = request.app.get("capture_log_handle")
  if log_handle is not None:
    log_handle.close()
    request.app["capture_log_handle"] = None
  return web.json_response({"ok": True, "capture": _capture_status(request.app)})


async def offer(request: 'web.Request'):
  _verify_access(request)
  params = await request.json()
  body = StreamRequestBody(params["sdp"], ["driver"], ["testJoystick"], ["carState"])
  body_json = json.dumps(dataclasses.asdict(body))

  logger.info("Sending offer to webrtcd...")
  webrtcd_url = f"http://{WEBRTCD_HOST}:{WEBRTCD_PORT}/stream"
  async with ClientSession() as session, session.post(webrtcd_url, data=body_json) as resp:
    assert resp.status == 200
    answer = await resp.json()
    return web.json_response(answer)


def main(enable_joystick: bool | None = None):
  if enable_joystick is None:
    enable_joystick = os.getenv("BODYTELEOP_ENABLE_JOYSTICK", "1") == "1"

  # Enable joystick debug mode only for the original body teleop process.
  if enable_joystick and Params is not None:
    Params().put_bool("JoystickDebugMode", True)

  # App needs to be HTTPS for microphone and audio autoplay to work on the browser
  ssl_context = create_ssl_context()

  app = web.Application()
  app["params"] = Params() if Params is not None else None
  app["status_sm"] = messaging.SubMaster(["carState"]) if messaging is not None else None
  app["capture_proc"] = None
  app["capture_log_handle"] = None
  app["capture_meta"] = {}
  logger.info("LAN control auth disabled for local network use")
  app.router.add_get("/", index)
  app.router.add_get("/ping", ping, allow_head=True)
  app.router.add_post("/offer", offer)
  app.router.add_post("/sound", sound)
  app.router.add_get("/api/auth/status", api_auth_status)
  app.router.add_post("/api/auth/setup", api_auth_setup)
  app.router.add_post("/api/auth/login", api_auth_login)
  app.router.add_post("/api/auth/logout", api_auth_logout)
  app.router.add_get("/api/config", api_config)
  app.router.add_get("/api/status", api_status)
  app.router.add_post("/api/command/{name}", api_command)
  app.router.add_get("/api/capture/status", api_capture_status)
  app.router.add_post("/api/capture/start", api_capture_start)
  app.router.add_post("/api/capture/stop", api_capture_stop)
  app.router.add_get("/api/videos", api_videos_list)
  app.router.add_get("/api/videos/stream", api_videos_stream)
  app.router.add_post("/api/videos/protect", api_videos_protect)
  app.router.add_post("/api/videos/delete", api_videos_delete)
  app.router.add_static('/static', os.path.join(TELEOPDIR, 'static'))
  web.run_app(app, access_log=None, host="0.0.0.0", port=5000, ssl_context=ssl_context)


if __name__ == "__main__":
  main()
