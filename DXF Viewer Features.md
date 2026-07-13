# DXF Viewer


## Overview
This document consolidates the Search and Color Change feature specifications into a single, unified feature for the DXF Viewer. The original source documents are preserved below as integrated sections. Minor formatting adjustments may have been applied to ensure consistent Markdown structure.

---

## Summary
- Search entities by layer, type, text content, or block name.
- Visual highlighting via single color or auto-assigned palettes.
- Result interactions: hover highlight, click to zoom/focus, apply/reset colors.
- Supports large drawings with indexing considerations (implementation-specific).



---

# A. Text Search Feature

## Overview
The DXF Viewer now includes a comprehensive text search functionality that allows you to search for text within DXF files and highlight the results with visual overlays.

## Features

### 1. Search Dialog
- **Access**: Menu → Search → Search Text (or press Ctrl+F / Cmd+F)
- **Options**:
  - **Case sensitive**: Match exact case of search text
  - **Whole words only**: Match complete words only (not partial matches)

### 2. Visual Highlighting
- **Red color**: Text entities that match the search criteria are displayed in red
- **Dimmed gray**: All other entities are displayed in light gray (color 251)
- Original colors are automatically restored when search is cleared

### 3. Navigation
- **Find Next**: F3 or Menu → Search → Find Next
- **Find Previous**: Shift+F3 or Menu → Search → Find Previous
- **Status bar**: Shows current result number and total matches

### 4. Clear Search
- **Clear Search**: Ctrl+Shift+F or Menu → Search → Clear Search
- Removes all highlights and clears search results

## How It Works

### Search Algorithm
1. Iterates through all TEXT and MTEXT entities in the modelspace
2. Also searches within block definitions
3. Normalizes format codes via `utils/text_utils.clean_mtext_format_codes()`
   (ezdxf `plain_mtext`) so matching uses the *visible* text — applied to both
   TEXT and MTEXT. This replaced an earlier regex that missed `\A`/`\W`/`\T`
   codes present in most ULVAC MTEXT runs, which had prevented visible labels
   (e.g. `MPD RACK1`) from matching.
4. Supports regex patterns for whole-word matching

### Color Modification System
- Stores original colors for all entities before search
- Changes matched text entities to red (DXF color index 1)
- Dims all other entities to light gray (DXF color index 251)
- Restores original colors when search is cleared
- Refreshes the CAD viewer to display color changes immediately

### Navigation
- Centers the view on each search result
- Updates highlight colors to indicate current selection
- Wraps around when reaching the end of results

## Usage Example

1. Open a DXF file in the viewer
2. Press Ctrl+F (or Cmd+F on Mac) to open the search dialog
3. Enter your search term (e.g., "Test Label")
4. Optionally enable case-sensitive or whole-word search
5. Click "Search" or press Enter
6. Use F3/Shift+F3 to navigate between results
7. Press Ctrl+Shift+F to clear the search when done

## Technical Details

### Supported Entity Types
- TEXT entities (single-line text)
- MTEXT entities (multi-line text with formatting)
- Text within block definitions

### Coordinate System
- DXF coordinates are transformed to Qt coordinates
- Y-axis is inverted for proper display
- Rotation angles are adjusted for Qt's coordinate system

### Performance Considerations
- Search is performed in memory (fast for most files)
- Highlights are added as lightweight overlay items
- Large files with many text entities may show slight delay

## Testing

A test file `test_search.dxf` has been created with various text entities for testing:
```bash
python3 test_search.py  # Creates test_search.dxf
python3 dxf_viewer.py test_search.dxf  # Opens the test file
```

## Known Limitations

1. **Block References**: Text within blocks is found but highlighting position may not account for all block transformations (scale, rotation of INSERT entities)
2. **Text Width Estimation**: Width calculation is approximate based on character count
3. **Paper Space**: Currently only searches in model space, not paper space layouts
4. **Attribute Text**: ATTRIB entities within block references are not yet fully supported

## Future Enhancements

Potential improvements for future versions:
- Export search results to a report
- Search within dimensions and leaders
- Support for wildcards and regular expressions in search
- Search history/recent searches
- Replace functionality (would require DXF modification)
- Search within specific layers only



---

# A2. Handle Search Feature

## Overview
Find one or more entities directly by their DXF handle (the hex ID shown,
for example, next to a vertex coordinate in the region popover, or in File
Information) and highlight them — without needing to know any visible text.

## Features

### 1. Search Dialog
- **Access**: Menu → Search → Search Handle... (toolbar button "Search Handle")
- **Input**: one or more handles, e.g. `#212A` or `212A, 2ADC`. Separate
  multiple handles with a space or comma. The leading `#` and letter case are
  both optional.
