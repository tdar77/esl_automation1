# ESL AP monitor — first implementation

Desktop monitor for the AP serial shell. Requires Python 3.10+ and PySide6.
From this directory:

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python main.py --demo
# Live hardware:
.venv/Scripts/python main.py
```

Build and flash `ap_cli` with `CONFIG_ESL_AP_LOG=y` (already enabled in
`prj.conf` and `prj_debug.conf`). Select the AP COM port and its configured baud
rate, then Connect. The default shown is 115200; verify against your board.
Close other serial terminals first. The monitor expects the default Zephyr
`uart:~$`-style prompt; custom prompts require changing prompt recognition.
Connect does not initialize or reset the AP automatically. Initialize AP or
Auto sync when appropriate, then select a logged tag to ping it.

## What the data means

- Ping requests count successful returns from the AP ping API, including
  buffered commands in multiple-command mode. They are not acknowledgments.
- Requested image is the last accepted display-image index, not OTS upload
  completion or proof that the display changed.
- GATT responses count decoded response records (including ESL errors) from
  the connected-response callback. They are not matched ping responses.
- PAwR per-tag responses, RSSI, latency, loss, and delivery rate are **not yet
  measured**. A synchronized tag may respond via PAwR and have zero GATT responses.
- Rows are activity-log entries, not an inventory. Removed addresses remain
  in this first implementation until AP log initialization/reboot. Capacity
  and dropped-update count make exhaustion visible.
- Times in the table are ages at snapshot time. Snapshot age/staleness is
  shown separately. CLI addresses display/send in hexadecimal; JSON/CSV use
  numeric decimal IDs.

## Protocol

`esl_ap log` retains the text output. `esl_ap log json` emits one `@ESL `-prefixed
JSON object per line: `begin`, zero or more `tag` records, then `end`. All records
have `v:1` and a matching snapshot `id`. Begin contains `session`, `uptime_ms`,
`count`, `capacity`, and `dropped`. Tag contains `group`, `tag`, `ping_requests`,
`ping_age_ms`, `image`, `gatt_responses`, and `gatt_response_age_ms`. Unknown
ages/images use JSON null. Session is a non-security random identifier assigned
on log initialization; a serial reconnect also starts a separate host capture.
Uptime/age fields use unsigned 32-bit milliseconds; uptime wraps after ~49.7 days.

The parser commits only complete, validated snapshots. Console noise and ANSI
formatting are ignored. A shell timeout suspends commands until reconnect.
Refresh never sends a ping. Controls allow one command in flight; operation
results remain in the raw console because shell completion does not prove
asynchronous Bluetooth completion. No automatic legacy text parsing is provided;
update the AP firmware to use live monitoring.

## Capture and validation

Record session saves raw serial chunks and validated snapshots as JSON Lines.
Replay loads recorded snapshots while disconnected; it is a historical view,
not timed playback. The chart retains 300 samples; CSV exports up to the latest
10,000 snapshots' tag rows. Continuous recording preserves the full session.

```powershell
python -m unittest discover -s . -p 'test_*.py'
```

Hardware checklist: empty log; accepted ping; GATT response; PAwR-only tag;
unplug/reconnect; AP reboot; log capacity exhaustion; console activity during
polling. Verify text `log` still works. The default AP configuration supports
two tags; explicitly use `auto 2` (the GUI default), since the existing firmware
automation default is three. Larger networks require matching firmware limits.

Next work: complete device inventory and removal lifecycle, PAwR slot-to-request
attribution, RSSI, matched-response deadlines/latency, then active probe scheduling.
