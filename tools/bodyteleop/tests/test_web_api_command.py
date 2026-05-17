from __future__ import annotations

from pathlib import Path
import importlib
import json
import os
import sys
import types
import unittest
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

sys.modules.setdefault("openpilot.common", importlib.import_module("common"))
sys.modules.setdefault("openpilot.tools", importlib.import_module("tools"))

fake_aiohttp_web_module = types.ModuleType("aiohttp.web")


class FakeHttpError(Exception):
  def __init__(self, *args, **kwargs):
    text = kwargs.pop("text", "")
    super().__init__(text or (args[0] if args else ""))
    self.text = text


class HTTPBadRequest(FakeHttpError):
  pass


class HTTPForbidden(FakeHttpError):
  pass


class FakeResponse:
  def __init__(self, *, content_type: str | None = None, text: str = "", status: int = 200):
    self.content_type = content_type
    self.text = text
    self.status = status


def json_response(data: dict, status: int = 200):
  return FakeResponse(content_type="application/json", text=json.dumps(data), status=status)


fake_aiohttp_web_module.HTTPBadRequest = HTTPBadRequest
fake_aiohttp_web_module.HTTPForbidden = HTTPForbidden
fake_aiohttp_web_module.Response = FakeResponse
fake_aiohttp_web_module.json_response = json_response

fake_aiohttp_module = types.ModuleType("aiohttp")
fake_aiohttp_module.web = fake_aiohttp_web_module
fake_aiohttp_module.ClientSession = object

fake_aiohttp_client_exceptions = types.ModuleType("aiohttp.client_exceptions")


class ClientConnectorError(Exception):
  pass


fake_aiohttp_client_exceptions.ClientConnectorError = ClientConnectorError

sys.modules["aiohttp"] = fake_aiohttp_module
sys.modules["aiohttp.client_exceptions"] = fake_aiohttp_client_exceptions

fake_params_module = types.ModuleType("openpilot.common.params")
fake_params_module.Params = object
sys.modules["openpilot.common.params"] = fake_params_module

fake_remote_start_status_module = types.ModuleType("tools.bodyteleop.remote_start_status")
fake_remote_start_status_module.read_remote_start_config = lambda params: {}
fake_remote_start_status_module.read_remote_start_status = lambda params: {}
sys.modules["tools.bodyteleop.remote_start_status"] = fake_remote_start_status_module
sys.modules["openpilot.tools.bodyteleop.remote_start_status"] = fake_remote_start_status_module


real_command_service = importlib.import_module("tools.bodyteleop.command_service")
sys.modules["openpilot.tools.bodyteleop.command_service"] = real_command_service

sys.modules.pop("tools.bodyteleop.web", None)
from tools.bodyteleop import web


class FakeRequest:
  def __init__(self, *, command: str = "remote_start", remote: str = "192.168.1.10", payload=None, json_error: Exception | None = None, params=None, app=None):
    self.match_info = {"name": command}
    self.remote = remote
    self.app = {"params": object() if params is None else params} if app is None else app
    self._payload = {} if payload is None else payload
    self._json_error = json_error

  async def json(self):
    if self._json_error is not None:
      raise self._json_error
    return self._payload


class FakeResult:
  def __init__(self, body: dict):
    self._body = body
    self.command = body.get("requested", "")
    self.state = body.get("state", "")
    self.reason = body.get("reason", "")
    self.requested_at = body.get("requested_at", 0)
    self.details = body.get("details", {})

  def to_response(self) -> dict:
    return {k: v for k, v in self._body.items() if k != "requested_at"}


