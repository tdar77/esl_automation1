"""Parser tests; no Qt needed. Run from ap_gui/: python3 -m unittest"""

import unittest

from esl_gui import commands
from esl_gui import parser as ev


def parse(line: str):
    return ev.LineParser().parse(ev.clean_line(line))


class CleanLineTest(unittest.TestCase):
    def test_strips_vt100_and_cr(self):
        self.assertEqual(ev.clean_line("\x1b[1;32muart:~$ \x1b[mesl_ap log\r"),
                         "uart:~$ esl_ap log")


class ParserTest(unittest.TestCase):
    def test_boot_banner(self):
        self.assertEqual(parse("*** Booting Zephyr OS build v3.7.0 ***"), ev.Rebooted())

    def test_tag_synced(self):
        self.assertEqual(parse("[APPL]: ESL tag [1 : 15] synchronized (status 0x0000)"),
                         ev.TagSynced(1, 15, 0))
        self.assertEqual(parse("[APPL]: ESL tag [0 : 2] synchronized (status 0x0101)"),
                         ev.TagSynced(0, 2, 0x101))

    def test_printk_after_prompt(self):
        self.assertEqual(parse("uart:~$ [APPL_AUTO]: 2/4 tags synced"),
                         ev.AutoProgress(2, 4))

    def test_auto_lifecycle(self):
        self.assertEqual(parse("ESL AP automation started"), ev.AutoStarted())
        self.assertEqual(parse("[APPL_AUTO]: ESL tag [0:3] added, connecting"),
                         ev.AutoTagInProgress(0, 3))
        self.assertEqual(parse("[APPL_AUTO]: batch finished - synced tags retained"),
                         ev.AutoFinished())
        self.assertEqual(parse("[APPL_AUTO]: stop requested - finishing current tag"),
                         ev.AutoStopping())
        self.assertEqual(parse("[APPL_AUTO]: esl_ap auto_stop - state reset to IDLE"),
                         ev.AutoStopped())

    def test_auto_busy(self):
        self.assertEqual(parse("ESL AP automation busy. Use 'esl_ap auto_stop' and wait "
                               "for the current tag to finish."), ev.AutoBusy())
        self.assertEqual(parse("[APPL_AUTO]: esl_ap auto rejected - automation already "
                               "running (state 3)"), ev.AutoBusy())

    def test_auto_errors(self):
        self.assertIsInstance(parse("[APPL_AUTO]: ESL tag [0:1] connect failed (status 62)"),
                              ev.AutoError)
        self.assertIsInstance(parse("[APPL_AUTO]: tag disconnected before sync"), ev.AutoError)
        self.assertEqual(parse("Failed to start ESL AP automation (0x0103)"),
                         ev.AutoError("Failed to start ESL AP automation (0x0103)", generic=True))

    def test_group_errors(self):
        self.assertEqual(parse("Invalid group. Use 0-3."), ev.AutoError("Invalid group. Use 0-3."))
        self.assertEqual(
            parse("Invalid group or too many tags for the free response slots in that group."),
            ev.AutoError("Invalid group or too many tags for the free response slots in that group.",
                         generic=True))
        self.assertEqual(parse("[APPL_AUTO]: Invalid group 5 (valid groups: 0-3)"),
                         ev.AutoError("Invalid group 5 (valid groups: 0-3)"))
        self.assertIsInstance(parse("[APPL_AUTO]: Cannot add 5 tags to group 1: only 3 of 16 "
                                    "response slots free"), ev.AutoError)
        self.assertIsInstance(parse("[APPL_AUTO]: multi-group operation requires 16 entries "
                                    "per group"), ev.AutoError)

    def test_auto_requested(self):
        self.assertEqual(parse("[APPL_AUTO]: esl_ap auto requested (target 4 tags, next [1:3]) "
                               "- init + scan"), ev.AutoRequested(4, 1, 3))

    def test_auto_noise_ignored(self):
        self.assertIsNone(parse("[APPL_AUTO]: on_connected hook (tag [0:1], status 0, state 4)"))
        self.assertIsNone(parse("[APPL_AUTO]: failed tag [0:1] removed; address available "
                                "for retry"))

    def test_responses(self):
        self.assertEqual(parse("[APPL]: Group ID: 0, Response Slot: 0, Status: 1"),
                         ev.TagResponse(0, None))
        self.assertEqual(parse("[APPL]: ESL tag [2 : 5] response IND"), ev.TagResponse(2, 5))
        self.assertEqual(parse("\t\tSynchronised:ON"), ev.BasicStateFlag("Synchronised", True))
        self.assertEqual(parse("\t\tPending display update:OFF"),
                         ev.BasicStateFlag("Pending display update", False))
        self.assertEqual(parse("\tERROR {Error code:0x0B}"), ev.ResponseError(0x0B))

    def test_ping_send_failed(self):
        self.assertEqual(parse("Failed to ping ESL: 0x0106"), ev.PingSendFailed(0x106))


class CommandsTest(unittest.TestCase):
    def test_ping_ids_are_hex(self):
        self.assertEqual(commands.ping(1, 15), "esl_ap ping 1 f")
        self.assertEqual(commands.ping(20, 0), "esl_ap ping 14 0")

    def test_ranges(self):
        self.assertEqual(commands.auto(4), "esl_ap auto 4 0")
        self.assertEqual(commands.auto(16, 12), "esl_ap auto 16 12")  # decimal, unlike ping
        with self.assertRaises(ValueError):
            commands.auto(0)
        with self.assertRaises(ValueError):
            commands.ping(0, 0xFF)


if __name__ == "__main__":
    unittest.main()
