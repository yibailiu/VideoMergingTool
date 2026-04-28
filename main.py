import sys

from videomerge.cli import app
from videomerge.gui import launch_gui


if __name__ == "__main__":
    if getattr(sys, "frozen", False) and len(sys.argv) == 1:
        launch_gui()
    else:
        app()
