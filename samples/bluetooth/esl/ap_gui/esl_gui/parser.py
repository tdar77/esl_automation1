"""Turn ESL AP console lines into typed events.

This module is deliberately free of any Qt import so it can be unit tested
with plain ``python3 -m unittest``. Every pattern here mirrors a specific
printk/shell_print in the firmware (``src/appl/*.c``); if a firmware log
message changes, the matching rule below must change with it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

# Zephyr's shell emits VT100 sequences (colours, cursor moves) around output.
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def clean_line(raw: str) -> str:
    """Strip VT100 escapes and carriage returns from one console line."""
    return ANSI_ESCAPE.sub("", raw).replace("\r", "")


# --------------------------------------------------------------------- Events
@dataclass(frozen=True)
class Event:
    """Base class for everything the parser can emit."""


@dataclass(frozen=True)
class Rebooted(Event):
    """AP printed the Zephyr boot banner: all AP-side state is gone."""


@dataclass(frozen=True)
class TagSynced(Event):
    """appl_synchronised_ind_cb(): a tag finished (or failed) PAwR sync."""
    group: int
    esl: int
    status: int


@dataclass(frozen=True)
class AutoRequested(Event):
    """'[APPL_AUTO]: esl_ap auto requested (target n tags, next [g:e])'.

    Printed just before 'automation started', also for runs typed in the console.
    """
    target: int
    group: int
    next_esl: int


@dataclass(frozen=True)
class AutoStarted(Event):
    """cmd_ap_auto(): 'ESL AP automation started'."""


@dataclass(frozen=True)
class AutoBusy(Event):
    """cmd_ap_auto(): automation is already running."""


@dataclass(frozen=True)
class AutoTagInProgress(Event):
    """A tag was found and is being walked through connect -> sync."""
    group: int
    esl: int


@dataclass(frozen=True)
class AutoProgress(Event):
    """'[APPL_AUTO]: k/n tags synced'."""
    synced: int
    target: int


@dataclass(frozen=True)
class AutoFinished(Event):
    """Batch reached its target (or a requested stop completed)."""


@dataclass(frozen=True)
class AutoStopping(Event):
    """auto_stop was requested while a tag was mid-flight."""


@dataclass(frozen=True)
class AutoStopped(Event):
    """auto_stop reset the state machine to IDLE."""


@dataclass(frozen=True)
class AutoError(Event):
    """Automation failed to start or aborted (state machine is now IDLE).

    ``generic`` marks CLI summary lines that follow a more specific
    [APPL_AUTO] error, so the specific reason can be kept on screen.
    """
    message: str
    generic: bool = False


@dataclass(frozen=True)
class TagResponse(Event):
    """A tag answered a command (e.g. ping).

    In the synchronized state the AP only reports the group and response
    slot, so ``esl`` is None and the caller has to correlate the response
    with the command it sent. In the connected state the ESL ID is known.
    """
    group: int
    esl: int | None


@dataclass(frozen=True)
class BasicStateFlag(Event):
    """One flag line of a BASIC STATE response (follows a TagResponse)."""
    name: str
    on: bool


@dataclass(frozen=True)
class ResponseError(Event):
    """ERROR response TLV (follows a TagResponse)."""
    code: int


@dataclass(frozen=True)
class PingSendFailed(Event):
    """The AP could not queue the ping at all."""
    code: int


# ---------------------------------------------------------------------- Rules
Rule = tuple[re.Pattern[str], Callable[[re.Match[str]], Event | None]]

_AUTO_ERROR_HINT = re.compile(r"fail|cannot|invalid|requires|disconnected before",
                              re.IGNORECASE)


def _auto_trace(m: re.Match[str]) -> Event | None:
    """Classify a generic '[APPL_AUTO]: ...' line not matched by an earlier rule."""
    msg = m.group(1).strip()
    if "removed; address available for retry" in msg:
        # Cleanup that follows an error we already reported.
        return None
    if _AUTO_ERROR_HINT.search(msg):
        return AutoError(msg)
    return None


# Order matters: the first matching rule wins. Patterns use re.search because
# printk output can land on the same line as the shell prompt.
RULES: list[Rule] = [
    (re.compile(r"\*\*\* Booting Zephyr"), lambda m: Rebooted()),

    (re.compile(r"\[APPL\]: ESL tag \[(\d+) : (\d+)\] synchronized \(status 0x([0-9A-Fa-f]+)\)"),
     lambda m: TagSynced(int(m[1]), int(m[2]), int(m[3], 16))),

    # --- automation (cli_esl_ap.c / appl_esl_ap_auto.c)
    (re.compile(r"ESL AP automation started"), lambda m: AutoStarted()),
    (re.compile(r"ESL AP automation busy"), lambda m: AutoBusy()),
    (re.compile(r"(Failed to start ESL AP automation \(0x[0-9A-Fa-f]+\))"),
     lambda m: AutoError(m[1], generic=True)),
    (re.compile(r"(Invalid group or too many tags.*)"),
     lambda m: AutoError(m[1].strip(), generic=True)),
    (re.compile(r"(Invalid tag count\..*)"), lambda m: AutoError(m[1].strip())),
    (re.compile(r"(Invalid group\. Use .*)"), lambda m: AutoError(m[1].strip())),
    (re.compile(r"\[APPL_AUTO\]: esl_ap auto rejected"), lambda m: AutoBusy()),
    (re.compile(r"\[APPL_AUTO\]: esl_ap auto requested \(target (\d+) tags, "
                r"next \[(\d+):(\d+)\]\)"),
     lambda m: AutoRequested(int(m[1]), int(m[2]), int(m[3]))),
    (re.compile(r"\[APPL_AUTO\]: ESL tag \[(\d+):(\d+)\] added, connecting"),
     lambda m: AutoTagInProgress(int(m[1]), int(m[2]))),
    (re.compile(r"\[APPL_AUTO\]: (\d+)/(\d+) tags synced"),
     lambda m: AutoProgress(int(m[1]), int(m[2]))),
    (re.compile(r"\[APPL_AUTO\]: batch finished"), lambda m: AutoFinished()),
    (re.compile(r"\[APPL_AUTO\]: stop requested"), lambda m: AutoStopping()),
    (re.compile(r"\[APPL_AUTO\]: esl_ap auto_stop - state reset to IDLE"),
     lambda m: AutoStopped()),
    (re.compile(r"\[APPL_AUTO\]: (.*)"), _auto_trace),

    # --- command responses (appl_esl_ap.c)
    (re.compile(r"\[APPL\]: Group ID: (\d+), Response Slot: (\d+), Status: (\d+)"),
     lambda m: TagResponse(int(m[1]), None)),
    (re.compile(r"\[APPL\]: ESL tag \[(\d+) : (\d+)\] response IND"),
     lambda m: TagResponse(int(m[1]), int(m[2]))),
    (re.compile(r"^\s*(Service Needed|Synchronised|LED active|Pending LED update|"
                r"Pending display update):(ON|OFF)\s*$"),
     lambda m: BasicStateFlag(m[1], m[2] == "ON")),
    (re.compile(r"^\s*ERROR \{Error code:0x([0-9A-Fa-f]+)\}"),
     lambda m: ResponseError(int(m[1], 16))),

    # --- ping send failure (cli_esl_ap.c and appl_esl_ap.c both print one)
    (re.compile(r"Failed to ping ESL: 0x([0-9A-Fa-f]+)"),
     lambda m: PingSendFailed(int(m[1], 16))),
    (re.compile(r"ESL AP send ping failed- retval 0x([0-9A-Fa-f]+)"),
     lambda m: PingSendFailed(int(m[1], 16))),
]


class LineParser:
    """Stateless line classifier; kept as a class so rules can be swapped in tests."""

    def __init__(self, rules: list[Rule] | None = None) -> None:
        self.rules = RULES if rules is None else rules

    def parse(self, line: str) -> Event | None:
        for pattern, build in self.rules:
            m = pattern.search(line)
            if m:
                return build(m)
        return None
