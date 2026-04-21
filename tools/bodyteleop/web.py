import asyncio
import dataclasses
import hashlib
import ipaddress
import json
import logging
import os
import ssl
import subprocess

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


def _expected_token() -> str:
  if Params is not None:
    raw = Params().get("DongleId", encoding="utf-8") or "sunnypilot-local"
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
  sm.update(0)
  car_state = sm["carState"]
  fuel_gauge = float(getattr(car_state, "fuelGauge", 0.0))
  return {
    "batteryPercent": round(fuel_gauge * 100, 1),
    "charging": bool(getattr(car_state, "charging", False)),
    "ignitionOn": bool(getattr(car_state, "ignitionLine", False) or getattr(car_state, "ignitionCan", False)),
    "standstill": bool(getattr(car_state, "standstill", False)),
    "gear": str(getattr(car_state, "gearShifter", "unknown")),
    "updated": bool(sm.updated.get("carState", False)),
    "valid": bool(sm.valid.get("carState", False)),
    "logMonoTime": int(sm.logMonoTime.get("carState", 0)),
  }


async def api_config(request: 'web.Request'):
  _verify_local_auth(request)
  return web.json_response({
    "ok": True,
    "tokenHint": "Use X-Local-Token header with the generated token from logs",
  })


async def api_status(request: 'web.Request'):
  _verify_local_auth(request)
  sm = request.app["status_sm"]
  if sm is None:
    return web.json_response({"ok": True, "status": {"batteryPercent": 0.0, "charging": False, "updated": False, "valid": False, "statusAvailable": False}})
  status = _read_vehicle_status(sm)
  status["statusAvailable"] = True
  return web.json_response({"ok": True, "status": status})


async def api_command(request: 'web.Request'):
  _verify_local_auth(request)
  command = request.match_info["name"]
  if command not in COMMAND_PARAMS:
    raise web.HTTPBadRequest(text="Unknown command")

  params = request.app["params"]
  if params is None:
    return web.json_response({"ok": False, "error": "Params backend unavailable on this host"}, status=503)
  command_param = COMMAND_PARAMS[command]
  params.put_bool(command_param, False)
  params.put_bool(command_param, True)

  return web.json_response({"ok": True, "requested": command})


async def offer(request: 'web.Request'):
  params = await request.json()
  body = StreamRequestBody(params["sdp"], ["driver"], ["testJoystick"], ["carState"])
  body_json = json.dumps(dataclasses.asdict(body))

  logger.info("Sending offer to webrtcd...")
  webrtcd_url = f"http://{WEBRTCD_HOST}:{WEBRTCD_PORT}/stream"
  async with ClientSession() as session, session.post(webrtcd_url, data=body_json) as resp:
    assert resp.status == 200
    answer = await resp.json()
    return web.json_response(answer)


def main():
  # Enable joystick debug mode
  if Params is not None:
    Params().put_bool("JoystickDebugMode", True)

  # App needs to be HTTPS for microphone and audio autoplay to work on the browser
  ssl_context = create_ssl_context()

  app = web.Application()
  app["params"] = Params() if Params is not None else None
  app["status_sm"] = messaging.SubMaster(["carState"]) if messaging is not None else None
  logger.info("Local control token: %s", _expected_token())
  app.router.add_get("/", index)
  app.router.add_get("/ping", ping, allow_head=True)
  app.router.add_post("/offer", offer)
  app.router.add_post("/sound", sound)
  app.router.add_get("/api/config", api_config)
  app.router.add_get("/api/status", api_status)
  app.router.add_post("/api/command/{name}", api_command)
  app.router.add_static('/static', os.path.join(TELEOPDIR, 'static'))
  web.run_app(app, access_log=None, host="0.0.0.0", port=5000, ssl_context=ssl_context)


if __name__ == "__main__":
  main()
