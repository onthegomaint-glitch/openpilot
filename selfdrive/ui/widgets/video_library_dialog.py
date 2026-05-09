import os
import re
import subprocess
import threading
from dataclasses import dataclass

import numpy as np
import pyray as rl

from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import DialogResult, Widget
from openpilot.system.ui.widgets.button import gui_button, ButtonStyle
from openpilot.system.ui.widgets.keyboard import Keyboard
from openpilot.system.ui.widgets.list_view import button_item
from openpilot.system.ui.widgets.scroller import Scroller

VIDEO_LIBRARY_DIR = "/data/media/0/realdata"
VIDEO_ROUTE_RE = re.compile(r"^[A-Za-z0-9]{16}\|\d{4}-\d{2}-\d{2}--\d{2}-\d{2}-\d{2}$")
VIDEO_SEGMENT_RE = re.compile(r"^(?P<route>[A-Za-z0-9]{16}\|\d{4}-\d{2}-\d{2}--\d{2}-\d{2}-\d{2})--(?P<segment>\d+)$")
VIDEO_FILE_PREFERENCE = [
  ("qcamera.ts", "Q camera"),
  ("fcamera.hevc", "Road"),
  ("ecamera.hevc", "Wide"),
  ("dcamera.hevc", "Driver"),
]

FRAME_WIDTH = 1280
FRAME_HEIGHT = 720
FRAME_RATE = 12

BACKGROUND_COLOR = rl.Color(15, 15, 15, 255)
PANEL_COLOR = rl.Color(27, 27, 27, 255)
TEXT_DIM = rl.Color(180, 180, 180, 255)
SEARCH_COLOR = rl.Color(235, 235, 235, 255)


@dataclass
class VideoEntry:
  route_name: str
  segment_num: int
  camera_path: str
  camera_label: str
  modified_at: int

  @property
  def display_name(self) -> str:
    return f"{self.route_name}  seg {self.segment_num}  {self.camera_label}"

  @property
  def detail_text(self) -> str:
    return self.camera_path


class FfmpegVideoPlayer:
  def __init__(self):
    self._process: subprocess.Popen | None = None
    self._thread: threading.Thread | None = None
    self._lock = threading.Lock()
    self._frame: np.ndarray | None = None
    self._frame_ready = False
    self._active_path: str | None = None
    self._state_text = "Select a video to play"

  @property
  def state_text(self) -> str:
    with self._lock:
      return self._state_text

  def current_path(self) -> str | None:
    with self._lock:
      return self._active_path

  def play(self, path: str):
    if self.current_path() == path:
      return

    self.stop()
    frame_size = FRAME_WIDTH * FRAME_HEIGHT * 3
    cmd = [
      "ffmpeg",
      "-hide_banner",
      "-loglevel",
      "error",
      "-re",
      "-i",
      path,
      "-an",
      "-vf",
      f"fps={FRAME_RATE},scale={FRAME_WIDTH}:{FRAME_HEIGHT}:force_original_aspect_ratio=decrease,pad={FRAME_WIDTH}:{FRAME_HEIGHT}:(ow-iw)/2:(oh-ih)/2:black",
      "-pix_fmt",
      "rgb24",
      "-f",
      "rawvideo",
      "pipe:1",
    ]
    self._process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    with self._lock:
      self._active_path = path
      self._state_text = f"Playing {os.path.basename(path)}"
      self._frame = None
      self._frame_ready = False
    self._thread = threading.Thread(target=self._reader_thread, args=(frame_size,), daemon=True)
    self._thread.start()

  def stop(self):
    proc = self._process
    self._process = None
    if proc is not None:
      proc.terminate()
      try:
        proc.wait(timeout=1)
      except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=1)
    with self._lock:
      self._active_path = None
      self._frame = None
      self._frame_ready = False
      self._state_text = "Select a video to play"

  def _reader_thread(self, frame_size: int):
    proc = self._process
    if proc is None or proc.stdout is None:
      return

    try:
      while self._process is proc:
        buf = proc.stdout.read(frame_size)
        if len(buf) != frame_size:
          break
        frame = np.frombuffer(buf, dtype=np.uint8).reshape((FRAME_HEIGHT, FRAME_WIDTH, 3)).copy()
        with self._lock:
          if self._process is not proc:
            break
          self._frame = frame
          self._frame_ready = True
    finally:
      if self._process is proc:
        with self._lock:
          self._state_text = "Playback finished"
          self._active_path = None

  def pull_frame(self) -> np.ndarray | None:
    with self._lock:
      if not self._frame_ready or self._frame is None:
        return None
      self._frame_ready = False
      return self._frame


