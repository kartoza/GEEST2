from qgis.PyQt.QtWidgets import (
    QLabel,
)
from qgis.core import (
    QgsMessageLog,
)

from .base_configuration_widget import BaseConfigurationWidget


class RasterReclassificationConfigurationWidget(BaseConfigurationWidget):
    """

    Used for raster layers like drought etc that will be classified.

    Currently does not provide any configuration options, only layer selection.
    """

    def add_internal_widgets(self) -> None:
        """
        Adds the internal widgets required for selecting raster layers and their correspondings.
        This method is called during the widget initialization and sets up the layout for the UI components.
        """
        try:
            self.info_label = QLabel("Classify raster layer")
            self.layout.addWidget(self.info_label)
        except Exception as e:
            QgsMessageLog.logMessage(f"Error in add_internal_widgets: {e}", "Geest")
            import traceback

            QgsMessageLog.logMessage(traceback.format_exc(), "Geest")

    def get_data(self) -> dict:
        """
        Retrieves and returns the current state of the widget

        Returns:
            dict: A dictionary containing the current attributes of the raster layers and/ors.
        """
        if not self.isChecked():
            return None
        return self.attributes

    def set_internal_widgets_enabled(self, enabled: bool) -> None:
        """
        Enables or disables the internal widgets (raster layers) based on the state of the radio button.

        Args:
            enabled (bool): Whether to enable or disable the internal widgets.
        """
        try:
            self.info_label.setEnabled(enabled)
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error in set_internal_widgets_enabled: {e}", "Geest"
            )