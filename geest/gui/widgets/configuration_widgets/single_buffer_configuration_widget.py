import os
from qgis.PyQt.QtWidgets import (
    QLabel,
    QHBoxLayout,
    QSpinBox,
)
from qgis.core import QgsMessageLog

from .base_configuration_widget import BaseConfigurationWidget


class SingleBufferConfigurationWidget(BaseConfigurationWidget):
    """
    A specialized radio button with additional QSpinBox buffer distance.
    """

    def add_internal_widgets(self) -> None:
        """
        Adds internal widgets specific to self.set_internal_widgets_visible(self.isChecked()) - in this case there are none.
        """
        try:

            # Travel Increments input
            self.buffer_distance_layout = QHBoxLayout()
            self.buffer_distance_label = QLabel("Buffer Distance (m):")
            self.buffer_distance_input = QSpinBox()
            self.buffer_distance_input.setRange(0, 100000)
            self.buffer_distance_layout.addWidget(self.buffer_distance_label)
            self.buffer_distance_layout.addWidget(self.buffer_distance_input)
            default_distance = self.attributes.get("default_single_buffer_distance", 0)
            buffer_distance = self.attributes.get(
                "single_buffer_point_layer_distance", default_distance
            )
            if buffer_distance == 0:
                buffer_distance = default_distance
            try:
                self.buffer_distance_input.setValue(int(buffer_distance))
            except (ValueError, TypeError):
                self.buffer_distance_input.setValue(int(default_distance))

            # Add all layouts to the main layout
            self.layout.addLayout(self.buffer_distance_layout)
            self.buffer_distance_input.valueChanged.connect(self.update_data)

        except Exception as e:
            QgsMessageLog.logMessage(f"Error in add_internal_widgets: {e}", "Geest")
            import traceback

            QgsMessageLog.logMessage(traceback.format_exc(), "Geest")

    def get_data(self) -> dict:
        """
        Return the data as a dictionary, updating attributes with current value.
        """
        if not self.isChecked():
            return None

        self.attributes["single_buffer_point_layer_distance"] = (
            self.buffer_distance_input.value()
        )

        return self.attributes

    def set_internal_widgets_enabled(self, enabled: bool) -> None:
        """
        Enables or disables the internal widgets based on the state of the radio button.
        """
        try:
            self.buffer_distance_input.setEnabled(enabled)
            self.buffer_distance_label.setEnabled(enabled)
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error in set_internal_widgets_enabled: {e}", "Geest"
            )