"""Main application window for DXF Viewer."""

import os
import tempfile
from pathlib import Path
import ezdxf
from ezdxf.layouts import Modelspace
from PyQt5.QtWidgets import (
    QMainWindow, QTabWidget, QFileDialog, QMessageBox,
    QStatusBar, QToolBar, QAction, QDialog, QApplication,
    QGraphicsPolygonItem
)
from PyQt5.QtCore import Qt, QPointF, QRectF
from PyQt5.QtGui import (
    QKeySequence, QFont, QColor, QPen, QPolygonF, QPainterPath, QPainterPathStroker
)

from core.tab_manager import DXFTab
from core.color_manager import ColorManager
from core.search_manager import SearchManager
from core.region_search_manager import RegionSearchManager
from core.region_detector import extract_text_from_entity
from core.layer_consolidator import consolidate_layers as consolidate_doc_layers
from ui.dialogs import (
    BackgroundColorDialog, ColorChangeDialog, TextSearchDialog,
    HandleSearchDialog, BoundarySearchDialog, FileInfoDialog, ExportImageDialog
)

# ezdxf monkey patch for CADViewer compatibility
original_init = Modelspace.__init__

def patched_init(self, *args, **kwargs):
    original_init(self, *args, **kwargs)
    if not hasattr(self, 'errors'):
        self.errors = []

Modelspace.__init__ = patched_init


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


class DXFViewerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DXF Viewer")
        self.setGeometry(100, 100, 1200, 800)

        self.setAcceptDrops(True)  # ウィンドウ全体で Drag&Drop 有効化
        
        # UI要素を初期化
        self.create_menu_bar()
        self.create_toolbar()
        self.create_status_bar()

        # メインエリア - タブウィジェット
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self.close_tab)
        self.tab_widget.currentChanged.connect(self.on_tab_changed)
        self.setCentralWidget(self.tab_widget)
        
        # 初期状態でUIを無効化
        self.update_ui_state(file_loaded=False)
    
    def get_current_tab(self):
        """現在のアクティブなタブを取得"""
        current_index = self.tab_widget.currentIndex()
        if current_index >= 0:
            return self.tab_widget.widget(current_index)
        return None
    
    def create_new_tab(self, file_path=None):
        """新しいタブを作成"""
        tab = DXFTab(file_path)
        
        # タブのタイトルを設定
        if file_path:
            tab_title = os.path.basename(file_path)
        else:
            tab_title = "New Tab"
        
        # タブを追加してアクティブにする
        tab_index = self.tab_widget.addTab(tab.cad_viewer, tab_title)
        self.tab_widget.setCurrentIndex(tab_index)
        
        # タブにデータを保存
        tab.cad_viewer.tab_data = tab
        
        return tab
    
    def close_tab(self, index):
        """タブを閉じる"""
        if self.tab_widget.count() <= 1:
            # 最後のタブの場合はアプリケーションを終了
            self.close()
            return
        
        widget = self.tab_widget.widget(index)
        self.tab_widget.removeTab(index)
        if widget:
            widget.deleteLater()
    
    def on_tab_changed(self, index):
        """タブが変更されたときの処理"""
        self.update_ui_for_active_tab()
        
        # Update search-related UI based on current tab
        current_tab = self.get_current_tab()
        if current_tab and hasattr(current_tab, 'tab_data'):
            tab_data = current_tab.tab_data
            has_results = len(tab_data.search_results) > 0 and tab_data.search_active
            has_handle_results = (
                len(tab_data.handle_search_results) > 0 and tab_data.handle_search_active)
            self.clear_search_action.setEnabled(
                has_results or has_handle_results or tab_data.boundary_search_active)
            self.toolbar_clear_search_action.setEnabled(
                has_results or has_handle_results or tab_data.boundary_search_active)
            self.find_next_action.setEnabled(len(tab_data.search_results) > 1)
            self.find_prev_action.setEnabled(len(tab_data.search_results) > 1)

            self.clear_handle_search_action.setEnabled(has_handle_results)
            self.find_next_handle_action.setEnabled(len(tab_data.handle_search_results) > 1)
            self.find_prev_handle_action.setEnabled(len(tab_data.handle_search_results) > 1)

            # Boundary highlight clear is available whenever overlays exist
            self.clear_boundary_highlight_action.setEnabled(
                len(tab_data.boundary_overlay_items) > 0)
            
            # Update color change UI
            self.restore_colors_action.setEnabled(tab_data.color_change_active)
            self.toolbar_restore_colors_action.setEnabled(tab_data.color_change_active)
    
    def update_ui_for_active_tab(self):
        """アクティブタブに合わせてUIを更新"""
        current_tab = self.get_current_tab()
        
        if current_tab and hasattr(current_tab, 'tab_data'):
            tab_data = current_tab.tab_data
            file_loaded = tab_data.file_path is not None
            
            # UI状態を更新
            self.update_ui_state(file_loaded=file_loaded)
            
            # ウィンドウタイトルとステータスバーを更新
            if file_loaded:
                filename = os.path.basename(tab_data.file_path)
                self.setWindowTitle(f"DXF Viewer - {filename}")
                self.status_bar.showMessage(f"Loaded: {filename}")
            else:
                self.setWindowTitle("DXF Viewer")
                self.status_bar.showMessage("Ready")
        else:
            self.update_ui_state(file_loaded=False)
            self.setWindowTitle("DXF Viewer")
            self.status_bar.showMessage("Ready")
    
    def create_menu_bar(self):
        """メニューバーを作成"""
        menubar = self.menuBar()
        
        # メニューバーのフォントサイズを大きくする
        from PyQt5.QtGui import QFont
        menu_font = QFont()
        menu_font.setPointSize(14)  # フォントサイズを14ptに設定
        menubar.setFont(menu_font)
        
        # Fileメニュー
        file_menu = menubar.addMenu('File')
        
        # Open DXF File
        open_action = QAction('Open DXF File...', self)
        open_action.setShortcut(QKeySequence.Open)
        open_action.setFont(menu_font)  # メニューアイテムにもフォントを適用
        open_action.triggered.connect(self.open_file_dialog)
        file_menu.addAction(open_action)
        
        file_menu.addSeparator()
        
        # Exit
        exit_action = QAction('Exit', self)
        exit_action.setShortcut(QKeySequence.Quit)
        exit_action.setFont(menu_font)  # メニューアイテムにもフォントを適用
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Toolsメニュー
        tools_menu = menubar.addMenu('Tools')

        # File Info
        self.info_action = QAction('File Information...', self)
        self.info_action.setFont(menu_font)
        self.info_action.triggered.connect(self.show_file_info)
        self.info_action.setEnabled(False)
        tools_menu.addAction(self.info_action)

        tools_menu.addSeparator()

        # Export to Image
        self.export_action = QAction('Export to Image...', self)
        self.export_action.setFont(menu_font)
        self.export_action.triggered.connect(self.export_to_image)
        self.export_action.setEnabled(False)
        tools_menu.addAction(self.export_action)

        tools_menu.addSeparator()

        # Change All Colors
        self.change_colors_action = QAction('Change All Entity Colors...', self)
        self.change_colors_action.setFont(menu_font)
        self.change_colors_action.triggered.connect(self.change_all_colors)
        self.change_colors_action.setEnabled(False)
        tools_menu.addAction(self.change_colors_action)

        # Restore Original Colors
        self.restore_colors_action = QAction('Restore Original Colors', self)
        self.restore_colors_action.setFont(menu_font)
        self.restore_colors_action.triggered.connect(self.restore_all_colors)
        self.restore_colors_action.setEnabled(False)
        tools_menu.addAction(self.restore_colors_action)

        tools_menu.addSeparator()

        # Change Background Color
        self.background_color_action = QAction('Change Background Color...', self)
        self.background_color_action.setFont(menu_font)
        self.background_color_action.triggered.connect(self.change_background_color)
        self.background_color_action.setEnabled(False)
        tools_menu.addAction(self.background_color_action)

        tools_menu.addSeparator()

        # Consolidate Layers (Boundaries / Imported)
        self.consolidate_layers_action = QAction('Consolidate Layers', self)
        self.consolidate_layers_action.setFont(menu_font)
        self.consolidate_layers_action.setToolTip(
            'Consolidate all layers into Boundaries and Imported')
        self.consolidate_layers_action.triggered.connect(self.consolidate_layers)
        self.consolidate_layers_action.setEnabled(False)
        tools_menu.addAction(self.consolidate_layers_action)

        # Searchメニュー
        search_menu = menubar.addMenu('Search')

        # Search Text
        self.search_action = QAction('Search Text...', self)
        self.search_action.setShortcut(QKeySequence.Find)
        self.search_action.setFont(menu_font)
        self.search_action.triggered.connect(self.search_text)
        self.search_action.setEnabled(False)
        search_menu.addAction(self.search_action)

        # Clear Search
        self.clear_search_action = QAction('Clear Search', self)
        self.clear_search_action.setShortcut(QKeySequence('Ctrl+Shift+F'))
        self.clear_search_action.setFont(menu_font)
        self.clear_search_action.triggered.connect(self.clear_search)
        self.clear_search_action.setEnabled(False)
        search_menu.addAction(self.clear_search_action)

        search_menu.addSeparator()

        # Find Next
        self.find_next_action = QAction('Find Next', self)
        self.find_next_action.setShortcut(QKeySequence.FindNext)
        self.find_next_action.setIconText('Next')  # shorter label on the toolbar
        self.find_next_action.setFont(menu_font)
        self.find_next_action.triggered.connect(self.find_next)
        self.find_next_action.setEnabled(False)
        search_menu.addAction(self.find_next_action)

        # Find Previous
        self.find_prev_action = QAction('Find Previous', self)
        self.find_prev_action.setShortcut(QKeySequence.FindPrevious)
        self.find_prev_action.setIconText('Previous')  # shorter label on the toolbar
        self.find_prev_action.setFont(menu_font)
        self.find_prev_action.triggered.connect(self.find_previous)
        self.find_prev_action.setEnabled(False)
        search_menu.addAction(self.find_prev_action)

        search_menu.addSeparator()

        # Search Handle (one or more entities found directly by DXF handle, e.g. "#212A")
        self.search_handle_action = QAction('Search Handle...', self)
        self.search_handle_action.setIconText('Search Handle')
        self.search_handle_action.setFont(menu_font)
        self.search_handle_action.setToolTip('Find entities by DXF handle, e.g. #212A')
        self.search_handle_action.triggered.connect(self.search_handle)
        self.search_handle_action.setEnabled(False)
        search_menu.addAction(self.search_handle_action)

        # Clear Search Handle
        self.clear_handle_search_action = QAction('Clear Search Handle', self)
        self.clear_handle_search_action.setIconText('Clear')  # shorter label on the toolbar
        self.clear_handle_search_action.setFont(menu_font)
        self.clear_handle_search_action.triggered.connect(self.clear_search)
        self.clear_handle_search_action.setEnabled(False)
        search_menu.addAction(self.clear_handle_search_action)

        # Find Next Handle
        self.find_next_handle_action = QAction('Find Next Handle', self)
        self.find_next_handle_action.setIconText('Next')  # shorter label on the toolbar
        self.find_next_handle_action.setFont(menu_font)
        self.find_next_handle_action.triggered.connect(self.find_next_handle)
        self.find_next_handle_action.setEnabled(False)
        search_menu.addAction(self.find_next_handle_action)

        # Find Previous Handle
        self.find_prev_handle_action = QAction('Find Previous Handle', self)
        self.find_prev_handle_action.setIconText('Prev')  # shorter label on the toolbar
        self.find_prev_handle_action.setFont(menu_font)
        self.find_prev_handle_action.triggered.connect(self.find_previous_handle)
        self.find_prev_handle_action.setEnabled(False)
        search_menu.addAction(self.find_prev_handle_action)

        search_menu.addSeparator()

        # Search Boundary (rectangular region by name)
        self.search_boundary_action = QAction('Search Boundary...', self)
        self.search_boundary_action.setShortcut(QKeySequence('Ctrl+B'))
        self.search_boundary_action.setIconText('Search Boundary')
        self.search_boundary_action.setFont(menu_font)
        self.search_boundary_action.setToolTip('Search rectangular regions by name (Ctrl+B)')
        self.search_boundary_action.triggered.connect(self.search_boundary)
        self.search_boundary_action.setEnabled(False)
        search_menu.addAction(self.search_boundary_action)

        # Clear Boundary Highlight (removes persisted region overlays)
        self.clear_boundary_highlight_action = QAction('Clear Boundary Highlight', self)
        self.clear_boundary_highlight_action.setIconText('Clear')  # shorter label on the toolbar
        self.clear_boundary_highlight_action.setFont(menu_font)
        self.clear_boundary_highlight_action.setToolTip('Remove persisted region boundary highlights')
        self.clear_boundary_highlight_action.triggered.connect(self.clear_boundary_highlight)
        self.clear_boundary_highlight_action.setEnabled(False)
        search_menu.addAction(self.clear_boundary_highlight_action)

    def create_toolbar(self):
        """ツールバーを作成"""
        toolbar = QToolBar()
        
        # ツールバーのフォントサイズを大きくする
        from PyQt5.QtGui import QFont
        toolbar_font = QFont()
        toolbar_font.setPointSize(14)  # フォントサイズを14ptに設定
        toolbar.setFont(toolbar_font)
        
        self.addToolBar(toolbar)
        
        # Open File
        open_action = QAction('Open', self)
        open_action.setFont(toolbar_font)  # ツールバーアイテムにもフォントを適用
        open_action.triggered.connect(self.open_file_dialog)
        toolbar.addAction(open_action)
        
        toolbar.addSeparator()
        
        # File Info
        self.toolbar_info_action = QAction('Info', self)
        self.toolbar_info_action.setFont(toolbar_font)  # ツールバーアイテムにもフォントを適用
        self.toolbar_info_action.triggered.connect(self.show_file_info)
        self.toolbar_info_action.setEnabled(False)
        toolbar.addAction(self.toolbar_info_action)
        
        # Export
        self.toolbar_export_action = QAction('Export', self)
        self.toolbar_export_action.setFont(toolbar_font)  # ツールバーアイテムにもフォントを適用
        self.toolbar_export_action.triggered.connect(self.export_to_image)
        self.toolbar_export_action.setEnabled(False)
        toolbar.addAction(self.toolbar_export_action)
        
        toolbar.addSeparator()
        
        # Search Text group
        self.toolbar_search_action = QAction('Search Text', self)
        self.toolbar_search_action.setFont(toolbar_font)
        self.toolbar_search_action.triggered.connect(self.search_text)
        self.toolbar_search_action.setEnabled(False)
        toolbar.addAction(self.toolbar_search_action)

        # Clear Search
        self.toolbar_clear_search_action = QAction('Clear', self)
        self.toolbar_clear_search_action.setFont(toolbar_font)
        self.toolbar_clear_search_action.triggered.connect(self.clear_search)
        self.toolbar_clear_search_action.setEnabled(False)
        toolbar.addAction(self.toolbar_clear_search_action)

        # Search navigation — reuse the menu actions (shared enabled state,
        # iconText shortens the label shown on the toolbar button)
        for action in (self.find_next_action, self.find_prev_action):
            action.setFont(toolbar_font)
            toolbar.addAction(action)

        toolbar.addSeparator()

        # Search Handle group — reuse the menu actions (shared enabled state)
        for action in (self.search_handle_action, self.clear_handle_search_action,
                       self.find_next_handle_action, self.find_prev_handle_action):
            action.setFont(toolbar_font)
            toolbar.addAction(action)

        toolbar.addSeparator()

        # Search Boundary group — reuse the menu actions (shared enabled state)
        for action in (self.search_boundary_action, self.clear_boundary_highlight_action):
            action.setFont(toolbar_font)
            toolbar.addAction(action)

        # --- Second toolbar row: Change Colors onward ---
        self.addToolBarBreak()
        toolbar2 = QToolBar()
        toolbar2.setFont(toolbar_font)
        self.addToolBar(toolbar2)

        # Change Colors
        self.toolbar_change_colors_action = QAction('Change Colors', self)
        self.toolbar_change_colors_action.setFont(toolbar_font)
        self.toolbar_change_colors_action.triggered.connect(self.change_all_colors)
        self.toolbar_change_colors_action.setEnabled(False)
        toolbar2.addAction(self.toolbar_change_colors_action)
        
        # Restore Colors
        self.toolbar_restore_colors_action = QAction('Restore Colors', self)
        self.toolbar_restore_colors_action.setFont(toolbar_font)
        self.toolbar_restore_colors_action.triggered.connect(self.restore_all_colors)
        self.toolbar_restore_colors_action.setEnabled(False)
        toolbar2.addAction(self.toolbar_restore_colors_action)

        toolbar2.addSeparator()

        # Background Color
        self.toolbar_background_color_action = QAction('Background Color', self)
        self.toolbar_background_color_action.setFont(toolbar_font)
        self.toolbar_background_color_action.triggered.connect(self.change_background_color)
        self.toolbar_background_color_action.setEnabled(False)
        toolbar2.addAction(self.toolbar_background_color_action)

        toolbar2.addSeparator()

        # Consolidate Layers (last) — reuse the menu action (shared enabled state)
        self.consolidate_layers_action.setFont(toolbar_font)
        toolbar2.addAction(self.consolidate_layers_action)
    
    def create_status_bar(self):
        """ステータスバーを作成"""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")
    
    def open_file_dialog(self):
        """ファイル選択ダイアログを開く"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open DXF File", "", "DXF Files (*.dxf);;All Files (*)"
        )
        if file_path:
            self.load_dxf(file_path)
    
    def show_file_info(self):
        """ファイル情報ダイアログを表示"""
        current_tab = self.get_current_tab()
        if not current_tab or not hasattr(current_tab, 'tab_data') or not current_tab.tab_data.file_path:
            QMessageBox.warning(self, "No File", "No DXF file is currently loaded.")
            return
        
        dialog = FileInfoDialog(self)
        dialog.show_file_info(current_tab.tab_data.file_path)
        dialog.exec_()
    
    def export_to_image(self):
        """画像エクスポートダイアログを表示"""
        current_tab = self.get_current_tab()
        if not current_tab or not hasattr(current_tab, 'tab_data') or not current_tab.tab_data.file_path:
            QMessageBox.warning(self, "No File", "No DXF file is currently loaded.")
            return

        tab_data = current_tab.tab_data

        # 出力ファイル選択
        output_path, _ = QFileDialog.getSaveFileName(
            self, "Export to Image",
            Path(tab_data.file_path).stem + ".png",
            "PNG Files (*.png);;SVG Files (*.svg);;PDF Files (*.pdf);;All Files (*)"
        )

        if output_path:
            # Get current layer visibility from viewer and save to a temporary DXF file
            temp_dxf_path = None
            try:
                # Get layer visibility from CADViewer
                layer_states = self.get_layer_visibility(tab_data)

                if layer_states is not None:
                    # Save to temporary file with current layer visibility
                    temp_dxf_path = self.save_with_layer_visibility(tab_data, layer_states)
                    export_path = temp_dxf_path if temp_dxf_path else tab_data.file_path
                else:
                    export_path = tab_data.file_path

                # Export with current background color
                dialog = ExportImageDialog(self)
                dialog.export_to_image(export_path, output_path, tab_data.background_color)
                dialog.exec_()
            finally:
                # Clean up temporary file
                if temp_dxf_path and os.path.exists(temp_dxf_path):
                    try:
                        os.remove(temp_dxf_path)
                    except:
                        pass
    
    def get_layer_visibility(self, tab_data):
        """Get layer visibility state from CADViewer"""
        try:
            # Access the CADViewer's layer checkboxes to get visibility state
            if hasattr(tab_data.cad_viewer, '_layer_checkboxes'):
                layer_states = {}
                # _layer_checkboxes is a generator that yields (index, checkbox) tuples
                for index, checkbox in tab_data.cad_viewer._layer_checkboxes():
                    layer_name = checkbox.text()
                    is_checked = checkbox.checkState() == Qt.Checked
                    layer_states[layer_name] = is_checked
                return layer_states if layer_states else None
            return None
        except Exception as e:
            print(f"Error getting layer visibility: {e}")
            return None

    def save_with_layer_visibility(self, tab_data, layer_states):
        """Save DXF to temporary file with current layer visibility"""
        try:
            if not tab_data.dxf_doc:
                return None

            # Create a temporary file
            temp_fd, temp_path = tempfile.mkstemp(suffix='.dxf')
            os.close(temp_fd)

            # Store original layer states to restore them later
            original_states = {}
            for layer_name, is_visible in layer_states.items():
                if layer_name in tab_data.dxf_doc.layers:
                    layer = tab_data.dxf_doc.layers.get(layer_name)
                    # Store original state
                    original_states[layer_name] = layer.is_on()
                    # Set layer off/on based on visibility
                    if is_visible:
                        layer.on()
                    else:
                        layer.off()

            # Save to temporary file
            tab_data.dxf_doc.saveas(temp_path)

            # Restore original layer states
            for layer_name, was_on in original_states.items():
                if layer_name in tab_data.dxf_doc.layers:
                    layer = tab_data.dxf_doc.layers.get(layer_name)
                    if was_on:
                        layer.on()
                    else:
                        layer.off()

            return temp_path

        except Exception as e:
            print(f"Error saving with layer visibility: {e}")
            return None

    def update_ui_state(self, file_loaded=False):
        """UIの状態を更新"""
        self.export_action.setEnabled(file_loaded)
        self.info_action.setEnabled(file_loaded)
        self.toolbar_export_action.setEnabled(file_loaded)
        self.toolbar_info_action.setEnabled(file_loaded)
        self.search_action.setEnabled(file_loaded)
        self.toolbar_search_action.setEnabled(file_loaded)
        self.search_handle_action.setEnabled(file_loaded)
        self.search_boundary_action.setEnabled(file_loaded)
        self.consolidate_layers_action.setEnabled(file_loaded)
        self.change_colors_action.setEnabled(file_loaded)
        self.toolbar_change_colors_action.setEnabled(file_loaded)
        self.background_color_action.setEnabled(file_loaded)
        self.toolbar_background_color_action.setEnabled(file_loaded)
    
    def change_background_color(self):
        """Change the background color of the viewer"""
        current_tab = self.get_current_tab()
        if not current_tab or not hasattr(current_tab, 'tab_data'):
            return

        tab_data = current_tab.tab_data

        # Show background color dialog
        dialog = BackgroundColorDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            color, color_name = dialog.get_selected_color()

            # Apply background color to the CAD viewer
            if hasattr(tab_data.cad_viewer, 'set_background_color'):
                tab_data.cad_viewer.set_background_color(color)

                # Store background color as hex string for export
                tab_data.background_color = color.name()  # Converts QColor to #RRGGBB

                self.status_bar.showMessage(f"Background color changed to {color_name}")

    def change_all_colors(self):
        """Change all entity colors to a specified color"""
        current_tab = self.get_current_tab()
        if not current_tab or not hasattr(current_tab, 'tab_data'):
            return
        
        tab_data = current_tab.tab_data
        if not tab_data.dxf_doc:
            QMessageBox.warning(self, "No File", "No DXF file is currently loaded.")
            return
        
        # Clear any active search first
        if tab_data.search_active or tab_data.boundary_search_active:
            self.clear_search()
        # A boundary overlay persisted after Clear Search would be stale now
        self.clear_boundary_highlight()

        # Show color dialog
        dialog = ColorChangeDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            color_index, color_name, rgb_value = dialog.get_selected_color()
            preserve_text = dialog.should_preserve_text()

            # Store original colors if not already stored
            if not tab_data.color_change_active:
                self.store_colors_for_change(tab_data)

            # Apply color to all entities
            self.apply_color_to_all_entities(tab_data, color_index, rgb_value, preserve_text)

            # Update UI
            tab_data.color_change_active = True
            self.restore_colors_action.setEnabled(True)
            self.toolbar_restore_colors_action.setEnabled(True)

            # Update status bar
            if preserve_text:
                self.status_bar.showMessage(f"Changed all entities to {color_name} (text preserved)")
            else:
                self.status_bar.showMessage(f"Changed all entities to {color_name}")
    
    def restore_all_colors(self):
        """Restore original colors after color change"""
        current_tab = self.get_current_tab()
        if not current_tab or not hasattr(current_tab, 'tab_data'):
            return
        
        tab_data = current_tab.tab_data
        if tab_data.color_change_active and tab_data.color_change_backup:
            # Restore colors from backup
            self.restore_colors_from_backup(tab_data)
            
            # Clear backup
            tab_data.color_change_backup.clear()
            tab_data.color_change_active = False
            
            # Refresh viewer
            self.refresh_viewer(tab_data)
            
            # Update UI
            self.restore_colors_action.setEnabled(False)
            self.toolbar_restore_colors_action.setEnabled(False)
            self.status_bar.showMessage("Original colors restored")
    
    def store_colors_for_change(self, tab_data):
        """Store original colors before changing all entity colors"""
        ColorManager.store_entity_colors(tab_data)
    
    def apply_color_to_all_entities(self, tab_data, color_index, rgb_value, preserve_text=False):
        """Apply specified color to all entities"""
        ColorManager.apply_color_to_all_entities(tab_data, color_index, rgb_value, preserve_text)
        self.refresh_viewer(tab_data)
    
    def restore_colors_from_backup(self, tab_data):
        """Restore colors from the color change backup"""
        ColorManager.restore_colors_from_backup(tab_data)
    
    def search_text(self):
        """Open search dialog and perform text search"""
        current_tab = self.get_current_tab()
        if not current_tab or not hasattr(current_tab, 'tab_data'):
            return
        
        tab_data = current_tab.tab_data
        if not tab_data.dxf_doc:
            QMessageBox.warning(self, "No File", "No DXF file is currently loaded.")
            return
        
        # Show search dialog
        dialog = TextSearchDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            params = dialog.get_search_params()
            search_text = params['text']
            
            if not search_text:
                return
            
            # Clear previous search
            self.clear_search()
            
            # Store original colors for ALL entities before search
            SearchManager.store_all_entity_colors(tab_data)

            # Store the selected dim color
            tab_data.search_dim_color = params['dim_color']

            # Perform search
            tab_data.search_results = SearchManager.find_text_entities(
                tab_data.dxf_doc,
                search_text,
                params['case_sensitive'],
                params['whole_word']
            )
            
            if tab_data.search_results:
                # Apply color changes to highlight results
                SearchManager.apply_search_highlighting(tab_data)
                self.refresh_viewer(tab_data)
                
                # Enable navigation actions
                tab_data.search_active = True
                self.clear_search_action.setEnabled(True)
                self.toolbar_clear_search_action.setEnabled(True)
                self.find_next_action.setEnabled(len(tab_data.search_results) > 1)
                self.find_prev_action.setEnabled(len(tab_data.search_results) > 1)
                
                # Navigate to first result
                tab_data.current_search_index = 0
                self.navigate_to_result(tab_data, tab_data.search_results, 0)
                
                # Update status bar
                self.status_bar.showMessage(
                    f"Found {len(tab_data.search_results)} occurrence(s) of '{search_text}'"
                )
            else:
                QMessageBox.information(
                    self,
                    "Search Result",
                    f"No occurrences of '{search_text}' found."
                )
                self.status_bar.showMessage("No matches found")
    
    def clear_search(self):
        """Clear all search highlights and restore original colors.

        Clears whichever of text search, handle search, and boundary search
        are currently active — the three modes are mutually exclusive in
        practice (each clears the others before starting), but this handles
        all of them so every "Clear" button/shortcut acts as a global clear.
        """
        current_tab = self.get_current_tab()
        if current_tab and hasattr(current_tab, 'tab_data'):
            tab_data = current_tab.tab_data

            cleared = False

            if tab_data.search_active or tab_data.handle_search_active:
                # Restore original colors (shared backup for both modes)
                SearchManager.restore_original_colors(tab_data)

                if tab_data.search_active:
                    tab_data.search_results.clear()
                    tab_data.current_search_index = -1
                    tab_data.search_active = False
                    self.find_next_action.setEnabled(False)
                    self.find_prev_action.setEnabled(False)
                    cleared = True

                if tab_data.handle_search_active:
                    tab_data.handle_search_results.clear()
                    tab_data.current_handle_search_index = -1
                    tab_data.handle_search_active = False
                    self.find_next_handle_action.setEnabled(False)
                    self.find_prev_handle_action.setEnabled(False)
                    cleared = True

                # Refresh the viewer
                self.refresh_viewer(tab_data)

            if tab_data.boundary_search_active:
                self._clear_boundary_search(tab_data)
                cleared = True

            if cleared:
                self.clear_search_action.setEnabled(False)
                self.toolbar_clear_search_action.setEnabled(False)
                self.clear_handle_search_action.setEnabled(False)
                self.status_bar.showMessage("Search cleared")

    def find_next(self):
        """Navigate to next search result"""
        current_tab = self.get_current_tab()
        if not current_tab or not hasattr(current_tab, 'tab_data'):
            return

        tab_data = current_tab.tab_data
        if tab_data.search_results:
            tab_data.current_search_index = (tab_data.current_search_index + 1) % len(tab_data.search_results)
            self.navigate_to_result(tab_data, tab_data.search_results, tab_data.current_search_index)

    def find_previous(self):
        """Navigate to previous search result"""
        current_tab = self.get_current_tab()
        if not current_tab or not hasattr(current_tab, 'tab_data'):
            return

        tab_data = current_tab.tab_data
        if tab_data.search_results:
            tab_data.current_search_index = (tab_data.current_search_index - 1) % len(tab_data.search_results)
            self.navigate_to_result(tab_data, tab_data.search_results, tab_data.current_search_index)

    # ------------------------------------------------------------------
    # Handle search (find one or more entities directly by DXF handle)
    # ------------------------------------------------------------------
    def search_handle(self):
        """Open the handle search dialog and highlight the resolved entities."""
        current_tab = self.get_current_tab()
        if not current_tab or not hasattr(current_tab, 'tab_data'):
            return

        tab_data = current_tab.tab_data
        if not tab_data.dxf_doc:
            QMessageBox.warning(self, "No File", "No DXF file is currently loaded.")
            return

        dialog = HandleSearchDialog(self)
        if dialog.exec_() != QDialog.Accepted:
            return

        params = dialog.get_search_params()
        handles_text = params['handles'].strip()
        if not handles_text:
            return

        results, not_found = SearchManager.find_entities_by_handles(tab_data.dxf_doc, handles_text)

        if not results:
            QMessageBox.information(
                self, "Search Handle",
                f"No entity found for handle(s): {', '.join(not_found)}")
            self.status_bar.showMessage("No matching entity found")
            return

        # Mutually exclusive with the other search modes.
        self.clear_search()
        self.clear_boundary_highlight()

        SearchManager.store_all_entity_colors(tab_data)
        tab_data.handle_search_dim_color = params['dim_color']
        tab_data.handle_search_results = results

        SearchManager.apply_highlighting(tab_data, results, params['dim_color'])
        self.refresh_viewer(tab_data)

        tab_data.handle_search_active = True
        self.clear_search_action.setEnabled(True)
        self.toolbar_clear_search_action.setEnabled(True)
        self.clear_handle_search_action.setEnabled(True)
        self.find_next_handle_action.setEnabled(len(results) > 1)
        self.find_prev_handle_action.setEnabled(len(results) > 1)

        tab_data.current_handle_search_index = 0
        self.navigate_to_result(tab_data, tab_data.handle_search_results, 0)

        summary = f"Found {len(results)} entity(ies) by handle"
        if not_found:
            summary += f"; not found: {', '.join(not_found)}"
        self.status_bar.showMessage(summary)

    def find_next_handle(self):
        """Navigate to next handle-search result"""
        current_tab = self.get_current_tab()
        if not current_tab or not hasattr(current_tab, 'tab_data'):
            return

        tab_data = current_tab.tab_data
        if tab_data.handle_search_results:
            tab_data.current_handle_search_index = (
                tab_data.current_handle_search_index + 1) % len(tab_data.handle_search_results)
            self.navigate_to_result(
                tab_data, tab_data.handle_search_results, tab_data.current_handle_search_index)

    def find_previous_handle(self):
        """Navigate to previous handle-search result"""
        current_tab = self.get_current_tab()
        if not current_tab or not hasattr(current_tab, 'tab_data'):
            return

        tab_data = current_tab.tab_data
        if tab_data.handle_search_results:
            tab_data.current_handle_search_index = (
                tab_data.current_handle_search_index - 1) % len(tab_data.handle_search_results)
            self.navigate_to_result(
                tab_data, tab_data.handle_search_results, tab_data.current_handle_search_index)

    # ------------------------------------------------------------------
    # Boundary (rectangular region) search
    # ------------------------------------------------------------------
    def search_boundary(self):
        """Open the boundary search dialog and highlight matching regions."""
        current_tab = self.get_current_tab()
        if not current_tab or not hasattr(current_tab, 'tab_data'):
            return

        tab_data = current_tab.tab_data
        if not tab_data.dxf_doc:
            QMessageBox.warning(self, "No File", "No DXF file is currently loaded.")
            return

        dialog = BoundarySearchDialog(self)
        if dialog.exec_() != QDialog.Accepted:
            return

        params = dialog.get_search_params()
        query = params['text'].strip()
        corners_text = params['corners_text'].strip()
        if not query and not corners_text:
            return

        # Pasted vertex coordinates take precedence over the name field when
        # both are filled in — pasting a coordinate list is a deliberate,
        # more specific action than whatever text happens to remain in the
        # name field from a previous search.
        corners = []
        if corners_text:
            corners = RegionSearchManager.parse_corner_list(corners_text)
            if not corners:
                QMessageBox.warning(
                    self, "Search Boundary",
                    "Could not parse any vertex coordinates from the pasted text.")
                return
        by_corners = bool(corners)
        search_label = f"{len(corners)} pasted vertices" if by_corners else query

        # A boundary search is mutually exclusive with the text/boundary search
        # already applied; clear any existing highlight and persisted overlay.
        self.clear_search()
        self.clear_boundary_highlight()

        # The first analysis (and the dim re-render) can take several seconds on
        # large files, so keep the busy cursor over the whole heavy operation.
        QApplication.setOverrideCursor(Qt.WaitCursor)
        analysis = None
        matched = []
        try:
            analysis = RegionSearchManager.get_analysis(tab_data)
            if analysis and not analysis.get('error'):
                if by_corners:
                    matched = RegionSearchManager.find_region_by_corners(analysis, corners)
                else:
                    matched = RegionSearchManager.find_matching_regions(
                        analysis, query, params['case_sensitive'], params['whole_word'])
                if matched:
                    self._apply_boundary_highlight(
                        tab_data, matched, params['dim_color'], params['keep_highlight'])
        finally:
            QApplication.restoreOverrideCursor()

        # User-facing messages are shown without the busy cursor.
        if not analysis or analysis.get('error'):
            message = (analysis or {}).get('error') or "Region analysis failed."
            QMessageBox.information(self, "Search Boundary", message)
            self.status_bar.showMessage("No regions detected")
            return

        if not matched:
            QMessageBox.information(
                self, "Search Boundary",
                f"No regions matching '{search_label}' were found.")
            self.status_bar.showMessage("No matching regions found")
            return

        self.status_bar.showMessage(
            f"Found {len(matched)} region(s) matching '{search_label}'")

    def _apply_boundary_highlight(self, tab_data, matched, dim_color, keep_highlight):
        """Dim the drawing, draw region overlays, zoom to fit, and update state."""
        tab_data.matched_regions = matched
        tab_data.boundary_keep_highlight = keep_highlight
        tab_data.search_dim_color = dim_color

        SearchManager.store_all_entity_colors(tab_data)
        self._dim_all_entities(tab_data)
        self._highlight_matched_labels(tab_data, matched)
        self.refresh_viewer(tab_data)
        tab_data.boundary_overlay_items = []  # destroyed by the refresh above
        self.draw_boundary_overlays(tab_data, matched)
        self.zoom_to_regions(tab_data, matched)

        tab_data.boundary_search_active = True
        self.clear_search_action.setEnabled(True)
        self.toolbar_clear_search_action.setEnabled(True)
        self.clear_boundary_highlight_action.setEnabled(True)

    def _clear_boundary_search(self, tab_data):
        """Restore dimmed colors; keep or drop the overlay per the saved flag."""
        SearchManager.restore_original_colors(tab_data)
        tab_data.boundary_search_active = False

        keep = tab_data.boundary_keep_highlight
        matched = tab_data.matched_regions

        # Rebuilding the scene destroys the existing overlay items.
        self.refresh_viewer(tab_data)
        tab_data.boundary_overlay_items = []

        if keep and matched:
            self.draw_boundary_overlays(tab_data, matched)
            self.clear_boundary_highlight_action.setEnabled(True)
        else:
            tab_data.matched_regions = []
            self.clear_boundary_highlight_action.setEnabled(False)

    def clear_boundary_highlight(self):
        """Remove the boundary overlay; also un-dim if a boundary search is active."""
        current_tab = self.get_current_tab()
        if not current_tab or not hasattr(current_tab, 'tab_data'):
            return

        tab_data = current_tab.tab_data
        if not tab_data.boundary_overlay_items and not tab_data.boundary_search_active:
            return

        if tab_data.boundary_search_active:
            # The drawing is still dimmed — restore original colors and re-render
            # (otherwise the drawing would be left in the single dim color).
            SearchManager.restore_original_colors(tab_data)
            tab_data.boundary_search_active = False
            self.refresh_viewer(tab_data)
            tab_data.boundary_overlay_items = []  # destroyed by the refresh
            if not tab_data.search_active:
                self.clear_search_action.setEnabled(False)
                self.toolbar_clear_search_action.setEnabled(False)
        else:
            # Only a persisted (post-Clear-Search) overlay remains.
            self.remove_boundary_overlays(tab_data)

        tab_data.matched_regions = []
        tab_data.boundary_keep_highlight = False
        self.clear_boundary_highlight_action.setEnabled(False)
        self.status_bar.showMessage("Boundary highlight cleared")

    def _dim_all_entities(self, tab_data):
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

    def _highlight_matched_labels(self, tab_data, matched_regions):
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

        RED_COLOR_INDEX = 1
        RED_RGB = 0xFF0000
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

    def draw_boundary_overlays(self, tab_data, regions):
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
            # _OverlayPolygonItem has an empty shape(), so it is ignored by the
            # CAD viewer's scene().items(pos) hover/click picking — symbols and
            # wiring inside the region stay hoverable and selectable.
            item = _OverlayPolygonItem(qpoly)
            item.setPen(pen)
            item.setZValue(1e9)  # keep the outline above the drawing
            scene.addItem(item)
            tab_data.boundary_overlay_items.append(item)

    def remove_boundary_overlays(self, tab_data):
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

    def zoom_to_regions(self, tab_data, regions):
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

    # ------------------------------------------------------------------
    # Layer consolidation
    # ------------------------------------------------------------------
    def consolidate_layers(self):
        """Collapse all source layers into 'Boundaries' and 'Imported'.

        'Boundaries' receives the boundary linework of the detected rectangular
        regions; everything else goes to 'Imported'. The change is in-memory
        only — reopening the file restores the original layers.
        """
        current_tab = self.get_current_tab()
        if not current_tab or not hasattr(current_tab, 'tab_data'):
            return

        tab_data = current_tab.tab_data
        if not tab_data.dxf_doc:
            QMessageBox.warning(self, "No File", "No DXF file is currently loaded.")
            return

        # Clear active search/highlight first — we are about to rewrite layers.
        if tab_data.search_active or tab_data.boundary_search_active:
            self.clear_search()
        self.clear_boundary_highlight()

        QApplication.setOverrideCursor(Qt.WaitCursor)
        analysis = None
        stats = None
        try:
            analysis = RegionSearchManager.get_analysis(tab_data)
            if analysis and not analysis.get('error'):
                stats = consolidate_doc_layers(tab_data.dxf_doc, analysis['regions'])
                tab_data.msp = tab_data.dxf_doc.modelspace()
                # Original colors no longer correspond to the rewritten layers.
                tab_data.original_entity_colors.clear()
                self.refresh_viewer(tab_data)
        finally:
            QApplication.restoreOverrideCursor()

        if not analysis or analysis.get('error'):
            message = (analysis or {}).get('error') or "Region analysis failed."
            QMessageBox.information(self, "Consolidate Layers", message)
            self.status_bar.showMessage("No regions detected")
            return

        QMessageBox.information(
            self, "Consolidate Layers",
            "Consolidated into 2 layers:\n"
            f"  Boundaries: {stats['boundaries']} entities\n"
            f"  Imported: {stats['imported']} entities\n"
            f"Removed {len(stats['removed'])} source layer(s).\n\n"
            "Reopen the file to restore the original layers.")
        self.status_bar.showMessage(
            f"Consolidated layers — Boundaries: {stats['boundaries']}, "
            f"Imported: {stats['imported']}")

    def find_text_entities(self, doc, search_text, case_sensitive=False, whole_word=False):
        """Find all text entities matching search criteria"""
        import re
        
        results = []
        
        # Prepare search pattern
        if not case_sensitive:
            search_text = search_text.lower()
        
        if whole_word:
            pattern = r'\b' + re.escape(search_text) + r'\b'
            regex = re.compile(pattern, re.IGNORECASE if not case_sensitive else 0)
        
        # Search in modelspace
        msp = doc.modelspace()
        for entity in msp:
            if entity.dxftype() in ['TEXT', 'MTEXT']:
                entity_text = entity.dxf.text if hasattr(entity.dxf, 'text') else ''
                
                # Handle MTEXT formatting codes
                if entity.dxftype() == 'MTEXT':
                    # Remove common MTEXT formatting codes
                    import re
                    entity_text = re.sub(r'\\[HPLpfFcC][^;]*;', '', entity_text)
                    entity_text = re.sub(r'[{}]', '', entity_text)
                
                compare_text = entity_text if case_sensitive else entity_text.lower()
                
                # Check for match
                match = False
                if whole_word:
                    match = regex.search(compare_text) is not None
                else:
                    match = search_text in compare_text
                
                if match:
                    # Get entity properties
                    position = None
                    rotation = 0
                    height = 1.0
                    original_color = entity.dxf.color if hasattr(entity.dxf, 'color') else 256  # 256 = BYLAYER
                    
                    if entity.dxftype() == 'TEXT':
                        position = entity.dxf.insert
                        rotation = entity.dxf.rotation if hasattr(entity.dxf, 'rotation') else 0
                        height = entity.dxf.height if hasattr(entity.dxf, 'height') else 1.0
                    elif entity.dxftype() == 'MTEXT':
                        position = entity.dxf.insert
                        rotation = entity.dxf.rotation if hasattr(entity.dxf, 'rotation') else 0
                        height = entity.dxf.char_height if hasattr(entity.dxf, 'char_height') else 1.0
                    
                    if position:
                        # Estimate text width (simple approximation)
                        width = len(entity_text) * height * 0.6
                        
                        result = SearchResult(
                            entity=entity,
                            text=entity_text,
                            position=position,
                            rotation=rotation,
                            height=height,
                            width=width,
                            original_color=original_color
                        )
                        results.append(result)
        
        # Also search in blocks
        for block in doc.blocks:
            if block.name.startswith('*'):
                continue
                
            for entity in block:
                if entity.dxftype() in ['TEXT', 'MTEXT']:
                    entity_text = entity.dxf.text if hasattr(entity.dxf, 'text') else ''
                    
                    if entity.dxftype() == 'MTEXT':
                        entity_text = re.sub(r'\\[HPLpfFcC][^;]*;', '', entity_text)
                        entity_text = re.sub(r'[{}]', '', entity_text)
                    
                    compare_text = entity_text if case_sensitive else entity_text.lower()
                    
                    match = False
                    if whole_word:
                        match = regex.search(compare_text) is not None
                    else:
                        match = search_text in compare_text
                    
                    if match:
                        # Note: Block entities would need transformation based on INSERT entities
                        # For simplicity, we're recording them but highlighting might need adjustment
                        position = entity.dxf.insert if hasattr(entity.dxf, 'insert') else (0, 0, 0)
                        rotation = entity.dxf.rotation if hasattr(entity.dxf, 'rotation') else 0
                        height = entity.dxf.height if hasattr(entity.dxf, 'height') else 1.0
                        width = len(entity_text) * height * 0.6
                        original_color = entity.dxf.color if hasattr(entity.dxf, 'color') else 256
                        
                        result = SearchResult(
                            entity=entity,
                            text=entity_text,
                            position=position,
                            rotation=rotation,
                            height=height,
                            width=width,
                            original_color=original_color
                        )
                        results.append(result)
        
        return results
    
    def store_all_entity_colors(self, tab_data):
        """Store original colors for all entities in the document"""
        if not tab_data.dxf_doc:
            return
        
        tab_data.original_entity_colors.clear()
        
        # Store colors for all modelspace entities
        msp = tab_data.dxf_doc.modelspace()
        for entity in msp:
            if hasattr(entity.dxf, 'handle'):
                handle = entity.dxf.handle
                # Store color if it exists, or None to indicate BYLAYER
                if hasattr(entity.dxf, 'color'):
                    tab_data.original_entity_colors[handle] = entity.dxf.color
                else:
                    tab_data.original_entity_colors[handle] = None
        
        # Store colors for block entities
        for block in tab_data.dxf_doc.blocks:
            for entity in block:
                if hasattr(entity.dxf, 'handle'):
                    handle = entity.dxf.handle
                    if hasattr(entity.dxf, 'color'):
                        tab_data.original_entity_colors[handle] = entity.dxf.color
                    else:
                        tab_data.original_entity_colors[handle] = None
    
    def apply_search_highlighting(self, tab_data):
        """Apply color changes to highlight search results"""
        if not tab_data.dxf_doc or not tab_data.search_results:
            return

        # Use the user-selected dimmed color (tuple of index and RGB)
        dimmed_color_index, dimmed_rgb = tab_data.search_dim_color
        RED_COLOR_INDEX = 1
        RED_RGB = 0xFF0000

        # Dim all entities first
        msp = tab_data.dxf_doc.modelspace()
        for entity in msp:
            if hasattr(entity.dxf, 'color'):
                # Check if this entity is in search results
                is_result = any(r.entity.dxf.handle == entity.dxf.handle for r in tab_data.search_results)
                if not is_result:
                    try:
                        entity.dxf.color = dimmed_color_index
                        entity.dxf.true_color = dimmed_rgb
                    except:
                        pass

        # Also dim entities in blocks
        for block in tab_data.dxf_doc.blocks:
            if not block.name.startswith('*'):  # Skip system blocks
                for entity in block:
                    if hasattr(entity.dxf, 'color'):
                        is_result = any(r.entity.dxf.handle == entity.dxf.handle for r in tab_data.search_results)
                        if not is_result:
                            try:
                                entity.dxf.color = dimmed_color_index
                                entity.dxf.true_color = dimmed_rgb
                            except:
                                pass

        # Highlight search results in red
        for result in tab_data.search_results:
            if hasattr(result.entity.dxf, 'color'):
                try:
                    result.entity.dxf.color = RED_COLOR_INDEX
                    result.entity.dxf.true_color = RED_RGB
                except:
                    pass

        # Refresh the viewer
        self.refresh_viewer(tab_data)
    
    def restore_original_colors(self, tab_data):
        """Restore original colors for all entities"""
        if not tab_data.dxf_doc or not tab_data.original_entity_colors:
            return
        
        # Restore colors for modelspace entities
        msp = tab_data.dxf_doc.modelspace()
        for entity in msp:
            if hasattr(entity.dxf, 'handle'):
                handle = entity.dxf.handle
                if handle in tab_data.original_entity_colors:
                    original_color = tab_data.original_entity_colors[handle]
                    if original_color is not None:
                        # Entity had a color, restore it
                        entity.dxf.color = original_color
                    else:
                        # Entity didn't have a color attribute (was BYLAYER)
                        # Remove the color attribute if possible, or set to 256 (BYLAYER)
                        if hasattr(entity.dxf, 'color'):
                            try:
                                entity.dxf.color = 256  # 256 = BYLAYER
                            except:
                                pass  # Some entities may not support color changes
        
        # Restore colors for block entities
        for block in tab_data.dxf_doc.blocks:
            for entity in block:
                if hasattr(entity.dxf, 'handle'):
                    handle = entity.dxf.handle
                    if handle in tab_data.original_entity_colors:
                        original_color = tab_data.original_entity_colors[handle]
                        if original_color is not None:
                            entity.dxf.color = original_color
                        else:
                            if hasattr(entity.dxf, 'color'):
                                try:
                                    entity.dxf.color = 256  # 256 = BYLAYER
                                except:
                                    pass
        
        # Clear stored colors
        tab_data.original_entity_colors.clear()
    
    def refresh_viewer(self, tab_data):
        """Refresh the CAD viewer with updated colors"""
        if tab_data.cad_viewer and tab_data.dxf_doc and tab_data.msp:
            try:
                # Store current view transform
                graphics_view = tab_data.cad_viewer.graphics_view
                if graphics_view:
                    old_transform = graphics_view.transform()
                    old_center = graphics_view.mapToScene(graphics_view.viewport().rect().center())

                # Clear the current scene
                if hasattr(tab_data.cad_viewer, 'clear_scene'):
                    tab_data.cad_viewer.clear_scene()

                # Re-audit and reload the document completely
                auditor = tab_data.dxf_doc.audit()
                tab_data.cad_viewer.set_document(tab_data.dxf_doc, auditor)

                # Restore view transform
                if graphics_view and old_transform is not None:
                    graphics_view.setTransform(old_transform)
                    graphics_view.centerOn(old_center)

            except Exception as e:
                print(f"Error refreshing viewer: {e}")
    
    def navigate_to_result(self, tab_data, results, index):
        """Center view on a specific result from the given results list.

        ``results`` is passed explicitly (rather than reading
        ``tab_data.search_results``) so this is shared between text search
        and handle search, which keep independent result lists.
        """
        if not results or index < 0 or index >= len(results):
            return

        result = results[index]
        graphics_view = tab_data.cad_viewer.graphics_view

        if graphics_view and result.position:
            # Center the view on the result
            x = float(result.position[0])
            y = float(result.position[1])

            # Entities sit in the scene at their true DXF coordinates
            # (the view applies the vertical flip), so center on (x, y).
            scene_point = QPointF(x, y)

            # Center the view on this point
            graphics_view.centerOn(scene_point)

            # Update status bar
            self.status_bar.showMessage(
                f"Result {index + 1} of {len(results)}: '{result.text[:50]}...'"
                if len(result.text) > 50 else
                f"Result {index + 1} of {len(results)}: '{result.text}'"
            )

    def load_dxf(self, file_path):
        # 新しいタブを作成
        tab = self.create_new_tab(file_path)
        
        try:
            tab.dxf_doc = ezdxf.readfile(file_path)
            tab.msp = tab.dxf_doc.modelspace()
        except Exception as e:
            QMessageBox.critical(self, "DXF Error", f"Failed to load DXF file:\n{e}")
            # エラーの場合はタブを削除
            current_index = self.tab_widget.currentIndex()
            if current_index >= 0:
                self.close_tab(current_index)
            return

        try:
            # Audit the document
            auditor = tab.dxf_doc.audit()
            tab.cad_viewer.set_document(tab.dxf_doc, auditor)
            if hasattr(tab.cad_viewer, 'zoom_extents'):
                tab.cad_viewer.zoom_extents()
        except Exception as e:
            QMessageBox.warning(self, "Viewer Error", f"Error initializing CAD viewer:\n{e}")

        # UI状態を更新
        self.update_ui_for_active_tab()

    # ウィンドウ全体で Drag&Drop イベント処理
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            file_path = urls[0].toLocalFile()
            if file_path.lower().endswith('.dxf'):
                self.load_dxf(file_path)
            else:
                QMessageBox.warning(self, "Invalid File", "Please drop a DXF file.")


