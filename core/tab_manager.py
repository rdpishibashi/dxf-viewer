"""Tab management for DXF Viewer."""

from ui.viewer_widget import PinchZoomCADViewer


class SearchResult:
    """Container for a single search result."""

    def __init__(self, entity, text, position, rotation=0, height=1.0, width=None, original_color=None):
        """Initialize search result.

        Args:
            entity: DXF entity object
            text: Text content of the entity
            position: (x, y) or (x, y, z) position tuple
            rotation: Rotation angle in degrees
            height: Text height
            width: Estimated text width
            original_color: Original color of the entity
        """
        self.entity = entity
        self.text = text
        self.position = position
        self.rotation = rotation
        self.height = height
        self.width = width
        self.original_color = original_color
        self.highlight_item = None  # QGraphicsItem for highlighting


class DXFTab:
    """Container for per-tab state and data."""

    def __init__(self, file_path=None):
        """Initialize tab with optional file path.

        Args:
            file_path: Path to DXF file to load (optional)
        """
        self.cad_viewer = PinchZoomCADViewer()
        self.cad_viewer.setAcceptDrops(False)
        self.dxf_doc = None
        self.msp = None
        self.file_path = file_path

        # Search-related attributes
        self.search_results = []
        self.current_search_index = -1
        self.overlay_scene = None
        self.overlay_items = []
        self.original_entity_colors = {}  # Store original colors for all entities
        self.search_active = False  # Track if search is active
        self.search_dim_color = (251, 0xC0C0C0)  # Default dimmed color (index, RGB)

        # Color change attributes
        self.color_change_active = False  # Track if colors have been changed
        self.color_change_backup = {}  # Store original colors for color change feature

        # Background color (stored as hex string for ezdxf compatibility)
        self.background_color = "#000000"  # Default black background
