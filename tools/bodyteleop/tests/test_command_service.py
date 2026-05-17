from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import importlib
import types

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

sys.modules.setdefault("openpilot.common", importlib.import_module("common"))
sys.modules.setdefault("openpilot.tools", importlib.import_module("tools"))

fake_params_module = types.ModuleType("openpilot.common.params")
fake_params_module.Params = object
sys.modules.setdefault("openpilot.common.params", fake_params_module)

fake_remote_start_status_module = types.ModuleType("tools.bodyteleop.remote_start_status")
fake_remote_start_status_module.trigger_remote_start_request = lambda params: None
fake_remote_start_status_module.write_remote_start_config = lambda params, config: None
fake_remote_start_status_module.write_remote_start_status = lambda params, status: None
sys.modules.setdefault("tools.bodyteleop.remote_start_status", fake_remote_start_status_module)
sys.modules.setdefault("openpilot.tools.bodyteleop.remote_start_status", fake_remote_start_status_module)

from tools.bodyteleop.command_service import (
  CommandError,
  execute_command,
  normalize_remote_start_payload,
)


class FakeParams:
  def __init__(self):
    self.bools: dict[str, bool] = {}

  def get_bool(self, key: str) -> bool:
    return bool(self.bools.get(key, False))

  def put_bool(self, key: str, value: bool) -> None:
    self.bools[key] = bool(value)


class TestCommandService(unittest.TestCase):
  def test_unknown_command_rejected(self):
    with self.assertRaisesRegex(CommandError, "Unknown command"):
      execute_command("definitely_not_real", {}, FakeParams(), now=123)

  def test_remote_start_payload_normalization(self):
    cfg = normalize_remote_start_payload({
      "ac": {
        "enabled": False,
        "temperatureC": 19,
        "fanLevel": 4,
        "frontDefrost": True,
      },
    })

    self.assertIs(cfg.enabled, False)
    self.assertEqual(cfg.temperature_c, 19.0)
    self.assertEqual(cfg.fan_level, 4)
    self.assertIs(cfg.front_defrost, True)

  @patch("tools.bodyteleop.command_service.trigger_remote_start_request")
  @patch("tools.bodyteleop.command_service.write_remote_start_status")
  @patch("tools.bodyteleop.command_service.write_remote_start_config")
  def test_remote_start_writes_config_status_and_triggers_request(self, write_config, write_status, trigger_request):
    params = FakeParams()

    result = execute_command("remote_start", {
      "ac": {
        "enabled": True,
        "temperatureC": 22,
        "fanLevel": 3,
        "frontDefrost": False,
      },
    }, params, now=456)

    self.assertIs(result.ok, True)
    self.assertEqual(result.command, "remote_start")
    self.assertEqual(result.state, "requested")
    self.assertEqual(result.reason, "waiting for vehicle-side worker")
    self.assertEqual(result.details["config"], {
      "enabled": True,
      "temperatureC": 22.0,
      "fanLevel": 3,
      "frontDefrost": False,
    })

    write_config.assert_called_once_with(params, result.details["config"])
    write_status.assert_called_once_with(params, {
      "state": "requested",
      "reason": "waiting for vehicle-side worker",
      "updatedAt": 456,
      "config": result.details["config"],
    })
    trigger_request.assert_called_once_with(params)

  def test_charge_start_toggles_request_flag(self):
    self._assert_charge_command("charge_start", "LanChargeStartRequested")

  def test_charge_stop_toggles_request_flag(self):
    self._assert_charge_command("charge_stop", "LanChargeStopRequested")

  def test_sentry_toggle_flips_state(self):
    params = FakeParams()
    params.put_bool("LanSentryModeEnabled", False)

    result = execute_command("sentry_toggle", {}, params, now=321)

    self.assertIs(result.ok, True)
    self.assertEqual(result.command, "sentry_toggle")
    self.assertEqual(result.state, "completed")
    self.assertEqual(result.reason, "sentry state updated")
    self.assertEqual(result.details, {"enabled": True})
    self.assertIs(params.get_bool("LanSentryModeEnabled"), True)

  def _assert_charge_command(self, command: str, param_name: str):
    params = FakeParams()

    result = execute_command(command, {}, params, now=789)

    self.assertIs(result.ok, True)
    self.assertEqual(result.command, command)
    self.assertEqual(result.state, "requested")
    self.assertEqual(result.reason, "request flag updated")
    self.assertIs(params.get_bool(param_name), True)
