"""Regression test for layer consolidation (Boundaries / Imported).

Verifies that `core.layer_consolidator.consolidate_layers` collapses a drawing
into exactly the two target layers (plus protected layers), captures the
detected region boundary linework into 'Boundaries', and that every region's
rectangle perimeter is represented.

Run:
    python tests/regression/test_layer_consolidation.py [path/to/EE*.dxf ...]

Samples are auto-discovered in sample-dxf/ (symlinked from Tools/sample-dxf/,
shared across projects). The DXF samples are not committed; the sample checks
are skipped (exit 0) when absent.
"""

import glob
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_SAMPLE_DIR = os.path.join(_ROOT, 'sample-dxf')


def _find_sample(name):
    """Find a sample DXF by exact filename anywhere under the shared pool.

    sample-dxf/ keeps loose files at its top level plus named subfolders for
    curated sets — both files and folders are expected to keep being added
    over time, and existing files may be moved into a (new or existing)
    subfolder. A filename hardcoded in EXPECTED_MIN_BOUNDARIES below should
    still be found and tested even after such a move.
    """
    direct = os.path.join(_SAMPLE_DIR, name)
    if os.path.exists(direct):
        return direct
    for dirpath, _dirnames, filenames in os.walk(_SAMPLE_DIR):
        if name in filenames:
            return os.path.join(dirpath, name)
    return direct


import ezdxf

from core.region_detector import analyze_dxf_regions
from core.layer_consolidator import (
    consolidate_layers, BOUNDARIES_LAYER, IMPORTED_LAYER,
)

# Minimum expected boundary line counts (established 2026-06-15).
EXPECTED_MIN_BOUNDARIES = {
    'EE6868-500-01C.dxf': 100,
    'EE6888-602-01A.dxf': 15,
}

_ALLOWED_LAYERS = {'0', 'Defpoints', BOUNDARIES_LAYER, IMPORTED_LAYER}


def _region_perimeter_covered(region, boundary_lines, tol=1.0):
    """True if all four extreme sides of the region have a boundary line.

    Shared edges between nested regions are attributed by line span overlap
    (not midpoint) so that a long edge serving two regions counts for both.
    """
    xs = [p[0] for p in region['polygon']]
    ys = [p[1] for p in region['polygon']]
    xl, xr, yb, yt = min(xs), max(xs), min(ys), max(ys)
    sides = {'L': False, 'R': False, 'B': False, 'T': False}
    for (s, e) in boundary_lines:
        vert = abs(s[0] - e[0]) <= tol
        horz = abs(s[1] - e[1]) <= tol
        mx = (s[0] + e[0]) / 2.0
        my = (s[1] + e[1]) / 2.0
        ylo, yhi = min(s[1], e[1]), max(s[1], e[1])
        xlo, xhi = min(s[0], e[0]), max(s[0], e[0])
        if vert and abs(mx - xl) <= tol and yhi >= yb - tol and ylo <= yt + tol:
            sides['L'] = True
        if vert and abs(mx - xr) <= tol and yhi >= yb - tol and ylo <= yt + tol:
            sides['R'] = True
        if horz and abs(my - yb) <= tol and xhi >= xl - tol and xlo <= xr + tol:
            sides['B'] = True
        if horz and abs(my - yt) <= tol and xhi >= xl - tol and xlo <= xr + tol:
            sides['T'] = True
    return all(sides.values())


def check_file(path):
    name = os.path.basename(path)
    analysis = analyze_dxf_regions(path)
    error = analysis.get('error')
    if error:
        if '図面枠' in error and '見つかりませんでした' in error:
            # Sample pool is shared across projects (Tools/sample-dxf/); some
            # files there don't use the ULVAC frame/boundary convention this
            # test exercises (e.g. fixtures curated for other projects).
            # That's not a regression in this code, so skip rather than fail.
            print(f"{name}: skip (no drawing frame detected)")
            return None
        print(f"{name}: FAIL analysis error: {error}")
        return False

    doc = ezdxf.readfile(path)
    stats = consolidate_layers(doc, analysis['regions'])
    ok = True

    # 1. Only the two target layers (plus protected) remain.
    remaining = {layer.dxf.name for layer in doc.layers}
    extra = remaining - _ALLOWED_LAYERS
    if extra:
        print(f"{name}: FAIL leftover layers: {sorted(extra)}")
        ok = False

    # 2. Every modelspace entity is on Boundaries or Imported.
    bad = {e.dxf.layer for e in doc.modelspace()
           if hasattr(e.dxf, 'layer') and e.dxf.layer not in (BOUNDARIES_LAYER, IMPORTED_LAYER)}
    if bad:
        print(f"{name}: FAIL modelspace entities on unexpected layers: {sorted(bad)}")
        ok = False

    # 3. Boundary count meets the recorded minimum.
    min_b = EXPECTED_MIN_BOUNDARIES.get(name)
    if min_b is not None and stats['boundaries'] < min_b:
        print(f"{name}: FAIL boundaries {stats['boundaries']} < {min_b}")
        ok = False

    # 4. Every region's rectangle perimeter is represented in Boundaries.
    blines = [(e.dxf.start, e.dxf.end) for e in doc.modelspace()
              if e.dxf.layer == BOUNDARIES_LAYER and e.dxftype() == 'LINE']
    uncovered = [r['default_name'] for r in analysis['regions']
                 if not _region_perimeter_covered(r, blines)]
    if uncovered:
        print(f"{name}: FAIL regions without full perimeter: {uncovered}")
        ok = False

    print(f"{name}: {'OK' if ok else 'FAIL'} "
          f"(boundaries={stats['boundaries']}, imported={stats['imported']}, "
          f"removed={len(stats['removed'])})")
    return ok


def main(argv):
    if argv[1:]:
        paths = argv[1:]
    else:
        discovered = glob.glob(os.path.join(_SAMPLE_DIR, 'EE*.dxf'))
        # Make sure every EXPECTED_MIN_BOUNDARIES fixture is included even if
        # it has moved into a subfolder the flat top-level glob doesn't see.
        expected_paths = [_find_sample(name) for name in EXPECTED_MIN_BOUNDARIES]
        paths = sorted(set(discovered) | {p for p in expected_paths if os.path.exists(p)})
    if not paths:
        print("No EE*.dxf samples found — skipping layer consolidation regression.")
        print('PASS')
        return 0
    results = [check_file(p) for p in paths]
    ok = all(r is not False for r in results)
    print('PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
