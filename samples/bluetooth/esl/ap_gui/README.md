# ESL AP GUI

A PyQt6 desktop app for controlling the ESL Access Point (`ap_cli`) firmware
over its UART shell. Anything the GUI does could also be done by typing
`esl_ap ...` commands in a serial terminal. The GUI sends those same commands
and parses the AP's console output to show what is happening.

Current features:

| Tab | What it does | Shell command(s) |
|---|---|---|
| **Auto Sync** | Sync *N* more tags to the PAwR train, with live status and progress | `esl_ap auto <n> <group>`, `esl_ap auto_stop` |
| **Tags / Ping** | Table of synced tags; ping one or more tags and show the response | `esl_ap ping <grp> <esl>` |
| Console (always visible) | Full AP output, plus a free-form command line with Up/Down history | anything |

## Running it

The AP must run a build of `ap_cli` that has the shell enabled
(`prj.conf` or `prj_debug.conf`) and `CONFIG_ESL_AP_AUTOMATION=y`. The default
baud rate is 115200. You need Python 3.10 or newer.

Only one program can hold the serial port at a time, so close any other
terminal (PuTTY, Tera Term, minicom, VS Code serial monitor) before
connecting.

### Windows

```bat
cd path\to\zephyr\samples\bluetooth\esl\ap_gui
py -3 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

python esl_ap_gui.py                 & rem pick the port in the toolbar
python esl_ap_gui.py --port COM5     & rem or connect on startup
```

- **Choosing the port:** the LaunchPad's XDS110 debugger creates two COM
  ports. The shell is on the one named **XDS110 Class Application/User UART**.
  The Port dropdown shows each port's description, and you can also find it in
  Device Manager under *Ports (COM & LPT)*.
- **If the board is attached to WSL with `usbipd`, Windows can't see it.**
  Run `usbipd detach --busid <id>` in an administrator PowerShell, or unplug
  and replug the board, and the COM port comes back.
- **The repo lives inside WSL**, so it is reachable from Windows at
  `\\wsl.localhost\Ubuntu-22.04\home\<user>\...`. `cmd.exe` cannot `cd` into
  a UNC path. Use PowerShell (it can) or `pushd \\wsl.localhost\...`, which
  maps a temporary drive letter. You can also copy the `ap_gui` folder to a
  Windows drive.

#### Standalone .exe

`build_windows.bat` uses PyInstaller to package the app into
`dist\esl_ap_gui.exe`. That one file runs on any Windows PC with no Python
installed. Run the script from a Windows command prompt in this directory. It
creates its own `.venv-win` virtual environment the first time it runs.
Because PyInstaller can only build for the OS it runs on, the script must run
on Windows, not WSL. `build/`, `dist/` and the `.spec` file are git-ignored.

### Linux / WSL

```bash
cd zephyr/samples/bluetooth/esl/ap_gui
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python3 esl_ap_gui.py --port /dev/ttyACM0
```

Your user needs to be in the `dialout` group. Under WSL2, the board must be
attached with `usbipd attach --wsl --busid <id>`, and the window is displayed
through WSLg.

## Using it

### Auto Sync

1. Set **Tags to sync** and **Group**, then press **Start auto sync**. This
   sends `esl_ap auto <n> <group>`. Both arguments are decimal, unlike
   `ping`, which takes hex.
2. **Status** and **Current tag** follow the firmware's automation state
   machine. **Progress** follows the `[APPL_AUTO]: k/n tags synced` lines.
3. **Stop** sends `esl_ap auto_stop`. It is enabled whenever the GUI is
   connected, even if the GUI didn't see the run start (for example, it
   connected mid-run or the run was started from the console). If a tag is
   being synced, the firmware finishes that tag first and then stops.
   Otherwise it stops right away. Pressing Stop when nothing is running is
   harmless: it resets the firmware's automation to idle and re-enables
   **Start**.

Each run fills one group. It syncs *n* additional tags into that group,
using the group's next free ESL IDs. For example, `auto 3 2` assigns `2:0`
to `2:2`, and a later `auto 2 2` assigns `2:3` and `2:4`. Tags already synced
in any group keep their addresses. A group has 16 response slots, so
**Tags to sync** goes up to 16. If you start a run from the console, the GUI
reads the group from the firmware's `auto requested (... next [g:e])` line and
updates **Group** to match.

