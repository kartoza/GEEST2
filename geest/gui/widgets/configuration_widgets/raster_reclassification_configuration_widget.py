from qgis.PyQt.QtWidgets import (
    QLabel,
)
from .base_configuration_widget import BaseConfigurationWidget
from geest.utilities import log_message


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
            log_message(
                f"Error in add_internal_widgets: {e}", tag="Geest", level=Qgis.Critical
            )
            import traceback

            log_message(traceback.format_exc(), tag="Geest", level=Qgis.Critical)

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
            log_message(
                f"Error in set_internal_widgets_enabled: {e}",
                tag="Geest",
                level=Qgis.Critical,
            )