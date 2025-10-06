"""Application setup and signal handling utilities."""

import sys
import signal
from PyQt5.QtCore import QTimer


# Global variables for application state
app = None
windows = []


def clean_exit():
    """Safely exit the application, closing all windows."""
    print("\nViewer terminated by user.")

    # Close all windows
    for window in windows:
        window.close()

    # Cleanup application
    if app:
        app.quit()

    # Final exit
    sys.exit(0)


def setup_signal_handlers():
    """Set up signal handlers for graceful shutdown (e.g., Ctrl+C)."""
    def signal_handler(sig, frame):
        # Exit safely within Qt event loop
        QTimer.singleShot(0, clean_exit)

    # Catch Ctrl+C signal
    signal.signal(signal.SIGINT, signal_handler)
