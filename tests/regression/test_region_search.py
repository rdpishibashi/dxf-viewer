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

import ezdxf

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.region_detector import analyze_dxf_regions, extract_text_from_entity
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
    # min_regions は2026-06-21に10→9から9→8へ修正。境界線と同じ線種を持つが
    # どこにも閉じていない「行き止まり枝」を面探索前に除去するようになったことで
    # （行き止まり枝の往復が頂点座標を汚すアーティファクト対策）、frame=0 の同一
    # 物理領域が「綺麗な4頂点版（名称候補1件: CN I/F B.D TYPE3 (CN-IF3-1A)）」と
    # 「枝の往復で座標が汚れ bbox が変わった12頂点版（無関係なラベルまで誤って
    # 名称候補に取り込んでいた、例 SB-1A(L1)）」の2領域として重複検出されていたバグ
    # も同時に解消され、1領域に統合された（面積27.89%は両者で一致）。
    'DE5434-553-10B.dxf': {
        'frames': 5,
        'min_regions': 8,
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

    # Direct-modelspace (clean_text, rounded x, y) -> True, for resolving matched_labels
    # back to a real on-screen entity (the boundary search highlights this entity, not
    # just the region outline; see ui.main_window._highlight_matched_labels).
    direct_labels = set()
    doc = ezdxf.readfile(path)
    for entity in doc.modelspace():
        if entity.dxftype() not in ('TEXT', 'MTEXT'):
            continue
        _, clean_text, (x, y) = extract_text_from_entity(entity)
        if clean_text:
            direct_labels.add((clean_text, round(x, 3), round(y, 3)))

    for (query, cs, ww), expected_count in exp['queries'].items():
        matched = RegionSearchManager.find_matching_regions(analysis, query, cs, ww)
        got = len(matched)
        if got != expected_count:
            print(f"{name}: FAIL query={query!r} case={cs} whole={ww} "
                  f"got {got} != {expected_count}")
            ok = False

        for region in matched:
            labels = region.get('matched_labels', [])
            if not labels:
                print(f"{name}: FAIL query={query!r} region id={region['id']} "
                      "matched with no matched_labels (highlight would do nothing)")
                ok = False
                continue
            for (text, x, y) in labels:
                if (text, round(x, 3), round(y, 3)) not in direct_labels:
                    print(f"{name}: FAIL query={query!r} matched_labels entry "
                          f"{(text, x, y)!r} does not resolve to a modelspace entity")
                    ok = False

    ok = check_corner_search(name, analysis) and ok

    print(f"{name}: {'OK' if ok else 'FAIL'} (frames={frames}, regions={regions})")
    return ok


def check_corner_search(name, analysis):
    """Round-trip: format a region's corners like DXF-extract-labels's
    popover ("頂点の座標"), parse it back, and confirm it resolves to that
    same region (and only that region).
    """
    ok = True
    regions = analysis.get('regions', [])
    # A handful of regions is enough to exercise the round-trip without
    # making this regression test slow on files with many regions.
    for region in regions[:5]:
        corners = region.get('corners', [])
        if not corners:
            continue
        text = '\n'.join(f"{i + 1}: ({x:.2f}, {y:.2f})" for i, (x, y) in enumerate(corners))

        parsed = RegionSearchManager.parse_corner_list(text)
        if parsed != [(round(x, 2), round(y, 2)) for (x, y) in corners]:
            print(f"{name}: FAIL parse_corner_list round-trip mismatch for "
                  f"region id={region['id']}")
            ok = False
            continue

        matched = RegionSearchManager.find_region_by_corners(analysis, parsed)
        if len(matched) != 1:
            print(f"{name}: FAIL corner search for region id={region['id']} "
                  f"matched {len(matched)} regions, expected 1")
            ok = False
            continue
        if matched[0]['id'] != region['id'] or matched[0]['frame'] != region['frame']:
            print(f"{name}: FAIL corner search for region id={region['id']} "
                  f"resolved to a different region {matched[0]['id']!r}")
            ok = False

    # A coordinate list that matches no region must return no match.
    bogus = [(1.0, 1.0), (2.0, 1.0), (2.0, 2.0), (1.0, 2.0)]
    if RegionSearchManager.find_region_by_corners(analysis, bogus):
        print(f"{name}: FAIL corner search matched a region for unrelated coordinates")
        ok = False

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
