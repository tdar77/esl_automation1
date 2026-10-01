"""Feature panels shown as tabs in the main window.

To add a feature, write a QWidget subclass with a TITLE attribute whose
constructor takes the EslApController, and append it to PANELS.
"""

from .auto_sync import AutoSyncPanel
from .ping import PingPanel

PANELS = [AutoSyncPanel, PingPanel]
