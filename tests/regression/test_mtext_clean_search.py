"""Regression test for plain_mtext-based search text normalization.

Verifies that `clean_mtext_format_codes` (utils/text_utils.py) — adopted to fix
search matching against MTEXT format codes — behaves correctly on real ULVAC
drawings and never re-introduces the old behaviour where `\\A` / `\\W` / `\\T`
codes leaked into the searchable text.

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

from utils.text_utils import clean_mtext_format_codes


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
    return True


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
    print('PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
