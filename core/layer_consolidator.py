"""Layer consolidation for boundary search results.

Collapses a drawing's many source layers (e.g. the ``NoLayerName_xxx`` layers
seen in ULVAC exports) into two clearly named English layers:

  - ``Boundaries`` : the boundary linework of the detected rectangular regions
  - ``Imported``   : every other entity

Region-boundary lines are identified by the region-detection geometry: a
modelspace LINE that uses the region line style (lineweight 25 / ACI color 2)
and lies on an edge of a detected region polygon. Block-definition and other
entities are placed in ``Imported`` (block content is shared across INSERTs and
is not reclassified geometrically).

Modelspace LWPOLYLINE entities using the region line style are exploded into
individual LINE/ARC entities first (see ``_explode_region_style_lwpolylines``),
so that a polyline with only some of its segments on a region edge can have
those segments classified into ``Boundaries`` independently of the rest —
a single LWPOLYLINE entity cannot be split between the two layers as a whole.

The operation mutates the in-memory document only; the source file is untouched,
so reopening the file restores the original layers.
"""

from core.region_detector import DEFAULT_REGION_CONFIG

BOUNDARIES_LAYER = "Boundaries"
IMPORTED_LAYER = "Imported"

# Layers that must never be removed from the table.
_PROTECTED_LAYERS = {"0", "Defpoints", BOUNDARIES_LAYER, IMPORTED_LAYER}


def _merge_intervals(items, level_tol):
    """Merge same-level intervals [(level, lo, hi), ...] into maximal spans.

    Groups by level (within ``level_tol``) and unions overlapping/touching
    intervals so that a region edge split across collinear intermediate
    vertices becomes one span.
    """
    if not items:
        return []
    items = sorted(items)
    out = []
    group = [items[0]]
    for it in items[1:]:
        if it[0] - group[-1][0] <= level_tol:
            group.append(it)
        else:
            out.extend(_union_group(group))
            group = [it]
    out.extend(_union_group(group))
    return out


def _union_group(group):
    level = sum(g[0] for g in group) / len(group)
    spans = sorted((g[1], g[2]) for g in group)
    merged = [list(spans[0])]
    for lo, hi in spans[1:]:
        if lo <= merged[-1][1] + 1e-6:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    return [(level, lo, hi) for lo, hi in merged]


# Axis-alignment tolerance for region polygon edges. Polygon vertices are the
# product of several upstream clustering/averaging steps (region_detector.py
# uses tolerances from 0.1 to 2.0 for its own coordinate clustering), so two
# vertices that are geometrically "the same point" routinely differ by a few
# micro-units of float noise — observed: a B CHAMBER edge in EE6313-546-01E.dxf
# had endpoints 4.3e-6 apart in y. The previous 1e-6 tolerance was tighter than
# that noise floor, so the edge matched neither the vertical nor the horizontal
# branch and was silently dropped from both lists. 1e-3 absorbs that noise
# while staying far below the real edge-matching tolerance (`tol`, default 0.6
# in `consolidate_layers`), so genuinely diagonal edges are never misclassified.
_AXIS_TOL = 1e-3


def _collect_region_edges(regions, level_tol=0.6):
    """Return merged axis-aligned edges of all region polygons as (V, H).

    V: [(x, y0, y1), ...]  vertical edges
    H: [(y, x0, x1), ...]  horizontal edges
    """
    vertical = []
    horizontal = []
    for region in regions:
        poly = region['polygon']
        n = len(poly)
        for i in range(n):
            x1, y1 = poly[i]
            x2, y2 = poly[(i + 1) % n]
            if abs(x1 - x2) <= _AXIS_TOL and abs(y1 - y2) > _AXIS_TOL:
                vertical.append((x1, min(y1, y2), max(y1, y2)))
            elif abs(y1 - y2) <= _AXIS_TOL and abs(x1 - x2) > _AXIS_TOL:
                horizontal.append((y1, min(x1, x2), max(x1, x2)))
    return _merge_intervals(vertical, level_tol), _merge_intervals(horizontal, level_tol)


def _line_on_edges(start, end, vertical, horizontal, tol):
    """True if a line segment overlaps (any extent of) a region edge at the
    same level.

    Uses overlap rather than full-containment: a real boundary LINE entity
    may physically run a bit past the exact polygon corner (e.g. continuing
    into a T-junction with unrelated geometry, or shared with adjacent
    untracked space), so requiring the entity to fall entirely within the
    edge's span would wrongly exclude it. This matches the overlap semantics
    the regression test's own perimeter-coverage check already uses
    (`tests/regression/test_layer_consolidation.py::_region_perimeter_covered`),
    so the feature and its test agree on what counts as "on" an edge.
    """
    x1, y1 = start[0], start[1]
    x2, y2 = end[0], end[1]
    if abs(x1 - x2) <= tol and abs(y1 - y2) > tol:  # vertical line
        lx = (x1 + x2) / 2.0
        lo, hi = min(y1, y2), max(y1, y2)
        for (ex, ey0, ey1) in vertical:
            if abs(lx - ex) <= tol and hi >= ey0 - tol and lo <= ey1 + tol:
                return True
    elif abs(y1 - y2) <= tol and abs(x1 - x2) > tol:  # horizontal line
        ly = (y1 + y2) / 2.0
        lo, hi = min(x1, x2), max(x1, x2)
        for (ey, ex0, ex1) in horizontal:
            if abs(ly - ey) <= tol and hi >= ex0 - tol and lo <= ex1 + tol:
                return True
    return False


