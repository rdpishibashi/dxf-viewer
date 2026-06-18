"""Regression test for boundary (rectangular region) search.

Exercises the UI-independent core: region detection (`core.region_detector`)
and name matching (`core.region_search_manager`) against the real ULVAC sample
drawings. The overlay drawing itself is GUI code and is not covered here.

Run:
    python tests/regression/test_region_search.py [path/to/EE*.dxf ...]

The DXF samples are not committed; the sample-data checks are skipped (exit 0)
when the files are absent.
"""

import glob
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.region_detector import analyze_dxf_regions
from core.region_search_manager import RegionSearchManager


# Expected detection/matching per sample file (established 2026-06-15).
EXPECTED = {
    'EE6868-500-01C.dxf': {
        'frames': 13,
        'min_regions': 20,
        'queries': {
            ('RACK1', False, False): 18,   # 'RACK1' + 'MPD RACK1'
            ('rack1', True, False): 0,      # case-sensitive miss
            ('MPD', False, False): 10,      # 'MPD RACK1' + 'MPD RACK2'
            ('NONEXIST', False, False): 0,
        },
    },
    'EE6888-602-01A.dxf': {
        'frames': 1,
        'min_regions': 3,
        'queries': {
            ('SYSTEM', False, False): 1,
            ('SB-1A', False, False): 2,
            ('nonexist', False, False): 0,
        },
    },
    # EE6888-631-01A / EE6492-631-02A: boundaries drawn as LWPOLYLINE (not LINE).
    # Frame detection uses _merge_collinear(bridge=False) to join split frame sides.
    # Region detection uses LINE-first 2-pass with LWPOLYLINE fallback (2026-06-17).
    'EE6888-631-01A.dxf': {
        'frames': 1,
        'min_regions': 4,
        'queries': {
            # 'SYSTEM' matches 4: 2 regions named 'SYSTEM I/F BOX' + 2 'SB-1A' regions
            # that list 'SYSTEM I/F BOX' as a name candidate.
            ('SYSTEM', False, False): 4,
            ('SB-1A', False, False): 2,
            ('nonexist', False, False): 0,
        },
    },
    'EE6492-631-02A.dxf': {
        'frames': 1,
        'min_regions': 4,
        'queries': {
            ('SYSTEM', False, False): 4,
            ('SB-1A', False, False): 2,
            ('nonexist', False, False): 0,
        },
    },
    # 図面枠・領域境界線は通常向きだが、ラベル(MTEXT)の大半が90°回転して描かれている
    # ファイル。名称ラベルが横エッジでなく縦エッジ脇に置かれ、かつ部品が横線分（本来の
    # 縦線分に相当）を途切れさせるため、90°回転対応（縦エッジ名称フォールバック・
    # 横線分ギャップ橋渡し）が無いと regions=0 になっていた（2026-06-18 修正）。
    'DE5434-553-10B.dxf': {
        'frames': 5,
        'min_regions': 9,
        'queries': {
            ('LA CHAMBER', False, False): 3,
            ('CONTROL BOX CORE FX', False, False): 2,
            ('CONTROL BOX CORE RX', False, False): 2,
            ('NONEXIST', False, False): 0,
        },
    },
}


def check_file(path):
    name = os.path.basename(path)
    exp = EXPECTED.get(name)
    if exp is None:
        print(f"{name}: no expectations recorded — skipping")
        return True

    analysis = analyze_dxf_regions(path)
    if analysis.get('error'):
        print(f"{name}: FAIL analysis error: {analysis['error']}")
        return False

    ok = True
    frames = len(analysis['frames'])
    regions = len(analysis['regions'])
    if frames != exp['frames']:
        print(f"{name}: FAIL frames {frames} != {exp['frames']}")
        ok = False
    if regions < exp['min_regions']:
        print(f"{name}: FAIL regions {regions} < {exp['min_regions']}")
        ok = False

    for (query, cs, ww), expected_count in exp['queries'].items():
        got = len(RegionSearchManager.find_matching_regions(analysis, query, cs, ww))
        if got != expected_count:
            print(f"{name}: FAIL query={query!r} case={cs} whole={ww} "
                  f"got {got} != {expected_count}")
            ok = False

    print(f"{name}: {'OK' if ok else 'FAIL'} (frames={frames}, regions={regions})")
    return ok


def main(argv):
    paths = argv[1:] or sorted(
        glob.glob(os.path.join(_ROOT, 'EE*.dxf')) + glob.glob(os.path.join(_ROOT, 'DE*.dxf')))
    if not paths:
        print("No EE*.dxf samples found — skipping region search regression.")
        print('PASS')
        return 0
    ok = all(check_file(p) for p in paths)
    print('PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
