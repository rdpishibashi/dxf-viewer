"""Color management for DXF entities."""


class ColorManager:
    """Manages color operations on DXF entities."""

    @staticmethod
    def store_entity_colors(tab_data):
        """Store original colors for all entities before modification.

        Args:
            tab_data: DXFTab instance containing the DXF document
        """
        if not tab_data.dxf_doc:
            return

        tab_data.color_change_backup.clear()

        # Store colors for modelspace entities
        msp = tab_data.dxf_doc.modelspace()
        for entity in msp:
            if hasattr(entity.dxf, 'handle'):
                handle = entity.dxf.handle
                if hasattr(entity.dxf, 'color'):
                    tab_data.color_change_backup[handle] = entity.dxf.color
                else:
                    tab_data.color_change_backup[handle] = None

        # Store colors for block entities
        for block in tab_data.dxf_doc.blocks:
            for entity in block:
                if hasattr(entity.dxf, 'handle'):
                    handle = entity.dxf.handle
                    if hasattr(entity.dxf, 'color'):
                        tab_data.color_change_backup[handle] = entity.dxf.color
                    else:
                        tab_data.color_change_backup[handle] = None

    @staticmethod
    def apply_color_to_all_entities(tab_data, color_index, rgb_value, preserve_text=False):
        """Apply specified color to all entities.

        Args:
            tab_data: DXFTab instance containing the DXF document
            color_index: DXF color index (ACI)
            rgb_value: RGB color value as integer (0xRRGGBB)
            preserve_text: If True, skip TEXT and MTEXT entities
        """
        if not tab_data.dxf_doc:
            return

        # Apply color to modelspace entities
        msp = tab_data.dxf_doc.modelspace()
        for entity in msp:
            # Skip text entities if preserve_text is True
            if preserve_text and entity.dxftype() in ['TEXT', 'MTEXT']:
                continue

            # Set both ACI color and true_color to ensure consistent rendering
            try:
                entity.dxf.color = color_index
                # Always set true_color to override ACI auto-switching behavior
                entity.dxf.true_color = rgb_value
            except:
                pass  # Some entities might not support color

        # Apply color to block entities
        for block in tab_data.dxf_doc.blocks:
            if not block.name.startswith('*'):  # Skip system blocks
                for entity in block:
                    if preserve_text and entity.dxftype() in ['TEXT', 'MTEXT']:
                        continue

                    try:
                        entity.dxf.color = color_index
                        entity.dxf.true_color = rgb_value
                    except:
                        pass

    @staticmethod
    def restore_colors_from_backup(tab_data):
        """Restore colors from the color change backup.

        Args:
            tab_data: DXFTab instance containing the DXF document and backup
        """
        if not tab_data.dxf_doc or not tab_data.color_change_backup:
            return

        # Restore colors for modelspace entities
        msp = tab_data.dxf_doc.modelspace()
        for entity in msp:
            if hasattr(entity.dxf, 'handle'):
                handle = entity.dxf.handle
                if handle in tab_data.color_change_backup:
                    original_color = tab_data.color_change_backup[handle]
                    if original_color is not None:
                        entity.dxf.color = original_color
                    else:
                        # Entity didn't have color, set to BYLAYER
                        if hasattr(entity.dxf, 'color'):
                            try:
                                entity.dxf.color = 256  # BYLAYER
                            except:
                                pass

        # Restore colors for block entities
        for block in tab_data.dxf_doc.blocks:
            for entity in block:
                if hasattr(entity.dxf, 'handle'):
                    handle = entity.dxf.handle
                    if handle in tab_data.color_change_backup:
                        original_color = tab_data.color_change_backup[handle]
                        if original_color is not None:
                            entity.dxf.color = original_color
                        else:
                            if hasattr(entity.dxf, 'color'):
                                try:
                                    entity.dxf.color = 256  # BYLAYER
                                except:
                                    pass
