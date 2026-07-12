"""Main application window for DXF Viewer."""

import os
import tempfile
from pathlib import Path
import ezdxf
from ezdxf.layouts import Modelspace
from PyQt5.QtWidgets import (
    QMainWindow, QTabWidget, QFileDialog, QMessageBox, QDialog, QApplication
)
from PyQt5.QtCore import Qt, QPointF

from core.tab_manager import DXFTab
from core.color_manager import ColorManager
from core.search_manager import SearchManager
from core.region_search_manager import RegionSearchManager
from core.layer_consolidator import consolidate_layers as consolidate_doc_layers
from ui import boundary_overlay, main_window_actions
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


class DXFViewerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DXF Viewer")
        self.setGeometry(100, 100, 1200, 800)

        self.setAcceptDrops(True)  # ウィンドウ全体で Drag&Drop 有効化
        
        # UI要素を初期化（メニュー/ツールバー/ステータスバーの構築は
        # ui/main_window_actions.py に分離。アクションは self の属性に載る）
        main_window_actions.create_menu_bar(self)
        main_window_actions.create_toolbar(self)
        main_window_actions.create_status_bar(self)

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

    def _current_tab_data(self, require_doc=False):
        """アクティブタブの DXFTab データを返す（無ければ None）。

        require_doc=True なら DXF ドキュメント読込済みであることも要求し、
        未読込時は共通の "No File" 警告を出して None を返す。
        """
        current_tab = self.get_current_tab()
        if not current_tab or not hasattr(current_tab, 'tab_data'):
            return None
        tab_data = current_tab.tab_data
        if require_doc and not tab_data.dxf_doc:
            QMessageBox.warning(self, "No File", "No DXF file is currently loaded.")
            return None
        return tab_data

    def _update_search_actions(self, tab_data):
        """検索系アクションの enabled 状態を tab_data の状態から一括更新する。

        タブ切り替え時と、各検索モードの開始・クリア後の両方から呼ぶ
        （かつては各所が個別に setEnabled を並べており、更新漏れの温床だった）。
        """
        has_results = len(tab_data.search_results) > 0 and tab_data.search_active
        has_handle_results = (
            len(tab_data.handle_search_results) > 0 and tab_data.handle_search_active)
        can_clear = has_results or has_handle_results or tab_data.boundary_search_active
        self.clear_search_action.setEnabled(can_clear)
        self.toolbar_clear_search_action.setEnabled(can_clear)
        self.find_next_action.setEnabled(len(tab_data.search_results) > 1)
        self.find_prev_action.setEnabled(len(tab_data.search_results) > 1)

        self.clear_handle_search_action.setEnabled(has_handle_results)
        self.find_next_handle_action.setEnabled(len(tab_data.handle_search_results) > 1)
        self.find_prev_handle_action.setEnabled(len(tab_data.handle_search_results) > 1)

        # Boundary highlight clear is available whenever overlays exist
        self.clear_boundary_highlight_action.setEnabled(
            len(tab_data.boundary_overlay_items) > 0)
    
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
        """タブを閉じる（最後の1枚を閉じてもアプリは終了せず、起動時と同じ
        ブランク状態に戻す。QTabWidget が空になると currentChanged(-1) が
        自動発火し、on_tab_changed → update_ui_for_active_tab() の
        "タブなし" 分岐がタイトル/ステータスバー/アクション有効状態を
        起動直後と同じ状態にリセットする）"""
        widget = self.tab_widget.widget(index)
        self.tab_widget.removeTab(index)
        if widget:
            widget.deleteLater()
    
    def on_tab_changed(self, index):
        """タブが変更されたときの処理"""
        self.update_ui_for_active_tab()
        
        # Update search-related UI based on current tab
        tab_data = self._current_tab_data()
        if tab_data:
            self._update_search_actions(tab_data)
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
            self._sync_layout_combo(tab_data)

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
            self._sync_layout_combo(None)
            self.setWindowTitle("DXF Viewer")
            self.status_bar.showMessage("Ready")

    def _sync_layout_combo(self, tab_data):
        """Repopulate the toolbar layout combo for the given tab, or clear it.

        Each tab has its own CAD viewer with its own independently tracked
        current layout (Model or a paper-space layout), so this must run on
        every tab switch as well as right after a file loads. Signals are
        blocked while rebuilding so this repopulation itself doesn't trigger
        on_layout_changed().
        """
        combo = self.layout_combo
        combo.blockSignals(True)
        try:
            combo.clear()
            if tab_data and tab_data.dxf_doc:
                combo.addItems(list(tab_data.dxf_doc.layouts.names_in_taborder()))
                combo.setCurrentText(tab_data.cad_viewer.current_layout_name())
                combo.setEnabled(True)
            else:
                combo.setEnabled(False)
        finally:
            combo.blockSignals(False)

    def on_layout_changed(self, name):
        """Handle the toolbar layout combo box selection changing.

        Switches the active tab's CAD viewer to draw the selected layout
        (Model or a paper-space layout, e.g. a title block placed outside
        Model space). No-ops on the blank/empty text combo.clear() emits
        while being repopulated (that path also has signals blocked, but
        this guard is cheap insurance) and when the selection doesn't
        actually change.
        """
        if not name:
            return
        tab_data = self._current_tab_data()
        if not tab_data or not tab_data.dxf_doc:
            return
        if name == tab_data.cad_viewer.current_layout_name():
            return
        tab_data.cad_viewer.draw_layout(name, reset_view=True)

    def open_file_dialog(self):
        """ファイル選択ダイアログを開く"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open DXF File", "", "DXF Files (*.dxf);;All Files (*)"
        )
        if file_path:
            self.load_dxf(file_path)
    
    def show_file_info(self):
        """ファイル情報ダイアログを表示"""
        tab_data = self._current_tab_data()
        if not tab_data or not tab_data.file_path:
            QMessageBox.warning(self, "No File", "No DXF file is currently loaded.")
            return

        dialog = FileInfoDialog(self)
        dialog.show_file_info(tab_data.file_path)
        dialog.exec_()
    
    def export_to_image(self):
        """画像エクスポートダイアログを表示"""
        tab_data = self._current_tab_data()
        if not tab_data or not tab_data.file_path:
            QMessageBox.warning(self, "No File", "No DXF file is currently loaded.")
            return

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
        tab_data = self._current_tab_data()
        if not tab_data:
            return

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
        tab_data = self._current_tab_data(require_doc=True)
        if not tab_data:
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
                ColorManager.store_entity_colors(tab_data)

            # Apply color to all entities
            ColorManager.apply_color_to_all_entities(
                tab_data, color_index, rgb_value, preserve_text)
            self.refresh_viewer(tab_data)

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
        tab_data = self._current_tab_data()
        if not tab_data:
            return
        if tab_data.color_change_active and tab_data.color_change_backup:
            # Restore colors from backup
            ColorManager.restore_colors_from_backup(tab_data)
            
            # Clear backup
            tab_data.color_change_backup.clear()
            tab_data.color_change_active = False
            
            # Refresh viewer
            self.refresh_viewer(tab_data)
            
            # Update UI
            self.restore_colors_action.setEnabled(False)
            self.toolbar_restore_colors_action.setEnabled(False)
            self.status_bar.showMessage("Original colors restored")
    
    def search_text(self):
        """Open search dialog and perform text search"""
        tab_data = self._current_tab_data(require_doc=True)
        if not tab_data:
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
                self._update_search_actions(tab_data)
                
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
        tab_data = self._current_tab_data()
        if not tab_data:
            return

        cleared = False

        if tab_data.search_active or tab_data.handle_search_active:
            # Restore original colors (shared backup for both modes)
            SearchManager.restore_original_colors(tab_data)

            if tab_data.search_active:
                tab_data.search_results.clear()
                tab_data.current_search_index = -1
                tab_data.search_active = False
                cleared = True

            if tab_data.handle_search_active:
                tab_data.handle_search_results.clear()
                tab_data.current_handle_search_index = -1
                tab_data.handle_search_active = False
                cleared = True

            # Refresh the viewer
            self.refresh_viewer(tab_data)

        if tab_data.boundary_search_active:
            self._clear_boundary_search(tab_data)
            cleared = True

        if cleared:
            self._update_search_actions(tab_data)
            self.status_bar.showMessage("Search cleared")

    def _step_search_result(self, results_attr, index_attr, step):
        """検索結果リストを巡回ナビゲートする（テキスト検索とHandle検索で共用）。

        results_attr/index_attr は tab_data 上の結果リスト・現在位置の属性名。
        """
        tab_data = self._current_tab_data()
        if not tab_data:
            return
        results = getattr(tab_data, results_attr)
        if results:
            index = (getattr(tab_data, index_attr) + step) % len(results)
            setattr(tab_data, index_attr, index)
            self.navigate_to_result(tab_data, results, index)

    def find_next(self):
        """Navigate to next search result"""
        self._step_search_result('search_results', 'current_search_index', +1)

    def find_previous(self):
        """Navigate to previous search result"""
        self._step_search_result('search_results', 'current_search_index', -1)

    # ------------------------------------------------------------------
    # Handle search (find one or more entities directly by DXF handle)
    # ------------------------------------------------------------------
    def search_handle(self):
        """Open the handle search dialog and highlight the resolved entities."""
        tab_data = self._current_tab_data(require_doc=True)
        if not tab_data:
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
        self._update_search_actions(tab_data)

        tab_data.current_handle_search_index = 0
        self.navigate_to_result(tab_data, tab_data.handle_search_results, 0)

        summary = f"Found {len(results)} entity(ies) by handle"
        if not_found:
            summary += f"; not found: {', '.join(not_found)}"
        self.status_bar.showMessage(summary)

    def find_next_handle(self):
        """Navigate to next handle-search result"""
        self._step_search_result('handle_search_results', 'current_handle_search_index', +1)

    def find_previous_handle(self):
        """Navigate to previous handle-search result"""
        self._step_search_result('handle_search_results', 'current_handle_search_index', -1)

    # ------------------------------------------------------------------
    # Boundary (rectangular region) search
    # ------------------------------------------------------------------
    def search_boundary(self):
        """Open the boundary search dialog and highlight matching regions."""
        tab_data = self._current_tab_data(require_doc=True)
        if not tab_data:
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
        area_ratio = params.get('min_area_pct', 10) / 100.0
        analysis = None
        matched = []
        try:
            analysis = RegionSearchManager.get_analysis(tab_data, area_ratio=area_ratio)
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
        boundary_overlay.dim_all_entities(tab_data)
        boundary_overlay.highlight_matched_labels(tab_data, matched)
        self.refresh_viewer(tab_data)
        tab_data.boundary_overlay_items = []  # destroyed by the refresh above
        boundary_overlay.draw_boundary_overlays(tab_data, matched)
        boundary_overlay.zoom_to_regions(tab_data, matched)

        tab_data.boundary_search_active = True
        self._update_search_actions(tab_data)

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
            boundary_overlay.draw_boundary_overlays(tab_data, matched)
        else:
            tab_data.matched_regions = []

    def clear_boundary_highlight(self):
        """Remove the boundary overlay; also un-dim if a boundary search is active."""
        tab_data = self._current_tab_data()
        if not tab_data:
            return
        if not tab_data.boundary_overlay_items and not tab_data.boundary_search_active:
            return

        if tab_data.boundary_search_active:
            # The drawing is still dimmed — restore original colors and re-render
            # (otherwise the drawing would be left in the single dim color).
            SearchManager.restore_original_colors(tab_data)
            tab_data.boundary_search_active = False
            self.refresh_viewer(tab_data)
            tab_data.boundary_overlay_items = []  # destroyed by the refresh
        else:
            # Only a persisted (post-Clear-Search) overlay remains.
            boundary_overlay.remove_boundary_overlays(tab_data)

        tab_data.matched_regions = []
        tab_data.boundary_keep_highlight = False
        self._update_search_actions(tab_data)
        self.status_bar.showMessage("Boundary highlight cleared")

    # ------------------------------------------------------------------
    # Layer consolidation
    # ------------------------------------------------------------------
    def consolidate_layers(self):
        """Collapse all source layers into 'Boundaries' and 'Imported'.

        'Boundaries' receives the boundary linework of the detected rectangular
        regions; everything else goes to 'Imported'. The change is in-memory
        only — reopening the file restores the original layers.
        """
        tab_data = self._current_tab_data(require_doc=True)
        if not tab_data:
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

                # Re-audit and reload the document completely, preserving
                # whichever layout (Model or a paper-space layout) is
                # currently displayed — otherwise this would silently snap
                # back to "Model" every time (see Layout Switching in
                # TECHNICAL.md).
                auditor = tab_data.dxf_doc.audit()
                tab_data.cad_viewer.set_document(
                    tab_data.dxf_doc, auditor,
                    layout=tab_data.cad_viewer.current_layout_name())

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


