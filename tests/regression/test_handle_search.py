"""Regression test for Search Handle (find entities by DXF handle, e.g. "#212A").

Covers two layers:
1. `SearchManager.find_entities_by_handles()` — handle parsing/normalization
   (leading '#', case-insensitivity, comma/space separated lists, duplicates,
   not-found handles) and lookup via `doc.entitydb` for entities both in
   modelspace and inside a block definition.
2. A headless GUI smoke test of `DXFViewerApp.search_handle()` /
   `clear_search()` — exercises the actual dim/highlight/restore wiring used
   by the toolbar and menu actions, with the modal dialog bypassed.

Run:
    python tests/regression/test_handle_search.py [path/to/EE*.dxf]

Without arguments it auto-discovers EE*.dxf in sample-dxf/ (symlinked from
Tools/sample-dxf/, shared across projects). The DXF samples are not committed;
the test is skipped (exit 0) when none are present.
"""

import glob
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Sample DXFs are shared across projects in Tools/sample-dxf/, symlinked into
# each project's root as `sample-dxf`.
_SAMPLE_DIR = os.path.join(_ROOT, 'sample-dxf')

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import ezdxf

from core.search_manager import SearchManager


def find_sample_handles(doc):
    """Return (modelspace_handle, block_handle) for use as test fixtures."""
    msp_handle = None
    for entity in doc.modelspace():
        if hasattr(entity.dxf, 'handle'):
            msp_handle = entity.dxf.handle
            break

    block_handle = None
    for block in doc.blocks:
        if block.name.startswith('*'):
            continue
        for entity in block:
            if hasattr(entity.dxf, 'handle'):
                block_handle = entity.dxf.handle
                break
        if block_handle:
            break

    return msp_handle, block_handle


def run_lookup_cases(file_path):
    failures = []
    doc = ezdxf.readfile(file_path)
    msp_handle, block_handle = find_sample_handles(doc)
    if not msp_handle or not block_handle:
        failures.append(f"{file_path}: could not find sample handles to test with")
        return failures

    # Leading '#', lower case, comma+space separated, with a duplicate and an
    # unresolvable handle mixed in.
    query = f"#{msp_handle}, {block_handle.lower()}  {msp_handle.lower()} ZZZZ999"
    results, not_found = SearchManager.find_entities_by_handles(doc, query)

    found_handles = {r.entity.dxf.handle for r in results}
    if found_handles != {msp_handle, block_handle}:
        failures.append(
            f"{file_path}: expected handles {{{msp_handle}, {block_handle}}}, "
            f"got {found_handles}")
    if len(results) != 2:
        failures.append(
            f"{file_path}: duplicate handle was not collapsed, got {len(results)} results")
    if not_found != ['ZZZZ999']:
        failures.append(f"{file_path}: expected not_found ['ZZZZ999'], got {not_found}")

    for r in results:
        if r.position is None:
            failures.append(f"{file_path}: handle {r.entity.dxf.handle} resolved with no position")

    # Pure not-found query.
    results2, not_found2 = SearchManager.find_entities_by_handles(doc, "NOPE1, NOPE2")
    if results2:
        failures.append(f"{file_path}: expected no results for nonexistent handles, got {results2}")
    if set(not_found2) != {'NOPE1', 'NOPE2'}:
        failures.append(f"{file_path}: expected not_found ['NOPE1','NOPE2'], got {not_found2}")

    return failures


def run_gui_smoke_case(file_path):
    """Exercise DXFViewerApp.search_handle()/clear_search() headlessly."""
    failures = []

    from PyQt5.QtWidgets import QApplication, QDialog
    import ui.main_window as main_window_mod

    app = QApplication.instance() or QApplication([])

    doc = ezdxf.readfile(file_path)
    msp_handle, block_handle = find_sample_handles(doc)
    if not msp_handle or not block_handle:
        failures.append(f"{file_path}: could not find sample handles for GUI smoke test")
        return failures

    window = main_window_mod.DXFViewerApp()
    try:
        window.load_dxf(file_path)
        tab_data = window.get_current_tab().tab_data

        target_entity = tab_data.dxf_doc.entitydb.get(msp_handle)
        original_color = getattr(target_entity.dxf, 'color', 256)

        class _StubDialog:
            def __init__(self, *a, **kw):
                pass

            def exec_(self):
                return QDialog.Accepted

            def get_search_params(self):
                return {
                    'handles': f"#{msp_handle}, {block_handle}",
                    'dim_color': (251, 0xC0C0C0),
                }

        original_dialog_cls = main_window_mod.HandleSearchDialog
        main_window_mod.HandleSearchDialog = _StubDialog
        try:
            window.search_handle()
        finally:
            main_window_mod.HandleSearchDialog = original_dialog_cls

        if not tab_data.handle_search_active:
            failures.append(f"{file_path}: handle_search_active was not set True")
        if len(tab_data.handle_search_results) != 2:
            failures.append(
                f"{file_path}: expected 2 handle_search_results, got "
                f"{len(tab_data.handle_search_results)}")
        if not window.clear_search_action.isEnabled():
            failures.append(f"{file_path}: clear_search_action was not enabled after search_handle()")
        if not window.clear_handle_search_action.isEnabled():
            failures.append(f"{file_path}: clear_handle_search_action was not enabled")

        target_entity_color = getattr(target_entity.dxf, 'color', None)
        if target_entity_color != 1:
            failures.append(
                f"{file_path}: matched entity was not recolored red, color={target_entity_color}")

        # A non-matched entity should have been dimmed.
        dimmed_sample = None
        for entity in tab_data.dxf_doc.modelspace():
            if hasattr(entity.dxf, 'handle') and entity.dxf.handle not in (msp_handle, block_handle):
                dimmed_sample = entity
                break
        if dimmed_sample is not None and getattr(dimmed_sample.dxf, 'color', None) != 251:
            failures.append(
                f"{file_path}: expected a non-matched entity to be dimmed to color 251, "
                f"got {getattr(dimmed_sample.dxf, 'color', None)}")

        window.clear_search()

        if tab_data.handle_search_active:
            failures.append(f"{file_path}: handle_search_active still True after clear_search()")
        if tab_data.handle_search_results:
            failures.append(f"{file_path}: handle_search_results not cleared after clear_search()")
        if window.clear_handle_search_action.isEnabled():
            failures.append(f"{file_path}: clear_handle_search_action still enabled after clear_search()")

        restored_color = getattr(target_entity.dxf, 'color', None)
        if restored_color != original_color:
            failures.append(
                f"{file_path}: color not restored after clear_search(), "
                f"expected {original_color}, got {restored_color}")
    finally:
        window.close()

    return failures


def main():
    args = sys.argv[1:]
    files = args if args else sorted(glob.glob(os.path.join(_SAMPLE_DIR, 'EE*.dxf')))

    if not files:
        print("No sample DXF files found — skipping test_handle_search.py")
        return 0

    all_failures = []
    for f in files:
        all_failures.extend(run_lookup_cases(f))
        all_failures.extend(run_gui_smoke_case(f))

    if all_failures:
        print(f"FAILED ({len(all_failures)} issue(s)):")
        for msg in all_failures:
            print(f"  - {msg}")
        return 1

    print(f"OK — handle search verified across {len(files)} file(s)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
