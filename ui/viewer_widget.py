"""Custom CAD viewer widget with enhanced functionality."""

from ezdxf.addons.drawing.qtviewer import (
    CADViewer, CADWidget, CADGraphicsView, CADGraphicsViewWithOverlay,
)
from ezdxf.addons.drawing.config import Configuration
from ezdxf.addons.drawing.pyqt import (
    PyQtBackend, CorrespondingDXFEntity, CorrespondingDXFParentStack,
)
from ezdxf.math import Vec2, Vec3
from ezdxf.npshapes import to_qpainter_path
from PyQt5.QtCore import Qt, QEvent, QTimer
from PyQt5.QtWidgets import QGraphicsView, QGraphicsPathItem
from PyQt5.QtGui import QBrush, QColor, QPainterPathStroker

# 右側パネル（レイヤー表示・要素属性表示。ezdxf CADViewer の self.sidebar）の
# 初期横幅を、ezdxf 側デフォルト（コンテナ幅の 1/4）の何%に縮小するか。
SIDEBAR_WIDTH_SCALE = 0.65

# 要素属性表示パネル・マウス座標表示の X/Y/Z 座標を表示する小数点以下桁数。
# これは表示フォーマットのみに影響する（後述の _on_element_hovered 参照）。
COORDINATE_DISPLAY_DECIMALS = 2


def _format_dxf_attrib_value(value):
    """要素属性表示パネル用に DXF 属性値を1行分フォーマットする。

    座標・ベクトル値（Vec2/Vec3。ブロック(INSERT)展開後の仮想エンティティでも
    直接配置エンティティでも常に Vec2/Vec3 型——ezdxf の str(Vec3(...)) は
    "Vec3(...)" ではなく素の "(x, y, z)" タプル形式を返す点に注意。安全のため
    念のためプレーンな座標タプルも同じ分岐で扱う）は COORDINATE_DISPLAY_DECIMALS
    桁に丸める。半径・文字高さ・尺度・レイヤー名・色番号等（すべて単純な
    float/str/int で Vec2/Vec3/座標タプルではない）はそのまま ezdxf の元の精度で
    表示する。

    ezdxf 自身の表示形式（str(Vec3(...)) の "(x, y, z)"）をそのまま踏襲し、
    丸め以外の見た目の変更（"Vec3(...)" 等のプレフィックス付与）はしない。

    文字列化した後のテキストを正規表現で丸める方式ではなく、値の型で判定する
    のは、str() 表現だけでは Vec3/Vec2/座標タプルのいずれもが同じ "(x, y, z)"
    /"(x, y)" 形式になり区別できない（＝正規表現では非座標のプレーンタプル
    属性が万一あった場合と区別する手立てがない）ため。
    """
    if isinstance(value, (Vec2, Vec3)):
        rounded = tuple(round(c, COORDINATE_DISPLAY_DECIMALS) for c in value.xyz) \
            if isinstance(value, Vec3) else \
            tuple(round(c, COORDINATE_DISPLAY_DECIMALS) for c in (value.x, value.y))
        return str(rounded)
    if (isinstance(value, tuple) and 2 <= len(value) <= 3
            and all(isinstance(c, (int, float)) for c in value)):
        rounded = tuple(round(float(c), COORDINATE_DISPLAY_DECIMALS) for c in value)
        return str(rounded)
    return str(value)


