import sys
import os

# ── Python 3.15 lazy-import workaround ──────────────────────────────────────
# In Python 3.15 the stdlib uses lazy loaders. When mediapipe's serial_dispatcher
# (or any QThread body) first imports `concurrent.futures`, it may receive a lazy
# proxy whose sub-attributes haven't been materialised yet.  Force the real
# concrete classes into the module dict *before* any QThread or mediapipe code runs.
import concurrent.futures
from concurrent.futures.thread import ThreadPoolExecutor as _TPE
from concurrent.futures.process import ProcessPoolExecutor as _PPE
concurrent.futures.ThreadPoolExecutor = _TPE
concurrent.futures.ProcessPoolExecutor = _PPE

# Ensure the posekeys package root is on the path when run directly
sys.path.insert(0, os.path.dirname(__file__))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from app.main_window import MainWindow

DARK_STYLE = """
QWidget { background:#1e1e2e; color:#cdd6f4; font-size:13px; }
QMainWindow { background:#1e1e2e; }
"""


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("PoseKeys")
    app.setStyleSheet(DARK_STYLE)
    icon_path = os.path.join(os.path.dirname(__file__), "assets", "icon.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