The line under the controls estimates the chosen group's free slots from the
tags the GUI has seen sync. Tags synced before the GUI connected aren't
counted, so treat the number as a hint. The firmware does the real check and
rejects the run in these cases:

- the group is beyond its configured group count (`Invalid group 5 (valid groups: 0-3)`)
- the count exceeds the group's free slots (`Cannot add 5 tags to group 1: only 3 of 16 response slots free`)

The reason appears in **Status**. When the firmware prints both a specific
`[APPL_AUTO]` error and the CLI's generic summary, the GUI keeps the specific
one.

**Sync time** shows the last tag's timing, plus the average, minimum and
maximum for the current run. The same numbers are stored per tag in the
**Scan time** and **Sync time** columns of the Tags tab. Two durations are
measured:

| Measurement | From | To |
|---|---|---|
| Scan time | `ESL AP automation started`, or `[APPL_AUTO]: k/n tags synced` for later tags | `[APPL_AUTO]: ESL tag [g:e] added, connecting` |
| Sync time | `... added, connecting` | `[APPL]: ESL tag [g : e] synchronized (status 0x0000)` |

Sync time covers connect, GATT/OTS discovery, configuration, and PAwR sync.
For the first tag in a session, it also includes the 1 s
`APPL_ESL_AP_AUTO_SYNC_DELAY` after periodic advertising starts, so expect
the first tag to be about 1 s slower. The times are taken when each console
line reaches the PC, so UART/USB delay adds a few milliseconds of error. That
is negligible against syncs that take seconds, so no firmware support is
needed. Scan time is blank if the GUI connected while the AP was already
scanning. Tags synced by hand (`esl_ap sync_esl` from the console) have no
timing, because the firmware prints no "added" line for them.

If the firmware reports a failure (connect, discovery, config or sync), the
run stops. Status then shows `Aborted: <firmware message>`. Start it again to
retry.

### Tags / Ping

- A tag is added to the table when the AP prints
  `[APPL]: ESL tag [g : e] synchronized (status 0x0000)`.
- The **Show** dropdown narrows the table to one group, or shows all groups.
  Each entry includes a tag count, e.g. `Group 1 (16 tags)`. New groups appear
  as their tags sync, and your selection stays in place while tags are added.
  Picking a group also fills that group into the **Ping address** Group box.
  The filter only changes what is displayed. Tags in other groups are still
  tracked and updated.
- To ping, double-click a row, or select one or more rows and press
  **Ping selected**.
- **Ping address** pings any group/ESL ID, whether or not it is in the table.
  Use it for tags that were synced before the GUI connected. The AP has no
  command that lists synced tags yet, so the GUI only knows the tags it saw
  sync. Pinging an address adds it to the table with *Synced at = unknown*.
- **Last ping** shows one of these results:
  - `waiting…`: the ping was sent and no response has arrived yet.
  - `OK`: the tag responded. **Latency** is the time from sending the command
    to receiving the response line. **State flags** lists the BASIC STATE bits
    that are ON.
  - `Error 0xNN`: the tag responded with an ESL error code.
  - `Send failed 0xNNNN`: the AP could not queue the ping.
  - `No response`: nothing arrived within 10 s (`PING_TIMEOUT_S` in
    `controller.py`).

When the AP reboots (the GUI sees the `*** Booting Zephyr` banner), the table
is cleared, because all synced state on the AP is lost.

## How it works

```
  serial port ──► SerialLink ──lines──► EslApController ──► Qt signals ──► panels
 (QSerialPort)    serial_link.py         controller.py       + TagTableModel
                                            │    ▲
                                  parse()   ▼    │ Event objects
                                         LineParser (parser.py, no Qt)

  panels ──► controller.start_auto()/ping()/send_command() ──► commands.py ──► SerialLink
```

