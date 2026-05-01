# Bluelink CAN Capture Checklist

Use this during the paid Bluelink window so each command is captured cleanly.

## Setup

1. Power the comma on and confirm SSH works:

   ```powershell
   ssh comma@192.168.86.227
   ```

2. Keep the car parked, doors closed, and avoid pressing vehicle buttons during a capture.

3. Run one Bluelink action per capture. Clean labels make later diffing much easier.

4. Captures save on the comma under:

   ```bash
   /data/bluelink_captures/
   ```

## Manual Capture Command

Run this on the comma, changing only the label:

```bash
cd /data/openpilot
VIRTUAL_ENV=/usr/local/venv PYTHONPATH=/data/openpilot PATH=/usr/comma/shims:/usr/local/venv/bin:/usr/local/.cargo/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin python3 -m tools.bodyteleop.capture_can_window --seconds 180 --label baseline
```

When it prints `capturing CAN...`, follow the test step below.

## Capture Sequence

| Label | What to do after capture starts |
|-------|---------------------------------|
| `baseline` | Wait 3 minutes. Do not use Bluelink or press car buttons. |
| `climate_on` | Wait 20 seconds, then press remote climate/start in Bluelink. |
| `climate_off` | Wait 20 seconds, then stop remote climate in Bluelink. |
| `temp_low` | Wait 20 seconds, then set the lowest temperature in Bluelink. |
| `temp_high` | Wait 20 seconds, then set the highest temperature in Bluelink. |
| `defrost_on` | Wait 20 seconds, then turn front defrost on in Bluelink. |
| `defrost_off` | Wait 20 seconds, then turn front defrost off in Bluelink. |
| `charge_start` | Wait 20 seconds, then press start charging in Bluelink. |
| `charge_stop` | Wait 20 seconds, then press stop charging in Bluelink. |
| `lock` | Wait 20 seconds, then lock from Bluelink. |
| `unlock` | Wait 20 seconds, then unlock from Bluelink. |

## Notes

- Wait the full 2-3 minutes after each Bluelink action. The vehicle can receive commands slowly.
- If a Bluelink command fails, keep the capture anyway and label the result in your notes.
- Do not mix multiple commands into one capture unless we are intentionally testing a sequence later.

## Copy Captures Back To The PC

From PowerShell on the PC:

```powershell
scp comma@192.168.86.227:/data/bluelink_captures/*.jsonl .
```