class VideoLibraryDialog(Widget):
  def __init__(self):
    super().__init__()
    self._keyboard = Keyboard(max_text_size=64)
    self._query = ""
    self._entries: list[VideoEntry] = []
    self._player = FfmpegVideoPlayer()
    self._texture = rl.load_texture_from_image(
      rl.Image(None, FRAME_WIDTH, FRAME_HEIGHT, 1, rl.PixelFormat.PIXELFORMAT_UNCOMPRESSED_R8G8B8)
    )
    self._font_bold = gui_app.font(FontWeight.BOLD)
    self._font_normal = gui_app.font(FontWeight.NORMAL)
    self._title_font_size = 72
    self._body_font_size = 44
    self._scroller = Scroller([], spacing=0, line_separator=True)
    self._refresh_entries()

  def close(self):
    self._player.stop()
    if self._texture and self._texture.id:
      rl.unload_texture(self._texture)

  def __del__(self):
    self.close()

  def _refresh_entries(self):
    self._entries = self._scan_entries(self._query)
    items = [
      button_item(
        entry.display_name,
        "PLAY",
        description=entry.detail_text,
        callback=lambda selected=entry: self._player.play(selected.camera_path),
      )
      for entry in self._entries
    ]
    self._scroller = Scroller(items, spacing=0, line_separator=True)

  def _scan_entries(self, query: str) -> list[VideoEntry]:
    entries: list[VideoEntry] = []
    if not os.path.isdir(VIDEO_LIBRARY_DIR):
      return entries

    query_lower = query.strip().lower()
    with os.scandir(VIDEO_LIBRARY_DIR) as route_entries:
      for route_entry in route_entries:
        if not route_entry.is_dir():
          continue

        if match := VIDEO_SEGMENT_RE.fullmatch(route_entry.name):
          entry = self._segment_entry(match.group("route"), int(match.group("segment")), route_entry.path)
          if entry is not None:
            entries.append(entry)
          continue

        if not VIDEO_ROUTE_RE.fullmatch(route_entry.name):
          continue

        try:
          with os.scandir(route_entry.path) as segment_entries:
            for segment_entry in segment_entries:
              if not segment_entry.is_dir() or not segment_entry.name.isdigit():
                continue
              entry = self._segment_entry(route_entry.name, int(segment_entry.name), segment_entry.path)
              if entry is not None:
                entries.append(entry)
        except OSError:
          continue

    if query_lower:
      entries = [entry for entry in entries if query_lower in entry.route_name.lower() or query_lower in entry.display_name.lower()]

    entries.sort(key=lambda entry: entry.modified_at, reverse=True)
    return entries[:120]

  def _segment_entry(self, route_name: str, segment_num: int, segment_dir: str) -> VideoEntry | None:
    for filename, label in VIDEO_FILE_PREFERENCE:
      full_path = os.path.join(segment_dir, filename)
      if os.path.isfile(full_path):
        try:
          modified_at = int(os.path.getmtime(full_path))
        except OSError:
          modified_at = 0
        return VideoEntry(route_name, segment_num, full_path, label, modified_at)
    return None

  def _handle_search(self):
    self._keyboard.reset()
    self._keyboard.clear()
    self._keyboard.set_title("Search Videos", "Enter route text")
    self._keyboard._input_box.text = self._query
    gui_app.set_modal_overlay(self._keyboard, callback=self._on_search_result)

  def _on_search_result(self, result: int):
    if result == DialogResult.CONFIRM:
      self._query = self._keyboard.text.strip()
      self._refresh_entries()

  def _render(self, rect: rl.Rectangle):
    rl.draw_rectangle_rec(rect, BACKGROUND_COLOR)

    margin = 40
    header_h = 140
    control_h = 110
    list_h = rect.height * 0.36

    panel_rect = rl.Rectangle(rect.x + margin, rect.y + margin, rect.width - margin * 2, rect.height - margin * 2)
    rl.draw_rectangle_rounded(panel_rect, 0.03, 30, PANEL_COLOR)

    title = "Video Library"
    title_pos = rl.Vector2(panel_rect.x + 40, panel_rect.y + 28)
    rl.draw_text_ex(self._font_bold, title, title_pos, self._title_font_size, 0, rl.WHITE)

    close_rect = rl.Rectangle(panel_rect.x + panel_rect.width - 260, panel_rect.y + 18, 220, 90)
    if gui_button(close_rect, "Close", button_style=ButtonStyle.NORMAL) == 1:
      self._player.stop()
      return DialogResult.CANCEL

    query_rect = rl.Rectangle(panel_rect.x + 40, panel_rect.y + header_h, panel_rect.width - 560, control_h)
    search_rect = rl.Rectangle(panel_rect.x + panel_rect.width - 500, panel_rect.y + header_h, 220, control_h)
    clear_rect = rl.Rectangle(panel_rect.x + panel_rect.width - 260, panel_rect.y + header_h, 220, control_h)

    rl.draw_rectangle_rounded(query_rect, 0.2, 20, rl.Color(38, 38, 38, 255))
    query_text = self._query if self._query else "All stored videos"
    query_size = measure_text_cached(self._font_normal, query_text, 48)
    rl.draw_text_ex(
      self._font_normal,
      query_text,
      rl.Vector2(query_rect.x + 30, query_rect.y + (query_rect.height - query_size.y) / 2),
      48,
      0,
      SEARCH_COLOR,
    )

    if gui_button(search_rect, "Search", button_style=ButtonStyle.PRIMARY) == 1:
      self._handle_search()
    if gui_button(clear_rect, "Clear", button_style=ButtonStyle.NORMAL, is_enabled=bool(self._query)) == 1:
      self._query = ""
      self._refresh_entries()

    video_rect = rl.Rectangle(panel_rect.x + 40, panel_rect.y + header_h + control_h + 25, panel_rect.width - 80, 470)
    rl.draw_rectangle_rounded(video_rect, 0.03, 20, rl.BLACK)

    frame = self._player.pull_frame()
    if frame is not None:
      rl.update_texture(self._texture, rl.ffi.cast("void *", frame.ctypes.data))

    if self._player.current_path():
      src_rect = rl.Rectangle(0, 0, float(FRAME_WIDTH), float(FRAME_HEIGHT))
      dst_rect = rl.Rectangle(video_rect.x, video_rect.y, video_rect.width, video_rect.height)
      rl.draw_texture_pro(self._texture, src_rect, dst_rect, rl.Vector2(0, 0), 0.0, rl.WHITE)
    else:
      placeholder = self._player.state_text
      placeholder_size = measure_text_cached(self._font_normal, placeholder, 52)
      rl.draw_text_ex(
        self._font_normal,
        placeholder,
        rl.Vector2(video_rect.x + (video_rect.width - placeholder_size.x) / 2, video_rect.y + (video_rect.height - placeholder_size.y) / 2),
        52,
        0,
        TEXT_DIM,
      )

    status_text = f"{len(self._entries)} matches"
    state_text = self._player.state_text
    rl.draw_text_ex(self._font_normal, status_text, rl.Vector2(video_rect.x, video_rect.y + video_rect.height + 16), self._body_font_size, 0, TEXT_DIM)
    rl.draw_text_ex(self._font_normal, state_text, rl.Vector2(video_rect.x + 280, video_rect.y + video_rect.height + 16), self._body_font_size, 0, rl.WHITE)

    list_rect = rl.Rectangle(panel_rect.x + 40, panel_rect.y + panel_rect.height - list_h - 30, panel_rect.width - 80, list_h)
    self._scroller.render(list_rect)
    return DialogResult.NO_ACTION
