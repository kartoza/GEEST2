from qgis.PyQt.QtWidgets import (
    QDoubleSpinBox, QSpinBox, QLineEdit, QComboBox, QRadioButton, QButtonGroup,
    QPushButton, QLabel, QHBoxLayout, QVBoxLayout, QWidget
)
from qgis.PyQt.QtCore import Qt
from qgis.gui import QgsLayerComboBox
from qgis.core import QgsMapLayer

class GeestWidgetFactory:
    @staticmethod
    def create_widget(widget_type, spec, parent):
        if widget_type == 'doublespinbox':
            widget = QDoubleSpinBox(parent)
            widget.setRange(spec.get('min', 0), spec.get('max', spec.get('Index Score', 100)))
            widget.setDecimals(spec.get('decimals', 2))
            widget.setValue(spec.get('Default Index Score', 0.0))
            return widget
        elif widget_type == 'spinbox':
            widget = QSpinBox(parent)
            widget.setRange(spec.get('min', 0), spec.get('max', 99999))
            widget.setValue(spec.get('default', 0))
            return widget
        elif widget_type == 'lineedit':
            widget = QLineEdit(parent)
            widget.setText(spec.get('default', ''))
            return widget
        elif widget_type == 'dropdown':
            widget = QComboBox(parent)
            options = spec.get('options', [])
            widget.addItems(options)
            default = spec.get('default')
            if default in options:
                widget.setCurrentText(default)
            elif options:
                widget.setCurrentText(options[0])
            return widget
        elif widget_type == 'pushbutton':
            widget = QPushButton(spec.get('text', 'Download'), parent)
            # Connect button to a placeholder function or leave it to the caller
            return widget
        elif widget_type == 'layerselector':
            widget = QgsLayerComboBox(parent)
            layer_type = spec.get('layer_type', 'vector')  # 'vector' or 'raster'
            if layer_type == 'vector':
                widget.setFilters(QgsMapLayer.VectorLayer)
            elif layer_type == 'raster':
                widget.setFilters(QgsMapLayer.RasterLayer)
            widget.setCurrentLayer(spec.get('default_layer', None))
            return widget
        else:
            return None

    @staticmethod
    def get_widget_value(widget, spec):
        widget_type = spec.get('type')
        if widget_type in ['doublespinbox', 'spinbox']:
            return widget.value()
        elif widget_type == 'lineedit':
            return widget.text()
        elif widget_type == 'dropdown':
            return widget.currentText()
        elif widget_type == 'pushbutton':
            return widget.text()
        elif widget_type == 'layerselector':
            layer = widget.currentLayer()
            return layer.name() if layer else None
        else:
            return None

    @staticmethod
    def create_widgets_from_dict(config_dict, parent):
        """
        Creates widgets based on the provided configuration dictionary.

        :param config_dict: Dictionary containing widget configurations.
        :param parent: Parent widget.
        :return: QWidget containing the created widgets, possibly grouped with radio buttons.
        """
        widgets_to_create = []
        widget_specs = []

        # Iterate through the config_dict to identify which widgets to create
        for key, value in config_dict.items():
            if key.startswith("Use") and value:
                # Determine the type of widget based on the key
                if key.endswith("Downloader"):
                    widget_type = 'pushbutton'
                    spec = {
                        'type': widget_type,
                        'text': 'Download from ' + key.replace("Use ", "").replace(" Downloader", ""),
                        'source': key.replace("Use ", "").replace(" Downloader", "")
                    }
                elif key.endswith("Buffer Point"):
                    widget_type = 'lineedit'
                    spec = {
                        'type': widget_type,
                        'label': key,
                        'default': config_dict.get(key.replace("Use ", ""), "")
                    }
                elif key.endswith("Create Grid"):
                    widget_type = 'spinbox'
                    spec = {
                        'type': widget_type,
                        'min': 0,
                        'max': 1000,
                        'default': config_dict.get(key, 0)
                    }
                elif key.endswith("Rasterize Layer"):
                    widget_type = 'layerselector'
                    spec = {
                        'type': widget_type,
                        'layer_type': 'raster',
                        'default_layer': config_dict.get(key, None)
                    }
                else:
                    continue  # Skip keys that do not match any known widget type

                widget_specs.append(spec)

        # If multiple widgets are to be created, group them with radio buttons
        if len(widget_specs) > 1:
            container = QWidget(parent)
            layout = QVBoxLayout()
            button_group = QButtonGroup(container)

            for idx, spec in enumerate(widget_specs):
                radio_button = QRadioButton(spec.get('text', 'Option'))
                if idx == 0:
                    radio_button.setChecked(True)
                button_group.addButton(radio_button, id=idx)
                layout.addWidget(radio_button)

                # Create the actual widget
                widget = GeestWidgetFactory.create_widget(spec['type'], spec, container)
                layout.addWidget(widget)

            container.setLayout(layout)
            return container
        elif len(widget_specs) == 1:
            # Only one widget to create
            widget = GeestWidgetFactory.create_widget(widget_specs[0]['type'], widget_specs[0], parent)
            return widget
        else:
            # No widgets to create
            return None
