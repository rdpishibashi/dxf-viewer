"""Regression test for plain_mtext-based search text normalization.

Verifies that `clean_mtext_format_codes` (utils/text_utils.py) — adopted to fix
search matching against MTEXT format codes — behaves correctly on real ULVAC
drawings and never re-introduces the old behaviour where `\\A` / `\\W` / `\\T`
codes leaked into the searchable text. Also verifies `normalize_width` (same
module), used by Search Text/Boundary to match a query typed in one width
(zenkaku/hankaku) against a label written in the other.

Run:
    python tests/regression/test_mtext_clean_search.py [path/to/EE*.dxf ...]

Without arguments it auto-discovers EE*.dxf in sample-dxf/ (symlinked from
Tools/sample-dxf/, shared across projects). The DXF samples are not committed;
the test is skipped (exit 0) when none are present.
"""

import glob
import os
import sys

# Make the project root importable when run directly.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_SAMPLE_DIR = os.path.join(_ROOT, 'sample-dxf')

import ezdxf

from core.search_manager import SearchManager
from utils.text_utils import clean_mtext_format_codes, normalize_width


# A handful of synthetic cases that must always hold, regardless of sample data.
UNIT_CASES = [
    # (raw, expected)
    (r'\A1;\W0.909755;\T0.909755;MPD RACK1', 'MPD RACK1'),
    (r'\A1;\W0.759555;\T0.759555;TRANSFOMER\PTEMP.LIMIT(MPD)',
     'TRANSFOMER TEMP.LIMIT(MPD)'),
    (r'\A1;\W0.909755;\T0.909755;to\PSYSTEM\PINTERLOCK\P(-514)',
     'to SYSTEM INTERLOCK (-514)'),
    ('\\A1;\\W1.387564;\\T1.250633;　', ''),      # full-width-space-only cell
    ('      When a heater is broken', 'When a heater is broken'),
    ('', ''),
]

# Format-code fragments that must NEVER survive into searchable text.
FORBIDDEN_SUBSTRINGS = (r'\A', r'\W', r'\T', r'\P', r'\H', r'\C', '{', '}')

# normalize_width: full-width (zenkaku) Latin letters/digits/symbols must fold
# to their half-width (hankaku) form; kana/kanji must be left untouched.
WIDTH_CASES = [
    ('ＳＹＳＴＥＭ', 'SYSTEM'),
    ('SYSTEM', 'SYSTEM'),
    ('ＲＡＣＫ１', 'RACK1'),
    ('Ｉ／Ｆ', 'I/F'),
    ('ラック１', 'ラック1'),   # katakana untouched, only the digit folds
    ('', ''),
]


def run_unit_cases():
    failures = []
    for raw, expected in UNIT_CASES:
        got = clean_mtext_format_codes(raw)
        if got != expected:
            failures.append(f"  raw={raw!r}\n    expected={expected!r}\n    got     ={got!r}")
    if failures:
        print("UNIT CASES FAILED:")
        print('\n'.join(failures))
        return False
    print(f"unit cases: {len(UNIT_CASES)} passed")

    width_failures = []
    for raw, expected in WIDTH_CASES:
        got = normalize_width(raw)
        if got != expected:
            width_failures.append(f"  raw={raw!r}\n    expected={expected!r}\n    got     ={got!r}")
    if width_failures:
        print("WIDTH CASES FAILED:")
        print('\n'.join(width_failures))
        return False
    print(f"width cases: {len(WIDTH_CASES)} passed")
    return True


def _find_sample(name):
    """Find a sample DXF by exact filename anywhere under the shared pool
    (same lookup as tests/regression/test_region_search.py's _find_sample)."""
    direct = os.path.join(_SAMPLE_DIR, name)
    if os.path.exists(direct):
        return direct
    for dirpath, _dirnames, filenames in os.walk(_SAMPLE_DIR):
        if name in filenames:
            return os.path.join(dirpath, name)
    return direct


def check_width_insensitive_search(paths):
    """Search Text must find a label regardless of the width the query and
    the label happen to use (zenkaku query vs hankaku label and vice versa).
    """
    ok = True
    for path in paths:
        name = os.path.basename(path)
        doc = ezdxf.readfile(path)
        hankaku = SearchManager.find_text_entities(doc, 'SYSTEM', False, False)
        zenkaku = SearchManager.find_text_entities(doc, 'ＳＹＳＴＥＭ', False, False)
        if len(hankaku) != len(zenkaku):
            print(f"{name}: FAIL width-insensitive search mismatch "
                  f"(hankaku query={len(hankaku)}, zenkaku query={len(zenkaku)})")
            ok = False
        else:
            print(f"{name}: width-insensitive search OK ({len(hankaku)} hits both ways)")

    # EE6492-039-38A.dxf's labels are written entirely in zenkaku (e.g.
    # ＳＹＳＴＥＭ　Ｉ／Ｆ　ＢＯＸ) — this is the fixture proving the hankaku
    # query side actually crosses the width boundary, not just a 0==0 no-op.
    zenkaku_labeled = _find_sample('EE6492-039-38A.dxf')
    if os.path.exists(zenkaku_labeled):
        doc = ezdxf.readfile(zenkaku_labeled)
        hits = SearchManager.find_text_entities(doc, 'SYSTEM', False, False)
        if not hits:
            print("EE6492-039-38A.dxf: FAIL hankaku query 'SYSTEM' found 0 hits "
                  "against zenkaku-only labels")
            ok = False
        else:
            print(f"EE6492-039-38A.dxf: hankaku query crosses width boundary OK "
                  f"({len(hits)} hits)")

    return ok


def iter_text(doc):
    for e in doc.modelspace():
        if e.dxftype() in ('TEXT', 'MTEXT'):
            yield e
    for b in doc.blocks:
        if b.name.startswith('*'):
            continue
        for e in b:
            if e.dxftype() in ('TEXT', 'MTEXT'):
                yield e


def check_no_format_leak(paths):
    ok = True
    for path in paths:
        doc = ezdxf.readfile(path)
        total = leaks = 0
        for e in iter_text(doc):
            total += 1
            raw = e.dxf.text if hasattr(e.dxf, 'text') else ''
            cleaned = clean_mtext_format_codes(raw)
            if any(s in cleaned for s in FORBIDDEN_SUBSTRINGS):
                leaks += 1
                if leaks <= 5:
                    print(f"  LEAK in {os.path.basename(path)}: {cleaned!r} (raw={raw!r})")
        status = 'OK' if leaks == 0 else f'{leaks} LEAKS'
        print(f"{os.path.basename(path)}: {total} entities, {status}")
        ok = ok and leaks == 0
    return ok


def main(argv):
    paths = argv[1:] or sorted(glob.glob(os.path.join(_SAMPLE_DIR, 'EE*.dxf')))
    ok = run_unit_cases()
    if not paths:
        print("No EE*.dxf samples found — skipping sample-data check.")
    else:
        ok = check_no_format_leak(paths) and ok
        ok = check_width_insensitive_search(paths) and ok
    print('PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
