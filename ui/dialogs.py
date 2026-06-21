"""Dialog windows for DXF Viewer."""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QGroupBox, QCheckBox, QLineEdit, QTextEdit,
    QDialogButtonBox, QProgressBar
)
from PyQt5.QtGui import QColor, QFont
from workers.ezdxf_worker import EzdxfWorker


class BackgroundColorDialog(QDialog):
    """Dialog for changing background color."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Change Background Color")
        self.setModal(True)
        self.resize(400, 150)

        layout = QVBoxLayout(self)

        # Color selection
        color_group = QGroupBox("Select Background Color")
        color_layout = QVBoxLayout()

        # Color dropdown
        self.color_combo = QComboBox()
        self.color_combo.addItems([
            "Black",
            "White",
            "Dark Gray",
            "Gray",
            "Light Gray",
            "Dark Blue",
            "Navy"
        ])

        # Set Black as default
        self.color_combo.setCurrentText("Black")

        color_layout.addWidget(QLabel("Choose background color:"))
        color_layout.addWidget(self.color_combo)

        color_group.setLayout(color_layout)
        layout.addWidget(color_group)

        # Buttons
        button_layout = QHBoxLayout()
        self.apply_button = QPushButton("Apply")
        self.apply_button.clicked.connect(self.accept)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.apply_button)
        button_layout.addWidget(self.cancel_button)
        layout.addLayout(button_layout)

    def get_selected_color(self):
        """Get the selected QColor."""
        color_map = {
            "Black": QColor(0, 0, 0),
            "White": QColor(255, 255, 255),
            "Dark Gray": QColor(64, 64, 64),
            "Gray": QColor(128, 128, 128),
            "Light Gray": QColor(192, 192, 192),
            "Dark Blue": QColor(0, 0, 64),
            "Navy": QColor(0, 0, 128)
        }
        color_name = self.color_combo.currentText()
        return color_map.get(color_name, QColor(0, 0, 0)), color_name


class ColorChangeDialog(QDialog):
    """Dialog for changing all entity colors."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Change All Entity Colors")
        self.setModal(True)
        self.resize(400, 200)

        layout = QVBoxLayout(self)

        # Color selection
        color_group = QGroupBox("Select Color")
        color_layout = QVBoxLayout()

        # Color dropdown
        self.color_combo = QComboBox()
        self.color_combo.addItems([
            "White",
            "Red",
            "Yellow",
            "Green",
            "Cyan",
            "Blue",
            "Magenta",
            "Black",
            "Gray",
            "Light Gray"
        ])

        # Set White as default
        self.color_combo.setCurrentText("White")

        color_layout.addWidget(QLabel("Choose color for all entities:"))
        color_layout.addWidget(self.color_combo)

        # Add option to keep original colors for specific entity types
        self.preserve_text_check = QCheckBox("Preserve text entity colors")
        self.preserve_text_check.setToolTip("Keep original colors for TEXT and MTEXT entities")
        color_layout.addWidget(self.preserve_text_check)

        color_group.setLayout(color_layout)
        layout.addWidget(color_group)

        # Buttons
        button_layout = QHBoxLayout()
        self.apply_button = QPushButton("Apply")
        self.apply_button.clicked.connect(self.accept)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.apply_button)
        button_layout.addWidget(self.cancel_button)
        layout.addLayout(button_layout)

    def get_selected_color(self):
        """Get the selected DXF color index and RGB value."""
        # DXF color index 0 is BYBLOCK (not black!)
        # We use explicit RGB for black instead
        color_map = {
            "White": (7, 0xFFFFFF),
            "Red": (1, 0xFF0000),
            "Yellow": (2, 0xFFFF00),
            "Green": (3, 0x00FF00),
            "Cyan": (4, 0x00FFFF),
            "Blue": (5, 0x0000FF),
            "Magenta": (6, 0xFF00FF),
            "Black": (250, 0x000000),  # Use color 250 with explicit black RGB
            "Gray": (8, 0x808080),
            "Light Gray": (9, 0xC0C0C0)
        }
        color_name = self.color_combo.currentText()
        color_index, rgb_value = color_map.get(color_name, (7, 0xFFFFFF))
        return color_index, color_name, rgb_value

    def should_preserve_text(self):
        """Check if text colors should be preserved."""
        return self.preserve_text_check.isChecked()


