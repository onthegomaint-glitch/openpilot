from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cereal import car


@dataclass(frozen=True)
class RemoteStartRequest:
  enabled: bool
  temperature_c: float
  fan_level: int
  front_defrost: bool

  def as_dict(self) -> dict[str, Any]:
    return {
      "enabled": self.enabled,
      "temperatureC": self.temperature_c,
      "fanLevel": self.fan_level,
      "frontDefrost": self.front_defrost,
    }


@dataclass(frozen=True)
class RemoteStartResult:
  state: str
  reason: str
  details: dict[str, Any] | None = None


class RemoteStartAdapter:
  name = "unsupported"

  def __init__(self, CP: car.CarParams):
    self.CP = CP

  @property
  def supported(self) -> bool:
    return False

  def execute(self, request: RemoteStartRequest) -> RemoteStartResult:
    return RemoteStartResult(
      "unsupported",
      "vehicle actuation backend not implemented for this platform yet",
      {"adapter": self.name},
    )


class HyundaiKonaEVAdapter(RemoteStartAdapter):
  name = "hyundai_kona_ev"

  def execute(self, request: RemoteStartRequest) -> RemoteStartResult:
    return RemoteStartResult(
      "blocked",
      "Hyundai Kona EV remote-start CAN frames are outside the current panda Hyundai safety allowlist",
      {
        "allowedSafetyFrames": ["LKAS11/0x340", "CLU11/0x4f1", "LFAHDA_MFC/0x485"],
        "candidateRemoteFrames": ["TMU_GW_E_01/0x53a", "FATC11/0x383"],
        "nextStep": "capture stock Bluelink/telematics remote-start traffic or add a reviewed safety mode before sending actuator frames",
      },
    )


def adapter_for_car(CP: car.CarParams) -> RemoteStartAdapter:
  if str(CP.carFingerprint) in ("HYUNDAI_KONA_EV", "HYUNDAI_KONA_EV_2022"):
    return HyundaiKonaEVAdapter(CP)
  return RemoteStartAdapter(CP)
