"""Boundary (rectangular region) search for DXF drawings.

UI-independent logic that locates named rectangular regions (detected by
``core.region_detector``) whose name matches a query. The first analysis for a
tab is cached on the :class:`~core.tab_manager.DXFTab` so subsequent searches are
instant.

Highlighting itself (scene overlays, dimming) is performed by the UI layer; this
module only supplies the geometry/name matching.
"""

import math
import re

from core.region_detector import analyze_dxf_regions
from utils.text_utils import normalize_width


class RegionSearchManager:
    """Run and cache region detection, and match regions by name."""

    _DEFAULT_AREA_RATIO = 0.10

    @staticmethod
    def get_analysis(tab_data, area_ratio=None):
        """Return the (cached) region analysis for a tab.

        Runs :func:`analyze_dxf_regions` against the tab's source file on first
        use and caches the result on ``tab_data.region_analysis``. Region
        detection reads from the file on disk, so it is unaffected by any color
        changes applied to the in-memory document.

        When ``area_ratio`` differs from the default (0.10), the analysis is
        run with the custom threshold and the result is **not** stored in the
        cache (the cache always holds the default-threshold result so that
        subsequent default-threshold searches are still instant).

        Args:
            tab_data: DXFTab instance (must have ``file_path``).
            area_ratio: Minimum region area as a fraction of the frame area
                (e.g. 0.10 for 10%).  None → use the default 0.20.

        Returns:
            The analysis dict, or None when the tab has no file path.
        """
        if not tab_data.file_path:
            return None
        default_ratio = RegionSearchManager._DEFAULT_AREA_RATIO
        use_custom = area_ratio is not None and abs(area_ratio - default_ratio) > 1e-6
        if use_custom:
            return analyze_dxf_regions(tab_data.file_path,
                                       config={'area_ratio': area_ratio})
        if tab_data.region_analysis is None:
            tab_data.region_analysis = analyze_dxf_regions(
                tab_data.file_path, config={'area_ratio': default_ratio})
        return tab_data.region_analysis

    @staticmethod
    def find_matching_regions(analysis, query, case_sensitive=False, whole_word=False):
        """Return the region dicts whose top-priority name matches ``query``.

        A region matches when ``query`` matches its ``default_name`` — the
        single highest-priority candidate selected by
        ``region_detector.region_name_candidates()``'s tier ranking (1: nearest
        bottom edge / right edge when rotated, 2: nearest top edge / left edge
        when rotated, 3: nearest point on the boundary overall) — honoring the
        case-sensitivity and whole-word options (same semantics as the text
        search).

        Only the top candidate is checked, not the full ``name_candidates``
        list: that list records every nearby label as a fuzzy, distance-ranked
        guess, so nested/adjacent regions can each list the other's name too
        (e.g. in ``EE6313-546-01E.dxf``, the outer ``B CHAMBER`` region and the
        fully contained ``BAKE HEATER UNIT RX`` region each have both names as
        candidates). Matching only the top-ranked one ties the highlighted
        boundary to the name actually assigned to that region.

        Each returned region is a shallow copy of the corresponding entry in
        ``analysis['regions']`` with an extra ``matched_labels`` key: a single
        ``(text, x, y)`` tuple for the matched name, using the coordinates
        recorded in ``name_candidate_positions``. The UI layer uses this
        coordinate to highlight the matched label entity itself, not just the
        region boundary.

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

        # Width-fold (zenkaku<->hankaku) so a query typed in either width
        # matches a region name written in the other.
        query = normalize_width(query)
        regex = None
        if whole_word:
            flags = 0 if case_sensitive else re.IGNORECASE
            regex = re.compile(r'\b' + re.escape(query) + r'\b', flags)
        needle = query if case_sensitive else query.lower()

        matched = []
        for region in analysis.get('regions', []):
            text = region.get('default_name', '')
            if not text or not RegionSearchManager._name_matches(text, needle, regex, case_sensitive):
                continue
            pos = region.get('name_candidate_positions', {}).get(text)
            matched_labels = [(text, pos[0], pos[1])] if pos else []
            matched.append(dict(region, matched_labels=matched_labels))
        return matched

    @staticmethod
    def _name_matches(name, needle, regex, case_sensitive):
        haystack = normalize_width(name)
        if regex is not None:
            return regex.search(haystack) is not None
        haystack = haystack if case_sensitive else haystack.lower()
        return needle in haystack

    @staticmethod
    def parse_corner_list(text):
        """Parse a pasted vertex-coordinate list into a list of (x, y) tuples.

        Accepts the format shown by DXF-extract-labels's region popover
        ("頂点の座標（左下から / N点）"), one vertex per line, e.g.::

            1: (185.19, 23.07)
            2: (634.21, 23.07)

        The leading index and parentheses are tolerated but not required; any
        line containing two comma-separated numbers is parsed, others are
        skipped (so stray header/blank lines copied along with the list do
        not break parsing).

        Args:
            text: Raw pasted text.

        Returns:
            List of (x, y) float tuples, in the order they appear in the text.
        """
        points = []
        for line in (text or '').splitlines():
            m = re.search(r'(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)', line)
            if m:
                points.append((float(m.group(1)), float(m.group(2))))
        return points

    @staticmethod
    def find_region_by_corners(analysis, corners, tol=0.15):
        """Return the region (if any) whose polygon corners match ``corners``.

        ``corners`` is typically the output of :meth:`parse_corner_list` fed
        from a vertex list copied out of DXF-extract-labels's region popover.
        Matching against each region's own ``corners`` (``_polygon_corners()``
        output) is order- and rotation-independent — it only requires the same
        point count and a one-to-one assignment where every given point lies
        within ``tol`` of a distinct region corner — so it tolerates the
        2-decimal rounding in the pasted text as well as any incidental
        difference in winding/start-point between the two tools (both run the
        same corner-extraction algorithm on the same source file, but this
        keeps the match robust even if that ever drifts).

        Args:
            analysis: Result of :func:`analyze_dxf_regions`.
            corners: List of (x, y) tuples to match.
            tol: Maximum per-point distance (DXF units) to count as a match.

        Returns:
            A list with the single matching region dict (shallow copy, for
            symmetry with :meth:`find_matching_regions`'s return type), or an
            empty list when no region matches.
        """
        if not analysis or not corners:
            return []

        for region in analysis.get('regions', []):
            if RegionSearchManager._corners_match(corners, region.get('corners', []), tol):
                return [dict(region)]
        return []

    @staticmethod
    def _corners_match(given, region_corners, tol):
        if len(given) != len(region_corners) or not given:
            return False
        remaining = list(region_corners)
        for (px, py) in given:
            best_idx, best_dist = None, None
            for i, (qx, qy) in enumerate(remaining):
                dist = math.hypot(px - qx, py - qy)
                if best_dist is None or dist < best_dist:
                    best_idx, best_dist = i, dist
            if best_idx is None or best_dist > tol:
                return False
            remaining.pop(best_idx)
        return True
