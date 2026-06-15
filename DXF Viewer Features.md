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