def _entity_attribs_string_rounded(dxf_entity, indent=""):
    """ezdxf の qtviewer._entity_attribs_string() 相当（座標のみ丸める版）。

    DXF Attributes 一覧を1行ずつ整形する。ezdxf 本体の _entity_attribs_string()
    は site-packages 内のサードパーティコードで直接編集できないため、
    PinchZoomCADViewer._on_element_hovered() から呼ぶ代替実装として複製している。
    ezdxf 側の将来のフォーマット変更はここには自動反映されない点に注意。
    """
    text = ""
    for key, value in dxf_entity.dxf.all_existing_dxf_attribs().items():
        text += f"{indent}- {key}: {_format_dxf_attrib_value(value)}\n"
    return text


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

        # Shrink the sidebar (layer list + element attribute panel) to
        # SIDEBAR_WIDTH_SCALE of ezdxf's default width, and keep it a fixed
        # pixel width across window resizes (only the CAD view stretches).
        #
        # This can't be done synchronously here: at __init__ time this widget
        # has not yet been embedded into the app's QTabWidget (that happens
        # in main_window.create_new_tab(), right after DXFTab() — which calls
        # this constructor — returns), so QSplitter.centralWidget().width()
        # is still 0 and any setSizes() call here would be computed from a
        # meaningless baseline. QTimer.singleShot(0, ...) defers the call to
        # the next event-loop iteration, by which point the widget has its
        # real, laid-out size.
        QTimer.singleShot(0, self._shrink_sidebar_width)

    def _shrink_sidebar_width(self):
        """Shrink the sidebar to SIDEBAR_WIDTH_SCALE of its current (ezdxf
        default) width, and pin it to a fixed pixel width thereafter.

        centralWidget() is the outer horizontal QSplitter set up by
        ezdxf's CADViewer.__init__ (container.addWidget(self._cad);
        container.addWidget(self.sidebar)) — not stored as an attribute
        there, so it's retrieved via centralWidget() rather than a saved
        reference.
        """
        container = self.centralWidget()
        if container is None:
            return
        sizes = container.sizes()
        if len(sizes) != 2:
            return
        cad_width, sidebar_width = sizes
        new_sidebar_width = int(sidebar_width * SIDEBAR_WIDTH_SCALE)
        new_cad_width = cad_width + (sidebar_width - new_sidebar_width)
        container.setSizes([new_cad_width, new_sidebar_width])
        # Stretch factors govern how a QSplitter redistributes space on
        # resize (not on first show): give all resize delta to the CAD view
        # (index 0) and none to the sidebar (index 1), so the sidebar keeps
        # this fixed pixel width when the main window is resized. Manual
        # drag-resize of the splitter handle is unaffected.
        container.setStretchFactor(0, 1)
        container.setStretchFactor(1, 0)

    def _on_mouse_moved(self, mouse_pos):
        """Override ezdxf's 4-decimal mouse position display with
        COORDINATE_DISPLAY_DECIMALS (2), matching the element-attribute
        panel below it. Display-only — does not affect any coordinate used
        for hit-testing, search, region detection, or export (all of those
        read full-precision coordinates straight from the ezdxf document,
        independent of this label's text)."""
        self.mouse_pos.setText(
            f"mouse position: {mouse_pos.x():.{COORDINATE_DISPLAY_DECIMALS}f}, "
            f"{mouse_pos.y():.{COORDINATE_DISPLAY_DECIMALS}f}\n"
        )

    def _on_element_hovered(self, elements, index):
        """Round Vec2/Vec3/coordinate-tuple (X/Y/Z) attribute values shown
        in the element-attribute panel to COORDINATE_DISPLAY_DECIMALS places.

        This is a copy of ezdxf's own CADViewer._on_element_hovered(),
        substituting _entity_attribs_string_rounded() for
        _entity_attribs_string() (site-packages code can't be edited
        directly). A text-level regex substitution was considered instead of
        this copy, but rejected: ezdxf's own display calls f"{value}" on
        every DXF attribute, which for Vec2/Vec3 invokes __str__() — and
        Vec3.__str__() returns a bare "(x, y, z)" tuple, not "Vec3(x, y, z)"
        (that's only __repr__()). Since every non-coordinate tuple-shaped
        attribute would render identically, a regex has no reliable anchor
        to distinguish "this is a coordinate" from "this happens to also be
        a 2-3 element numeric tuple" — the value's actual Python type (this
        copy inspects it directly) is the only reliable signal. Future
        ezdxf changes to this method's non-coordinate logic won't
        automatically propagate here.

        This is display-only. Rounding here does not touch the DXF entity's
        actual attribute values (re-read fresh from the document on every
        hover) or any other coordinate-based processing in the app (search
        matching, region detection, hit-testing, export) — none of those
        read from this panel, so there is no internal-precision tradeoff to
        make by rounding the display.
        """
        if not elements:
            text = "No element selected"
        else:
            text = f"Selected: {index + 1} / {len(elements)}    (click to cycle)\n"
            element = elements[index]
            dxf_entity = element.data(CorrespondingDXFEntity)
            if isinstance(dxf_entity, str):
                dxf_entity = self.load_dxf_entity(dxf_entity)
            if dxf_entity is None:
                text += "No data"
            else:
                text += (
                    f"Selected Entity: {dxf_entity}\n"
                    f"Layer: {dxf_entity.dxf.layer}\n\nDXF Attributes:\n"
                )
                text += _entity_attribs_string_rounded(dxf_entity)

                dxf_parent_stack = element.data(CorrespondingDXFParentStack)
                if dxf_parent_stack:
                    text += "\nParents:\n"
                    for entity in reversed(dxf_parent_stack):
                        text += f"- {entity}\n"
                        text += _entity_attribs_string_rounded(entity, indent="    ")
        self.selected_info.setPlainText(text)

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
