"""Regression test: element-attribute panel / mouse-position coordinates are
rounded to COORDINATE_DISPLAY_DECIMALS (2) places for display.

This is a display-only change. `PinchZoomCADViewer._on_element_hovered()` /
`_on_mouse_moved()` (`ui/viewer_widget.py`) never touch the DXF entity's
actual attribute values (re-read fresh from the ezdxf document on every
hover) or any other coordinate-based processing elsewhere in the app
(search matching, region detection, hit-testing, export) — none of those
read from this panel's displayed text, so there is no internal-precision
tradeoff being made here.

Covers two layers:
1. `_format_dxf_attrib_value()` / `_entity_attribs_string_rounded()` — pure
   functions, no Qt/GUI needed. Verifies Vec3, Vec2, and non-coordinate
   numeric attributes (radius, char_height, ints, strings) are each handled
   correctly, and that the coordinate output format matches ezdxf's own
   `str(Vec3(...))` style (a bare "(x, y, z)" tuple, not "Vec3(x, y, z)" —
   confirmed empirically: ezdxf's display code does f"{value}", which calls
   Vec3.__str__(), not Vec3.__repr__()).
2. A headless GUI smoke test of `PinchZoomCADViewer._on_element_hovered()` /
   `_on_mouse_moved()` against a real sample DXF file, covering both a
   directly-placed entity and an entity reached through a block/INSERT
   reference (both are Vec2/Vec3-typed in ezdxf, but this was verified
   empirically rather than assumed, since the two paths go through
   different internal ezdxf code).

Run:
    python tests/regression/test_coordinate_display_rounding.py [path/to/EE*.dxf]

Without arguments it auto-discovers *.dxf in sample-dxf/ (symlinked from
Tools/sample-dxf/, shared across projects).
"""

import glob
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_SAMPLE_DIR = os.path.join(_ROOT, 'sample-dxf')

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication

# Module-level reference: PyQt5 garbage-collects the QApplication singleton
# almost immediately if nothing holds a Python reference to it (see
# test_close_all_tabs.py for the crash this causes).
_app = QApplication.instance() or QApplication([])


def run_format_dxf_attrib_value_cases():
    """Pure-function unit tests for the value-type-based rounding logic."""
    failures = []
    from ezdxf.math import Vec2, Vec3
    from ui.viewer_widget import _format_dxf_attrib_value, COORDINATE_DISPLAY_DECIMALS

    if COORDINATE_DISPLAY_DECIMALS != 2:
        failures.append(
            f"expected COORDINATE_DISPLAY_DECIMALS == 2, got {COORDINATE_DISPLAY_DECIMALS} "
            f"(this test's expected strings assume 2)")

    cases = [
        (Vec3(2952.0, 59.00000003814691, 0.0), "(2952.0, 59.0, 0.0)"),
        (Vec3(1.005, 2.004999, -3.5), "(1.0, 2.0, -3.5)"),  # banker's rounding, same as round()
        (Vec2(1.234567, -2.987654), "(1.23, -2.99)"),
        (270.8184594899177, "270.8184594899177"),  # plain float (e.g. radius) untouched
        (3.230000019073486, "3.230000019073486"),  # e.g. char_height untouched
        (7, "7"),  # int (e.g. color) untouched
        ("NoLayerName_042", "NoLayerName_042"),  # string (e.g. layer) untouched
        ((1.0, 2.0, 3.0), "(1.0, 2.0, 3.0)"),  # bare 3-tuple: still coordinate-shaped, rounded
    ]
    for value, expected in cases:
        actual = _format_dxf_attrib_value(value)
        if actual != expected:
            failures.append(f"_format_dxf_attrib_value({value!r}): expected {expected!r}, got {actual!r}")

    return failures


def run_entity_attribs_string_rounded_case():
    """A real ezdxf entity's coordinate attribute is rounded; a non-coordinate
    numeric attribute (radius) on the same entity is left untouched."""
    failures = []
    import ezdxf
    from ui.viewer_widget import _entity_attribs_string_rounded

    doc = ezdxf.new()
    msp = doc.modelspace()
    circle = msp.add_circle(
        (1.123456789, 2.987654321), radius=4.199999999999932)

    text = _entity_attribs_string_rounded(circle)
    if "- center: (1.12, 2.99, 0.0)" not in text:
        failures.append(f"center was not rounded to 2 decimals in:\n{text}")
    if "- radius: 4.199999999999932" not in text:
        failures.append(f"radius (non-coordinate) was unexpectedly altered in:\n{text}")

    return failures


