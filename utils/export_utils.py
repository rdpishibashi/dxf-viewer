"""Utilities for exporting DXF files to images."""

import ezdxf
from ezdxf.addons.drawing import RenderContext, Frontend
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
import matplotlib.pyplot as plt


def export_dxf_to_image(dxf_path, output_path, background_color="#000000"):
    """Export DXF file to image with specified background color.

    Args:
        dxf_path: Path to source DXF file
        output_path: Path to output image file
        background_color: Background color as hex string (e.g., '#FFFFFF' for white)

    Returns:
        tuple: (success: bool, message: str)
    """
    try:
        # Load DXF document
        doc = ezdxf.readfile(dxf_path)
        msp = doc.modelspace()

        # Determine output format from file extension
        output_lower = output_path.lower()
        if output_lower.endswith('.png'):
            fmt = 'png'
        elif output_lower.endswith('.svg'):
            fmt = 'svg'
        elif output_lower.endswith('.pdf'):
            fmt = 'pdf'
        else:
            fmt = 'png'  # Default to PNG

        # Create render context
        ctx = RenderContext(doc)

        # Create matplotlib figure with background color
        fig = plt.figure(facecolor=background_color)
        ax = fig.add_axes([0, 0, 1, 1])

        # Set axis background color
        ax.set_facecolor(background_color)

        # Remove axis lines and ticks
        ax.set_axis_off()

        # Create backend
        backend = MatplotlibBackend(ax)

        # Render the DXF
        Frontend(ctx, backend).draw_layout(msp, finalize=True)

        # Save to file with explicit background color
        fig.savefig(
            output_path,
            format=fmt,
            dpi=300,  # High quality
            facecolor=background_color,
            edgecolor='none',
            bbox_inches='tight',
            pad_inches=0.1
        )
        plt.close(fig)

        return True, "Export successful"

    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        return False, f"Export failed: {str(e)}\n{error_details}"
