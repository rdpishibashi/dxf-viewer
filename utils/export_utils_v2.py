"""Alternative export utilities using PIL for guaranteed background control."""

import os
import tempfile
import ezdxf
from ezdxf.addons.drawing import RenderContext, Frontend
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
import matplotlib
import matplotlib.pyplot as plt
from PIL import Image, ImageDraw

# Configure matplotlib for high-quality text rendering
matplotlib.rcParams['text.antialiased'] = True
matplotlib.rcParams['path.simplify'] = False
matplotlib.rcParams['path.simplify_threshold'] = 0.0
matplotlib.rcParams['agg.path.chunksize'] = 0


def export_dxf_to_image_with_background(dxf_path, output_path, background_color="#000000"):
    """Export DXF to image with guaranteed background color using PIL.

    This version renders the DXF to a transparent PNG first, then composites
    it onto a background of the desired color. This guarantees the background
    color is exactly what you specify.

    Args:
        dxf_path: Path to source DXF file
        output_path: Path to output image file
        background_color: Background color as hex string (e.g., '#FFFFFF' for white)

    Returns:
        tuple: (success: bool, message: str)
    """
    temp_png = None
    try:
        # Load DXF document
        doc = ezdxf.readfile(dxf_path)
        msp = doc.modelspace()

        # Determine output format
        output_lower = output_path.lower()
        if output_lower.endswith('.png'):
            fmt = 'png'
        elif output_lower.endswith('.pdf'):
            fmt = 'pdf'
        elif output_lower.endswith('.svg'):
            fmt = 'svg'
        else:
            fmt = 'png'

        # Step 1: Render DXF to temporary transparent PNG at high resolution
        temp_fd, temp_png = tempfile.mkstemp(suffix='.png')
        os.close(temp_fd)

        # Create render context
        ctx = RenderContext(doc)

        # Create matplotlib figure with print-quality DPI
        # Use larger figure size for better resolution
        # Use 1200 DPI for high-quality printing
        fig = plt.figure(figsize=(50, 50), dpi=1200, facecolor='none')
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_facecolor('none')
        ax.set_axis_off()

        # Create backend and render
        backend = MatplotlibBackend(ax)
        Frontend(ctx, backend).draw_layout(msp, finalize=True)

        # Save to temporary PNG with transparency at print-quality DPI
        fig.savefig(
            temp_png,
            format='png',
            dpi=1200,
            facecolor='none',
            edgecolor='none',
            bbox_inches='tight',
            pad_inches=0.05,
            transparent=True
        )
        plt.close(fig)

        # Step 2: Composite onto background color using PIL
        # Open the transparent PNG
        foreground = Image.open(temp_png).convert('RGBA')

        # Create background image with desired color
        background = Image.new('RGBA', foreground.size, background_color)

        # Composite foreground onto background
        result = Image.alpha_composite(background, foreground)

        # Convert to RGB for formats that don't support transparency
        if fmt in ['pdf', 'jpg', 'jpeg']:
            result = result.convert('RGB')

        # Save final image with print-quality settings
        if fmt == 'pdf':
            # For PDF, save with print-quality resolution (1200 DPI)
            result.save(output_path, 'PDF', resolution=1200.0, quality=100)
        elif fmt == 'svg':
            # SVG needs special handling - save as high-res PNG instead
            output_png = output_path.replace('.svg', '.png')
            result.save(output_png, 'PNG', dpi=(1200, 1200), optimize=False)
            return True, f"Export successful (saved as PNG: {output_png})"
        else:
            # PNG format - save with DPI metadata
            result.save(output_path, 'PNG', dpi=(1200, 1200), optimize=False)

        return True, "Export successful"

    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        return False, f"Export failed: {str(e)}\n{error_details}"

    finally:
        # Clean up temporary file
        if temp_png and os.path.exists(temp_png):
            try:
                os.remove(temp_png)
            except:
                pass