- **Color for non-matching entities**: same dim-color option as text search.

### 2. Visual Highlighting
- Matching entities are recolored red; everything else is dimmed, the same
  scheme as plain text search.
- The view centers on the first match. If a handle has no computable position
  (e.g. an MTEXT whose visible text is empty), it is still found and
  highlighted, just not auto-centered on.

### 3. Navigation
- **Find Next Handle** / **Find Previous Handle** (toolbar: "Next" / "Prev" in
  the Search Handle group) step between multiple matched handles, the same way
  Find Next/Previous does for text search.

### 4. Clearing
- **Clear Search Handle** (toolbar: "Clear" in the Search Handle group), or
  the general **Clear Search** (Ctrl+Shift+F), restores original colors.

## How It Works
- Handles are resolved via `doc.entitydb`, which indexes every entity in the
  file regardless of whether it lives in modelspace, a paperspace layout, or a
  block definition — so a handle copied from anywhere in the file resolves
  directly with no scanning.
- Text search, Boundary search, and Handle search are mutually exclusive: each
  one clears any other active search before starting.

## Known Limitations
1. A handle belonging to a block definition is shared by every INSERT of that
   block (same constraint as text search recoloring block-sourced matches):
   recoloring it affects all instances of that block, not just one.
2. Some entities have no computable position to auto-center on (very rare —
   e.g. an MTEXT with whitespace-only visible text); they are still found and
   highlighted.

---

# C. Boundary (Region) Search Feature

## Overview
Search a drawing for **rectangular regions** (functional areas such as racks or
boxes enclosed by hand-drawn boundary lines) **by name** and highlight the
matching boundaries. Complements the text search.

## Features

### 1. Search Dialog
- **Access**: Menu → Search → Search Boundary... (or press Ctrl+B)
- **Options**:
  - **Search Text**: region name to find
  - **Case sensitive** / **Whole words only**: same semantics as text search
  - **Color for non-matching entities**: dim color applied to everything else
  - **Keep boundary highlight after Clear Search**: when checked, the region
    outline stays visible after Clear Search restores the dimmed drawing

### 2. Visual Highlighting
- Matching region boundaries are drawn as **red outlines** overlaid on the view
  (non-destructive — the DXF document is not recolored for the outline)
- The matched name label itself (the text that matched your search) is also
  recolored red, the same way plain text search highlights matches — so the
  string you searched for stands out inside its red-outlined region. This only
  works for labels placed directly in modelspace; labels coming from a shared
  block (INSERT) keep the dimmed color, since recoloring them would affect
  every other instance of that block (same limitation as plain text search)
- All other entities are dimmed to the selected color
- All matches are highlighted at once and the view zooms to fit them

### 3. Clearing
- **Clear Search** (Ctrl+Shift+F): restores the dimmed drawing to its original
  colors. If *Keep boundary highlight* was checked, the red outlines remain.
- **Clear Boundary Highlight**: removes the red outlines. If the search is still
  active (drawing dimmed), it also restores the original colors, so the drawing
  is never left in the single dim color.

## How It Works

### Region Detection
- Reuses the rectangular-region detection from DXF-extract-labels
  (`core/region_detector.py`). Identification keys: drawing frame =
  lineweight 100; region boundary = lineweight 25 with color 2 (ACI yellow).
- Region names are taken from labels near the bottom edge of each region.
- Detection reads the file from disk, so it is unaffected by on-screen dimming.

### Performance
- The first boundary search analyzes the drawing (a few seconds on large files,
  shown with a busy cursor). The result is cached per tab, so subsequent
  boundary searches are instant.

## Known Limitations
1. Requires drawings that use the ULVAC frame/boundary line conventions
   (lineweight 100 frame, lineweight 25 / color 2 boundaries). Drawings without
   them report "no regions detected".
2. Unnamed regions are not matched (search is by name).

---

# D. Layer Consolidation Feature

## Overview
Collapse a drawing's many source layers (ULVAC exports contain dozens of
`NoLayerName_xxx` layers) into two clearly named English layers:
- **Boundaries**: the boundary linework of the detected rectangular regions
- **Imported**: every other entity

## Access
- Toolbar → Consolidate Layers (or Menu → Tools → Consolidate Layers)

## How It Works
1. Runs (cached) region detection to find the rectangular regions.
2. Modelspace lines that use the region line style (lineweight 25, ACI color 2)
   and lie on a detected region edge are moved to **Boundaries**.
3. All other entities (including block contents and paperspace) are moved to
   **Imported**.
4. The now-unused source layers are removed (the `0` and `Defpoints` layers are
   kept).

