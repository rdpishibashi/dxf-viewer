"""Custom CAD viewer widget with enhanced functionality."""

from ezdxf.addons.drawing.qtviewer import CADViewer
from PyQt5.QtCore import Qt, QEvent
from PyQt5.QtWidgets import QGraphicsView
from PyQt5.QtGui import QBrush, QColor


class PinchZoomCADViewer(CADViewer):
    """CADViewer with pinch gesture zoom and background color support."""

    def __init__(self):
        super().__init__()

        # Hide ezdxf CADViewer's built-in menus (Select Layout, Reload, etc.)
        # so they don't appear in macOS's global menu bar.
        self.menuBar().setNativeMenuBar(False)
        self.menuBar().hide()

        # Enable pinch gesture only
        self.grabGesture(Qt.PinchGesture)

        # Find the graphics view
        self.graphics_view = self._find_graphics_view()

        # Set default background color to black
        if self.graphics_view:
            self.set_background_color(QColor(0, 0, 0))

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
