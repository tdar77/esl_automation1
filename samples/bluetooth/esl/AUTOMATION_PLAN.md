# ESL Demo Automation — Incremental Plan

**Status legend:** `[ ]` not started · `[~]` in progress · `[x]` validated by user on hardware

This file is the living tracker for automating this ESL sample. It lives here
(not just in a Claude plan-mode scratch file) so it survives context clears —
update it after every increment lands, and re-read it at the start of a new
session to know exactly where things stand.

## Context

The ESL sample currently requires a human at a UART shell for everything: the tag
only initializes/advertises when someone types `esl_tag init` / `esl_tag start`,
and the AP only progresses a tag through connect → discover → config → sync when
someone manually types the corresponding `esl_ap <cmd>` one step at a time. The
goal is to turn this into a demo that boots and configures itself: tags come up
and advertise with no human input, and the AP can be told "go sync N tags" and
walks its whole state machine automatically, disconnecting and looping to the
next tag until N are synced. Once that automation is proven, the tag's shell can
be removed entirely (it's dead weight once nothing needs to be typed), and as a
final step tags gain non-volatile logging of pings/PAwR messages/images so field
behavior can be inspected without a live shell session.

The user implements and hardware-validates each increment personally, one at a
time, clearing AI context between steps — this file is the only continuity
between those sessions.

## Parallel session strategy (single branch, file-disjoint tracks)

`zephyr/` is its own git repo (branch `v3.7.0-ti-1.00-esl-lnt`, tracking the TI
Bitbucket fork `tdar/zephyr.git`). Tracks A and B touch completely disjoint
files — Track A only edits `src/appl/appl_main.c`, `src/appl/cli_esl_tag.c`, and
`tag_cli/*`; Track B only edits `src/appl/appl_esl_ap.c`,
`src/appl/appl_esl_ap_auto.c/.h` (new), `src/appl/cli_esl_ap.c`, and `ap_cli/*`.
There is zero file overlap between the build targets, so **both tracks can be
developed directly on the same working tree/branch at the same time** by two
separate AI sessions with no branching needed — commit increments from each
track independently as they're validated.

Track C is the one exception: Track C1 (storage skeleton, new files only) is
still fully parallel-safe on the same branch. Track C2 (wiring into
`appl_esl_tag.c`/`tag_cli/` build files) overlaps Track A's files, so it should
simply be sequenced after Track A's session has landed A1-A5 — no separate
branch is needed, just do C2 after A is done (or have the same session that did
Track A also do C2).

## Kconfig / coexistence strategy

New options keep the manual shell fallback alive until explicitly disabled, so
each increment is a pure addition rather than a rewrite:

**`tag_cli/Kconfig`** (new `menu`/`config` entries, same file that already
defines `BT_ESL_TAG`, `BT_ESL_LED`, etc.):
- `ESL_TAG_AUTO_INIT` (bool, default `n`) — `main()` calls `appl_init_esl()` at boot.
- `ESL_TAG_AUTO_ADV` (bool, default `n`, `depends on ESL_TAG_AUTO_INIT`) — auto-start advertising once init completes.
- `ESL_TAG_DISABLE_SHELL` (bool, default `n`) — compiles the shell command table out of `cli_esl_tag.c`.
- `ESL_TAG_LOG` (bool, default `n`) — compiles the new in-RAM log module in (renamed from `ESL_TAG_FLASH_LOG`; no longer pulls in `CONFIG_NVS` — see Track C1).

**`ap_cli/Kconfig`** (same file that defines `BT_ESL_AP`, `BT_ESL_SYNC_RETRY_COUNT`, etc.):
- `ESL_AP_AUTOMATION` (bool, default `y` once merged) — compiles the new `appl_esl_ap_auto.c` module and `esl_ap auto` / `esl_ap auto_stop` commands in.
- `ESL_AP_AUTO_SYNC_COUNT` (int, range 1-32, default **3**) — the "N" for item 5.

`ESL_TAG_DISABLE_SHELL=y` should only be set in `tag_cli/prj_release.conf` (Track
A, increment A5) — `prj.conf` and `prj_debug.conf` keep the shell for bring-up and
for validating the `esl_tag log_test` debug command (Track C1).

---

## Track A — Tag auto-init / auto-advertise / shell removal

Files: `src/appl/appl_main.c`, `src/appl/cli_esl_tag.c`, `tag_cli/Kconfig`,
`tag_cli/prj*.conf`. File-disjoint from Track B — can be run in a parallel AI
session on the same branch. Strictly sequential within itself (A1→A5).

- [x] **A1. Kconfig scaffolding (no behavior change)** — implemented 2026-08-18
  - File: `tag_cli/Kconfig`
  - Added the four `ESL_TAG_*` options above (`ESL_TAG_AUTO_INIT`, `ESL_TAG_AUTO_ADV` depends on it, `ESL_TAG_DISABLE_SHELL`, `ESL_TAG_FLASH_LOG` selects `NVS`), all default `n`.
  - **User to validate:** `west build` succeeds unchanged; `menuconfig` shows the new options; manual `esl_tag init`/`start` behave exactly as today.

- [x] **A2. Auto-init at boot** — implemented and validated 2026-08-18
  - File: `src/appl/appl_main.c`
  - `main()` now calls `appl_init_esl()` before the idle loop, guarded by `#ifdef CONFIG_ESL_TAG_AUTO_INIT` ([appl_main.c:118-120](src/appl/appl_main.c#L118-L120)).
  - Re-entry guard implemented differently than originally sketched: instead of a flag in `cmd_tag_init` (`cli_esl_tag.c`), the guard lives in `appl_init_esl()` itself ([appl_main.c:98-111](src/appl/appl_main.c#L98-L111)) via a static `esl_initialized` `UCHAR`. This is the single choke point both the boot auto-init and the manual `esl_tag init` shell command call through, so one guard covers both callers without touching/duplicating logic in `cli_esl_tag.c`. `cli_esl_tag.c` was **not** edited for A2.
  - Validate: build tag firmware with `CONFIG_ESL_TAG_AUTO_INIT=y` (temporarily in `prj_debug.conf`); boot with zero shell input; confirm the `"[APPL]: ESL PL initialized successfully"` log and tag-init side effects appear without typing anything. Confirm a manual `esl_tag init` afterward just logs `"[APPL]: ESL already initialized, skipping"` instead of re-running init. Confirm `esl_tag start` still manually works.

- [x] **A3. Auto-advertise on init completion** — implemented and validated 2026-08-18
  - File: `src/appl/appl_main.c`
  - Inside `esl_init_complete_cb`, right after `appl_esl_tag_init();`, added `#ifdef CONFIG_ESL_TAG_AUTO_ADV` calling `appl_esl_tag_start_advertise();` ([appl_main.c:70-78](src/appl/appl_main.c#L70-L78)).
  - Validate: build with both `CONFIG_ESL_TAG_AUTO_INIT=y` and `CONFIG_ESL_TAG_AUTO_ADV=y` (temporarily in `prj_debug.conf`); boot with zero shell input; confirm via a BLE scanner that the tag is advertising within a couple seconds of power-on; confirm `esl_tag stop` still manually works as a fallback.

- [x] **A4. Flip production defaults** — implemented 2026-08-18, awaiting hardware validation
  - Files: `tag_cli/prj.conf`, `tag_cli/prj_release.conf` (`prj_debug.conf` left untouched, as planned)
  - Added a `### ESL Auto Configuration` section to both files setting `CONFIG_ESL_TAG_AUTO_INIT=y` and `CONFIG_ESL_TAG_AUTO_ADV=y`. `CONFIG_SHELL` untouched in both.
  - Validate: clean rebuild + flash from `prj.conf` and from `prj_release.conf`; confirm auto-boot-and-advertise persists; confirm `config_image`, `config_bs`, `get_time`, `reset` shell commands still work.

- [x] **A5. Shell removal (item 1), release-only** — implemented 2026-08-18, awaiting hardware validation
  - Files: `src/appl/cli_esl_tag.c`, `tag_cli/prj_release.conf`
  - Wrapped the whole body of `cli_esl_tag.c` (the `SHELL_STATIC_SUBCMD_SET_CREATE`/`SHELL_CMD_REGISTER` block plus all seven `cmd_*` functions — `cmd_tag_init`, `cmd_start_adv`, `cmd_stop_adv`, `cmd_config_image`, `cmd_config_bs`, `cmd_get_time`, `cmd_reset`) in `#if !defined(CONFIG_ESL_TAG_DISABLE_SHELL)` / `#endif` ([cli_esl_tag.c:27](src/appl/cli_esl_tag.c#L27), [:146](src/appl/cli_esl_tag.c#L146)), nested inside the existing `#ifdef BT_ESL_SUPPORT_TAG_ROLE`.
  - In `prj_release.conf`: changed `CONFIG_SHELL=y` → `CONFIG_SHELL=n`, and added `CONFIG_ESL_TAG_DISABLE_SHELL=y` to the `### ESL Auto Configuration` section (alongside A4's `CONFIG_ESL_TAG_AUTO_INIT=y` / `CONFIG_ESL_TAG_AUTO_ADV=y`). `CONFIG_PRINTK=y` left as-is for boot-log observability. `prj.conf`/`prj_debug.conf` untouched.
  - Validate: build `prj_release.conf`; confirm smaller image; flash and confirm it boots/advertises via the A2/A3 auto-path with **no serial shell prompt**; confirm `prj_debug.conf` still gives you a shell.

### Building the release conf

`tag_cli/prj_release.conf` follows Zephyr's `prj_<suffix>.conf` overlay
convention, so it's picked up via `FILE_SUFFIX` rather than a separate app:

```
west build -b <your_board> -p always zephyr/samples/bluetooth/esl/tag_cli -- -DFILE_SUFFIX=release
```

- `-p always` forces a pristine build — needed here since comparing against a
  `prj_debug.conf`/plain `prj.conf` build otherwise risks stale CMake cache
  leaking config in (e.g. `CONFIG_SHELL` sticking at `y`).
- Equivalent explicit form, if `FILE_SUFFIX` isn't picked up for some reason:
  `-- -DCONF_FILE=prj_release.conf`.
- Flash as usual afterward: `west flash`.

---

## Track B — AP automation state machine (items 4 + 5)

File-disjoint from Track A — can be run in a parallel AI session on the same
branch. **Internally strictly sequential** (B1→B11) — each state layers on the
previous one in the same new module, per the user's explicit request to build
this in visible sub-steps.

**Architectural seam:** all automation logic lives in a new module
`src/appl/appl_esl_ap_auto.c` / `.h`. `src/appl/appl_esl_ap.c` is touched exactly
once (B1) to insert one-line hook calls at the end of the existing callbacks —
every later increment (B2-B11) edits only `appl_esl_ap_auto.c`. This is what
keeps each sub-step small and low-conflict.

- [~] **B1. Scaffolding + hook insertion (behavior-neutral)** — implemented 2026-08-18, awaiting hardware validation
  - New files: `src/appl/appl_esl_ap_auto.c`, `src/appl/appl_esl_ap_auto.h`
  - Edited: `src/appl/appl_esl_ap.c` — add one hook call at the end of each of `appl_connected_ind_cb` ([:200](src/appl/appl_esl_ap.c#L200)), `appl_disconnected_ind_cb` ([:234](src/appl/appl_esl_ap.c#L234)), `appl_discovered_ind_cb` ([:260](src/appl/appl_esl_ap.c#L260)), `appl_configured_ind_cb` ([:273](src/appl/appl_esl_ap.c#L273)), `appl_synchronised_ind_cb` ([:292](src/appl/appl_esl_ap.c#L292)), `appl_esl_device_found_ind_cb` ([:462](src/appl/appl_esl_ap.c#L462)), and `appl_esl_ap_ots_disc_complete` ([:1362](src/appl/appl_esl_ap.c#L1362)) — e.g. `appl_esl_ap_auto_on_connected(esl_addr, status);`. No-ops when automation is disabled.
  - Also edited: `src/appl/cli_esl_ap.c` (register `auto` / `auto_stop` subcommands under `esl_ap`, alongside the existing table at [cli_esl_ap.c:28-66](src/appl/cli_esl_ap.c#L28-L66)), `ap_cli/Kconfig`, `ap_cli/CMakeLists.txt` (add the new source file to `target_sources`, [ap_cli/CMakeLists.txt:33-39](ap_cli/CMakeLists.txt#L33-L39)).
  - Define `enum appl_esl_ap_auto_state { AUTO_IDLE, AUTO_SCANNING, AUTO_ADDING, AUTO_CONNECTING, AUTO_DISCOVERING, AUTO_DISCOVERING_OTS, AUTO_CONFIGURING, AUTO_STARTING_PADV, AUTO_SYNCING, AUTO_DONE }`; static state var; static `synced_count`; static `target_count` seeded from `CONFIG_ESL_AP_AUTO_SYNC_COUNT`. All hook functions exist but only log for now. `esl_ap auto` just sets state to `AUTO_IDLE` and logs.
  - Validate: pure regression — run the full existing manual sequence (`init`→`start_scan`→`add_esl`→`connect_esl`→`discover`→`discover_ots`→`config_esl`→`start_padv`→`sync_esl`) exactly as before; confirm nothing changed. Run `esl_ap auto`; confirm it just logs and does nothing else.

- [x] **B2. Automate init + first scan** — implemented 2026-08-18, validated on hardware 2026-08-18
  - File: `appl_esl_ap_auto.c` only
  - `appl_esl_ap_auto_start()` calls `appl_init_esl()` then `appl_esl_ap_scan_esl_device(BT_ESL_TRUE)` ([appl_esl_ap.c:648](src/appl/appl_esl_ap.c#L648)); state → `AUTO_SCANNING`.
  - Validate: on a freshly booted AP, run only `esl_ap auto`; confirm AP init success followed by scan start, matching manual `init`+`start_scan` output.

- [x] **B3. Automate device selection + add** — implemented and validated 2026-08-18 (required a follow-on fix — see B4 note / session log — for an intermittent AP scan-miss bug, unrelated to B3's own logic)
  - File: `appl_esl_ap_auto.c` only
  - In the device-found hook: while in `AUTO_SCANNING`, stop scan (`appl_esl_ap_scan_esl_device(BT_ESL_FALSE)`), synthesize `BT_ESL_ADDR{group_id=0, esl_id=synced_count}`, call `appl_esl_ap_add_esl_tag()` ([appl_esl_ap.c:673](src/appl/appl_esl_ap.c#L673)); state → `AUTO_CONNECTING`.
  - Validate: with one advertising tag in range, run `esl_ap auto`; confirm scan stops right after the tag is found and it's added to the tag table (check with existing `esl_dev_list`).

- [x] **B4. Automate connect** — implemented and validated 2026-08-18
  - File: `appl_esl_ap_auto.c` only
  - Right after B3's add succeeds, `appl_esl_ap_auto_on_device_found()` now sets state to `AUTO_CONNECTING` and calls `appl_esl_ap_connect_esl(&esl_addr)` ([appl_esl_ap.c:731](src/appl/appl_esl_ap.c#L731)); on failure, logs via `APPL_ESL_ERR` and reverts to `AUTO_IDLE` (same pattern as B2/B3's error paths).
  - Validate: with one tag in range, run `esl_ap auto`; confirm connection completes automatically (watch for the `appl_connected_ind_cb` log) with zero manual `connect_esl`.

- [x] **B5. Automate service discovery** — implemented and validated 2026-08-18
  - File: `appl_esl_ap_auto.c` only
  - On successful-connect hook while `AUTO_CONNECTING`: call `appl_esl_ap_discover_esl_service()` ([appl_esl_ap.c:780](src/appl/appl_esl_ap.c#L780)); state → `AUTO_DISCOVERING`.
  - Validate: confirm ESL service discovery starts automatically right after connect.

- [x] **B6. Automate OTS discovery (conditional)** — implemented and validated 2026-08-18
  - File: `appl_esl_ap_auto.c` only
  - On successful-discover hook: `#ifdef APPL_ESL_AP_OTS_SUPPORT` call `appl_esl_ap_discover_ots()` → `AUTO_DISCOVERING_OTS`; else skip straight to `appl_esl_ap_config()` → `AUTO_CONFIGURING`.
  - Validate: test both build variants (`CONFIG_BT_OTS_CLIENT` on/off, [ap_cli/CMakeLists.txt:23-26](ap_cli/CMakeLists.txt#L23-L26)); confirm OTS discovery only auto-fires in the OTS build, config starts directly otherwise.

- [x] **B7. Automate config kickoff after OTS** — implemented and validated 2026-08-18
  - File: `appl_esl_ap_auto.c` only (compiled only under `APPL_ESL_AP_OTS_SUPPORT`)
  - Hook off `appl_esl_ap_ots_disc_complete` ([appl_esl_ap.c:1387](src/appl/appl_esl_ap.c#L1387)) — that function already calls `BT_esl_config_ots_pl` internally on success; your hook fires after, unconditionally continuing: call `appl_esl_ap_config()`; state → `AUTO_CONFIGURING`.
  - Validate: OTS-enabled build — confirm config auto-fires after OTS config completes.

- [x] **B8. Automate periodic-adv start + sync kickoff** — implemented and validated 2026-08-18
  - File: `appl_esl_ap_auto.c` only
  - On successful-configured hook: if a static `padv_started` flag is false, call `appl_esl_ap_start_periodic_adv()` ([appl_esl_ap.c:608](src/appl/appl_esl_ap.c#L608)) and set the flag (guards against double-start across B10's loop); then call `appl_esl_ap_sync_with_esl()` ([appl_esl_ap.c:778](src/appl/appl_esl_ap.c#L778)); state → `AUTO_SYNCING`.
  - Success check verified against the EtherMind header (`BT_esl_api.h`, `CONFIGURED_IND_CB` doxygen): `error` is an ATT error code (`0` = no error) and `result` is `BT_ESL_AP_SUCCESS` (`0x0000`) on success — same `0`/`BT_ESL_AP_SUCCESS` convention used by every other AP callback in this file.
  - Validate: confirm PAwR starts automatically (only once) and sync is requested right after config.

- [x] **B9. Complete single-tag chain + synced counter** — implemented and validated 2026-08-18
  - File: `appl_esl_ap_auto.c` only
  - On successful-synchronised hook: `synced_count++`, log `"%d/%d tags synced"`; state → `AUTO_DONE`.
  - Validate: full end-to-end — run `esl_ap auto` once on a freshly booted AP with one tag powered on; confirm the tag reaches `SYNCHRONIZED` fully automatically with zero other manual commands. **This completes item 4.**

- [x] **B10. Loop until N tags synced (item 5)** — implemented and validated 2026-08-19
  - File: `appl_esl_ap_auto.c` only
  - Extend B9: if `synced_count < target_count`, call `appl_esl_ap_disconnect_esl()`, then re-scan (`appl_esl_ap_scan_esl_device(BT_ESL_TRUE)`) and state → `AUTO_SCANNING` (re-entering B3's flow, next `esl_id = synced_count`). If `synced_count == target_count`, log completion and stay `AUTO_DONE`.
  - Validate: set `CONFIG_ESL_AP_AUTO_SYNC_COUNT=2` for a fast bench check; with two tags in range, run `esl_ap auto` once; confirm disconnect → rescan → sync-tag-2 → "2/2 tags synced" and the loop stops (no third scan).

- [x] **B10b. Optional tag-count argument on `esl_ap auto` (unplanned, user-requested 2026-08-19)** — implemented and validated 2026-08-19
  - Files: `appl_esl_ap_auto.c`/`.h`, `cli_esl_ap.c` (deliberate seam exception — same precedent as B11 already touching `cli_esl_ap.c`; the CLI argument has to be parsed where the shell command is registered)
  - `appl_esl_ap_auto_start(void)` → `appl_esl_ap_auto_start(UCHAR count)`: `count == 0` keeps the existing `CONFIG_ESL_AP_AUTO_SYNC_COUNT` default, any other value (1-32) overrides `target_count` for that run.
  - `auto` shell command changed from `SHELL_CMD` to `SHELL_CMD_ARG(..., 1, 1)` (1 optional arg); `cmd_ap_auto()` parses `argv[1]` via `strtol(argv[1], NULL, 10)` when `argc == 2`, rejects out-of-range (not 1-32) with `-ENOEXEC`, and passes the result (or `0`) through to `appl_esl_ap_auto_start()`.
  - Validate: `esl_ap auto` (no arg) still uses the Kconfig default; `esl_ap auto 2` with two tags in range produces the same "2/2 tags synced" result as B10's bench test; `esl_ap auto 0` and `esl_ap auto 99` are both rejected with the invalid-count message and automation does not start.

- [x] **B11. Guard rails / abort command** — implemented and validated 2026-08-19
  - Files: `appl_esl_ap_auto.c`/`.h`, `cli_esl_ap.c`
  - Add a re-entrancy guard (reject a second `esl_ap auto` while state isn't `AUTO_IDLE`/`AUTO_DONE`) and an `esl_ap auto_stop` command that force-resets to `AUTO_IDLE`. Lean on existing `CONFIG_BT_ESL_SYNC_RETRY_COUNT` / `CONFIG_BT_ESL_AP_CONFIG_TIMEOUT` ([ap_cli/Kconfig:70-86](ap_cli/Kconfig#L70-L86)) for retry/timeout rather than inventing new ones.
  - Note: `esl_ap auto_stop` (`cmd_ap_auto_stop` → `appl_esl_ap_auto_stop()`) already existed from B1's scaffolding and already unconditionally force-resets to `AUTO_IDLE` — no changes needed there. The actual remaining work was the re-entrancy guard: `appl_esl_ap_auto_start()` signature changed from `void` to `API_RESULT`; at entry, if `auto_state` is neither `AUTO_IDLE` nor `AUTO_DONE`, it logs and returns `BT_ESL_AP_BUSY` without touching any state (no reset, no scan toggle, run in progress is left untouched). `cmd_ap_auto()` in `cli_esl_ap.c` checks the return value and prints "ESL AP automation already running. Use 'esl_ap auto_stop' first." on `BT_ESL_AP_BUSY`, or a generic failure message for any other non-success code, both returning `-ENOEXEC`.
  - Validate: start `esl_ap auto`, mid-sequence run `esl_ap auto` again — confirm it's rejected with the "already running" message and the original run is undisturbed (no restart, no state reset); run `esl_ap auto_stop` mid-sequence — confirm clean return to idle and all manual `esl_ap` commands still work afterward; confirm a fresh `esl_ap auto` after `auto_stop` starts normally.

---

## Track C — Flash logging (item 3, last, per user's instruction) — SUPERSEDED 2026-08-19

**Strategy change (2026-08-19):** the user discarded the ring-buffer design
below (C1's PAwR-message/image rings, C2's plan to log every PAwR command
callback) entirely, before C2 was ever implemented. New instruction: tags
track only (1) a ping count + time since last ping, and (2) the last image
received, printed via `esl_tag log`; the AP tracks the same two things
**per tag** (a new per-tag device table) via `esl_ap log`. This is split into
two independent, parallel-safe tracks — see **Track C2 (redefined) — Tag
Logging** and **Track D1 — AP Logging** below. C1 (as described just below)
is kept for history only; its module was rewritten from scratch rather than
incrementally modified, and C2's original scope (wiring PAwR-message logging
into ~10 tag command callbacks) was dropped rather than implemented. Full
design rationale: `i-want-to-make-eager-beacon.md`.

C1 (new files only) is fully isolated and can start anytime in parallel with
A/B on the same branch. C2 overlaps Track A's files (`appl_esl_tag.c`,
`tag_cli/*`), so it should be sequenced after Track A finishes A1-A5 — no
branch needed, just do it after, ideally by the same session that did Track A.

There is currently **no app-level persistent storage** anywhere in this sample —
only the generic `CONFIG_SETTINGS`-backed `settings_load()` in `BT_esl_pl.c`
(~line 684) used by the BT stack itself for bonding/keys. C1 was originally
planned as NVS/flash-backed, but that assumed MCUboot's dual-slot layout was
live; a real generated `.config` (board `lp_em_cc2745r10_q1`) confirmed
`CONFIG_BOOTLOADER_MCUBOOT` and `CONFIG_USE_DT_CODE_PARTITION` are both off in
this project, so the board's `mcuboot`/`image-0`/`image-1` devicetree
partitions are decorative, not a real constraint — but using them safely would
still require a per-board devicetree overlay plus an explicit
`CONFIG_FLASH_LOAD_SIZE` cap (currently `0`/unbounded) to stop the linker
growing into a reserved log region. Given C1 is a debugging/demo aid rather
than a persistence guarantee, the user chose the simpler path: **build
RAM-only now, keep flash for later.** The RAM version shares the exact same
public API a flash-backed version would use, so flash support (if ever
needed) is a pure swap of the `.c` file with zero call-site changes — see
`i-want-to-make-eager-beacon.md`'s "Deferred flash-backed alternative" for
the design if this comes up again.

- [x] **C1. In-RAM log module skeleton + self-test (parallel-safe)** — implemented 2026-08-18, **superseded 2026-08-19** — module rewritten from scratch under the new Track C2 (redefined) below; kept here for history only, no hardware validation was ever done on this ring-buffer version
  - New files: `src/appl/appl_esl_tag_log.c` (compiled only under `CONFIG_ESL_TAG_LOG`), `src/appl/appl_esl_tag_log.h` (real prototypes under `CONFIG_ESL_TAG_LOG`, `static inline` no-op stubs otherwise, so C2's future call sites never need their own `#ifdef`).
  - Kconfig: renamed `ESL_TAG_FLASH_LOG` → `ESL_TAG_LOG` in `tag_cli/Kconfig`, dropped `select NVS` (no longer needed — RAM-only, no flash/devicetree changes at all).
  - Storage: non-persistent (lost on reset/power-cycle) — pings are a plain `UINT32` counter (`appl_esl_log_ping()` takes no args, just increments it — see 2026-08-19 revision below), PAwR ring (capacity 20, up to 32 bytes + actual `len` + timestamp), image-received ring (capacity 10, `{image_index, timestamp}`). Timestamps via the existing `BT_esl_get_current_time_pl()`. Internal dump implementation uses `APPL_ESL_INF` (printk-based, no `shell`-variable dependency), not `CONSOLE_OUT` as originally sketched — `appl_esl_tag_log.c` has no `shell` in scope since it's a plain library module, not a shell command handler.
  - Plan-doc correction carried forward as planned: added `appl_esl_tag_log.c` to `tag_cli/CMakeLists.txt` (conditional on `CONFIG_ESL_TAG_LOG`) and the temporary `esl_tag log_test write` / `esl_tag log_test dump` debug subcommands in `cli_esl_tag.c` (nested inside A5's `#if !defined(CONFIG_ESL_TAG_DISABLE_SHELL)`, further guarded by `#ifdef CONFIG_ESL_TAG_LOG`) as part of **C1**, not C2 — C1 can't be built or self-tested without them. C2 remains purely "wire into real receive paths."
  - `appl_esl_tag.c` and all `prj*.conf` files **not touched** — C1 is opt-in/build-invisible until C2 wires it up and enables the flag for test builds.
  - Validated by build only so far (real `west build` for `lp_em_cc2340r53`): flag forced on (`-DCONFIG_ESL_TAG_LOG=y`) links cleanly, FLASH 61.34%/RAM 75.23% used; default build (flag unset) also links cleanly, FLASH 61.16%/RAM 73.49% used, confirming the `esl_tag` command table and log module are fully excluded when the flag is off. **Still awaiting hardware validation**: flash flag-on build, run `esl_tag log_test write` a few times then `esl_tag log_test dump`, confirm ping/PAwR/image entries appear with plausible timestamps.

- [ ] **C2 (original scope). Wire into real receive paths — ABANDONED 2026-08-19, never implemented**
  - This was the plan to log every PAwR command callback generically (~10 callbacks) into the C1 ring buffers. Superseded before any code was written — see **Track C2 (redefined)** below for what was actually built instead.

---

## Track C2 (redefined) — Tag Logging

Files: `src/appl/appl_esl_tag_log.c`/`.h` (rewritten in place, same filenames
as old C1), `src/appl/appl_esl_tag.c` (two call sites), `src/appl/cli_esl_tag.c`/`.h`
(replaces the old `log_test` debug subcommands with a real `log` command),
`tag_cli/prj.conf`/`prj_debug.conf`. Independent of Track D1 — can be
developed/validated in parallel with it.

- [~] **C2-1. Rewrite log module to ping-count + last-ping-time + last-image** — implemented 2026-08-19, awaiting hardware validation
  - `appl_esl_tag_log.h`: dropped `appl_esl_log_pawr_msg`; new API `appl_esl_log_init(void)`, `appl_esl_log_ping(void)`, `appl_esl_log_image_received(UCHAR image_index)`, `appl_esl_log_dump_all(void)` — real prototypes under `CONFIG_ESL_TAG_LOG`, `static inline` no-op stubs otherwise (unchanged pattern from old C1).
  - `appl_esl_tag_log.c`: replaced both ring buffers with plain state — `appl_esl_log_ping_count` (`UINT32`, uncapped), `appl_esl_log_last_ping_time` (`UINT32`, valid iff `ping_count > 0`), `appl_esl_log_last_image_index` (`UCHAR`) + `appl_esl_log_has_image` (`UCHAR` flag, since image index 0 is itself valid). `appl_esl_log_ping()` takes no args (increments count, stamps time via `BT_esl_get_current_time_pl()`); `appl_esl_log_image_received(image_index)` stores index and sets the flag. `appl_esl_log_dump_all()` prints the fixed 3-line format via `CONSOLE_OUT`:
    ```
    Number of Pings: <count>
    Time since last ping: <elapsed>s   (or "never")
    Latest Image Received: <index>     (or "none")
    ```
  - Call sites in `appl_esl_tag.c`: `appl_esl_log_ping()` added to `appl_esl_tag_ping_cmd_cb`'s validated-success path (right before the existing `BT_esl_tag_send_basic_state` call); `appl_esl_log_image_received(image_index)` added to `appl_esl_tag_ots_image_written_cb`'s `rem == 0` (transfer-complete) branch.
  - `cli_esl_tag.c`/`.h`: removed the old `log_test write`/`log_test dump` debug subcommands and `cmd_log_test_write`/`cmd_log_test_dump`; added a single `esl_tag log` command (`SHELL_CMD(log, NULL, "Print ping/image log", cmd_log)`) calling `appl_esl_log_dump_all()`, guarded by `CONFIG_ESL_TAG_LOG` same as before.
  - `tag_cli/prj.conf` / `prj_debug.conf`: `CONFIG_ESL_TAG_LOG=y` already present from the old C1 work (unchanged) — no new config edit needed for this step; `tag_cli/Kconfig`'s description string was updated to match the new (non-ring-buffer) design.
  - Validate: `west build -b lp_em_cc2745r10_q1 -p always zephyr/samples/bluetooth/esl/tag_cli` — confirm clean compile with `CONFIG_ESL_TAG_LOG=y`. Hardware: send a real ping, send a real image, run `esl_tag log`, confirm all three printed values are plausible. **Build-verified 2026-08-19 (`lp_em_cc2340r53`) — clean compile after fixing a `CONSOLE_OUT` misuse bug, see session log. Hardware validation still pending.**

---

## Track D1 — AP Logging

New module, no history to carry forward. Files: new
`src/appl/appl_esl_ap_log.c`/`.h`, `src/appl/appl_esl_ap.c` (three call
sites + init call), `src/appl/cli_esl_ap.c`/`.h` (new `log` command),
`ap_cli/Kconfig`, `ap_cli/CMakeLists.txt`, `ap_cli/prj.conf`/`prj_debug.conf`.
Independent of Track C2 (redefined) — can be developed/validated in
parallel with it.

- [~] **D1-1. New per-tag log module + AP-side hooks + CLI + build wiring** — implemented 2026-08-19, awaiting hardware validation
  - New `appl_esl_ap_log.h`: `appl_esl_ap_log_init(void)`, `appl_esl_ap_log_ping(BT_ESL_ADDR *esl_addr)`, `appl_esl_ap_log_image_sent(BT_ESL_ADDR *esl_addr, UCHAR image_index)`, `appl_esl_ap_log_dump_all(void)` — real prototypes under new Kconfig symbol `CONFIG_ESL_AP_LOG`, `static inline` no-op stubs otherwise (mirrors the tag-side pattern).
  - New `appl_esl_ap_log.c`: per-tag table `appl_esl_ap_log_table[APPL_ESL_MAX_NO_OF_TAGS_PER_GROUP]` of `{in_use, group_id, esl_id, ping_count, last_ping_time, last_image_index, has_image}`, keyed by linear search on `(group_id, esl_id)` via `appl_esl_ap_log_find_or_alloc()` (claims first free slot on miss; logs via `APPL_ESL_ERR` and returns `NULL` — update dropped, no crash — if the table is full). Bug found and fixed during implementation: the find-or-alloc free-slot tracking originally used an `INT16 free_index = -1` sentinel, a signed type not used anywhere else in this codebase; replaced with the codebase's established `UCHAR`-boolean-flag idiom (`UCHAR free_index` + `UCHAR have_free_index`, same shape as `appl_esl_ap_get_esl_tag_from_bd_address`'s `UCHAR found` in `appl_esl_ap.c`). `appl_esl_ap_log_dump_all()` prints one block per `in_use` entry via `CONSOLE_OUT`:
    ```
    Tag [<group_id>:<esl_id>]
      Number of Pings: <count>
      Time since last ping: <elapsed>s   (or "never")
      Latest Image Sent: <index>          (or "none")
    ```
  - `appl_esl_ap.c`: added `#include "appl_esl_ap_log.h"`; added `appl_esl_ap_log_init();` call inside `appl_esl_ap_init()`; added the log call as a new `else` branch (right before `return retval;`, i.e. only on confirmed send success) in all three send functions — `appl_esl_ap_send_ping` → `appl_esl_ap_log_ping(esl_addr)`, `appl_esl_ap_send_display_image` → `appl_esl_ap_log_image_sent(esl_addr, image_index)`, `appl_esl_ap_send_display_timed_image` → `appl_esl_ap_log_image_sent(esl_addr, image_index)`.
  - `cli_esl_ap.h`/`.c`: added `#include "appl_esl_ap_log.h"`, `cmd_log` prototype, `SHELL_CMD(log, NULL, "Print per-tag ping/image log", cmd_log)` registration, and `cmd_log` implementation calling `appl_esl_ap_log_dump_all()` — all guarded by `CONFIG_ESL_AP_LOG`, mirroring the tag-side `cmd_log` exactly. Left the existing unimplemented `esl_dev_list` stub alone (separate, pre-existing command).
  - Build/config wiring, all new: `ap_cli/Kconfig` — added `ESL_AP_LOG` (bool, default `n`, `depends on BT_ESL_AP`); `ap_cli/CMakeLists.txt` — added conditional `target_sources` for `appl_esl_ap_log.c` under `CONFIG_ESL_AP_LOG`; `ap_cli/prj.conf` and `ap_cli/prj_debug.conf` — added `CONFIG_ESL_AP_LOG=y` to both (test-build default, same rationale as the tag side).
  - Validate: `west build -b lp_em_cc2745r10_q1 -p always zephyr/samples/bluetooth/esl/ap_cli` — confirm clean compile with `CONFIG_ESL_AP_LOG=y`. Hardware: send a real ping and a real display-image command to a synced tag, run `esl_ap log`, confirm the per-tag values match reality. **Build-verified 2026-08-19 (`lp_em_cc2340r53`) — clean compile after fixing a `CONSOLE_OUT` misuse bug, see session log. Hardware validation still pending.**

---

## Suggested order if working solo/serially

A1 → A2 → A3 → A4 (tag auto-boot proven) → B1..B11 (AP automation proven) → A5
(shell-off release overlay) → C2 (redefined, tag logging) / D1 (AP logging) —
these two are file-disjoint and can be done in either order or in parallel,
last per the user's instruction.

## Critical files reference

- `src/appl/appl_main.c`
- `src/appl/cli_esl_tag.c`
- `src/appl/appl_esl_ap.c`
- `src/appl/appl_esl_ap.h`
- `src/appl/cli_esl_ap.c`
- `src/appl/appl_esl_tag.c`
- `tag_cli/Kconfig`
- `tag_cli/CMakeLists.txt`
- `ap_cli/Kconfig`
- `ap_cli/CMakeLists.txt`

## Session log

Append a line here each time a context-cleared session finishes an increment,
so the next session knows what actually happened (not just what was planned).

- 2026-08-18: Plan created and placed in this folder.
- 2026-08-18: A1 implemented — added `ESL_TAG_AUTO_INIT`, `ESL_TAG_AUTO_ADV`, `ESL_TAG_DISABLE_SHELL`, `ESL_TAG_FLASH_LOG` to `tag_cli/Kconfig`, all default `n`. No other files touched. Awaiting user hardware/build validation before starting A2.
- 2026-08-18: B1 implemented — new `src/appl/appl_esl_ap_auto.c/.h` module (state enum, `appl_esl_ap_auto_start/stop`, one log-only hook per callback); one-line hook call added at the end of each of the 7 callbacks listed in the plan in `appl_esl_ap.c`; `esl_ap auto` / `auto_stop` shell commands added in `cli_esl_ap.c/.h`; `ESL_AP_AUTOMATION` (default `y`) and `ESL_AP_AUTO_SYNC_COUNT` (default 3) added to `ap_cli/Kconfig`; `appl_esl_ap_auto.c` added to `ap_cli/CMakeLists.txt` conditionally on `CONFIG_ESL_AP_AUTOMATION`. No existing manual command behavior changed. Awaiting user hardware/build validation before starting B2.
- 2026-08-18: A2 implemented — `appl_main.c`'s `main()` now calls `appl_init_esl()` before the idle loop, guarded by `#ifdef CONFIG_ESL_TAG_AUTO_INIT`. Re-entrancy guard placed inside `appl_init_esl()` itself (static `esl_initialized` flag) rather than in `cli_esl_tag.c`'s `cmd_tag_init` as originally sketched — this is the single choke point both boot auto-init and manual `esl_tag init` call through, so `cli_esl_tag.c` was left untouched. No other files changed. User validated on hardware before requesting A3.
- 2026-08-18: A3 implemented — inside `esl_init_complete_cb` in `appl_main.c`, added `#ifdef CONFIG_ESL_TAG_AUTO_ADV` calling `appl_esl_tag_start_advertise()` right after `appl_esl_tag_init()`. No other files changed. User confirmed working on hardware. Tag auto-boot-and-advertise (A2+A3) is now fully proven; next up is A4 (flip production defaults) whenever the user is ready.
- 2026-08-18: A4 implemented — added `CONFIG_ESL_TAG_AUTO_INIT=y` / `CONFIG_ESL_TAG_AUTO_ADV=y` to `tag_cli/prj.conf` and `tag_cli/prj_release.conf` (note: `prj.conf` already had these two lines added manually at the end of the file, presumably from earlier A2/A3 bench testing — consolidated into one properly-placed `### ESL Auto Configuration` section, removed the duplicate). `prj_debug.conf` and `CONFIG_SHELL` left untouched in both files. Awaiting user hardware/build validation before starting A5 (shell removal, release-only).
- 2026-08-18: B2 implemented — `appl_esl_ap_auto_start()` in `appl_esl_ap_auto.c` now calls `appl_init_esl()` then `appl_esl_ap_scan_esl_device(BT_ESL_TRUE)` and sets state to `AUTO_SCANNING` (was previously just a log line staying in `AUTO_IDLE`). Added a failure path not in the original one-line spec: if `appl_esl_ap_scan_esl_device` doesn't return `BT_ESL_AP_SUCCESS`, logs via `APPL_ESL_ERR` and reverts state to `AUTO_IDLE` rather than claiming `AUTO_SCANNING` on a failed scan start — mirrors the existing error-check pattern in `cmd_start_scan` (`cli_esl_ap.c`). No other files touched (only `appl_esl_ap_auto.c`, per the plan's architectural seam). User validated on hardware 2026-08-18: confirmed on fresh AP boot.
- 2026-08-18: B3 implemented — `appl_esl_ap_auto_on_device_found()` in `appl_esl_ap_auto.c` now, while in `AUTO_SCANNING`, stops the scan (`appl_esl_ap_scan_esl_device(BT_ESL_FALSE)`), synthesizes `BT_ESL_ADDR{group_id=0, esl_id=synced_count}`, and calls `appl_esl_ap_add_esl_tag(&esl_addr, peer_addr)`; on success moves state to `AUTO_CONNECTING`, on failure logs via `APPL_ESL_ERR` and reverts to `AUTO_IDLE`. Hook is a no-op if a device-found event fires outside `AUTO_SCANNING` (e.g. leftover reports after scan stop). No other files touched. Awaiting user hardware validation (one advertising tag in range, run `esl_ap auto`, confirm scan stops right after the tag is found and it's added — check with `esl_dev_list`) before starting B4.
- 2026-08-18: Pre-existing bug fix attempt #1 (not a B-track increment, **superseded — did not fix it on hardware, see next entry**) — `appl_esl_ap_scan_esl_device()` in `appl_esl_ap.c` forced a `BT_esl_ap_scan_esl_device(BT_ESL_FALSE)` before every start. User confirmed on hardware this did not resolve the intermittent scan-miss.
- 2026-08-18: Pre-existing bug fix attempt #2 (not a B-track increment) — reverted attempt #1 in `appl_esl_ap.c` (`appl_esl_ap_scan_esl_device()` back to its pre-session form, `appl_esl_ap.c:673-694`), and instead added a periodic rescan retry loop entirely inside `appl_esl_ap_auto.c` — this **restores** Track B's "only `appl_esl_ap_auto.c` changes" seam. New: a `static K_WORK_DELAYABLE_DEFINE(rescan_work, rescan_work_handler)` (first use of `zephyr/kernel.h` work items anywhere in `src/appl`); while `auto_state == AUTO_SCANNING`, `rescan_work_handler()` toggles `appl_esl_ap_scan_esl_device(FALSE)`→`(TRUE)` every `APPL_ESL_AP_AUTO_RESCAN_INTERVAL` (`K_SECONDS(4)`) and reschedules itself. `appl_esl_ap_auto_start()` schedules the first retry after a successful scan start; `appl_esl_ap_auto_on_device_found()` cancels it as soon as a tag is actually found (before stopping scan/adding the tag); `appl_esl_ap_auto_stop()` also cancels it. Manual shell scan commands (`start_scan`/`stop_scan`) are completely unaffected — only the automation path retries. User validated on hardware 2026-08-18: confirmed working.
- 2026-08-18: A5 implemented — wrapped the shell command table and all seven `cmd_*` functions in `cli_esl_tag.c` in `#if !defined(CONFIG_ESL_TAG_DISABLE_SHELL)` / `#endif`; in `tag_cli/prj_release.conf` set `CONFIG_SHELL=n` and added `CONFIG_ESL_TAG_DISABLE_SHELL=y`. `prj.conf`/`prj_debug.conf` untouched — both still build with the shell present. This is the last Track A increment (A1-A5 now all implemented); awaiting user hardware/build validation (smaller release image, boots/advertises via A2/A3 auto-path with no serial shell prompt, `prj_debug.conf` still gives a shell).
- 2026-08-18: B4 implemented — `appl_esl_ap_auto_on_device_found()` in `appl_esl_ap_auto.c`, right after B3's `appl_esl_ap_add_esl_tag()` succeeds, now sets state to `AUTO_CONNECTING` and calls `appl_esl_ap_connect_esl(&esl_addr)`; on failure logs via `APPL_ESL_ERR` and reverts to `AUTO_IDLE` (same error-path pattern as B2/B3). No other files touched. User validated on hardware 2026-08-18: `appl_connected_ind_cb` fired automatically with zero manual `connect_esl`.
- 2026-08-18: B5 implemented — `appl_esl_ap_auto_on_connected()` in `appl_esl_ap_auto.c` now, while `auto_state == AUTO_CONNECTING`: if `status != 0` (connect failed), logs via `APPL_ESL_ERR` and reverts to `AUTO_IDLE`; otherwise sets state to `AUTO_DISCOVERING` and calls `appl_esl_ap_discover_esl_service(esl_addr)`, reverting to `AUTO_IDLE` on a non-success return (same error-path pattern as B2-B4). Hook is a no-op if a connect event fires outside `AUTO_CONNECTING`. No other files touched. User validated on hardware 2026-08-18: ESL service discovery started automatically right after connect.
- 2026-08-18: B6 implemented — `appl_esl_ap_auto_on_discovered()` in `appl_esl_ap_auto.c` now, while `auto_state == AUTO_DISCOVERING`: if `status != BT_ESL_AP_SUCCESS`, logs via `APPL_ESL_ERR` and reverts to `AUTO_IDLE`; otherwise, under `#ifdef APPL_ESL_AP_OTS_SUPPORT` sets state to `AUTO_DISCOVERING_OTS` and calls `appl_esl_ap_discover_ots(&esl_addr)`, else sets state to `AUTO_CONFIGURING` and calls `appl_esl_ap_config(&esl_addr)` directly — both paths revert to `AUTO_IDLE` on a non-success return (same error-path pattern as B2-B5). Hook is a no-op if a discover event fires outside `AUTO_DISCOVERING`. No other files touched. User validated on hardware 2026-08-18: confirmed working on the current build variant.
- 2026-08-18: B7 implemented — added a static `current_esl_addr` in `appl_esl_ap_auto.c`, set in `appl_esl_ap_auto_on_device_found()` alongside the existing `esl_addr` construction (needed because `appl_esl_ap_ots_disc_complete`'s callback only hands back a `BT_ESL_BD_ADDR *`, not an `esl_addr`, since it's a GATT OTS callback rather than an ESL AP one). `appl_esl_ap_auto_on_ots_disc_complete()` now, while `auto_state == AUTO_DISCOVERING_OTS`: unconditionally (per plan — `appl_esl_ap_ots_disc_complete` already handled the OTS config internally on success) sets state to `AUTO_CONFIGURING` and calls `appl_esl_ap_config(&current_esl_addr)`, reverting to `AUTO_IDLE` on a non-success return. Hook is a no-op outside `AUTO_DISCOVERING_OTS`. This code path only compiles under `APPL_ESL_AP_OTS_SUPPORT`, matching the existing hook's guard. No other files touched. User validated on hardware 2026-08-18: config auto-fired after OTS config completed.
- 2026-08-18: B8 implemented — added a static `padv_started` (`BT_ESL_FALSE` initially) in `appl_esl_ap_auto.c`. `appl_esl_ap_auto_on_configured()` now, while `auto_state == AUTO_CONFIGURING`: treats `error == 0` AND `result == BT_ESL_AP_SUCCESS` as success (verified against the EtherMind `BT_esl_api.h` `CONFIGURED_IND_CB` doxygen — `error` is an ATT-layer error code, `result` is the ESL-layer result, both must be clear), otherwise logs via `APPL_ESL_ERR` and reverts to `AUTO_IDLE`. On success: if `padv_started` is still false, calls `appl_esl_ap_start_periodic_adv()` (reverting to `AUTO_IDLE` on failure) and sets the flag so periodic adv is only ever started once across the session (needed ahead of B10's per-tag loop); then unconditionally sets state to `AUTO_SYNCING` and calls `appl_esl_ap_sync_with_esl(esl_addr)`, reverting to `AUTO_IDLE` on failure. No other files touched. User validated on hardware 2026-08-18: PAwR started automatically (only once) and sync was requested right after config.
- 2026-08-18: B9 implemented — `appl_esl_ap_auto_on_synchronised()` in `appl_esl_ap_auto.c` now, while `auto_state == AUTO_SYNCING`: if `status != BT_ESL_AP_SUCCESS`, logs via `APPL_ESL_ERR` and reverts to `AUTO_IDLE`; otherwise increments `synced_count`, logs `"%d/%d tags synced"`, and sets state to `AUTO_DONE` (same error-path pattern as B2-B8). Hook is a no-op outside `AUTO_SYNCING`. No other files touched. This completes the single-tag automated chain end-to-end (item 4). Awaiting user hardware validation (freshly booted AP + one powered-on tag, run `esl_ap auto` once, confirm the tag reaches `SYNCHRONIZED` fully automatically with zero other manual commands) before starting B10.
- 2026-08-18: B9 bug report + fix — user reported a `status 0x0101` "sync failed" log on hardware right after B9 landed, despite the tag appearing to work. Investigated the EtherMind header (`BT_esl_api.h:958-984`) rather than guessing: `0x0100` is the ESL-AP module's error-code base, `0x0101` = `BT_ESL_AP_TIMEOUT`, a genuine specifically-defined failure, not a benign/context-encoded value — so B9's `status != BT_ESL_AP_SUCCESS` check itself was correct. Root cause instead: the manual CLI flow has an incidental human-typing delay between `start_padv` and `sync_esl`; B8's automation collapses that to zero (both calls fire back-to-back inside `appl_esl_ap_auto_on_configured()`), and `BT_esl_start_periodic_adv_pl` only guarantees the PAwR HCI commands completed, not that the controller has settled into actually broadcasting — the immediate sync request was racing that. Fix (still only in `appl_esl_ap_auto.c`): added `APPL_ESL_AP_AUTO_SYNC_DELAY` (`K_SECONDS(1)`) and a new `sync_delay_work` (`k_work_delayable`, same pattern as B2's `rescan_work`); when periodic adv is started for the first time, `on_configured()` now stores the tag in `sync_pending_addr` and reschedules `sync_delay_work` instead of calling `appl_esl_ap_sync_with_esl()` immediately — `sync_delay_work_handler()` fires the actual sync call after the delay elapses (still no-ops if `auto_state` moved on). Subsequent tags (padv already running) still sync immediately, unchanged. `appl_esl_ap_auto_stop()` also cancels `sync_delay_work`. B9 stays `[~]` — awaiting user re-validation on hardware that the 1s delay eliminates the `0x0101` timeout on the first tag's sync.
- 2026-08-18: B9 re-validated — user confirmed the sync-delay fix works on hardware; no more `0x0101` timeout, tag reaches `SYNCHRONIZED` fully automatically end-to-end with zero manual commands. B9 marked `[x]`. Single-tag automated chain (item 4) is now fully proven; next up is B10 (loop until N tags synced) whenever the user is ready.
- 2026-08-19: B10 implemented — extended `appl_esl_ap_auto_on_synchronised()` in `appl_esl_ap_auto.c` (no other files touched): after `synced_count++` and the `"%d/%d tags synced"` log, if `synced_count >= target_count` logs a completion line and stays `AUTO_DONE` (unchanged behavior); otherwise calls `appl_esl_ap_disconnect_esl(esl_addr)` (reverting to `AUTO_IDLE` on failure, same error-path pattern as B2-B9), then sets state to `AUTO_SCANNING` and calls `appl_esl_ap_scan_esl_device(BT_ESL_TRUE)` (same revert-on-failure pattern) — re-entering B3's scanning flow so the next tag found gets `esl_id = synced_count` (already correct in the existing `on_device_found` logic). Also reschedules `rescan_work` after the successful re-scan start, mirroring `appl_esl_ap_auto_start()`'s own scheduling, so B3/B4's periodic scan-toggle retry keeps working identically on every loop iteration, not just the first. Awaiting user hardware validation: set `CONFIG_ESL_AP_AUTO_SYNC_COUNT=2`, place two tags in range, run `esl_ap auto` once, confirm disconnect → rescan → sync tag 2 → "2/2 tags synced" and the loop stops with no third scan.
- 2026-08-19: B10 bug report + fix — user's first-tag log showed `appl_esl_ap_disconnect_esl()` failing with `0x0105` right after the sync-complete log. Investigated the EtherMind header again rather than guessing: `0x0105` = `BT_ESL_AP_INVALID_STATE` (`0x0005 | BT_ESL_AP_ERR_ID`, `BT_esl_api.h:978`). The log order explained it: `on_disconnected` (state 8) fires *before* `on_synchronised` (state 8) for the same tag — the tag drops its ACL connection on its own once PAwR sync takes over, ahead of the sync-complete event arriving. So by the time B10's new disconnect call runs, the tag is already gone; the module correctly reports there's no connection left to disconnect. Fix (still only in `appl_esl_ap_auto.c`): `appl_esl_ap_auto_on_synchronised()` now treats `BT_ESL_AP_INVALID_STATE` from `appl_esl_ap_disconnect_esl()` as "already disconnected, continue" (logs via `APPL_ESL_TRC`, falls through to `AUTO_SCANNING`/rescan as normal) instead of a fatal error; any other non-success code still reverts to `AUTO_IDLE` as before. B10 stays `[~]` — awaiting user re-validation that the loop now proceeds past tag 1 cleanly to "2/2 tags synced".
- 2026-08-19: B10 re-validated — user confirmed "that works" after the `BT_ESL_AP_INVALID_STATE` fix; the loop now proceeds cleanly through disconnect → rescan → tag 2. B10 marked `[x]`.
- 2026-08-19: B10b implemented (unplanned, user-requested) — user asked to control the tag count via an argument to `esl_ap auto` rather than only the Kconfig default. `appl_esl_ap_auto_start()` signature changed to take `UCHAR count` (`appl_esl_ap_auto.c`/`.h`): `0` keeps using `CONFIG_ESL_AP_AUTO_SYNC_COUNT`, any other value (validated 1-32) overrides `target_count` for that run. `cli_esl_ap.c`'s `auto` shell command changed from `SHELL_CMD` to `SHELL_CMD_ARG(..., 1, 1)` (one optional arg) and `cmd_ap_auto()` now parses `argv[1]` with `strtol(argv[1], NULL, 10)` when `argc == 2` (decimal, matching this file's existing convention for indices/counts vs. hex for addresses), rejecting out-of-range input with `-ENOEXEC` before automation starts. This deliberately touches `cli_esl_ap.c` in addition to `appl_esl_ap_auto.c` — a seam exception, but the same one B11 already plans to take, since the CLI argument has to be parsed at the point the shell command is registered. Awaiting user hardware validation: `esl_ap auto` (no arg) still defaults correctly; `esl_ap auto 2` with two tags in range reaches "2/2 tags synced"; `esl_ap auto 0` and `esl_ap auto 99` are both rejected without starting automation.
- 2026-08-19: B10b re-validated — user confirmed "that worked" on hardware for the tag-count argument: `esl_ap auto` (no arg) still defaults correctly, `esl_ap auto 2` reached "2/2 tags synced", and the invalid-count rejections behaved as expected. B10b marked `[x]`.
- 2026-08-19: B11 implemented — the `esl_ap auto_stop` command (`cmd_ap_auto_stop` → `appl_esl_ap_auto_stop()`) turned out to already exist from B1's scaffolding and already unconditionally force-resets `auto_state` to `AUTO_IDLE` and cancels both `rescan_work`/`sync_delay_work`, so no changes were needed there. The remaining scope was the re-entrancy guard: `appl_esl_ap_auto_start()` in `appl_esl_ap_auto.c`/`.h` changed from `void` to `API_RESULT` — at entry, if `auto_state` is neither `AUTO_IDLE` nor `AUTO_DONE`, it now logs via `APPL_ESL_ERR` and returns `BT_ESL_AP_BUSY` immediately, leaving any in-progress run completely untouched (no state reset, no scan toggle); otherwise behaves as before and returns `BT_ESL_AP_SUCCESS` (or the stack's failure code on a scan-start failure, same revert-to-`AUTO_IDLE` pattern as B2-B10). `cmd_ap_auto()` in `cli_esl_ap.c` now checks this return value: `BT_ESL_AP_BUSY` prints "ESL AP automation already running. Use 'esl_ap auto_stop' first." and returns `-ENOEXEC`; any other non-success prints a generic failure message with the code and also returns `-ENOEXEC`; success path unchanged. No new Kconfig retry/timeout options were added, consistent with the plan's guidance to lean on the existing stack-level ones. Awaiting user hardware validation: start `esl_ap auto`, run `esl_ap auto` again mid-sequence and confirm it's rejected with the "already running" message while the original run continues undisturbed; run `esl_ap auto_stop` mid-sequence and confirm clean return to idle with manual `esl_ap` commands still working; confirm a fresh `esl_ap auto` after `auto_stop` starts normally.
- 2026-08-19: B11 re-validated — user confirmed "it's working!" on hardware for the re-entrancy guard: a second `esl_ap auto` mid-sequence is rejected without disturbing the run in progress, and `esl_ap auto_stop` cleanly returns to idle with manual commands still functional afterward. B11 marked `[x]`. **This completes Track B (B1-B11) end-to-end.**
- 2026-08-18: C1 implemented — after investigation via a real generated `.config` confirmed MCUboot and `USE_DT_CODE_PARTITION` are both off in this project (not just unused), the user rejected the plan's original NVS/flash-partition design in favor of a simpler RAM-only ring-buffer log, sharing the same public API so a flash-backed version can be dropped in later as a pure `.c`-file swap. New `src/appl/appl_esl_tag_log.c`/`.h` (RAM ring buffers for pings/PAwR messages/images, capacities 20/20/10); `tag_cli/Kconfig`'s `ESL_TAG_FLASH_LOG` renamed to `ESL_TAG_LOG` (dropped `select NVS`); `appl_esl_tag_log.c` wired into `tag_cli/CMakeLists.txt` conditionally; temporary `esl_tag log_test write`/`dump` debug subcommands added to `cli_esl_tag.c`/`.h` (guarded by `CONFIG_ESL_TAG_LOG`, nested inside A5's shell guard) — moving this CMake/CLI wiring from C2 into C1 per the plan's file-attribution correction, since C1 can't be self-tested without them. Internal log dump uses `APPL_ESL_INF` rather than `CONSOLE_OUT` as originally sketched, since the module has no `shell` variable in scope (not a shell-command handler) — `CONSOLE_OUT` is still used for the new commands' own direct output in `cli_esl_tag.c`, which does have `shell` in scope. `appl_esl_tag.c` and all `prj*.conf` files untouched (C2's job). Verified via two real `west build`s for `lp_em_cc2340r53`: flag forced on links cleanly (FLASH 61.34%/RAM 75.23%); default build (flag unset) also links cleanly (FLASH 61.16%/RAM 73.49%) with the log module and `log_test` subcommand fully excluded. Awaiting user hardware validation (flash the flag-on build, exercise `esl_tag log_test write`/`dump`, confirm plausible entries) before starting C2.
- 2026-08-19: C1 revised (user-requested, before hardware validation) — pings no longer store individual entries, just a running count. `appl_esl_tag_log.c`: removed `APPL_ESL_LOG_PING_ENTRY`/`APPL_ESL_LOG_PING_MAX`/the ping ring array and its next-index; `appl_esl_log_ping_count` is now a plain `UINT32` counter incremented with no cap (was previously the ring's occupancy count, capped at 20). `appl_esl_log_ping()` signature changed from `(BT_ESL_BD_ADDR *addr)` to `(void)` in `appl_esl_tag_log.h` (both the real prototype and the no-op stub) since the address was only ever used to populate the now-removed per-entry struct. `appl_esl_log_dump_all()` no longer loops/prints individual ping entries — the summary header line (`"%d pings, %d PAwR msgs, %d images"`) already reported the count and still does. `cli_esl_tag.c`'s `cmd_log_test_write()` updated to call `appl_esl_log_ping()` with no argument and dropped its now-unused `dummy_addr` local. PAwR and image logging untouched (still ring buffers, capacities 20/10). Re-verified with a fresh `west build` (`lp_em_cc2340r53`, `-DCONFIG_ESL_TAG_LOG=y`) — links cleanly. Still pre-hardware-validation; C1 remains `[x]` (implemented) with hardware validation still pending for the module as a whole.
- 2026-08-19: **Strategy change** — user discarded the entire ring-buffer log design (Track C1's PAwR-message/image rings, Track C2's plan to log every PAwR command callback) before C2 was ever implemented, in favor of a much simpler design: tags track ping-count + time-since-last-ping + last-image-received, printed via `esl_tag log`; the AP tracks the same two things **per tag** via a new device table, printed via `esl_ap log`. Split into two independent, file-disjoint tracks so they could be built in parallel: **Track C2 (redefined) — Tag Logging** and **Track D1 — AP Logging**. Full plan approved and recorded in `i-want-to-make-eager-beacon.md`.
- 2026-08-19: Track C2 (redefined) implemented — `appl_esl_tag_log.c`/`.h` rewritten from the old ring-buffer design down to a plain ping-count/last-ping-time/last-image struct; `appl_esl_log_ping()`/`appl_esl_log_image_received()` call sites wired into `appl_esl_tag_ping_cmd_cb` and `appl_esl_tag_ots_image_written_cb` in `appl_esl_tag.c`; old `log_test write`/`log_test dump` debug subcommands removed from `cli_esl_tag.c`/`.h` and replaced with a real `esl_tag log` command printing the 3-line format. `tag_cli/prj.conf`/`prj_debug.conf` already had `CONFIG_ESL_TAG_LOG=y` from the prior (now-superseded) C1 work, so no config change was needed; `tag_cli/Kconfig`'s `ESL_TAG_LOG` description string updated to match the new design. Code believed complete; **not yet build-verified** in this session — awaiting a `west build` run for `tag_cli` before hardware validation.
- 2026-08-19: Track D1 implemented — new `src/appl/appl_esl_ap_log.c`/`.h` module with a per-tag device table (`appl_esl_ap_log_table[APPL_ESL_MAX_NO_OF_TAGS_PER_GROUP]`, keyed by `(group_id, esl_id)` via `appl_esl_ap_log_find_or_alloc()`); hooked into `appl_esl_ap.c` (`appl_esl_ap_log_init()` call added to `appl_esl_ap_init()`, log calls added as new `else` branches in `appl_esl_ap_send_ping`/`appl_esl_ap_send_display_image`/`appl_esl_ap_send_display_timed_image` right before their `return retval;`); new `esl_ap log` command added to `cli_esl_ap.c`/`.h` (mirrors the tag-side `cmd_log` exactly); new Kconfig symbol `ESL_AP_LOG` added to `ap_cli/Kconfig`, conditional `target_sources` added to `ap_cli/CMakeLists.txt`, `CONFIG_ESL_AP_LOG=y` added to both `ap_cli/prj.conf` and `ap_cli/prj_debug.conf`. Bug found and fixed during implementation (before any build attempt): `appl_esl_ap_log_find_or_alloc()` initially used an `INT16 free_index = -1` sentinel — a signed type not used anywhere else in this codebase and very likely undefined in this SDK; replaced with the codebase's established `UCHAR`-boolean-flag idiom (`UCHAR free_index` + `UCHAR have_free_index`), mirroring `appl_esl_ap_get_esl_tag_from_bd_address`'s `UCHAR found` pattern already in `appl_esl_ap.c`. Code believed complete; **not yet build-verified** in this session — awaiting a `west build` run for `ap_cli` before hardware validation.
- 2026-08-19: Build verification for Track C2 (redefined) and Track D1 — found and fixed a real compile-blocking bug in both new dump-all functions, present since implementation (traces back to the plan document `i-want-to-make-eager-beacon.md` itself sketching `CONSOLE_OUT` for these functions, despite the plan's own C1 context section correctly noting that internal, non-shell-command functions can't use it). `CONSOLE_OUT` (`EM_platform.h`) expands to `shell_print(shell, ...)` and only works inside an actual `SHELL_CMD` handler with a `shell` variable in scope; `appl_esl_log_dump_all()` (`appl_esl_tag_log.c`) and `appl_esl_ap_log_dump_all()` (`appl_esl_ap_log.c`) are plain library functions with no such variable, so a `west build -b lp_em_cc2340r53 -p always -d build_tag_cli_log zephyr/samples/bluetooth/esl/tag_cli` run failed with `error: 'shell' undeclared`. Fix: replaced all 5 `CONSOLE_OUT` calls in `appl_esl_log_dump_all()` and all 6 in `appl_esl_ap_log_dump_all()` with `APPL_ESL_INF` (printk-based, no scope dependency) — the same pattern the original (superseded) C1 module already used correctly for this exact reason. Re-ran both builds clean: `tag_cli` (FLASH 61.22%/RAM 73.51%) and `ap_cli` (FLASH 66.85%/RAM 92.93%), both on `lp_em_cc2340r53`. Both `esl_tag log` and `esl_ap log` now build-clean; hardware validation of both remains the only outstanding item for Track C2 (redefined) and Track D1.
- 2026-08-19: Hardware bug report + fix — user pinged a tag, checked the log ~12 (real) seconds later, and `esl_tag log` printed `Time since last ping: 12000s`. Root cause: `BT_esl_get_current_time_pl()` (`BT_esl_pl.c:4549-4563`) returns milliseconds per its own doxygen, not seconds — the plan's design note that it returns "seconds since power-cycle" was based on the pre-existing `esl_tag get_time` command's output label (`cli_esl_tag.c:134`, `"Current Time: 0x%08X seconds since power-cycle"`), which is itself mislabeled (that command never converts the value at all). Both new log modules stored/diffed raw millisecond timestamps and printed the result with an `s` suffix as if it were already seconds. Fix: in `appl_esl_tag_log.c`'s `appl_esl_log_dump_all()` and `appl_esl_ap_log.c`'s `appl_esl_ap_log_dump_all()`, divide the `BT_esl_get_current_time_pl() - last_ping_time` delta by `1000U` before printing (`Time since last ping: %ds`). Ping-count and last-image logic untouched — only the elapsed-time display was wrong. Re-verified with fresh `west build`s for both `tag_cli` and `ap_cli` (`lp_em_cc2340r53`) — both link cleanly, sizes unchanged. Awaiting user hardware re-validation that the printed elapsed time now roughly matches real elapsed seconds on both `esl_tag log` and `esl_ap log`.
- 2026-08-19: Time fix re-validated — user confirmed "it's working!" on hardware. **This completes hardware validation for Track C2 (redefined) and Track D1.**
- 2026-08-19: User requested disabling `[ESL PL]` console logging while keeping application logging (`esl_tag log`/`esl_ap log`, `esl_tag get_time`, and all other existing CLI output). Traced it to `BT_esl_pl.h:116-172`: `ESL_PL_ERR`/`ESL_PL_TRC`/`ESL_PL_INF` route through `CONSOLE_ERR`/`CONSOLE_TRC`/`CONSOLE_INF` (printk) unconditionally whenever `CONFIG_ESL_PL_DEBUG_TO_CONSOLE` is set — bypassing the module's own `ESL_PL_NO_DEBUG`/`ESL_PL_DEBUG` no-op gating entirely. That flag was `=y` in all four config files (`tag_cli/prj.conf`, `tag_cli/prj_debug.conf`, `ap_cli/prj.conf`, `ap_cli/prj_debug.conf`) from earlier bench-debug setup; its Kconfig default is `n`. Flipped all four to `CONFIG_ESL_PL_DEBUG_TO_CONSOLE=n`, which reverts `ESL_PL_*` to `EM_debug_null` (true no-ops) — this only affects the ESL platform-layer macros, not `APPL_ESL_*`/`CONSOLE_OUT` (application-layer logging, used by everything in `src/appl/`, including both new log modules and their CLI commands), so application logging is untouched. Re-verified with fresh `west build`s for both `tag_cli` (FLASH 61.22%→59.51%) and `ap_cli` (FLASH 66.85%→64.04%) on `lp_em_cc2340r53` — both link cleanly, and the FLASH drop confirms the `[ESL PL]` debug strings are no longer compiled in. Awaiting user hardware confirmation that `[ESL PL]` lines are gone from the console while application output (including `esl_tag log`/`esl_ap log`) is unaffected.
