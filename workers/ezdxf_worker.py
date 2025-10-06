"""Background worker for running ezdxf commands."""

import sys
import subprocess
from PyQt5.QtCore import QThread, pyqtSignal
from utils.export_utils_v2 import export_dxf_to_image_with_background


class EzdxfWorker(QThread):
    """Worker thread for executing ezdxf commands in the background."""

    finished = pyqtSignal(bool, str)  # success, output

    def __init__(self, command, file_path, output_path=None, background_color=None):
        """Initialize the worker.

        Args:
            command: Command to run ('info' or 'draw')
            file_path: Path to the DXF file
            output_path: Output path for 'draw' command
            background_color: Background color as hex string (e.g., '#FFFFFF' for white)
        """
        super().__init__()
        self.command = command
        self.file_path = file_path
        self.output_path = output_path
        self.background_color = background_color

    def run(self):
        """Execute the ezdxf command."""
        try:
            # Use current Python interpreter
            python_exe = sys.executable

            # Build command
            if self.command == "info":
                cmd = [python_exe, "-m", "ezdxf", "info", self.file_path]

                # Execute command
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

                if result.returncode == 0:
                    output = result.stdout if result.stdout else "Command completed successfully"
                    self.finished.emit(True, output)
                else:
                    error = result.stderr if result.stderr else f"Command failed with return code {result.returncode}"
                    self.finished.emit(False, error)

            elif self.command == "draw":
                # Use custom export function with background color support
                bg_color = self.background_color if self.background_color else "#000000"
                success, message = export_dxf_to_image_with_background(
                    self.file_path, self.output_path, bg_color
                )
                self.finished.emit(success, message)

            else:
                self.finished.emit(False, f"Unknown command: {self.command}")
                return

        except subprocess.TimeoutExpired:
            self.finished.emit(False, "Command timed out after 30 seconds")
        except Exception as e:
            self.finished.emit(False, f"Error executing command: {str(e)}")
