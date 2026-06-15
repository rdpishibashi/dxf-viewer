"""Boundary (rectangular region) search for DXF drawings.

UI-independent logic that locates named rectangular regions (detected by
``core.region_detector``) whose name matches a query. The first analysis for a
tab is cached on the :class:`~core.tab_manager.DXFTab` so subsequent searches are
instant.

Highlighting itself (scene overlays, dimming) is performed by the UI layer; this
module only supplies the geometry/name matching.
"""

import re

from core.region_detector import analyze_dxf_regions


class RegionSearchManager:
    """Run and cache region detection, and match regions by name."""

    @staticmethod
    def get_analysis(tab_data):
        """Return the (cached) region analysis for a tab.

        Runs :func:`analyze_dxf_regions` against the tab's source file on first
        use and caches the result on ``tab_data.region_analysis``. Region
        detection reads from the file on disk, so it is unaffected by any color
        changes applied to the in-memory document.

        Args:
            tab_data: DXFTab instance (must have ``file_path``).

        Returns:
            The analysis dict, or None when the tab has no file path.
        """
        if tab_data.region_analysis is None:
            if not tab_data.file_path:
                return None
            tab_data.region_analysis = analyze_dxf_regions(tab_data.file_path)
        return tab_data.region_analysis

    @staticmethod
    def find_matching_regions(analysis, query, case_sensitive=False, whole_word=False):
        """Return the region dicts whose name matches ``query``.

        A region matches when ``query`` is found in its ``default_name`` or in
        any of its ``name_candidates`` texts, honoring the case-sensitivity and
        whole-word options (same semantics as the text search).

        Args:
            analysis: Result of :func:`analyze_dxf_regions`.
            query: Region name to search for.
            case_sensitive: If True, match case exactly.
            whole_word: If True, match whole words only.

        Returns:
            List of region dicts (subset of ``analysis['regions']``).
        """
        if not analysis or not query:
            return []

        regex = None
        if whole_word:
            flags = 0 if case_sensitive else re.IGNORECASE
            regex = re.compile(r'\b' + re.escape(query) + r'\b', flags)
        needle = query if case_sensitive else query.lower()

        matched = []
        for region in analysis.get('regions', []):
            names = []
            if region.get('default_name'):
                names.append(region['default_name'])
            names.extend(text for _dist, text in region.get('name_candidates', []))

            if RegionSearchManager._any_name_matches(names, needle, regex, case_sensitive):
                matched.append(region)
        return matched

    @staticmethod
    def _any_name_matches(names, needle, regex, case_sensitive):
        for name in names:
            if regex is not None:
                if regex.search(name):
                    return True
            else:
                haystack = name if case_sensitive else name.lower()
                if needle in haystack:
                    return True
        return False
