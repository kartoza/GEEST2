from qgis.PyQt.QtWidgets import QLabel, QDoubleSpinBox
from .base_configuration_widget import BaseConfigurationWidget
from qgis.core import Qgis
from geest.utilities import log_message


class IndexScoreConfigurationWidget(BaseConfigurationWidget):
    """
    A specialized radio button with additional widgets for IndexScore.
    """

    def add_internal_widgets(self) -> None:
        """
        Adds internal widgets specific to IndexScore.
        """
        try:
            self.info_label: QLabel = QLabel("Fill each polygon with a fixed value")
            self.layout.addWidget(self.info_label)
        except Exception as e:
            log_message(
                f"Error in add_internal_widgets: {e}", "Geest", level=Qgis.Critical
            )

    def get_data(self) -> dict:
        """
        Return the data as a dictionary, updating attributes with current value.
        """
        return self.attributes

    def set_internal_widgets_enabled(self, enabled: bool) -> None:
        """
        Enables or disables the internal widgets based on the state of the radio button.
        """
        try:
            self.info_label.setEnabled(enabled)
        except Exception as e:
            log_message(
                f"Error in set_internal_widgets_enabled: {e}",
                "Geest",
                level=Qgis.Critical,
            )