## Important Notes
1. **Non-destructive**: only the in-memory document is changed; the file on disk
   is untouched. **Reopen the file to restore the original layers.**
2. The change is reflected in the viewer's layer panel and in image export.
3. Boundary lines that live inside block definitions are not reclassified (block
   content is shared across INSERTs) and remain in **Imported**.

---

# E. Layout Switching Feature

## Overview
Some DXF files place the title block (drawing number, title text) outside
Model space, in a separate paper-space layout (e.g. `EE6492-464-01B.dxf`'s
title block lives in a layout named "ICADSX Layout"). The viewer used to
draw Model space only and hid ezdxf's own built-in "Select Layout" menu (to
keep it off macOS's global menu bar), so that content had no way to be
displayed — not a rendering limit, just a missing UI affordance.

Files produced by the ICADSX CAD tool (assembly drawings etc.) go further:
the fully composed drawing — border, title block, dimensions — lives
entirely in the "ICADSX Layout" paper-space layout, built from VIEWPORT
entities that reference and arrange Model space content. Model space itself
holds the same part geometry unarranged, with no border/title
block/dimensions, and isn't meant to be viewed directly. Verified across 20
real ICADSX-origin sample files (2026-07-13): whenever a layout named
exactly "ICADSX Layout" is present, it contains at least one VIEWPORT and
is the intended view.

## Access
- Files containing a layout named exactly "ICADSX Layout" open on that
  layout automatically (`_initial_layout_name()` in `ui/main_window.py`);
  every other file still opens on Model, unchanged.
- Toolbar → "Layout:" combo box, at the end of the second row (after Info),
  remains available to switch manually. Lists every layout in the file
  (`Model` plus any paper-space layouts), in tab order. Disabled when no
  file is loaded.

