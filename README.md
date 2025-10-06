# DXF Viewer (Refactored)

A PyQt5-based DXF file viewer with advanced features including search, color management, and export capabilities.

## Project Structure

```
DXF-viewer/
├── dxf_viewer.py          # Main entry point
├── requirements.txt       # Python dependencies
├── README.md             # This file
├── ui/                   # User interface components
│   ├── __init__.py
│   ├── main_window.py    # Main application window (DXFViewerApp)
│   ├── dialogs.py        # All dialog windows
│   └── viewer_widget.py  # Enhanced CAD viewer widget
├── core/                 # Business logic
│   ├── __init__.py
│   ├── tab_manager.py    # Tab state management
│   ├── color_manager.py  # Entity color operations
│   └── search_manager.py # Text search functionality
├── workers/              # Background tasks
│   ├── __init__.py
│   └── ezdxf_worker.py   # Ezdxf command worker thread
└── utils/                # Utility functions
    ├── __init__.py
    ├── file_utils.py     # File validation and helpers
    └── app_utils.py      # Application setup and signals

## Installation

```bash
pip install -r requirements.txt
```

**Note**: The export feature requires `matplotlib` for rendering with custom background colors.

## Usage

### Command Line

```bash
# Launch viewer
python dxf_viewer.py

# Open specific files
python dxf_viewer.py file1.dxf file2.dxf

# Extension is optional
python dxf_viewer.py drawing1 drawing2
```

### Features

- **Multi-tab Interface**: View multiple DXF files simultaneously
- **Search**: Find text entities with customizable highlighting
- **Color Management**: Change entity colors with background-aware rendering
- **Background Color**: Customize viewer background
- **Export**: Convert DXF to PNG/SVG/PDF
- **File Info**: View detailed DXF file information
- **Drag & Drop**: Open files by dropping them into the window

## Architecture

### Separation of Concerns

- **UI Layer** (`ui/`): All PyQt5 widgets and visual components
- **Core Layer** (`core/`): Business logic independent of UI
- **Workers** (`workers/`): Background thread operations
- **Utils** (`utils/`): Shared utility functions

### Key Classes

- **DXFViewerApp**: Main application window with menu/toolbar
- **DXFTab**: Per-tab state container
- **ColorManager**: Handles all entity color operations
- **SearchManager**: Text search and highlighting logic
- **PinchZoomCADViewer**: Enhanced CAD viewer with gestures

## Development

### Adding New Features

1. **UI Components**: Add to `ui/dialogs.py` or create new UI module
2. **Business Logic**: Add to appropriate manager in `core/`
3. **Background Tasks**: Add new worker in `workers/`
4. **Utilities**: Add shared functions to `utils/`

### Code Organization

- Each module has a single, clear responsibility
- Manager classes use static methods for stateless operations
- UI and business logic are separated for easier testing
- All dialogs are centralized in `ui/dialogs.py`

## Migration from Original

The original monolithic `dxf_viewer.py` (1683 lines) has been refactored into:
- 14 modular files
- Clear separation between UI, business logic, and utilities
- Easier to maintain, test, and extend

Original file preserved in `../DXF-processor/dxf_viewer.py`
