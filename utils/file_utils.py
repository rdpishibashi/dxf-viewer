"""File validation and DXF file utilities."""

import os


def ensure_dxf_extension(file_path):
    """Add .dxf extension to file path if it doesn't have one.

    Args:
        file_path: Path to the file

    Returns:
        File path with .dxf extension
    """
    if not file_path.lower().endswith('.dxf'):
        return file_path + '.dxf'
    return file_path


def is_valid_dxf_file(file_path):
    """Check if file exists and is a valid DXF file.

    Args:
        file_path: Path to the file to validate

    Returns:
        True if file is a valid DXF file, False otherwise
    """
    if not os.path.isfile(file_path):
        return False

    try:
        # Check extension
        if file_path.lower().endswith('.dxf'):
            return True

        # If no extension, check file content
        with open(file_path, 'rb') as f:
            header = f.read(128)
            # Simple DXF file check (look for AC10xx or AutoCAD strings)
            return b'AC10' in header or b'AutoCAD' in header
    except Exception:
        return False