class TextSearchDialog(QDialog):
    """Text search dialog for DXF files."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Search Text in DXF")
        self.setModal(True)
        self.resize(400, 300)

        layout = QVBoxLayout(self)

        # Search input
        search_group = QGroupBox("Search Text")
        search_layout = QVBoxLayout()

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Enter text to search...")
        self.search_input.returnPressed.connect(self.accept)
        search_layout.addWidget(self.search_input)

        # Search options
        options_layout = QHBoxLayout()
        self.case_sensitive_check = QCheckBox("Case sensitive")
        self.whole_word_check = QCheckBox("Whole words only")
        options_layout.addWidget(self.case_sensitive_check)
        options_layout.addWidget(self.whole_word_check)
        search_layout.addLayout(options_layout)

        search_group.setLayout(search_layout)
        layout.addWidget(search_group)

        # Non-matching entity color selection
        color_group = QGroupBox("Non-matching Entity Color")
        color_layout = QVBoxLayout()

        self.color_combo = QComboBox()
        self.color_combo.addItems([
            "Light Gray",
            "Gray",
            "White",
            "Black",
            "Red",
            "Yellow",
            "Green",
            "Cyan",
            "Blue",
            "Magenta"
        ])

        # Set Light Gray as default
        self.color_combo.setCurrentText("Light Gray")

        color_layout.addWidget(QLabel("Color for non-matching entities:"))
        color_layout.addWidget(self.color_combo)

        color_group.setLayout(color_layout)
        layout.addWidget(color_group)

        # Buttons
        button_layout = QHBoxLayout()
        self.search_button = QPushButton("Search")
        self.search_button.clicked.connect(self.accept)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.search_button)
        button_layout.addWidget(self.cancel_button)
        layout.addLayout(button_layout)

        # Focus on search input
        self.search_input.setFocus()

    def get_search_params(self):
        """Get search parameters."""
        return {
            'text': self.search_input.text(),
            'case_sensitive': self.case_sensitive_check.isChecked(),
            'whole_word': self.whole_word_check.isChecked(),
            'dim_color': self.get_selected_dim_color()
        }

    def get_selected_dim_color(self):
        """Get the selected DXF color index and RGB value for dimmed entities."""
        color_map = {
            "Light Gray": (251, 0xC0C0C0),
            "Gray": (8, 0x808080),
            "White": (7, 0xFFFFFF),
            "Black": (250, 0x000000),
            "Red": (1, 0xFF0000),
            "Yellow": (2, 0xFFFF00),
            "Green": (3, 0x00FF00),
            "Cyan": (4, 0x00FFFF),
            "Blue": (5, 0x0000FF),
            "Magenta": (6, 0xFF00FF)
        }
        color_name = self.color_combo.currentText()
        return color_map.get(color_name, (251, 0xC0C0C0))


class BoundarySearchDialog(QDialog):
    """Search dialog for rectangular region (boundary) names."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Search Boundary in DXF")
        self.setModal(True)
        self.resize(420, 460)

        layout = QVBoxLayout(self)

        # Region name input
        search_group = QGroupBox("Search Text")
        search_layout = QVBoxLayout()

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Enter region name to search...")
        self.search_input.returnPressed.connect(self.accept)
        search_layout.addWidget(self.search_input)

        # Search options
        options_layout = QHBoxLayout()
        self.case_sensitive_check = QCheckBox("Case sensitive")
        self.whole_word_check = QCheckBox("Whole words only")
        options_layout.addWidget(self.case_sensitive_check)
        options_layout.addWidget(self.whole_word_check)
        search_layout.addLayout(options_layout)

        search_group.setLayout(search_layout)
        layout.addWidget(search_group)

        # Vertex-coordinate input (alternative to name search)
        corners_group = QGroupBox("Or Search by Vertex Coordinates")
        corners_layout = QVBoxLayout()

        self.corners_input = QTextEdit()
        self.corners_input.setPlaceholderText(
            "Paste a vertex list copied from DXF-extract-labels's region\n"
            "popover, e.g.:\n"
            "1: (185.19, 23.07)\n"
            "2: (634.21, 23.07)\n"
            "3: (634.21, 104.00)\n..."
        )
        self.corners_input.setMaximumHeight(100)
        corners_layout.addWidget(self.corners_input)
        corners_layout.addWidget(QLabel(
            "When coordinates are given, the name search above is ignored."))

        corners_group.setLayout(corners_layout)
        layout.addWidget(corners_group)

        # Non-matching entity color selection
        color_group = QGroupBox("Non-matching Entity Color")
        color_layout = QVBoxLayout()

        self.color_combo = QComboBox()
        self.color_combo.addItems([
            "Light Gray",
            "Gray",
            "White",
            "Black",
            "Red",
            "Yellow",
            "Green",
            "Cyan",
            "Blue",
            "Magenta"
        ])
        self.color_combo.setCurrentText("Light Gray")

        color_layout.addWidget(QLabel("Color for non-matching entities:"))
        color_layout.addWidget(self.color_combo)

        color_group.setLayout(color_layout)
        layout.addWidget(color_group)

        # Keep the boundary highlight after Clear Search
        self.keep_highlight_check = QCheckBox(
            "Keep boundary highlight after Clear Search")
        layout.addWidget(self.keep_highlight_check)

        # Buttons
        button_layout = QHBoxLayout()
        self.search_button = QPushButton("Search")
        self.search_button.clicked.connect(self.accept)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.search_button)
        button_layout.addWidget(self.cancel_button)
        layout.addLayout(button_layout)

        self.search_input.setFocus()

    def get_search_params(self):
        """Get boundary search parameters."""
        return {
            'text': self.search_input.text(),
            'corners_text': self.corners_input.toPlainText(),
            'case_sensitive': self.case_sensitive_check.isChecked(),
            'whole_word': self.whole_word_check.isChecked(),
            'dim_color': self.get_selected_dim_color(),
            'keep_highlight': self.keep_highlight_check.isChecked()
        }

    def get_selected_dim_color(self):
        """Get the selected DXF color index and RGB value for dimmed entities."""
        color_map = {
            "Light Gray": (251, 0xC0C0C0),
            "Gray": (8, 0x808080),
            "White": (7, 0xFFFFFF),
            "Black": (250, 0x000000),
            "Red": (1, 0xFF0000),
            "Yellow": (2, 0xFFFF00),
            "Green": (3, 0x00FF00),
            "Cyan": (4, 0x00FFFF),
            "Blue": (5, 0x0000FF),
            "Magenta": (6, 0xFF00FF)
        }
        return color_map.get(self.color_combo.currentText(), (251, 0xC0C0C0))


