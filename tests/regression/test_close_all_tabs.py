"""Regression test: closing the last tab must not quit the application.

Bug: `DXFViewerApp.close_tab()` special-cased "only one tab remaining" by
calling `self.close()`, which (with Qt's default `quitOnLastWindowClosed`)
terminated the whole application. Expected behavior: closing the last tab
should return the app to the same blank state as at startup (0 tabs, window
title "DXF Viewer", status bar "Ready", file-dependent actions disabled) —
not exit.

`close_tab()` is also called from `load_dxf()`'s error-recovery path when
`ezdxf.readfile()` fails on a just-created tab; that path shares the fix
(previously, opening an invalid file with no other tabs open would also
have quit the app).

Run:
    python tests/regression/test_close_all_tabs.py
"""

import os
import sys
import tempfile
from unittest.mock import patch

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication

# Module-level reference: PyQt5 garbage-collects the QApplication singleton
# almost immediately if nothing holds a Python reference to it (a bare
# `QApplication.instance() or QApplication([])` expression statement is not
# enough — it crashes with "QWidget: Must construct a QApplication before a
# QWidget" the moment the first QWidget is created afterward).
_app = QApplication.instance() or QApplication([])


def _make_window():
    import ui.main_window as main_window_mod
    window = main_window_mod.DXFViewerApp()

    close_calls = {'count': 0}
    original_close = window.close

    def spy_close():
        close_calls['count'] += 1
        return original_close()

    window.close = spy_close
    return window, close_calls


def _assert_blank_state(window, failures, context):
    if window.tab_widget.count() != 0:
        failures.append(f"{context}: expected 0 tabs, got {window.tab_widget.count()}")
    if window.windowTitle() != "DXF Viewer":
        failures.append(f"{context}: window title not reset, got {window.windowTitle()!r}")
    if window.status_bar.currentMessage() != "Ready":
        failures.append(
            f"{context}: status bar not reset, got {window.status_bar.currentMessage()!r}")
    if window.export_action.isEnabled():
        failures.append(f"{context}: export_action should be disabled with no tabs")
    if window.search_action.isEnabled():
        failures.append(f"{context}: search_action should be disabled with no tabs")


def run_closing_last_of_multiple_tabs():
    """Closing tabs down to zero via tabCloseRequested's handler directly."""
    failures = []
    window, close_calls = _make_window()
    try:
        window.create_new_tab()
        window.create_new_tab()
        if window.tab_widget.count() != 2:
            failures.append(f"expected 2 tabs after create_new_tab x2, got {window.tab_widget.count()}")

        window.close_tab(0)
        if window.tab_widget.count() != 1:
            failures.append(f"expected 1 tab after closing one of two, got {window.tab_widget.count()}")
        if close_calls['count'] != 0:
            failures.append("close() was called while a tab still remained")

        window.close_tab(0)  # closing the last tab
        if close_calls['count'] != 0:
            failures.append(
                f"close() was called when closing the last tab (app would quit): "
                f"{close_calls['count']} call(s)")
        _assert_blank_state(window, failures, "after closing last of multiple tabs")
    finally:
        try:
            window.deleteLater()
        except Exception:
            pass
    return failures


def run_closing_single_tab_from_start():
    """A window that only ever had one tab: closing it must not quit either."""
    failures = []
    window, close_calls = _make_window()
    try:
        window.create_new_tab()
        if window.tab_widget.count() != 1:
            failures.append(f"expected 1 tab after create_new_tab, got {window.tab_widget.count()}")

        window.close_tab(0)
        if close_calls['count'] != 0:
            failures.append(
                f"close() was called when closing the only tab (app would quit): "
                f"{close_calls['count']} call(s)")
        _assert_blank_state(window, failures, "after closing the only tab")
    finally:
        try:
            window.deleteLater()
        except Exception:
            pass
    return failures


def run_load_dxf_failure_with_no_other_tabs():
    """load_dxf()'s error-recovery path (invalid file) shares the fix: opening
    a bad file with zero other tabs open must not quit the app either."""
    failures = []
    window, close_calls = _make_window()
    try:
        with tempfile.NamedTemporaryFile(suffix='.dxf', delete=False, mode='w') as f:
            f.write("NOT A VALID DXF FILE")
            bad_path = f.name

        try:
            with patch('ui.main_window.QMessageBox.critical') as mock_critical:
                window.load_dxf(bad_path)
                if not mock_critical.called:
                    failures.append("QMessageBox.critical was not invoked for an invalid DXF file")
        finally:
            os.unlink(bad_path)

        if close_calls['count'] != 0:
            failures.append(
                f"close() was called after a failed load_dxf() with no other tabs open: "
                f"{close_calls['count']} call(s)")
        _assert_blank_state(window, failures, "after failed load_dxf() with no other tabs")
    finally:
        try:
            window.deleteLater()
        except Exception:
            pass
    return failures


def main():
    all_failures = []
    all_failures.extend(run_closing_last_of_multiple_tabs())
    all_failures.extend(run_closing_single_tab_from_start())
    all_failures.extend(run_load_dxf_failure_with_no_other_tabs())

    if all_failures:
        print(f"FAILED ({len(all_failures)} issue(s)):")
        for msg in all_failures:
            print(f"  - {msg}")
        return 1

    print("OK — closing the last tab returns to blank state instead of quitting the app")
    return 0


if __name__ == '__main__':
    sys.exit(main())