## How It Works
1. Selecting an entry calls `PinchZoomCADViewer.draw_layout(name,
   reset_view=True)` (from ezdxf's `CADViewer`), which redraws the scene
   from that layout and zooms to fit it.
2. Each tab tracks its own current layout independently (ezdxf's
   `CADWidget` already does this per CAD viewer instance); switching tabs
   re-syncs the combo box to that tab's own selection.
3. `refresh_viewer()` — the shared re-render used by Search Text/Handle/
   Boundary, Color change/restore, and Consolidate Layers — now passes
   `layout=<the tab's current layout>` explicitly. Previously it always
   redrew Model, so triggering any of those operations while a paper-space
   layout was displayed would have silently snapped the view back to
   Model.
4. `PinchZoomCADViewer._install_dark_background_render_context()` forces
   ACI color 7 ("adapts to background") to resolve to white on every
   layout. ezdxf's `RenderContext` otherwise assumes Model space has a dark
   background (color 7 → white) but paper-space layouts have a *light*
   background — a printed sheet (color 7 → black). This viewer always uses
   one fixed black canvas regardless of layout, so a paper-space layout
   whose content is entirely color 7 (e.g. this file's title block) used to
   render fully black-on-black — drawn, but invisible.

## Known Limitations
- Search Text/Handle/Boundary, Color Change, and Consolidate Layers remain
  modelspace-only (unchanged by this feature — see their own sections
  above). Running them while a paper-space layout is displayed won't error,
  but any highlight/effect is computed against modelspace and won't be
  visible until you switch back to Model.
- Changing the background color (Tools → Change Background Color) only
  updates the Qt canvas brush — it does not update ezdxf's `RenderContext`,
  which still resolves ACI color 7 assuming this viewer's fixed black
  canvas. Picking a light background can make color-7 entities (white)
  hard to read. This pre-existing gap applies to Model space too and isn't
  specific to layout switching; fixing it is out of scope here.
- Export and File Information are unaffected either way: both always
  operate on modelspace/the whole file regardless of which layout is
  currently displayed.

---

# B. DXF Viewer - Color Change Feature

## Overview
The DXF Viewer now includes a feature to change all entity colors to a specified color. This is useful for:
- Creating uniform drawings for printing
- Improving visibility with specific color schemes
- Standardizing colors across different DXF files

## Features

### 1. Change All Entity Colors
**Access**: Tools → Change All Entity Colors...

Opens a dialog where you can:
- **Select a color** from a dropdown list:
  - White (default)
  - Red
  - Yellow
  - Green
  - Cyan
  - Blue
  - Magenta
  - Black
  - Gray
  - Light Gray

- **Preserve text colors** (optional):
  - Check "Preserve text entity colors" to keep TEXT and MTEXT entities in their original colors
  - Useful when you want to change drawing colors but keep text readable

### 2. Restore Original Colors
**Access**: Tools → Restore Original Colors

- Returns all entities to their original colors
- Only enabled after colors have been changed
- Preserves the original DXF file structure

## How to Use

### Change All Colors:
1. Open a DXF file
2. Go to Tools → Change All Entity Colors...
3. Select your desired color from the dropdown
4. Optionally check "Preserve text entity colors"
5. Click "Apply"
6. All entities (except preserved text) will change to the selected color

### Restore Colors:
1. After changing colors, go to Tools → Restore Original Colors
2. All entities return to their original colors

## Technical Details

### DXF Color Indices
The feature uses standard AutoCAD Color Index (ACI) values:
- 0: Black
- 1: Red
- 2: Yellow
- 3: Green
- 4: Cyan
- 5: Blue
- 6: Magenta
- 7: White
- 8: Gray
- 9: Light Gray
- 256: BYLAYER (inherits from layer)

### How It Works
1. **Backup**: Before changing colors, the original color of every entity is stored
2. **Apply**: Colors are changed directly in the DXF document structure
3. **Refresh**: The viewer is refreshed to show the new colors
4. **Restore**: Original colors can be restored from the backup

### Compatibility
- Works with both modelspace and block entities
- Handles entities with no color attribute (BYLAYER)
- Skips system blocks (those starting with *)

## Important Notes

1. **Non-destructive**: The original DXF file is not modified unless you explicitly save it
2. **Search interaction**: If a text search is active, it will be cleared before changing colors
3. **Per-tab state**: Each open tab maintains its own color change state
4. **Memory efficient**: Only stores color information, not full entity data

## Use Cases

### 1. Printing Preparation
Change all colors to black or white for clean prints:
```
Tools → Change All Entity Colors... → Select "Black" → Apply
```

### 2. Visibility Enhancement
Change to high-contrast colors for better screen viewing:
```
Tools → Change All Entity Colors... → Select "White" → Apply
```

### 3. Text Emphasis
Change drawing to gray while keeping text in original colors:
```
Tools → Change All Entity Colors... → Select "Gray" 
→ Check "Preserve text entity colors" → Apply
```

## Limitations

- Changes are temporary until the file is saved
- Some special entities might not support color changes
- Block references (INSERT entities) inherit colors from their definitions

---

## Change Log
- 2025-08-27 03:56:45 UTC: Initial merge of SEARCH_FEATURE and COLOR_CHANGE_FEATURE into one Markdown.
- 2026-06-15: Search text normalization moved to ezdxf `plain_mtext`
  (`utils/text_utils.clean_mtext_format_codes`), fixing missed `\A`/`\W`/`\T`
  MTEXT codes that prevented matching visible labels. Regression test added at
  `tests/regression/test_mtext_clean_search.py`.
- 2026-06-15: Added Boundary (Region) Search — search rectangular regions by
  name and highlight their boundaries (overlay), reusing the region detection
  from DXF-extract-labels (`core/region_detector.py`,
  `core/region_search_manager.py`). Regression test at
  `tests/regression/test_region_search.py`.
- 2026-06-15: Added Layer Consolidation (Tools → Consolidate Layers) — collapse
  all source layers into `Boundaries` (detected region edges) and `Imported`
  (`core/layer_consolidator.py`). Non-destructive; reopen to restore. Regression
  test at `tests/regression/test_layer_consolidation.py`.
- 2026-06-15: Fixed Restore Colors not returning to the import colors —
  `ColorManager` now backs up and restores `true_color` as well as the ACI color
  (true_color takes precedence when rendering, so leaving it set kept the
  changed color).
- 2026-06-23: Added Handle Search — find and highlight one or more entities
  directly by DXF handle (e.g. `#212A`), resolved via `doc.entitydb` so it
  works regardless of where the entity lives (modelspace, paperspace, or a
  block definition). Mutually exclusive with Text Search and Boundary Search.
- 2026-07-12: Added Layout Switching (toolbar combo box) so paper-space
  layouts — e.g. a title block placed outside Model space — can be viewed.
  Fixed `refresh_viewer()` to preserve the active layout instead of always
  redrawing Model, which Search/Color/Consolidate Layers all rely on via a
  shared code path. Regression test at
  `tests/regression/test_layout_switching.py`.
- 2026-07-12: Fixed paper-space layouts rendering fully black-on-black.
  ezdxf's `RenderContext` assumes Paper space has a light (printed-sheet)
  background and resolves ACI color 7 to black there, but this viewer
  always uses a fixed black canvas — so a layout using color 7 throughout
  (e.g. the title block above) was drawn but invisible. Added
  `PinchZoomCADViewer._install_dark_background_render_context()` to force
  color 7 to white on every layout. Regression test extended to check
  rendered pen/brush colors in the title-block area.
  Regression test at `tests/regression/test_handle_search.py`.