| File | Responsibility |
|---|---|
| `esl_ap_gui.py` | Entry point and CLI arguments |
| `build_windows.bat` | Packages the app as a standalone Windows `.exe` with PyInstaller |
| `esl_gui/serial_link.py` | Lists ports (`COMn` on Windows, `/dev/...` elsewhere), opens the port, splits the byte stream into lines, strips VT100 codes, writes commands (`\r\n`-terminated) |
| `esl_gui/parser.py` | **Pure Python.** Maps one console line to a typed `Event` (`TagSynced`, `AutoProgress`, `TagResponse`, …) through an ordered list of regex `RULES` |
| `esl_gui/commands.py` | Builds every command string the GUI sends |
| `esl_gui/controller.py` | Holds application state. Turns events into model updates and signals, and matches ping responses to the pings that were sent |
| `esl_gui/tag_model.py` | `QAbstractTableModel` with one row per tag (`TagInfo`). Views can wrap it in a proxy model (the Tags tab uses `GroupFilterProxy`), so code that maps a table row to a tag must call `proxy.mapToSource()` first |
| `esl_gui/main_window.py` | Connection toolbar, feature tabs and console |
| `esl_gui/panels/` | One file per feature tab, plus the console |
| `tests/` | Unit tests for the parser/commands and the controller (replays console lines, no hardware needed) |

Design rules that keep it easy to extend:

- **Panels never touch the serial port or parse text.** They call controller
  methods and react to controller signals or to `controller.tags`.
- **Firmware log formats live only in `parser.py`.** Each rule names the
  printk it matches. If you change a log message in `src/appl/*.c`, update
  the matching regex and its test.
- **Command strings live only in `commands.py`.**
- Everything runs on the Qt main thread. QSerialPort is event-driven, so the
  GUI has no worker threads and needs no locking.

### Firmware details the GUI depends on

- **`esl_ap ping` parses group and ESL IDs as hex** (`strtol(..., 16)` in
  `cli_esl_ap.c`), but every log line prints them in decimal.
  `commands.ping()` converts the IDs to hex. Tag `0:10` is sent as
  `esl_ap ping 0 a`.
- In the synchronized state, a ping response is only reported as
  `[APPL]: Group ID: g, Response Slot: s, ...`, with no ESL ID. The
  controller matches it to the **oldest pending ping in that group** (FIFO).
  This works as long as each ping goes out in its own PAwR subevent, which is
  the default with `multiple_cmd` off. If you add multi-command support,
  matching must use the response slot index instead.
- The `BASIC STATE` / `ERROR` lines that follow a response are attributed to
  the tag of that response.
- printk output can appear on the same line as the `uart:~$` prompt, so
  parser rules use `re.search` and are not anchored to the start of the line.

## Adding a feature

Example: a "Display image" tab for `esl_ap display_image`.

1. **Command:** add a builder to `commands.py`, e.g.
   `def display_image(group, esl, display_idx, image_idx) -> str`. Check the
   argument parsing in the matching `cmd_*` function in `cli_esl_ap.c`
   (hex vs decimal).
2. **Output:** if the firmware prints something you need, add an `Event`
   dataclass and a rule in `parser.py`. Put more specific patterns before
   the catch-all rules, because the first match wins. Add a test in
   `tests/test_parser.py` using the exact firmware line.
3. **State:** add a controller method that sends the command, and a
   `@_handle.register` method for the new event. That method either updates
   `self.tags` (add a field to `TagInfo` and a column to
   `TagTableModel.COLUMNS` / `_cell()`) or emits a new signal.
4. **UI:** create `esl_gui/panels/display_image.py` with a `QWidget`
   subclass that has a `TITLE` attribute and an `__init__(self, controller)`.
   Append it to `PANELS` in `esl_gui/panels/__init__.py`, and it shows up as a
   new tab.
5. Enable or disable the panel's buttons on `controller.connection_changed`,
   as the existing panels do.

## Tests

```bash
python3 -m unittest -v      # from ap_gui/ (on Windows: python -m unittest -v)
```

`test_parser.py` needs only the standard library. `test_controller.py` needs
PyQt6 and runs headless (`QT_QPA_PLATFORM=offscreen`). If PyQt6 is not
installed, it is skipped. Neither test needs hardware: the controller tests
replace the serial link and feed recorded console lines into it.

## Known limitations / next steps

- The AP cannot report which tags are already synced (`esl_ap esl_dev_list`
  is a stub). A firmware command that prints this list would let the GUI fill
  the table on connect.
- The GUI keeps no state between runs, and the tag table only reflects what
  it saw while connected.
- Multi-command mode (`esl_ap multiple_cmd` / `push_cmds`) is not supported
  by the ping matching (see above).
