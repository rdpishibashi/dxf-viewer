"""Custom CAD viewer widget with enhanced functionality."""

from ezdxf.addons.drawing.qtviewer import (
    CADViewer, CADWidget, CADGraphicsView, CADGraphicsViewWithOverlay,
)
from ezdxf.addons.drawing.config import Configuration
from ezdxf.addons.drawing.pyqt import PyQtBackend
from ezdxf.npshapes import to_qpainter_path
from PyQt5.QtCore import Qt, QEvent
from PyQt5.QtWidgets import QGraphicsView, QGraphicsPathItem
from PyQt5.QtGui import QBrush, QColor, QPainterPathStroker


class _ClickThroughPathItem(QGraphicsPathItem):
    """QGraphicsPathItem with outline-only hit area.

    Qt's qt_graphicsItem_shapeFromPath() calls addPath(path) on the stroked
    outline, so a closed QPainterPath's interior becomes part of the hit area
    and blocks hover/click detection of entities drawn underneath (e.g. entities
    inside a closed LWPOLYLINE).  Overriding shape() to return only the stroked
    outline makes the enclosed interior transparent to mouse events.
    """

    _HIT_WIDTH = 3.0  # scene units — narrow band along the outline

    def shape(self):
        stroker = QPainterPathStroker()
        stroker.setWidth(self._HIT_WIDTH)
        return stroker.createStroke(self.path())


class _ClickThroughBackend(PyQtBackend):
    """PyQtBackend that renders path entities with outline-only hit areas.

    Closed LWPOLYLINE entities go through draw_path().  With the default
    QGraphicsPathItem, a closed path's interior is included in shape(), so
    the LWPOLYLINE blocks hover detection of entities drawn inside it.
    Using _ClickThroughPathItem here makes the closed-path interior
    transparent to mouse events while keeping the outline selectable.
    """

    def draw_path(self, path, properties):
        if len(path) == 0:
            return
        item = _ClickThroughPathItem(to_qpainter_path([path]))
        item.setPen(self._get_pen(properties))
        item.setBrush(self._no_fill)
        self._add_item(item, properties.handle)


class _OutlineHighlightGraphicsView(CADGraphicsViewWithOverlay):
    """CADGraphicsViewWithOverlay that highlights only the hovered item's
    hit outline instead of its full bounding box.

    ezdxf's drawForeground() fills item.boundingRect() in green. For a closed
    path item (e.g. a closed LWPOLYLINE rendered as a region boundary),
    boundingRect() spans the entire enclosed area, so hovering near one edge
    paints the whole region green and obscures the entity actually under the
    cursor. Filling item.shape() instead confines the highlight to the
    outline band that was actually hit-tested (a no-op for plain LINE items,
    whose shape() already approximates their boundingRect()).
    """

    def mouseMoveEvent(self, event):
        # Without this guard, cursor movement alone (no button pressed) pans
        # the view in large multi-drawing DXF files.  The cause is that
        # AnchorUnderMouse — set by CADGraphicsView.__init__ — scrolls the
        # scene to keep the mouse-under-scene-point fixed whenever any layout
        # shift (e.g. sidebar label refresh) slightly resizes the viewport.
        # For a small single-drawing scene the scroll range is ~0 so the
        # effect is invisible; for a wide multi-drawing scene (scene >> viewport)
        # even a 1-pixel viewport change causes a large visible pan.
        # Fix: when no button is pressed, restore the scroll position after
        # calling super() so hover detection still runs but panning cannot occur.
        if event.buttons() & Qt.LeftButton:
            super().mouseMoveEvent(event)
            return
        h = self.horizontalScrollBar().value()
        v = self.verticalScrollBar().value()
        super().mouseMoveEvent(event)
        self.horizontalScrollBar().setValue(h)
        self.verticalScrollBar().setValue(v)

    def drawForeground(self, painter, rect):
        CADGraphicsView.drawForeground(self, painter, rect)
        if self._selected_items and self._mark_selection:
            item = self._selected_items[self._selected_index]
            path = item.sceneTransform().map(item.shape())
            painter.save()
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(0, 255, 0, 100))
            painter.drawPath(path)
            painter.restore()


