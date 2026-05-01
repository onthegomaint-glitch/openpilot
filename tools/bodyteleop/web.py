from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import ipaddress
import json
import logging
import os
import secrets
import ssl
import subprocess
import sys
import time

import pyaudio
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
SESSION_COOKIE = "lan_session"
SESSION_TTL_SECONDS = 60 * 60 * 24
CAPTURE_DIR = "/data/bluelink_captures"


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


def _expected_token() -> str:
  if Params is not None:
    raw = Params().get("DongleId") or "sunnypilot-local"
  else:
    raw = "sunnypilot-local"
  return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _is_authorized(request: 'web.Request') -> bool:
  token = request.headers.get("X-Local-Token") or request.query.get("token")
  return token == _expected_token()


def _verify_local_auth(request: 'web.Request'):
  if not _is_private_request(request):
    raise web.HTTPForbidden(text="Local network access only")
  if not _is_authorized(request):
    raise web.HTTPUnauthorized(text="Invalid token")


def _read_auth_config(params: Params | None) -> dict:
  if params is None:
    return {}
  cfg = params.get("LanAuthConfig", return_default=True)
  return cfg if isinstance(cfg, dict) else {}


def _hash_password(password: str, salt: str) -> str:
  return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 200_000).hex()


def _verify_session(request: 'web.Request') -> bool:
  session_token = request.cookies.get(SESSION_COOKIE)
  if not session_token:
    return False

  sessions = request.app["sessions"]
  session = sessions.get(session_token)
  if session is None:
    return False

  now = int(time.time())
  if now > session["expiresAt"]:
    del sessions[session_token]
    return False
  return True


def _verify_access(request: 'web.Request'):
  if not _is_private_request(request):
    raise web.HTTPForbidden(text="Local network access only")
  if _verify_session(request) or _is_authorized(request):
    return
  raise web.HTTPUnauthorized(text="Login required")


## UTILS
async def play_sound(sound: str):
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
    cfg = cap.get("LanRemoteStartConfig", return_default=True)
    if isinstance(cfg, dict):
      remote_start_config = cfg
    status = cap.get("LanRemoteStartStatus", return_default=True)
    if isinstance(status, dict):
      remote_start_status = status

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
  params = request.app["params"]
  auth_cfg = _read_auth_config(params)
  return web.json_response({
    "ok": True,
    "setupRequired": "username" not in auth_cfg,
    "authenticated": _verify_session(request),
  })


async def api_auth_setup(request: 'web.Request'):
  if not _is_private_request(request):
    raise web.HTTPForbidden(text="Local network access only")
  params = request.app["params"]
  if params is None:
    return web.json_response({"ok": False, "error": "Params backend unavailable on this host"}, status=503)

  auth_cfg = _read_auth_config(params)
  if "username" in auth_cfg:
    return web.json_response({"ok": False, "error": "Auth already configured"}, status=409)

  payload = await request.json()
  username = str(payload.get("username", "")).strip()
  password = str(payload.get("password", ""))
  if len(username) < 3 or len(password) < 8:
    return web.json_response({"ok": False, "error": "Username/password too short"}, status=400)

  salt = secrets.token_hex(16)
  params.put("LanAuthConfig", {
    "username": username,
    "salt": salt,
    "passwordHash": _hash_password(password, salt),
  })
  return web.json_response({"ok": True})


async def api_auth_login(request: 'web.Request'):
  if not _is_private_request(request):
    raise web.HTTPForbidden(text="Local network access only")
  params = request.app["params"]
  auth_cfg = _read_auth_config(params)
  if "username" not in auth_cfg:
    return web.json_response({"ok": False, "error": "Run setup first"}, status=400)

  payload = await request.json()
  username = str(payload.get("username", "")).strip()
  password = str(payload.get("password", ""))

  if username != auth_cfg["username"]:
    return web.json_response({"ok": False, "error": "Invalid credentials"}, status=401)
  if _hash_password(password, auth_cfg["salt"]) != auth_cfg["passwordHash"]:
    return web.json_response({"ok": False, "error": "Invalid credentials"}, status=401)

  token = secrets.token_urlsafe(32)
  request.app["sessions"][token] = {"username": username, "expiresAt": int(time.time()) + SESSION_TTL_SECONDS}
  response = web.json_response({"ok": True})
  response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="Strict", max_age=SESSION_TTL_SECONDS, secure=False)
  return response


async def api_auth_logout(request: 'web.Request'):
  token = request.cookies.get(SESSION_COOKIE)
  if token:
    request.app["sessions"].pop(token, None)
  response = web.json_response({"ok": True})
  response.del_cookie(SESSION_COOKIE)
  return response


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
      params.put("LanRemoteStartConfig", safe_cfg)
      params.put("LanRemoteStartStatus", {
        "state": "requested",
        "reason": "waiting for vehicle-side worker",
        "updatedAt": int(time.time()),
        "config": safe_cfg,
      })

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


async def api_capture_status(request: 'web.Request'):
  _verify_access(request)
  return web.json_response({"ok": True, "capture": _capture_status(request.app)})


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
  app["sessions"] = {}
  app["capture_proc"] = None
  app["capture_log_handle"] = None
  app["capture_meta"] = {}
  logger.info("Local control token: %s", _expected_token())
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
  app.router.add_static('/static', os.path.join(TELEOPDIR, 'static'))
  web.run_app(app, access_log=None, host="0.0.0.0", port=5000, ssl_context=ssl_context)


if __name__ == "__main__":
  main()
