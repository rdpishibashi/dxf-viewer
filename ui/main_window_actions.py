"""Menu bar / toolbar / status bar construction for the main window.

Pure widget building extracted from ``DXFViewerApp`` — each builder takes the
window, creates the widgets, and stores the actions back on it under the same
attribute names the rest of ``ui.main_window`` (and its enabled-state updates)
already uses. No behavior lives here: every action just connects to a window
method.

Toolbar buttons intentionally *reuse* menu actions where both exist (shared
enabled state); ``setIconText`` gives those actions a shorter label on the
toolbar while the menu keeps the full text.
"""

from PyQt5.QtWidgets import (
    QAction, QApplication, QComboBox, QLabel, QStatusBar, QToolBar
)
from PyQt5.QtGui import QFont, QKeySequence


def _ui_font():
    return QFont(QApplication.font())


def _make_action(window, text, slot, font, shortcut=None, icon_text=None,
                 tooltip=None, enabled=True):
    """Create a QAction wired to a window slot (the one repeated pattern here)."""
    action = QAction(text, window)
    action.setFont(font)
    if shortcut is not None:
        action.setShortcut(shortcut)
    if icon_text is not None:
        action.setIconText(icon_text)  # shorter label on the toolbar
    if tooltip is not None:
        action.setToolTip(tooltip)
    action.triggered.connect(slot)
    action.setEnabled(enabled)
    return action


def create_menu_bar(window):
    """メニューバーを作成"""
    menubar = window.menuBar()
    font = _ui_font()
    menubar.setFont(font)

    # File メニュー
    file_menu = menubar.addMenu('File')
    file_menu.addAction(_make_action(
        window, 'Open DXF File...', window.open_file_dialog, font,
        shortcut=QKeySequence.Open))
    file_menu.addSeparator()
    file_menu.addAction(_make_action(
        window, 'Exit', window.close, font, shortcut=QKeySequence.Quit))

    # Tools メニュー
    tools_menu = menubar.addMenu('Tools')
    window.info_action = _make_action(
        window, 'File Information...', window.show_file_info, font, enabled=False)
    tools_menu.addAction(window.info_action)
    tools_menu.addSeparator()

    window.export_action = _make_action(
        window, 'Export to Image...', window.export_to_image, font, enabled=False)
    tools_menu.addAction(window.export_action)
    tools_menu.addSeparator()

    window.change_colors_action = _make_action(
        window, 'Change All Entity Colors...', window.change_all_colors, font,
        enabled=False)
    tools_menu.addAction(window.change_colors_action)

    window.restore_colors_action = _make_action(
        window, 'Restore Original Colors', window.restore_all_colors, font,
        enabled=False)
    tools_menu.addAction(window.restore_colors_action)
    tools_menu.addSeparator()

    window.background_color_action = _make_action(
        window, 'Change Background Color...', window.change_background_color, font,
        enabled=False)
    tools_menu.addAction(window.background_color_action)
    tools_menu.addSeparator()

    window.consolidate_layers_action = _make_action(
        window, 'Consolidate Layers', window.consolidate_layers, font,
        tooltip='Consolidate all layers into Boundaries and Imported',
        enabled=False)
    tools_menu.addAction(window.consolidate_layers_action)

    # Search メニュー
    search_menu = menubar.addMenu('Search')

    # Search Text group
    window.search_action = _make_action(
        window, 'Search Text...', window.search_text, font,
        shortcut=QKeySequence.Find, enabled=False)
    search_menu.addAction(window.search_action)

    window.clear_search_action = _make_action(
        window, 'Clear Search', window.clear_search, font,
        shortcut=QKeySequence('Ctrl+Shift+F'), enabled=False)
    search_menu.addAction(window.clear_search_action)
    search_menu.addSeparator()

    window.find_next_action = _make_action(
        window, 'Find Next', window.find_next, font,
        shortcut=QKeySequence.FindNext, icon_text='Next', enabled=False)
    search_menu.addAction(window.find_next_action)

    window.find_prev_action = _make_action(
        window, 'Find Previous', window.find_previous, font,
        shortcut=QKeySequence.FindPrevious, icon_text='Prev', enabled=False)
    search_menu.addAction(window.find_prev_action)
    search_menu.addSeparator()

    # Search Handle group (one or more entities found directly by DXF handle)
    window.search_handle_action = _make_action(
        window, 'Search Handle...', window.search_handle, font,
        icon_text='Search Handle',
        tooltip='Find entities by DXF handle, e.g. #212A', enabled=False)
    search_menu.addAction(window.search_handle_action)

    window.clear_handle_search_action = _make_action(
        window, 'Clear Search Handle', window.clear_search, font,
        icon_text='Clear', enabled=False)
    search_menu.addAction(window.clear_handle_search_action)

    window.find_next_handle_action = _make_action(
        window, 'Find Next Handle', window.find_next_handle, font,
        icon_text='Next', enabled=False)
    search_menu.addAction(window.find_next_handle_action)

    window.find_prev_handle_action = _make_action(
        window, 'Find Previous Handle', window.find_previous_handle, font,
        icon_text='Prev', enabled=False)
    search_menu.addAction(window.find_prev_handle_action)
    search_menu.addSeparator()

    # Search Boundary group (rectangular region by name)
    window.search_boundary_action = _make_action(
        window, 'Search Boundary...', window.search_boundary, font,
        shortcut=QKeySequence('Ctrl+B'), icon_text='Search Boundary',
        tooltip='Search rectangular regions by name (Ctrl+B)', enabled=False)
    search_menu.addAction(window.search_boundary_action)

    window.clear_boundary_highlight_action = _make_action(
        window, 'Clear Boundary Highlight', window.clear_boundary_highlight, font,
        icon_text='Clear',
        tooltip='Remove persisted region boundary highlights', enabled=False)
    search_menu.addAction(window.clear_boundary_highlight_action)