def run_gui_smoke_case(file_path):
    """Exercise _on_element_hovered()/_on_mouse_moved() headlessly against a
    real DXF file, covering both a directly-placed and a block-nested entity."""
    failures = []

    from PyQt5.QtCore import QPointF
    import ui.main_window as main_window_mod
    from ezdxf.addons.drawing.pyqt import (
        CorrespondingDXFEntity, CorrespondingDXFParentStack,
    )

    window = main_window_mod.DXFViewerApp()
    try:
        window.resize(1200, 800)
        window.show()
        window.load_dxf(file_path)
        for _ in range(3):
            _app.processEvents()

        tab = window.get_current_tab()
        if tab is None:
            failures.append(f"{file_path}: load_dxf() produced no tab (invalid sample?)")
            return failures
        cv = tab.tab_data.cad_viewer
        scene = cv.graphics_view.scene()

        # Mouse position label.
        cv._on_mouse_moved(QPointF(123.456789, 987.654321))
        mouse_text = cv.mouse_pos.text()
        if "123.46, 987.65" not in mouse_text:
            failures.append(f"{file_path}: mouse position not rounded, got {mouse_text!r}")

        # Find at least one rendered item with an attached DXF entity, and
        # one whose parent stack is non-empty (i.e. reached via a block/
        # INSERT reference) if available.
        direct_item = None
        nested_item = None
        for item in scene.items():
            entity = item.data(CorrespondingDXFEntity)
            if entity is None:
                continue
            if direct_item is None:
                direct_item = item
            if nested_item is None and item.data(CorrespondingDXFParentStack) is not None:
                nested_item = item
            if direct_item is not None and nested_item is not None:
                break

        if direct_item is None:
            failures.append(f"{file_path}: no rendered entity item found to test hover on")
        else:
            cv._on_element_hovered([direct_item], 0)
            text = cv.selected_info.toPlainText()
            issue = _check_no_overprecise_coordinates(text)
            if issue:
                failures.append(f"{file_path} (direct entity): {issue}")

        if nested_item is not None:
            cv._on_element_hovered([nested_item], 0)
            text = cv.selected_info.toPlainText()
            issue = _check_no_overprecise_coordinates(text)
            if issue:
                failures.append(f"{file_path} (block-nested entity): {issue}")
    finally:
        window.close()

    return failures


def _check_no_overprecise_coordinates(text):
    """Return a failure message if any coordinate-shaped tuple in `text` has
    more than COORDINATE_DISPLAY_DECIMALS digits after the decimal point.

    Scans lines that look like "- <key>: (n[, n[, n]])" and checks each
    number's decimal-digit count; skips non-tuple-valued lines (radius,
    char_height, layer name, etc. are expected to keep full precision).
    """
    import re
    from ui.viewer_widget import COORDINATE_DISPLAY_DECIMALS

    tuple_line = re.compile(r'^\s*-\s+\w+:\s+\(([-\d.,\s]+)\)\s*$')
    number = re.compile(r'-?\d+\.(\d+)')
    for line in text.splitlines():
        m = tuple_line.match(line)
        if not m:
            continue
        for num_match in number.finditer(m.group(1)):
            digits = num_match.group(1)
            if len(digits) > COORDINATE_DISPLAY_DECIMALS:
                return f"coordinate not rounded to {COORDINATE_DISPLAY_DECIMALS} decimals: {line.strip()!r}"
    return None


def main():
    args = sys.argv[1:]
    files = args if args else sorted(glob.glob(os.path.join(_SAMPLE_DIR, '*.dxf')))[:5]

    all_failures = []
    all_failures.extend(run_format_dxf_attrib_value_cases())
    all_failures.extend(run_entity_attribs_string_rounded_case())

    if not files:
        print("No sample DXF files found — skipping GUI smoke test portion")
    else:
        for f in files:
            all_failures.extend(run_gui_smoke_case(f))

    if all_failures:
        print(f"FAILED ({len(all_failures)} issue(s)):")
        for msg in all_failures:
            print(f"  - {msg}")
        return 1

    print(f"OK — coordinates rounded to {2} decimal places in element-attribute "
          f"panel and mouse-position label ({len(files)} sample file(s) checked)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
