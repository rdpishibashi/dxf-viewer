"""Regression test: layout switching (Model <-> paper-space layouts).

Bug context: `EE6492-464-01B.dxf`'s title block (drawing number, title text)
lives in a paper-space layout ("ICADSX Layout" / INSERT JZB_0001), not in
Model space. DXF-viewer only ever drew "Model" and hid ezdxf's own built-in
"Select Layout" menu (to keep it out of macOS's global menu bar), so there
was no way to view that content at all — not a rendering limit, just a
missing UI affordance.

Fix: a toolbar layout combo box (`window.layout_combo`) drives
`PinchZoomCADViewer.draw_layout()` directly. The one real regression risk
this introduces: `refresh_viewer()` — the common re-render used by Search
Text/Handle/Boundary, Color change/restore, and Consolidate Layers (9 call
sites) — used to call `set_document()` without a `layout=` argument, which
defaults to "Model". Left unfixed, triggering any of those operations while
a paper-space layout was displayed would have silently snapped the view
back to Model. This test exercises that combination directly.

Run:
    python tests/regression/test_layout_switching.py
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication

# Module-level reference — see test_close_all_tabs.py for why this is needed
# (PyQt5 garbage-collects the QApplication singleton otherwise).
_app = QApplication.instance() or QApplication([])

PAPER_SPACE_FILE = '/Users/ryozo/Dropbox/Workspace/339_Unit内結線図/EE6492-464-01B.dxf'
MODEL_ONLY_SAMPLE = os.path.join(_ROOT, 'sample-dxf', 'samples', 'EE5611-695-04B.dxf')


def _make_window():
    import ui.main_window as main_window_mod
    return main_window_mod.DXFViewerApp()


def run_combo_populated_with_layouts():
    """Opening a Model+PaperSpace file populates the combo and defaults to Model."""
    failures = []
    if not os.path.isfile(PAPER_SPACE_FILE):
        return [f"sample file not found, skipping: {PAPER_SPACE_FILE}"]

    window = _make_window()
    try:
        window.load_dxf(PAPER_SPACE_FILE)
        tab_data = window._current_tab_data()
        if not tab_data or not tab_data.dxf_doc:
            failures.append("file failed to load")
            return failures

        items = [window.layout_combo.itemText(i) for i in range(window.layout_combo.count())]
        if items != ['Model', 'ICADSX Layout']:
            failures.append(f"expected combo items ['Model', 'ICADSX Layout'], got {items}")
        if window.layout_combo.currentText() != 'Model':
            failures.append(f"expected default selection 'Model', got {window.layout_combo.currentText()!r}")
        if tab_data.cad_viewer.current_layout_name() != 'Model':
            failures.append(
                f"expected cad_viewer to be showing Model initially, got "
                f"{tab_data.cad_viewer.current_layout_name()!r}")
    finally:
        window.deleteLater()
    return failures


def run_switching_layout_shows_title_block_text():
    """Switching to the paper-space layout actually draws it (no exception),
    and current_layout_name() reflects the switch."""
    failures = []
    if not os.path.isfile(PAPER_SPACE_FILE):
        return [f"sample file not found, skipping: {PAPER_SPACE_FILE}"]

    window = _make_window()
    try:
        window.load_dxf(PAPER_SPACE_FILE)
        tab_data = window._current_tab_data()

        window.layout_combo.setCurrentText('ICADSX Layout')
        if tab_data.cad_viewer.current_layout_name() != 'ICADSX Layout':
            failures.append(
                f"expected current_layout_name() == 'ICADSX Layout' after combo switch, got "
                f"{tab_data.cad_viewer.current_layout_name()!r}")
    except Exception as e:
        failures.append(f"switching to 'ICADSX Layout' raised: {e!r}")
    finally:
        window.deleteLater()
    return failures


def run_refresh_viewer_preserves_paper_layout():
    """The core regression: Search/Color/Consolidate must NOT reset the view
    back to Model while a paper-space layout is displayed."""
    failures = []
    if not os.path.isfile(PAPER_SPACE_FILE):
        return [f"sample file not found, skipping: {PAPER_SPACE_FILE}"]

    window = _make_window()
    try:
        window.load_dxf(PAPER_SPACE_FILE)
        tab_data = window._current_tab_data()
        window.layout_combo.setCurrentText('ICADSX Layout')

        checks = [
            ('search_text (no match, closes dialog-free path skipped)', None),
        ]

        # Directly exercise the pieces of refresh_viewer()-driving operations
        # that don't require a modal dialog, calling refresh_viewer() itself
        # (the shared code path) the same way all 9 call sites do.
        from core.search_manager import SearchManager
        from core.color_manager import ColorManager

        # Search-style highlight + refresh (mirrors search_text()'s internals)
        SearchManager.store_all_entity_colors(tab_data)
        tab_data.search_results = SearchManager.find_text_entities(tab_data.dxf_doc, 'EE6492')
        if tab_data.search_results:
            SearchManager.apply_search_highlighting(tab_data)
        window.refresh_viewer(tab_data)
        if tab_data.cad_viewer.current_layout_name() != 'ICADSX Layout':
            failures.append(
                "refresh_viewer() after a Search Text-style highlight reset the view to "
                f"{tab_data.cad_viewer.current_layout_name()!r} instead of staying on "
                "'ICADSX Layout'")

        # Restore + refresh (mirrors clear_search())
        SearchManager.restore_original_colors(tab_data)
        window.refresh_viewer(tab_data)
        if tab_data.cad_viewer.current_layout_name() != 'ICADSX Layout':
            failures.append(
                "refresh_viewer() after restoring colors reset the view to "
                f"{tab_data.cad_viewer.current_layout_name()!r} instead of staying on "
                "'ICADSX Layout'")

        # Color-change style mutate + refresh (mirrors change_all_colors())
        ColorManager.store_entity_colors(tab_data)
        ColorManager.apply_color_to_all_entities(tab_data, 1, 0xFF0000)
        window.refresh_viewer(tab_data)
        if tab_data.cad_viewer.current_layout_name() != 'ICADSX Layout':
            failures.append(
                "refresh_viewer() after a Change Colors-style mutation reset the view to "
                f"{tab_data.cad_viewer.current_layout_name()!r} instead of staying on "
                "'ICADSX Layout'")
        ColorManager.restore_colors_from_backup(tab_data)
        window.refresh_viewer(tab_data)
        if tab_data.cad_viewer.current_layout_name() != 'ICADSX Layout':
            failures.append(
                "refresh_viewer() after Restore Colors reset the view to "
                f"{tab_data.cad_viewer.current_layout_name()!r} instead of staying on "
                "'ICADSX Layout'")

    except Exception as e:
        failures.append(f"exercising refresh_viewer() on a paper layout raised: {e!r}")
    finally:
        window.deleteLater()
    return failures


def run_tab_switch_syncs_combo_independently():
    """Two tabs with different files/layouts must not leak state into each other."""
    failures = []
    if not os.path.isfile(PAPER_SPACE_FILE) or not os.path.isfile(MODEL_ONLY_SAMPLE):
        return [
            "sample file(s) not found, skipping: "
            f"{PAPER_SPACE_FILE if not os.path.isfile(PAPER_SPACE_FILE) else MODEL_ONLY_SAMPLE}"
        ]

    window = _make_window()
    try:
        window.load_dxf(PAPER_SPACE_FILE)
        paper_tab_index = window.tab_widget.currentIndex()
        window.layout_combo.setCurrentText('ICADSX Layout')

        window.load_dxf(MODEL_ONLY_SAMPLE)
        model_tab_index = window.tab_widget.currentIndex()
        items_on_model_tab = [
            window.layout_combo.itemText(i) for i in range(window.layout_combo.count())]
        if window.layout_combo.currentText() != 'Model':
            failures.append(
                f"newly opened tab should default to 'Model' in the combo, got "
                f"{window.layout_combo.currentText()!r}")

        # Switch back to the first tab — combo must reflect its own state
        # (still 'ICADSX Layout'), independent of the second tab.
        window.tab_widget.setCurrentIndex(paper_tab_index)
        if window.layout_combo.currentText() != 'ICADSX Layout':
            failures.append(
                "switching back to the first tab should restore combo selection "
                f"'ICADSX Layout', got {window.layout_combo.currentText()!r}")
        tab_data = window._current_tab_data()
        if tab_data.cad_viewer.current_layout_name() != 'ICADSX Layout':
            failures.append(
                "switching back to the first tab should leave its CAD viewer showing "
                f"'ICADSX Layout', got {tab_data.cad_viewer.current_layout_name()!r}")
    except Exception as e:
        failures.append(f"multi-tab layout combo sync raised: {e!r}")
    finally:
        window.deleteLater()
    return failures


def run_export_and_file_info_unaffected():
    """Export/File Info don't touch layout_combo/current_layout at all — this
    just documents (and locks in) that they don't error out when a
    paper-space layout is the active view."""
    failures = []
    if not os.path.isfile(PAPER_SPACE_FILE):
        return [f"sample file not found, skipping: {PAPER_SPACE_FILE}"]

    window = _make_window()
    try:
        window.load_dxf(PAPER_SPACE_FILE)
        window.layout_combo.setCurrentText('ICADSX Layout')
        tab_data = window._current_tab_data()

        # export_to_image()/show_file_info() open modal dialogs, so just
        # confirm the underlying document access they rely on still works
        # and current_layout_name() is untouched by mere data access.
        msp_count = len(tab_data.dxf_doc.modelspace())
        if msp_count <= 0:
            failures.append("modelspace entity count unexpectedly 0")
        if tab_data.cad_viewer.current_layout_name() != 'ICADSX Layout':
            failures.append("merely reading document data should not change the active layout")
    except Exception as e:
        failures.append(f"export/file-info-adjacent access raised: {e!r}")
    finally:
        window.deleteLater()
    return failures


def main():
    all_failures = []
    all_failures.extend(run_combo_populated_with_layouts())
    all_failures.extend(run_switching_layout_shows_title_block_text())
    all_failures.extend(run_refresh_viewer_preserves_paper_layout())
    all_failures.extend(run_tab_switch_syncs_combo_independently())
    all_failures.extend(run_export_and_file_info_unaffected())

    if all_failures:
        print(f"FAILED ({len(all_failures)} issue(s)):")
        for msg in all_failures:
            print(f"  - {msg}")
        return 1

    print("OK — layout switching works and refresh_viewer() preserves the active layout")
    return 0


if __name__ == '__main__':
    sys.exit(main())
