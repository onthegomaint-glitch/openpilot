#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import time

from cereal import messaging


def main() -> None:
  parser = argparse.ArgumentParser(description="Capture raw CAN messages from msgq for a timed Bluelink test window.")
  parser.add_argument("--seconds", type=float, default=180.0)
  parser.add_argument("--label", default="capture")
  parser.add_argument("--out-dir", default="/data/bluelink_captures")
  parser.add_argument("--out-file", default="")
  args = parser.parse_args()

  os.makedirs(args.out_dir, exist_ok=True)
  if args.out_file:
    out_path = args.out_file
  else:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    safe_label = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in args.label)
    out_path = os.path.join(args.out_dir, f"{stamp}_{safe_label}.jsonl")

  sock = messaging.sub_sock("can", timeout=1000)
  deadline = time.monotonic() + args.seconds
  count = 0

  print(f"capturing CAN for {args.seconds:.1f}s -> {out_path}", flush=True)
  with open(out_path, "w", encoding="utf-8") as f:
    while time.monotonic() < deadline:
      msg = messaging.recv_sock(sock, wait=True)
      if msg is None or not msg.valid or msg.which() != "can":
        continue
      recv_time = time.time()
      for can in msg.can:
        f.write(json.dumps({
          "time": recv_time,
          "src": int(can.src),
          "address": int(can.address),
          "busTime": int(can.busTime),
          "dat": bytes(can.dat).hex(),
        }, separators=(",", ":")) + "\n")
        count += 1

  print(f"done: {count} CAN frames -> {out_path}", flush=True)


if __name__ == "__main__":
  main()