class PinchZoomCADViewer(CADViewer):
    """CADViewer with pinch gesture zoom and background color support."""

    def __init__(self):
        super().__init__(
            cad=CADWidget(_OutlineHighlightGraphicsView(), config=Configuration())
        )

        # Hide ezdxf CADViewer's built-in menus (Select Layout, Reload, etc.)
        # so they don't appear in macOS's global menu bar.
        self.menuBar().setNativeMenuBar(False)
        self.menuBar().hide()

        # Replace PyQtBackend with _ClickThroughBackend so that closed path
        # entities (LWPOLYLINE etc.) do not block hover detection of entities
        # inside them.
        self._install_click_through_backend()

        # Enable pinch gesture only
        self.grabGesture(Qt.PinchGesture)

        # Find the graphics view
        self.graphics_view = self._find_graphics_view()

        # Set default background color to black
        if self.graphics_view:
            self.set_background_color(QColor(0, 0, 0))
            # Use center (not mouse position) as anchor when the viewport is
            # resized (e.g. window resize), so that a viewport size change
            # does not shift the scene under the cursor.  TransformationAnchor
            # stays AnchorUnderMouse so wheel-zoom still uses the cursor point.
            self.graphics_view.setResizeAnchor(QGraphicsView.AnchorViewCenter)

    def _install_click_through_backend(self):
        """Inject _ClickThroughBackend into the CADWidget.

        CADWidget._reset_backend() is called from set_document() each time a
        DXF file is (re)loaded.  Monkey-patching that method ensures every
        load uses our custom backend instead of the default PyQtBackend.
        """
        cad = self._cad

        def _reset_backend():
            cad._backend = _ClickThroughBackend()

        cad._reset_backend = _reset_backend
        cad._reset_backend()  # replace the already-created instance immediately

    def _find_graphics_view(self):
        """Find the QGraphicsView within the CADViewer widget tree."""
        def find_graphics_view_recursive(widget):
            if isinstance(widget, QGraphicsView):
                return widget
            for child in widget.findChildren(QGraphicsView):
                if child:
                    return child
            return None

        return find_graphics_view_recursive(self)

    def set_background_color(self, color):
        """Set the background color of the graphics view.

        Args:
            color: QColor object representing the desired background color
        """
        if self.graphics_view:
            self.graphics_view.setBackgroundBrush(QBrush(color))

    def event(self, event):
        """Handle events, specifically pinch gestures."""
        if event.type() == QEvent.Gesture:
            return self.gestureEvent(event)
        return super().event(event)

    def gestureEvent(self, event):
        """Process gesture events."""
        pinch_gesture = event.gesture(Qt.PinchGesture)

        if pinch_gesture:
            self.handlePinchGesture(pinch_gesture)

        return True

    def handlePinchGesture(self, gesture):
        """Handle pinch gesture for zooming.

        Args:
            gesture: QPinchGesture object
        """
        if not self.graphics_view:
            return

        if gesture.state() == Qt.GestureStarted:
            self.graphics_view.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)

        if gesture.state() in [Qt.GestureUpdated, Qt.GestureFinished]:
            scale_factor = gesture.scaleFactor()

            # Adjust scale factor (sensitivity adjustment)
            if scale_factor > 1.0:
                zoom_factor = 1.0 + (scale_factor - 1.0) * 0.3
            else:
                zoom_factor = 1.0 - (1.0 - scale_factor) * 0.3

            # Get current zoom level and apply limits
            current_transform = self.graphics_view.transform()
            current_scale = current_transform.m11()

            # Zoom limits: 0.01x to 100x
            if (zoom_factor > 1.0 and current_scale < 100.0) or \
               (zoom_factor < 1.0 and current_scale > 0.01):
                self.graphics_view.scale(zoom_factor, zoom_factor)