class TestApiCommand(unittest.IsolatedAsyncioTestCase):
  def test_create_status_sm_skips_messaging_when_disabled(self):
    with patch.dict(os.environ, {"BODYTELEOP_DISABLE_MESSAGING": "1"}):
      self.assertIsNone(web._create_status_sm())

  async def test_api_command_returns_execute_result_response(self):
    request = FakeRequest(payload={"ac": {"enabled": True}}, app={"params": object(), "command_statuses": {}})

    with patch.object(web, "execute_command", return_value=FakeResult({
      "ok": True,
      "requested": "remote_start",
      "state": "requested",
      "reason": "waiting for vehicle-side worker",
      "details": {},
    })) as execute_command:
      response = await web.api_command(request)

    self.assertEqual(response.status, 200)
    self.assertEqual(json.loads(response.text), {
      "ok": True,
      "requested": "remote_start",
      "state": "requested",
      "reason": "waiting for vehicle-side worker",
      "details": {},
    })
    self.assertEqual(request.app["command_statuses"]["remote_start"], {
      "state": "requested",
      "reason": "waiting for vehicle-side worker",
      "updatedAt": 0,
      "details": {},
    })
    execute_command.assert_called_once_with("remote_start", {"ac": {"enabled": True}}, request.app["params"])

  async def test_api_command_uses_empty_payload_when_json_fails(self):
    request = FakeRequest(json_error=ValueError("bad json"), app={"params": object(), "command_statuses": {}})

    with patch.object(web, "execute_command", return_value=FakeResult({
      "ok": True,
      "requested": "remote_start",
      "state": "requested",
      "reason": "request accepted",
      "details": {},
      "requested_at": 0,
    })) as execute_command:
      response = await web.api_command(request)

    self.assertEqual(response.status, 200)
    execute_command.assert_called_once_with("remote_start", {}, request.app["params"])

  async def test_api_command_maps_params_unavailable_to_503(self):
    request = FakeRequest()

    with patch.object(web, "execute_command", side_effect=web.CommandError("Params backend unavailable on this host")):
      response = await web.api_command(request)

    self.assertEqual(response.status, 503)
    self.assertEqual(json.loads(response.text), {
      "ok": False,
      "error": "Params backend unavailable on this host",
    })

  async def test_api_command_maps_invalid_payload_to_400(self):
    request = FakeRequest()

    with patch.object(web, "execute_command", side_effect=web.CommandError("Invalid remote_start payload")):
      response = await web.api_command(request)

    self.assertEqual(response.status, 400)
    self.assertEqual(json.loads(response.text), {
      "ok": False,
      "error": "Invalid remote_start payload",
    })

  async def test_api_command_maps_unknown_command_to_http_bad_request(self):
    request = FakeRequest(command="mystery")

    with patch.object(web, "execute_command", side_effect=web.CommandError("Unknown command")):
      with self.assertRaises(HTTPBadRequest):
        await web.api_command(request)

  async def test_api_command_rejects_public_network_request(self):
    request = FakeRequest(remote="8.8.8.8")

    with self.assertRaises(HTTPForbidden):
      await web.api_command(request)

  async def test_api_status_includes_uniform_command_statuses(self):
    app = {
      "params": object(),
      "status_sm": object(),
      "command_statuses": {
        "charge_start": {
          "state": "requested",
          "reason": "request flag updated",
          "updatedAt": 123,
          "details": {},
        },
      },
    }
    request = FakeRequest(app=app)

    with patch.object(web, "_read_vehicle_status", return_value={
      "batteryPercent": 80.0,
      "charging": False,
      "deviceVoltage": 12.3,
      "sentryEnabled": True,
      "remoteStartConfig": {},
      "remoteStartStatus": {
        "state": "requested",
        "reason": "waiting for vehicle-side worker",
        "updatedAt": 456,
        "config": {},
      },
    }):
      response = await web.api_status(request)

    payload = json.loads(response.text)
    self.assertEqual(response.status, 200)
    self.assertTrue(payload["ok"])
    self.assertEqual(payload["status"]["commandStatuses"]["charge_start"]["state"], "requested")
    self.assertEqual(payload["status"]["commandStatuses"]["remote_start"]["updatedAt"], 456)
    self.assertEqual(payload["status"]["commandStatuses"]["sentry_toggle"], {
      "state": "completed",
      "reason": "sentry state updated",
      "updatedAt": 0,
      "details": {"enabled": True},
    })
