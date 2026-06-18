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

        A region matches when ``query`` is found in any of its
        ``name_candidates`` texts (``default_name`` is always the first
        candidate, so it does not need a separate check), honoring the
        case-sensitivity and whole-word options (same semantics as the text
        search).

        Each returned region is a shallow copy of the corresponding entry in
        ``analysis['regions']`` with an extra ``matched_labels`` key: a list of
        ``(text, x, y)`` tuples for the specific candidate texts that matched
        the query, using the coordinates recorded in
        ``name_candidate_positions``. The UI layer uses these coordinates to
        highlight the matched label entity itself, not just the region
        boundary.

        Args:
            analysis: Result of :func:`analyze_dxf_regions`.
            query: Region name to search for.
            case_sensitive: If True, match case exactly.
            whole_word: If True, match whole words only.

        Returns:
            List of region dicts (copies of entries in ``analysis['regions']``).
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
            positions = region.get('name_candidate_positions', {})
            matched_labels = []
            for _dist, text in region.get('name_candidates', []):
                if not RegionSearchManager._name_matches(text, needle, regex, case_sensitive):
                    continue
                pos = positions.get(text)
                if pos:
                    matched_labels.append((text, pos[0], pos[1]))

            if matched_labels:
                matched.append(dict(region, matched_labels=matched_labels))
        return matched

    @staticmethod
    def _name_matches(name, needle, regex, case_sensitive):
        if regex is not None:
            return regex.search(name) is not None
        haystack = name if case_sensitive else name.lower()
        return needle in haystack