def _virtual_entity_attribs(entity):
    """Copy the dxf attributes that matter for boundary classification and
    visual fidelity from a (possibly virtual/unassigned) source entity."""
    attribs = {
        'layer': entity.dxf.layer,
        'color': entity.dxf.color,
        'lineweight': entity.dxf.lineweight,
        'linetype': entity.dxf.linetype,
    }
    if entity.dxf.hasattr('true_color'):
        attribs['true_color'] = entity.dxf.true_color
    return attribs


def _explode_region_style_lwpolylines(msp, lineweight, color):
    """Replace modelspace LWPOLYLINEs using the region line style with
    individual LINE/ARC entities (one per segment), so each segment can be
    classified into Boundaries/Imported independently by `_is_region_boundary_line`.

    `LWPolyline.virtual_entities()` yields LINE (straight segments) and ARC
    (bulge segments) primitives in the polyline's true location, inheriting
    its layer/color/lineweight/linetype; ARC segments are never boundary
    candidates (the detector only matches straight LINE edges) and simply end
    up in Imported like any other non-matching geometry, same as today.

    Only LWPOLYLINEs matching the region line style are exploded — anything
    else is left untouched and classified wholesale, same as before.
    """
    candidates = [
        e for e in msp
        if e.dxftype() == 'LWPOLYLINE'
        and getattr(e.dxf, 'lineweight', None) == lineweight
        and getattr(e.dxf, 'color', None) == color
    ]
    for lwp in candidates:
        for v in lwp.virtual_entities():
            attribs = _virtual_entity_attribs(v)
            if v.dxftype() == 'LINE':
                msp.add_line(v.dxf.start, v.dxf.end, dxfattribs=attribs)
            elif v.dxftype() == 'ARC':
                msp.add_arc(v.dxf.center, v.dxf.radius,
                            v.dxf.start_angle, v.dxf.end_angle, dxfattribs=attribs)
        msp.delete_entity(lwp)


def _is_region_boundary_line(entity, vertical, horizontal, lineweight, color, tol):
    if entity.dxftype() != 'LINE':
        return False
    if getattr(entity.dxf, 'lineweight', None) != lineweight:
        return False
    if getattr(entity.dxf, 'color', None) != color:
        return False
    return _line_on_edges(entity.dxf.start, entity.dxf.end, vertical, horizontal, tol)


def consolidate_layers(doc, regions, config=None, tol=0.6):
    """Reassign every entity to the ``Boundaries`` or ``Imported`` layer.

    Args:
        doc: ezdxf document to modify in place.
        regions: detected region dicts (``analysis['regions']``).
        config: optional region-config overrides (for line style keys).
        tol: coordinate tolerance for matching a line to a region edge.

    Returns:
        dict with ``boundaries`` / ``imported`` entity counts and the list of
        ``removed`` layer names.
    """
    cfg = dict(DEFAULT_REGION_CONFIG)
    if config:
        cfg.update(config)
    region_lw = cfg['region_lineweight']
    region_color = cfg['region_color']

    _explode_region_style_lwpolylines(doc.modelspace(), region_lw, region_color)

    vertical, horizontal = _collect_region_edges(regions or [])

    # Ensure the two target layers exist.
    if BOUNDARIES_LAYER not in doc.layers:
        doc.layers.add(BOUNDARIES_LAYER)
    if IMPORTED_LAYER not in doc.layers:
        doc.layers.add(IMPORTED_LAYER)

    boundaries = 0
    imported = 0

    # Modelspace: classify boundary lines geometrically.
    for entity in doc.modelspace():
        if not hasattr(entity.dxf, 'layer'):
            continue
        if _is_region_boundary_line(entity, vertical, horizontal,
                                    region_lw, region_color, tol):
            entity.dxf.layer = BOUNDARIES_LAYER
            boundaries += 1
        else:
            entity.dxf.layer = IMPORTED_LAYER
            imported += 1

    # Paperspace layouts and block definitions -> Imported (not reclassified).
    for layout in doc.layouts:
        if layout.name.lower() == 'model':
            continue
        for entity in layout:
            if hasattr(entity.dxf, 'layer'):
                entity.dxf.layer = IMPORTED_LAYER
                imported += 1
    for block in doc.blocks:
        if block.name.startswith('*'):
            continue
        for entity in block:
            if hasattr(entity.dxf, 'layer'):
                entity.dxf.layer = IMPORTED_LAYER
                imported += 1

    # Remove the now-unused source layers.
    removed = []
    for layer in list(doc.layers):
        name = layer.dxf.name
        if name in _PROTECTED_LAYERS or name.startswith('*'):
            continue
        try:
            doc.layers.remove(name)
            removed.append(name)
        except Exception:
            pass

    return {'boundaries': boundaries, 'imported': imported, 'removed': removed}
