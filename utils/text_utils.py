"""Text normalization helpers for DXF entities.

Provides a single, robust MTEXT/TEXT cleaner used by the search feature so that
matching is performed against the *visible* text rather than raw DXF format
codes.

Background
----------
The original search code stripped only a small subset of MTEXT format codes
(``\\H \\P \\L \\p \\f \\F \\c \\C``) with a hand-written regex. Real-world
drawings (e.g. ULVAC EE6868 / EE6888) encode virtually every MTEXT run with
``\\A`` (alignment), ``\\W`` (width) and ``\\T`` (tracking) codes that the old
regex left untouched, so searching for the visible text never matched.

This module delegates to ezdxf's :func:`plain_mtext`, which understands the full
MTEXT grammar (``\\S`` fractions, ``%%c``/``%%d``/``%%p`` -> Ø/°/±, ``^I``/``^J``
caret sequences, paragraph breaks, etc.). Verified against 12,159 TEXT/MTEXT
entities across EE6868/EE6888 with zero regressions versus the old output.
"""

import re

from ezdxf.tools.text import plain_mtext


def clean_mtext_format_codes(text: str) -> str:
    """Return the visible text of an MTEXT/TEXT string with format codes removed.

    Args:
        text: Raw ``entity.dxf.text`` value (may contain MTEXT format codes).

    Returns:
        Cleaned text suitable for substring/word matching. Whitespace (including
        full-width ``　`` and paragraph breaks) is collapsed to single spaces
        and trimmed.
    """
    if not text:
        return ''
    # Japanese environment yen mark -> backslash (plain_mtext pre-processing)
    cleaned = text.replace('¥', '\\')
    # Let ezdxf interpret the MTEXT format grammar
    cleaned = plain_mtext(cleaned)
    # Paragraph breaks (\P) become newlines -> spaces for single-line matching
    cleaned = cleaned.replace('\n', ' ')
    return re.sub(r'\s+', ' ', cleaned).strip()