class FileInfoDialog(QDialog):
    """Dialog to display DXF file information."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("DXF File Information")
        self.setModal(True)
        self.resize(800, 600)

        layout = QVBoxLayout(self)

        # Text display area
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setFont(self.get_monospace_font())
        layout.addWidget(self.text_edit)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # Indeterminate mode
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        # Buttons
        self.button_box = QDialogButtonBox(QDialogButtonBox.Close)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        self.worker = None

    def get_monospace_font(self):
        """Get a monospace font for displaying file info."""
        font = QFont("Courier New", 14)
        if not font.exactMatch():
            font = QFont("monospace", 14)
        return font

    def show_file_info(self, file_path):
        """Show file information by running ezdxf info command."""
        self.text_edit.clear()
        self.text_edit.append("Loading file information...")
        self.progress_bar.show()

        # Run ezdxf info in worker thread
        self.worker = EzdxfWorker("info", file_path)
        self.worker.finished.connect(self.on_info_finished)
        self.worker.start()

    def on_info_finished(self, success, output):
        """Handle completion of info command."""
        self.progress_bar.hide()
        self.text_edit.clear()

        if success:
            self.text_edit.append(output)
        else:
            self.text_edit.append(f"Error: {output}")

        if self.worker:
            self.worker.deleteLater()
            self.worker = None


class ExportImageDialog(QDialog):
    """Dialog for exporting DXF to image."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export to Image")
        self.setModal(True)
        self.resize(400, 300)

        layout = QVBoxLayout(self)

        # Message display
        self.label = QLabel("Exporting DXF to image...")
        layout.addWidget(self.label)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # Indeterminate mode
        layout.addWidget(self.progress_bar)

        # Status text
        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setMaximumHeight(100)
        layout.addWidget(self.status_text)

        # Buttons
        self.button_box = QDialogButtonBox(QDialogButtonBox.Close)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        self.worker = None

    def export_to_image(self, dxf_path, output_path, background_color=None):
        """Export DXF to image using ezdxf draw command.

        Args:
            dxf_path: Path to source DXF file
            output_path: Path to output image file
            background_color: Background color as hex string (e.g., '#FFFFFF')
        """
        self.status_text.append(f"Source: {dxf_path}")
        self.status_text.append(f"Output: {output_path}")
        if background_color:
            self.status_text.append(f"Background: {background_color}")
        self.status_text.append("Starting export...")

        # Run ezdxf draw in worker thread
        self.worker = EzdxfWorker("draw", dxf_path, output_path, background_color)
        self.worker.finished.connect(self.on_export_finished)
        self.worker.start()

    def on_export_finished(self, success, output):
        """Handle completion of export command."""
        self.progress_bar.hide()
        self.label.setText("Export completed!")

        if success:
            self.status_text.append("✅ Export successful!")
            self.status_text.append(output)
        else:
            self.status_text.append(f"❌ Export failed: {output}")

        if self.worker:
            self.worker.deleteLater()
            self.worker = None
