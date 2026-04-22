import time

import pyray as rl

from openpilot.selfdrive.ui.onroad.freeze_frame import trigger_freeze_frame_async
from openpilot.selfdrive.ui.ui_state import UI_BORDER_SIZE
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget


class FreezeFrameButton(Widget):
  """Small on-road control to save a diagnostic text snapshot under /data/freeze_frames/."""

  def __init__(self, width: int = 200, height: int = 72) -> None:
    super().__init__()
    self._rect = rl.Rectangle(0, 0, float(width), float(height))
    self._font = gui_app.font(FontWeight.SEMI_BOLD)
    self._label = "FREEZE"
    self._flash_until: float = 0.0

  def handle_mouse_event(self) -> bool:
    if not rl.check_collision_point_rec(rl.get_mouse_position(), self._rect):
      return False
    if rl.is_mouse_button_released(rl.MouseButton.MOUSE_BUTTON_LEFT):
      trigger_freeze_frame_async()
      self._flash_until = time.monotonic() + 1.2
    return True

  def _render(self, rect: rl.Rectangle) -> None:
    mouse_over = rl.check_collision_point_rec(rl.get_mouse_position(), self._rect)
    bg = rl.Color(0, 0, 0, 200)
    if time.monotonic() < self._flash_until:
      bg = rl.Color(40, 120, 80, 230)
    elif mouse_over and rl.is_mouse_button_down(rl.MouseButton.MOUSE_BUTTON_LEFT):
      bg = rl.Color(30, 30, 30, 220)

    rl.draw_rectangle_rounded(self._rect, 0.15, 12, bg)
    rl.draw_rectangle_rounded_lines_ex(self._rect, 0.15, 12, 2, rl.Color(255, 255, 255, 90))

    sz = 40
    tw = measure_text_cached(self._font, self._label, sz).x
    rl.draw_text_ex(
      self._font,
      self._label,
      rl.Vector2(
        self._rect.x + (self._rect.width - tw) / 2,
        self._rect.y + (self._rect.height - sz) / 2,
      ),
      sz,
      0,
      rl.Color(255, 255, 255, 240),
    )


def freeze_button_rect_for_hud(view_rect: rl.Rectangle) -> rl.Rectangle:
  """Place bottom-left inside the on-road view (above the border)."""
  w, h = 200.0, 72.0
  b = float(UI_BORDER_SIZE)
  x = view_rect.x + b
  y = view_rect.y + view_rect.height - h - b
  return rl.Rectangle(x, y, w, h)
