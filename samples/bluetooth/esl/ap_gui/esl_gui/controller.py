"""Glue between the serial link, the line parser and the GUI state.

Panels only ever talk to EslApController: they call its methods to send
commands and listen to its signals / its ``tags`` model for results. They
never touch the serial port or parse console text themselves.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from functools import singledispatchmethod

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from . import commands
from . import parser as ev
from .serial_link import SerialLink
from .tag_model import TagTableModel

# A ping goes out on the next PAwR subevent and the answer comes back in a
# response slot; anything slower than this is reported as "no response".
PING_TIMEOUT_S = 10.0


@dataclass
class PendingPing:
    group: int
    esl: int
    sent_at: float


class EslApController(QObject):
    connection_changed = pyqtSignal(bool)
    line_received = pyqtSignal(str)       # every console line, for the console panel
    command_sent = pyqtSignal(str)
    notice = pyqtSignal(str)              # short status-bar message

    auto_running_changed = pyqtSignal(bool)
    auto_status_changed = pyqtSignal(str)
    auto_progress = pyqtSignal(int, int)  # synced, target
    auto_current_tag = pyqtSignal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.link = SerialLink(self)
        self.parser = ev.LineParser()
        self.tags = TagTableModel(self)

        self.auto_running = False
        self._auto_requested = 0
        self._pending_pings: deque[PendingPing] = deque()
        # Tag the most recent response belongs to; BASIC STATE / ERROR lines
        # that follow a response are attributed to it.
        self._last_responder: tuple[int, int] | None = None

        self.link.line_received.connect(self._on_line)
        self.link.connection_changed.connect(self.connection_changed)
        self.link.error.connect(self.notice)

        self._ping_timer = QTimer(self)
        self._ping_timer.timeout.connect(self._expire_pings)
        self._ping_timer.start(500)

    # ---------------------------------------------------------- Connection
    def connect_port(self, port: str, baud: int) -> bool:
        ok = self.link.open(port, baud)
        if ok:
            self.notice.emit(f"Connected to {port} @ {baud}")
        return ok

    def disconnect_port(self) -> None:
        self.link.close()
        self.notice.emit("Disconnected")

    def is_connected(self) -> bool:
        return self.link.is_open()

    # ---------------------------------------------------------- Commands
    def send_command(self, text: str) -> None:
        if self.link.send_line(text):
            self.command_sent.emit(text)
        else:
            self.notice.emit("Not connected")

    def start_auto(self, count: int) -> None:
        self._auto_requested = count
        self.send_command(commands.auto(count))

    def stop_auto(self) -> None:
        if not self.is_connected():
            self.notice.emit("Not connected")
            return
        self.send_command(commands.auto_stop())
        if self.auto_running:
            self.auto_status_changed.emit("Stop requested…")
        else:
            # Nothing we know of is running, so no AutoStopped/AutoFinished
            # line may follow; unlock the controls now.
            self.auto_status_changed.emit("Stopped")

    def ping(self, group: int, esl: int) -> None:
        if not self.is_connected():
            self.notice.emit("Not connected")
            return
        tag = self.tags.ensure(group, esl)
        self.tags.update(group, esl, pings_sent=tag.pings_sent + 1,
                         last_ping="waiting…", latency_s=None)
        self._pending_pings.append(PendingPing(group, esl, time.monotonic()))
        self.send_command(commands.ping(group, esl))

    # ---------------------------------------------------------- Input
    def _on_line(self, line: str) -> None:
        self.line_received.emit(line)
        event = self.parser.parse(line)
        if event is not None:
            self._handle(event)

    @singledispatchmethod
    def _handle(self, event: ev.Event) -> None:
        """Events without a handler below are ignored."""

    @_handle.register
    def _(self, event: ev.Rebooted) -> None:
        self.tags.clear()
        self._pending_pings.clear()
        self._last_responder = None
        self._set_auto_running(False)
        self.auto_status_changed.emit("Idle (AP rebooted)")
        self.auto_current_tag.emit("")
        self.notice.emit("AP rebooted - tag list cleared")

    @_handle.register
    def _(self, event: ev.TagSynced) -> None:
        if event.status == 0:
            self.tags.update(event.group, event.esl, synced_at=datetime.now())
            self.notice.emit(f"Tag {event.group}:{event.esl} synced")

    # --- automation
    @_handle.register
    def _(self, event: ev.AutoStarted) -> None:
        self._set_auto_running(True)
        self.auto_status_changed.emit("Scanning for tags…")
        self.auto_progress.emit(0, self._auto_requested)

    @_handle.register
    def _(self, event: ev.AutoBusy) -> None:
        self.notice.emit("Automation already running - stop it first")

    @_handle.register
    def _(self, event: ev.AutoTagInProgress) -> None:
        # Also catches runs started before the GUI attached or from the console.
        self._set_auto_running(True)
        self.auto_status_changed.emit("Syncing tag…")
        self.auto_current_tag.emit(f"{event.group}:{event.esl}")

    @_handle.register
    def _(self, event: ev.AutoProgress) -> None:
        self.auto_progress.emit(event.synced, event.target)
        if event.synced < event.target:
            self._set_auto_running(True)
            self.auto_status_changed.emit("Scanning for tags…")
            self.auto_current_tag.emit("")

    @_handle.register
    def _(self, event: ev.AutoFinished) -> None:
        self._set_auto_running(False)
        self.auto_status_changed.emit("Done")
        self.auto_current_tag.emit("")

    @_handle.register
    def _(self, event: ev.AutoStopping) -> None:
        self.auto_status_changed.emit("Stopping after current tag…")

    @_handle.register
    def _(self, event: ev.AutoStopped) -> None:
        self._set_auto_running(False)
        self.auto_status_changed.emit("Stopped")
        self.auto_current_tag.emit("")

    @_handle.register
    def _(self, event: ev.AutoError) -> None:
        prefix = "Aborted" if self.auto_running else "Error"
        self._set_auto_running(False)
        self.auto_status_changed.emit(f"{prefix}: {event.message}")
        self.auto_current_tag.emit("")

    # --- ping responses
    @_handle.register
    def _(self, event: ev.TagResponse) -> None:
        pending = self._take_pending(event.group, event.esl)
        if pending is None:
            # Response to some other command (or a ping sent from a terminal).
            self._last_responder = (event.group, event.esl) if event.esl is not None else None
            return
        self._last_responder = (pending.group, pending.esl)
        self.tags.update(pending.group, pending.esl, last_ping="OK",
                         latency_s=time.monotonic() - pending.sent_at)

    @_handle.register
    def _(self, event: ev.BasicStateFlag) -> None:
        if self._last_responder is not None:
            self.tags.set_flag(*self._last_responder, event.name, event.on)

    @_handle.register
    def _(self, event: ev.ResponseError) -> None:
        if self._last_responder is not None:
            self.tags.update(*self._last_responder, last_ping=f"Error 0x{event.code:02X}")

    @_handle.register
    def _(self, event: ev.PingSendFailed) -> None:
        # The CLI and the app layer can both report the same failure; only
        # the first one finds a pending ping to fail.
        if self._pending_pings:
            pending = self._pending_pings.pop()
            self.tags.update(pending.group, pending.esl,
                             last_ping=f"Send failed 0x{event.code:04X}")

    # ---------------------------------------------------------- Helpers
    def _take_pending(self, group: int, esl: int | None) -> PendingPing | None:
        """Pop the oldest pending ping matching the response.

        Synchronized-state responses only carry the group, so pings to the
        same group are matched first-in first-out.
        """
        for pending in self._pending_pings:
            if pending.group == group and (esl is None or pending.esl == esl):
                self._pending_pings.remove(pending)
                return pending
        return None

    def _expire_pings(self) -> None:
        now = time.monotonic()
        while self._pending_pings and now - self._pending_pings[0].sent_at > PING_TIMEOUT_S:
            pending = self._pending_pings.popleft()
            self.tags.update(pending.group, pending.esl, last_ping="No response")

    def _set_auto_running(self, running: bool) -> None:
        if running != self.auto_running:
            self.auto_running = running
            self.auto_running_changed.emit(running)