def create_toolbar(window):
    """ツールバーを作成（1段目: Open＋検索3グループ / 2段目: 色変更系＋Export/Info＋Layout）"""
    font = _ui_font()

    toolbar = QToolBar()
    toolbar.setFont(font)
    window.addToolBar(toolbar)

    toolbar.addAction(_make_action(window, 'Open', window.open_file_dialog, font))
    toolbar.addSeparator()

    # Search Text group
    window.toolbar_search_action = _make_action(
        window, 'Search Text', window.search_text, font, enabled=False)
    toolbar.addAction(window.toolbar_search_action)

    window.toolbar_clear_search_action = _make_action(
        window, 'Clear', window.clear_search, font, enabled=False)
    toolbar.addAction(window.toolbar_clear_search_action)

    # Search navigation — reuse the menu actions (shared enabled state,
    # iconText shortens the label shown on the toolbar button)
    for action in (window.find_next_action, window.find_prev_action):
        action.setFont(font)
        toolbar.addAction(action)
    toolbar.addSeparator()

    # Search Handle group — reuse the menu actions (shared enabled state)
    for action in (window.search_handle_action, window.clear_handle_search_action,
                   window.find_next_handle_action, window.find_prev_handle_action):
        action.setFont(font)
        toolbar.addAction(action)
    toolbar.addSeparator()

    # Search Boundary group — reuse the menu actions (shared enabled state)
    for action in (window.search_boundary_action,
                   window.clear_boundary_highlight_action):
        action.setFont(font)
        toolbar.addAction(action)

    # --- Second toolbar row: Change Colors onward, then Export/Info/Layout ---
    window.addToolBarBreak()
    toolbar2 = QToolBar()
    toolbar2.setFont(font)
    window.addToolBar(toolbar2)

    window.toolbar_change_colors_action = _make_action(
        window, 'Change Colors', window.change_all_colors, font, enabled=False)
    toolbar2.addAction(window.toolbar_change_colors_action)

    window.toolbar_restore_colors_action = _make_action(
        window, 'Restore Colors', window.restore_all_colors, font, enabled=False)
    toolbar2.addAction(window.toolbar_restore_colors_action)
    toolbar2.addSeparator()

    window.toolbar_background_color_action = _make_action(
        window, 'Background Color', window.change_background_color, font,
        enabled=False)
    toolbar2.addAction(window.toolbar_background_color_action)
    toolbar2.addSeparator()

    # Consolidate Layers — reuse the menu action (shared enabled state)
    window.consolidate_layers_action.setFont(font)
    toolbar2.addAction(window.consolidate_layers_action)
    toolbar2.addSeparator()

    window.toolbar_export_action = _make_action(
        window, 'Export', window.export_to_image, font, enabled=False)
    toolbar2.addAction(window.toolbar_export_action)

    window.toolbar_info_action = _make_action(
        window, 'Info', window.show_file_info, font, enabled=False)
    toolbar2.addAction(window.toolbar_info_action)
    toolbar2.addSeparator()

    # Layout selector — switches which layout (Model or a paper-space
    # layout) the CAD viewer draws. Populated per-file in load_dxf() and
    # kept in sync per-tab in update_ui_for_active_tab().
    layout_label = QLabel('Layout:')
    layout_label.setFont(font)
    toolbar2.addWidget(layout_label)
    window.layout_combo = QComboBox()
    window.layout_combo.setFont(font)
    window.layout_combo.setEnabled(False)
    window.layout_combo.currentTextChanged.connect(window.on_layout_changed)
    toolbar2.addWidget(window.layout_combo)


def create_status_bar(window):
    """ステータスバーを作成"""
    window.status_bar = QStatusBar()
    window.setStatusBar(window.status_bar)
    window.status_bar.showMessage("Ready")
