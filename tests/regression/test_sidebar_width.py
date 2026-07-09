"""Regression test: sidebar (layer list + element attribute panel) width.

Feature: at startup, the right-side sidebar (ezdxf CADViewer's
`self.sidebar`, containing the layer list on top and the element attribute /
mouse-position panel below — they share one width since they're stacked in a
vertical QSplitter) should be shrunk to `SIDEBAR_WIDTH_SCALE` (65%) of
ezdxf's own default width (container width / 4), and stay pinned to that
fixed pixel width when the main window is resized — only the CAD drawing
view should grow/shrink.

`PinchZoomCADViewer._shrink_sidebar_width()` (`ui/viewer_widget.py`) can't
run synchronously in `__init__`: at that point the widget hasn't been
embedded into the app's QTabWidget yet (that happens in
`main_window.create_new_tab()`, right after the `DXFTab()` constructor —
which creates the `PinchZoomCADViewer` — returns), so
`self.centralWidget().width()` is still 0 and any `QSplitter.setSizes()`
call would be computed from a meaningless baseline. It's deferred via
`QTimer.singleShot(0, ...)` to the next event-loop iteration, by which time
the widget has its real laid-out size — this test must therefore
`processEvents()` after creating a tab before checking the sidebar width.

Run:
    python tests/regression/test_sidebar_width.py
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication

# Module-level reference: PyQt5 garbage-collects the QApplication singleton
# almost immediately if nothing holds a Python reference to it (see
# test_close_all_tabs.py for the crash this causes).
_app = QApplication.instance() or QApplication([])


def _make_window_with_tab(width=1200, height=800):
    import ui.main_window as main_window_mod
    from ui.viewer_widget import SIDEBAR_WIDTH_SCALE

    window = main_window_mod.DXFViewerApp()
    window.resize(width, height)
    window.show()
    window.create_new_tab()

    # Let the deferred _shrink_sidebar_width() (QTimer.singleShot(0, ...))
    # actually run.
    for _ in range(3):
        _app.processEvents()

    cv = window.get_current_tab().tab_data.cad_viewer
    return window, cv, SIDEBAR_WIDTH_SCALE


def run_startup_width_is_scaled():
    """Sidebar width at startup is SIDEBAR_WIDTH_SCALE of ezdxf's own
    default (container width / 4), not the unscaled ezdxf default."""
    failures = []
    window, cv, scale = _make_window_with_tab()
    try:
        container = cv.centralWidget()
        cad_width, sidebar_width = container.sizes()
        total = cad_width + sidebar_width
        expected_default = total // 4  # ezdxf's own container.setSizes([3w/4, w/4])
        expected_scaled = int(expected_default * scale)

        # Allow +/-2px slack for integer rounding across the two size
        # computations (ezdxf's initial layout vs. our scaling).
        if abs(sidebar_width - expected_scaled) > 2:
            failures.append(
                f"expected sidebar width ~{expected_scaled} ({scale:.0%} of "
                f"ezdxf default {expected_default}), got {sidebar_width}")

        # Sanity: definitely narrower than ezdxf's unscaled default, and not
        # collapsed to ~0.
        if sidebar_width >= expected_default:
            failures.append(
                f"sidebar was not shrunk: {sidebar_width} >= ezdxf default {expected_default}")
        if sidebar_width < 10:
            failures.append(f"sidebar collapsed to near-zero: {sidebar_width}")
    finally:
        try:
            window.deleteLater()
        except Exception:
            pass
    return failures


def run_window_resize_does_not_change_sidebar_width():
    """Enlarging and shrinking the main window must not change the
    sidebar's pixel width — only the CAD view should grow/shrink."""
    failures = []
    window, cv, _scale = _make_window_with_tab()
    try:
        container = cv.centralWidget()
        _cad_before, sidebar_before = container.sizes()

        for w, h in [(1600, 900), (900, 600), (1300, 850)]:
            window.resize(w, h)
            for _ in range(2):
                _app.processEvents()
            cad_after, sidebar_after = container.sizes()
            if sidebar_after != sidebar_before:
                failures.append(
                    f"resize to {w}x{h}: sidebar width changed "
                    f"{sidebar_before} -> {sidebar_after} (should stay fixed)")
            if cad_after == 0:
                failures.append(f"resize to {w}x{h}: CAD view width collapsed to 0")
    finally:
        try:
            window.deleteLater()
        except Exception:
            pass
    return failures


def run_multiple_tabs_each_get_scaled_independently():
    """Each tab has its own PinchZoomCADViewer; every tab's sidebar should
    be scaled, not just the first one created."""
    failures = []
    window, _cv, scale = _make_window_with_tab()
    try:
        window.create_new_tab()
        for _ in range(3):
            _app.processEvents()

        if window.tab_widget.count() != 2:
            failures.append(f"expected 2 tabs, got {window.tab_widget.count()}")

        widths = []
        for i in range(window.tab_widget.count()):
            tab_cv = window.tab_widget.widget(i).tab_data.cad_viewer
            widths.append(tab_cv.centralWidget().sizes()[1])

        if len(set(widths)) != 1:
            failures.append(f"tabs have inconsistent sidebar widths: {widths}")
    finally:
        try:
            window.deleteLater()
        except Exception:
            pass
    return failures


def main():
    all_failures = []
    all_failures.extend(run_startup_width_is_scaled())
    all_failures.extend(run_window_resize_does_not_change_sidebar_width())
    all_failures.extend(run_multiple_tabs_each_get_scaled_independently())

    if all_failures:
        print(f"FAILED ({len(all_failures)} issue(s)):")
        for msg in all_failures:
            print(f"  - {msg}")
        return 1

    print("OK — sidebar is shrunk to 65% at startup and stays fixed-width on window resize")
    return 0


if __name__ == '__main__':
    sys.exit(main())
