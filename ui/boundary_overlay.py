"""Scene-level rendering helpers for the boundary (region) search highlight.

Everything here operates on a :class:`~core.tab_manager.DXFTab` (``tab_data``)
and the Qt graphics scene inside its CAD viewer — none of it needs the main
window, so it lives outside ``ui.main_window`` to keep that class focused on
orchestration (dialogs, actions, status bar) rather than scene drawing.

The counterpart *matching* logic (which regions match a query) is UI-free and
lives in ``core.region_search_manager``.
"""

from PyQt5.QtWidgets import QGraphicsPolygonItem
from PyQt5.QtCore import Qt, QPointF, QRectF
from PyQt5.QtGui import QColor, QPen, QPolygonF, QPainterPath, QPainterPathStroker

from core.region_detector import extract_text_from_entity

# Same red as the plain text search highlight, so a matched label stands out
# inside its (also red-outlined) region.
RED_COLOR_INDEX = 1
RED_RGB = 0xFF0000


class _OverlayPolygonItem(QGraphicsPolygonItem):
    """Polygon overlay whose hit area is only its thin outline, not its interior.

    ezdxf's CADGraphicsViewWithOverlay picks the hovered/clicked element via
    ``scene().items(pos)`` and highlights the topmost one. A normal polygon item
    reports its filled interior as its shape, so it would be that topmost item
    across the whole region, stealing hover/clicks from the symbols and wiring
    underneath. Overriding ``shape()`` to return just the stroked outline keeps
    the interior click-through while the item still paints its red boundary.
    (An empty shape would also stop the item from being painted.)
    """

    _HIT_WIDTH = 3.0  # scene units — thin band along the boundary only

    def shape(self):
        outline = QPainterPath()
        outline.addPolygon(self.polygon())
        outline.closeSubpath()
        stroker = QPainterPathStroker()
        stroker.setWidth(self._HIT_WIDTH)
        return stroker.createStroke(outline)


def draw_boundary_overlays(tab_data, regions):
    """Draw matched region outlines as overlay items on the CAD scene."""
    graphics_view = tab_data.cad_viewer.graphics_view
    scene = graphics_view.scene() if graphics_view else None
    if scene is None:
        return

    pen = QPen(QColor(255, 0, 0))  # red boundary highlight
    pen.setWidthF(2.0)
    pen.setCosmetic(True)  # constant pixel width regardless of zoom

    for region in regions:
        # Entities are placed in the scene at their true DXF coordinates;
        # the view applies the vertical flip, so overlays use (x, y) too.
        qpoly = QPolygonF([QPointF(px, py) for (px, py) in region['polygon']])
        # _OverlayPolygonItem's shape() is only the thin outline, so it is
        # effectively ignored by the CAD viewer's scene().items(pos)
        # hover/click picking — symbols and wiring inside the region stay
        # hoverable and selectable.
        item = _OverlayPolygonItem(qpoly)
        item.setPen(pen)
        item.setZValue(1e9)  # keep the outline above the drawing
        scene.addItem(item)
        tab_data.boundary_overlay_items.append(item)


def remove_boundary_overlays(tab_data):
    """Remove overlay items from the scene and clear the list."""
    graphics_view = tab_data.cad_viewer.graphics_view
    scene = graphics_view.scene() if graphics_view else None
    for item in tab_data.boundary_overlay_items:
        try:
            if scene is not None:
                scene.removeItem(item)
        except Exception:
            pass
    tab_data.boundary_overlay_items = []


def zoom_to_regions(tab_data, regions):
    """Fit the view to the bounding box of all matched regions."""
    graphics_view = tab_data.cad_viewer.graphics_view
    if not graphics_view or not regions:
        return

    xs, ys = [], []
    for region in regions:
        for (px, py) in region['polygon']:
            xs.append(px)
            ys.append(py)  # scene coordinates == true DXF coordinates
    if not xs:
        return

    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    margin = 0.05 * max(width, height, 1.0)
    rect = QRectF(min(xs) - margin, min(ys) - margin,
                  width + 2 * margin, height + 2 * margin)
    graphics_view.fitInView(rect, Qt.KeepAspectRatio)


def dim_all_entities(tab_data):
    """Dim every entity to the selected dim color (boundary search)."""
    dim_index, dim_rgb = tab_data.search_dim_color

    def dim(entity):
        if hasattr(entity.dxf, 'color'):
            try:
                entity.dxf.color = dim_index
                entity.dxf.true_color = dim_rgb
            except Exception:
                pass

    for entity in tab_data.dxf_doc.modelspace():
        dim(entity)
    for block in tab_data.dxf_doc.blocks:
        if not block.name.startswith('*'):
            for entity in block:
                dim(entity)


def highlight_matched_labels(tab_data, matched_regions):
    """Color the label entity that produced each matched region name in red,
    the same red used by the plain text search, so the matched string
    stands out inside its (also red-outlined) region.

    Matching is done by (cleaned text, position) against the coordinates
    ``RegionSearchManager.find_matching_regions`` recorded for the matched
    candidate. Only direct modelspace TEXT/MTEXT entities are addressable
    this way: a label coming from an INSERT-expanded block is a virtual
    copy with no independent on-screen identity (the real entity lives in
    the block definition at block-local coordinates, shared by every
    INSERT of that block), so it is left dimmed like plain text search
    already does for block-sourced matches (see SearchManager).
    """
    targets = set()
    for region in matched_regions:
        for (text, x, y) in region.get('matched_labels', []):
            targets.add((text, round(x, 3), round(y, 3)))
    if not targets:
        return

    for entity in tab_data.dxf_doc.modelspace():
        if entity.dxftype() not in ('TEXT', 'MTEXT'):
            continue
        _, clean_text, (x, y) = extract_text_from_entity(entity)
        if not clean_text:
            continue
        if (clean_text, round(x, 3), round(y, 3)) not in targets:
            continue
        if hasattr(entity.dxf, 'color'):
            try:
                entity.dxf.color = RED_COLOR_INDEX
                entity.dxf.true_color = RED_RGB
            except Exception:
                pass
