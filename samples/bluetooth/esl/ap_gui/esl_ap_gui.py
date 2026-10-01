#!/usr/bin/env python3
"""Launch the ESL AP control GUI.

    python3 esl_ap_gui.py [--port COM5 | /dev/ttyACM0] [--baud 115200]
"""

import argparse
import sys

from PyQt6.QtWidgets import QApplication

from esl_gui.controller import EslApController
from esl_gui.main_window import MainWindow


def main() -> int:
    args = argparse.ArgumentParser(description=__doc__,
                                   formatter_class=argparse.RawDescriptionHelpFormatter)
    args.add_argument("--port", help="serial port of the AP board (e.g. COM5); connects on startup")
    args.add_argument("--baud", type=int, default=115200, help="baud rate (default: 115200)")
    opts = args.parse_args()

    app = QApplication(sys.argv)
    controller = EslApController()
    window = MainWindow(controller)
    window.show()
    if opts.port:
        window.connect_to(opts.port, opts.baud)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
