"""Utility modules for DXF Viewer.

Import submodules directly (e.g. ``from utils.text_utils import
normalize_width``) -- this package intentionally re-exports nothing, so that
importing one utility never drags in another's heavy dependencies
(matplotlib/PIL in export_utils) and the package init can never go stale.
"""
