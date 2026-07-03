"""Search functionality for DXF text entities."""

import re
from ezdxf import bbox as ezdxf_bbox
from .tab_manager import SearchResult
from utils.text_utils import clean_mtext_format_codes, normalize_width


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

        # Prepare search pattern. Width-fold (zenkaku<->hankaku) so a query
        # typed in either width matches a label written in the other.
        search_text = normalize_width(search_text)
        if not case_sensitive:
            search_text = search_text.lower()

        if whole_word:
            pattern = r'\b' + re.escape(search_text) + r'\b'
            regex = re.compile(pattern, re.IGNORECASE if not case_sensitive else 0)

        # Search in modelspace
        msp = doc.modelspace()
        for entity in msp:
            if entity.dxftype() in ['TEXT', 'MTEXT']:
                raw_text = entity.dxf.text if hasattr(entity.dxf, 'text') else ''

                # Normalize format codes (MTEXT/TEXT) so matching uses visible text
                entity_text = clean_mtext_format_codes(raw_text)

                compare_text = normalize_width(entity_text)
                if not case_sensitive:
                    compare_text = compare_text.lower()

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
                    raw_text = entity.dxf.text if hasattr(entity.dxf, 'text') else ''

                    entity_text = clean_mtext_format_codes(raw_text)

                    compare_text = normalize_width(entity_text)
                if not case_sensitive:
                    compare_text = compare_text.lower()

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
    def find_entities_by_handles(doc, handles_text):
        """Resolve a free-form, space/comma-separated list of DXF handles.

        Looks up ``doc.entitydb`` directly rather than scanning entities, so a
        handle resolves wherever it lives (modelspace, paperspace, or inside a
        block definition) in one step. Handles are matched as exact-case hex
        strings internally, so each input token is normalized (leading '#'
        stripped, upper-cased) before lookup, since a handle copied from
        elsewhere in the UI may include a '#' or differ in case.

        Args:
            doc: DXF document to search
            handles_text: handles separated by whitespace and/or commas,
                e.g. "#212A, 2adc"

        Returns:
            (results, not_found) — results is a list of SearchResult (one per
            resolved handle, in input order, duplicates collapsed); not_found
            is the list of normalized handle strings that did not resolve.
        """
        results = []
        not_found = []
        seen = set()

        for raw in re.split(r'[\s,]+', handles_text.strip()):
            handle = raw.strip().lstrip('#').upper()
            if not handle or handle in seen:
                continue
            seen.add(handle)

            entity = doc.entitydb.get(handle)
            if entity is None:
                not_found.append(handle)
                continue

            position = None
            try:
                extents = ezdxf_bbox.extents([entity], fast=True)
                if extents.has_data:
                    position = extents.center
            except Exception:
                pass
            if position is None:
                # bbox calculation has no data for some entities with no
                # visible geometry (e.g. an MTEXT whose visible text is
                # empty/whitespace-only) — fall back to the anchor point so
                # navigation still has somewhere to center on.
                position = getattr(entity.dxf, 'insert', None)

            results.append(SearchResult(
                entity=entity,
                text=f"#{handle} ({entity.dxftype()})",
                position=position,
                original_color=getattr(entity.dxf, 'color', 256)
            ))

        return results, not_found

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
                # Store both color and true_color
                color = entity.dxf.color if hasattr(entity.dxf, 'color') else None
                true_color = entity.dxf.true_color if hasattr(entity.dxf, 'true_color') else None
                tab_data.original_entity_colors[handle] = (color, true_color)

        # Store colors for block entities
        for block in tab_data.dxf_doc.blocks:
            for entity in block:
                if hasattr(entity.dxf, 'handle'):
                    handle = entity.dxf.handle
                    color = entity.dxf.color if hasattr(entity.dxf, 'color') else None
                    true_color = entity.dxf.true_color if hasattr(entity.dxf, 'true_color') else None
                    tab_data.original_entity_colors[handle] = (color, true_color)

    @staticmethod
    def apply_highlighting(tab_data, results, dim_color):
        """Dim every entity except the given results, which are highlighted red.

        Generalized version of ``apply_search_highlighting`` that takes the
        results list and dim color explicitly, so other search modes (e.g.
        handle search) can reuse the same dim/highlight pass without
        duplicating it.

        Args:
            tab_data: DXFTab instance
            results: list of SearchResult to highlight in red
            dim_color: (color_index, rgb) tuple applied to everything else
        """
        if not tab_data.dxf_doc or not results:
            return

        dimmed_color_index, dimmed_rgb = dim_color
        RED_COLOR_INDEX = 1
        RED_RGB = 0xFF0000
        result_handles = {
            r.entity.dxf.handle for r in results if hasattr(r.entity.dxf, 'handle')
        }

        def dim_if_not_result(entity):
            if hasattr(entity.dxf, 'color'):
                handle = getattr(entity.dxf, 'handle', None)
                if handle not in result_handles:
                    try:
                        entity.dxf.color = dimmed_color_index
                        entity.dxf.true_color = dimmed_rgb
                    except Exception:
                        pass

        # Dim all entities first
        for entity in tab_data.dxf_doc.modelspace():
            dim_if_not_result(entity)

        # Also dim entities in blocks
        for block in tab_data.dxf_doc.blocks:
            if not block.name.startswith('*'):  # Skip system blocks
                for entity in block:
                    dim_if_not_result(entity)

        # Highlight results in red
        for result in results:
            if hasattr(result.entity.dxf, 'color'):
                try:
                    result.entity.dxf.color = RED_COLOR_INDEX
                    result.entity.dxf.true_color = RED_RGB
                except Exception:
                    pass

    @staticmethod
    def apply_search_highlighting(tab_data):
        """Apply color changes to highlight search results.

        Args:
            tab_data: DXFTab instance with search results
        """
        SearchManager.apply_highlighting(tab_data, tab_data.search_results, tab_data.search_dim_color)

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
                    original_color, original_true_color = tab_data.original_entity_colors[handle]

                    # Restore color attribute
                    if original_color is not None:
                        entity.dxf.color = original_color
                    else:
                        # Entity didn't have a color attribute (was BYLAYER)
                        if hasattr(entity.dxf, 'color'):
                            try:
                                entity.dxf.color = 256  # 256 = BYLAYER
                            except:
                                pass

                    # Restore or clear true_color attribute
                    if original_true_color is not None:
                        entity.dxf.true_color = original_true_color
                    else:
                        # Remove true_color if it wasn't originally set
                        try:
                            delattr(entity.dxf, 'true_color')
                        except (AttributeError, KeyError):
                            pass

        # Restore colors for block entities
        for block in tab_data.dxf_doc.blocks:
            for entity in block:
                if hasattr(entity.dxf, 'handle'):
                    handle = entity.dxf.handle
                    if handle in tab_data.original_entity_colors:
                        original_color, original_true_color = tab_data.original_entity_colors[handle]

                        # Restore color attribute
                        if original_color is not None:
                            entity.dxf.color = original_color
                        else:
                            if hasattr(entity.dxf, 'color'):
                                try:
                                    entity.dxf.color = 256  # 256 = BYLAYER
                                except:
                                    pass

                        # Restore or clear true_color attribute
                        if original_true_color is not None:
                            entity.dxf.true_color = original_true_color
                        else:
                            # Remove true_color if it wasn't originally set
                            try:
                                delattr(entity.dxf, 'true_color')
                            except (AttributeError, KeyError):
                                pass

        # Clear stored colors
        tab_data.original_entity_colors.clear()
