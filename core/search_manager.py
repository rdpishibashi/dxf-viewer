"""Search functionality for DXF text entities."""

import re
from .tab_manager import SearchResult


class SearchManager:
    """Manages search operations in DXF documents."""

    @staticmethod
    def find_text_entities(doc, search_text, case_sensitive=False, whole_word=False):
        """Find all text entities matching search criteria.

        Args:
            doc: DXF document to search
            search_text: Text to search for
            case_sensitive: If True, perform case-sensitive search
            whole_word: If True, match whole words only

        Returns:
            List of SearchResult objects
        """
        results = []

        # Prepare search pattern
        if not case_sensitive:
            search_text = search_text.lower()

        if whole_word:
            pattern = r'\b' + re.escape(search_text) + r'\b'
            regex = re.compile(pattern, re.IGNORECASE if not case_sensitive else 0)

        # Search in modelspace
        msp = doc.modelspace()
        for entity in msp:
            if entity.dxftype() in ['TEXT', 'MTEXT']:
                entity_text = entity.dxf.text if hasattr(entity.dxf, 'text') else ''

                # Handle MTEXT formatting codes
                if entity.dxftype() == 'MTEXT':
                    # Remove common MTEXT formatting codes
                    entity_text = re.sub(r'\\[HPLpfFcC][^;]*;', '', entity_text)
                    entity_text = re.sub(r'[{}]', '', entity_text)

                compare_text = entity_text if case_sensitive else entity_text.lower()

                # Check for match
                match = False
                if whole_word:
                    match = regex.search(compare_text) is not None
                else:
                    match = search_text in compare_text

                if match:
                    # Get entity properties
                    position = None
                    rotation = 0
                    height = 1.0
                    original_color = entity.dxf.color if hasattr(entity.dxf, 'color') else 256  # 256 = BYLAYER

                    if entity.dxftype() == 'TEXT':
                        position = entity.dxf.insert
                        rotation = entity.dxf.rotation if hasattr(entity.dxf, 'rotation') else 0
                        height = entity.dxf.height if hasattr(entity.dxf, 'height') else 1.0
                    elif entity.dxftype() == 'MTEXT':
                        position = entity.dxf.insert
                        rotation = entity.dxf.rotation if hasattr(entity.dxf, 'rotation') else 0
                        height = entity.dxf.char_height if hasattr(entity.dxf, 'char_height') else 1.0

                    if position:
                        # Estimate text width (simple approximation)
                        width = len(entity_text) * height * 0.6

                        result = SearchResult(
                            entity=entity,
                            text=entity_text,
                            position=position,
                            rotation=rotation,
                            height=height,
                            width=width,
                            original_color=original_color
                        )
                        results.append(result)

        # Also search in blocks
        for block in doc.blocks:
            if block.name.startswith('*'):
                continue

            for entity in block:
                if entity.dxftype() in ['TEXT', 'MTEXT']:
                    entity_text = entity.dxf.text if hasattr(entity.dxf, 'text') else ''

                    if entity.dxftype() == 'MTEXT':
                        entity_text = re.sub(r'\\[HPLpfFcC][^;]*;', '', entity_text)
                        entity_text = re.sub(r'[{}]', '', entity_text)

                    compare_text = entity_text if case_sensitive else entity_text.lower()

                    match = False
                    if whole_word:
                        match = regex.search(compare_text) is not None
                    else:
                        match = search_text in compare_text

                    if match:
                        # Note: Block entities would need transformation based on INSERT entities
                        # For simplicity, we're recording them but highlighting might need adjustment
                        position = entity.dxf.insert if hasattr(entity.dxf, 'insert') else (0, 0, 0)
                        rotation = entity.dxf.rotation if hasattr(entity.dxf, 'rotation') else 0
                        height = entity.dxf.height if hasattr(entity.dxf, 'height') else 1.0
                        width = len(entity_text) * height * 0.6
                        original_color = entity.dxf.color if hasattr(entity.dxf, 'color') else 256

                        result = SearchResult(
                            entity=entity,
                            text=entity_text,
                            position=position,
                            rotation=rotation,
                            height=height,
                            width=width,
                            original_color=original_color
                        )
                        results.append(result)

        return results

    @staticmethod
    def store_all_entity_colors(tab_data):
        """Store original colors for all entities in the document.

        Args:
            tab_data: DXFTab instance
        """
        if not tab_data.dxf_doc:
            return

        tab_data.original_entity_colors.clear()

        # Store colors for all modelspace entities
        msp = tab_data.dxf_doc.modelspace()
        for entity in msp:
            if hasattr(entity.dxf, 'handle'):
                handle = entity.dxf.handle
                # Store color if it exists, or None to indicate BYLAYER
                if hasattr(entity.dxf, 'color'):
                    tab_data.original_entity_colors[handle] = entity.dxf.color
                else:
                    tab_data.original_entity_colors[handle] = None

        # Store colors for block entities
        for block in tab_data.dxf_doc.blocks:
            for entity in block:
                if hasattr(entity.dxf, 'handle'):
                    handle = entity.dxf.handle
                    if hasattr(entity.dxf, 'color'):
                        tab_data.original_entity_colors[handle] = entity.dxf.color
                    else:
                        tab_data.original_entity_colors[handle] = None

    @staticmethod
    def apply_search_highlighting(tab_data):
        """Apply color changes to highlight search results.

        Args:
            tab_data: DXFTab instance with search results
        """
        if not tab_data.dxf_doc or not tab_data.search_results:
            return

        # Use the user-selected dimmed color (tuple of index and RGB)
        dimmed_color_index, dimmed_rgb = tab_data.search_dim_color
        RED_COLOR_INDEX = 1
        RED_RGB = 0xFF0000

        # Dim all entities first
        msp = tab_data.dxf_doc.modelspace()
        for entity in msp:
            if hasattr(entity.dxf, 'color'):
                # Check if this entity is in search results
                is_result = any(r.entity.dxf.handle == entity.dxf.handle for r in tab_data.search_results)
                if not is_result:
                    try:
                        entity.dxf.color = dimmed_color_index
                        entity.dxf.true_color = dimmed_rgb
                    except:
                        pass

        # Also dim entities in blocks
        for block in tab_data.dxf_doc.blocks:
            if not block.name.startswith('*'):  # Skip system blocks
                for entity in block:
                    if hasattr(entity.dxf, 'color'):
                        is_result = any(r.entity.dxf.handle == entity.dxf.handle for r in tab_data.search_results)
                        if not is_result:
                            try:
                                entity.dxf.color = dimmed_color_index
                                entity.dxf.true_color = dimmed_rgb
                            except:
                                pass

        # Highlight search results in red
        for result in tab_data.search_results:
            if hasattr(result.entity.dxf, 'color'):
                try:
                    result.entity.dxf.color = RED_COLOR_INDEX
                    result.entity.dxf.true_color = RED_RGB
                except:
                    pass

    @staticmethod
    def restore_original_colors(tab_data):
        """Restore original colors for all entities.

        Args:
            tab_data: DXFTab instance with stored colors
        """
        if not tab_data.dxf_doc or not tab_data.original_entity_colors:
            return

        # Restore colors for modelspace entities
        msp = tab_data.dxf_doc.modelspace()
        for entity in msp:
            if hasattr(entity.dxf, 'handle'):
                handle = entity.dxf.handle
                if handle in tab_data.original_entity_colors:
                    original_color = tab_data.original_entity_colors[handle]
                    if original_color is not None:
                        # Entity had a color, restore it
                        entity.dxf.color = original_color
                    else:
                        # Entity didn't have a color attribute (was BYLAYER)
                        # Remove the color attribute if possible, or set to 256 (BYLAYER)
                        if hasattr(entity.dxf, 'color'):
                            try:
                                entity.dxf.color = 256  # 256 = BYLAYER
                            except:
                                pass  # Some entities may not support color changes

        # Restore colors for block entities
        for block in tab_data.dxf_doc.blocks:
            for entity in block:
                if hasattr(entity.dxf, 'handle'):
                    handle = entity.dxf.handle
                    if handle in tab_data.original_entity_colors:
                        original_color = tab_data.original_entity_colors[handle]
                        if original_color is not None:
                            entity.dxf.color = original_color
                        else:
                            if hasattr(entity.dxf, 'color'):
                                try:
                                    entity.dxf.color = 256  # 256 = BYLAYER
                                except:
                                    pass

        # Clear stored colors
        tab_data.original_entity_colors.clear()
