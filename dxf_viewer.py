"""DXF Viewer - Main entry point."""

import sys
import argparse
from PyQt5.QtWidgets import QApplication

from ui.main_window import DXFViewerApp
from utils.app_utils import setup_signal_handlers, app, windows
from utils.file_utils import ensure_dxf_extension, is_valid_dxf_file


def run_gui(dxf_files=None):
    """Run the GUI application.

    Args:
        dxf_files: Optional list of DXF file paths to open
    """
    import utils.app_utils as app_utils

    app_utils.app = QApplication(sys.argv)

    # Set up signal handlers for graceful shutdown
    setup_signal_handlers()

    # Create main window
    window = DXFViewerApp()

    # Load files if specified
    if dxf_files:
        for file_path in dxf_files:
            # Add .dxf extension if missing
            file_path = ensure_dxf_extension(file_path)

            # Validate and load DXF file
            if is_valid_dxf_file(file_path):
                try:
                    window.load_dxf(file_path)
                except Exception as e:
                    print(f"Error opening {file_path}: {e}")
            else:
                print(f"Warning: {file_path} is not a valid DXF file or does not exist")

    window.show()
    app_utils.windows.append(window)

    # Run event loop
    try:
        sys.exit(app_utils.app.exec())
    except KeyboardInterrupt:
        # KeyboardInterrupt is handled by signal handler
        pass
    except Exception as e:
        print(f"Error in application execution: {e}")
        sys.exit(1)


def main():
    """Main entry point for command-line execution."""
    parser = argparse.ArgumentParser(
        description='DXF Viewer - View and analyze DXF files',
        epilog='Example: python dxf_viewer.py file1.dxf file2.dxf'
    )
    parser.add_argument(
        'files',
        nargs='*',
        help='DXF files to open (extension .dxf will be added if missing)'
    )
    args = parser.parse_args()

    run_gui(args.files)


if __name__ == "__main__":
    main()
