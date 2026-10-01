"""Tags / Ping panel tests (group filter). Needs PyQt6; runs headless."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
    from esl_gui.controller import EslApController
    from esl_gui.panels.ping import PingPanel
except ImportError:  # pragma: no cover
    PingPanel = None


@unittest.skipIf(PingPanel is None, "PyQt6 not installed")
class GroupFilterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.c = EslApController()
        self.sent = []
        self.c.link.is_open = lambda: True
        self.c.link.send_line = lambda text: self.sent.append(text) or True
        self.panel = PingPanel(self.c)
        for group, esl in [(0, 0), (0, 1), (1, 0), (1, 1), (1, 2)]:
            self.c._on_line(f"[APPL]: ESL tag [{group} : {esl}] synchronized (status 0x0000)")

    def select_group(self, group):
        self.panel.group_filter.setCurrentIndex(self.panel.group_filter.findData(group))

    def visible(self):
        proxy = self.panel.proxy
        return [proxy.index(r, 0).data() for r in range(proxy.rowCount())]

    def test_dropdown_lists_groups_with_counts(self):
        items = [self.panel.group_filter.itemText(i)
                 for i in range(self.panel.group_filter.count())]
        self.assertEqual(items, ["All groups (5 tags)", "Group 0 (2 tags)", "Group 1 (3 tags)"])

    def test_filter_shows_only_selected_group(self):
        self.select_group(1)
        self.assertEqual(self.visible(), ["1:0", "1:1", "1:2"])
        self.assertEqual(self.panel.group.value(), 1)  # manual ping pre-filled
        self.select_group(None)
        self.assertEqual(len(self.visible()), 5)

    def test_selection_kept_when_tags_added(self):
        self.select_group(1)
        self.c._on_line("[APPL]: ESL tag [1 : 3] synchronized (status 0x0000)")
        self.c._on_line("[APPL]: ESL tag [2 : 0] synchronized (status 0x0000)")
        self.assertEqual(self.panel.group_filter.currentData(), 1)
        self.assertEqual(self.visible(), ["1:0", "1:1", "1:2", "1:3"])

    def test_ping_from_filtered_view_hits_right_tag(self):
        self.select_group(1)
        self.panel._ping_index(self.panel.proxy.index(0, 0))  # first visible row = 1:0
        self.assertEqual(self.sent, ["esl_ap ping 1 0"])

    def test_reboot_resets_to_all(self):
        self.select_group(1)
        self.c._on_line("*** Booting Zephyr OS build v3.7.0 ***")
        self.assertIsNone(self.panel.group_filter.currentData())
        self.assertEqual(self.panel.group_filter.count(), 1)


if __name__ == "__main__":
    unittest.main()
