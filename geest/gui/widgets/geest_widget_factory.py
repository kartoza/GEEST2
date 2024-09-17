from qgis.PyQt.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QRadioButton,
    QLabel,
    QPushButton,
    QButtonGroup,
    QLineEdit,
    QCheckBox,
    QSpinBox,
    QDoubleSpinBox,
    QComboBox,
    QFileDialog,
)
from qgis.PyQt.QtCore import Qt
from qgis.gui import QgsMapLayerComboBox
from qgis.core import QgsMapLayer

class GeestWidgetFactory:
    @staticmethod
    def create_widgets(layer_data: dict, parent=None):
        """
        Create widgets based on the provided layer_data dictionary.
        If multiple widgets are to be created, include radio buttons for selection.

        :param layer_data: Dictionary containing layer properties.
        :param parent: Parent widget.
        :return: QWidget containing the created widgets.
        """
        # Define mappings for 'Use' keys to widget specifications
        use_keys_mapping = {
            "Use Default Index Score": {
                "label": "Default Index Score",
                "type": "doublespinbox",
                "min": 0.0,
                "max": 100.0,
                "decimals": 1,
                "default": layer_data.get("Default Index Score", 0.0),
                "tooltip": "The default index score value."
            },
            "Use Multi Buffer Point": {
                "label": "Multi Buffer Distances",
                "type": "lineedit",
                "default": layer_data.get("Default Multi Buffer Distances", ""),
                "tooltip": "Enter comma-separated buffer distances."
            },
            "Use Single Buffer Point": {
                "label": "Single Buffer Distance",
                "type": "spinbox",
                "min": 0,
                "max": 10000,
                "default": layer_data.get("Default Single Buffer Distances", 0),
                "tooltip": "Enter buffer distance."
            },
            "Use Create Grid": {
                "label": "Pixel Size",
                "type": "spinbox",
                "min": 0,
                "max": 10000,
                "default": layer_data.get("Default pixel", 0),
                "tooltip": "Enter pixel size for grid creation."
            },
            "Use OSM Downloader": {
                "label": "Fetch the data from OSM",
                "description": "Using this option, we will try to fetch the data needed for this indicator directly from OSM.",
                "type": "download_button",
                "tooltip": "Download data from OSM."
            },
            "Use WBL Downloader": {
                "label": "Fetch the data from WBL",
                "description": "Using this option, we will try to fetch the data needed for this indicator directly from WBL.",
                "type": "download_button",
                "tooltip": "Download data from WBL."
            },
            "Use Humdata Downloader": {
                "label": "Fetch the data from HumData",
                "description": "Using this option, we will try to fetch the data needed for this indicator directly from HumData.",
                "type": "download_button",
                "tooltip": "Download data from HumData."
            },
            "Use Mapillary Downloader": {
                "label": "Fetch the data from Mapillary",
                "description": "Using this option, we will try to fetch the data needed for this indicator directly from Mapillary.",
                "type": "download_button",
                "tooltip": "Download data from Mapillary."
            },
            "Use Other Downloader": {
                "label": "Fetch the data from Other Source",
                "description": f"Using this option, we will try to fetch the data needed for this indicator directly from {layer_data.get('Use Other Downloader', '')}.",
                "type": "download_button",
                "tooltip": f"Download data from {layer_data.get('Use Other Downloader', 'Other Source')}."
            },
            "Use Add Layers Manually": {
                "label": "Add Layers Manually",
                "description": "Using this option, you can add layers manually.",
                "type": "layer_selector",
                "layer_type": "vector",
                "tooltip": "Select a vector layer."
            },
            "Use Classify Poly into Classes": {
                "label": "Classify Polygons into Classes",
                "description": "Using this option, you can classify polygons into classes.",
                "type": "layer_selector",
                "layer_type": "polygon",
                "tooltip": "Select a polygon layer."
            },
            "Use CSV to Point Layer": {
                "label": "Convert CSV to Point Layer",
                "description": "Using this option, you can convert a CSV file to a point layer.",
                "type": "csv_to_point",
                "tooltip": "Select a CSV file and specify longitude and latitude columns."
            },
            "Use Poly per Cell": {
                "label": "Poly per Cell",
                "description": "Using this option, create a polygon per grid cell.",
                "type": "layer_selector",
                "layer_type": "polygon",
                "tooltip": "Select a polygon layer."
            },
            "Use Polyline per Cell": {
                "label": "Polyline per Cell",
                "description": "Using this option, create a polyline per grid cell.",
                "type": "layer_selector",
                "layer_type": "polyline",
                "tooltip": "Select a polyline layer."
            },
            "Use Point per Cell": {
                "label": "Point per Cell",
                "description": "Using this option, create a point per grid cell.",
                "type": "layer_selector",
                "layer_type": "point",
                "tooltip": "Select a point layer."
            }
        }

        # Identify all 'Use' keys that are enabled
        use_keys_enabled = {k: v for k, v in layer_data.items() if k.startswith("Use") and v}

        # If no 'Use' keys are enabled, return an empty widget
        if not use_keys_enabled:
            return QWidget()

        # Prepare to create widgets
        container = QWidget(parent)
        main_layout = QVBoxLayout()
        container.setLayout(main_layout)

        # Check how many 'Use' keys are enabled
        if len(use_keys_enabled) > 1:
            # Create radio buttons for selection
            radio_group_layout = QHBoxLayout()
            radio_group = QButtonGroup(container)
            radio_group.setExclusive(True)

            widget_containers = []

            for idx, (use_key, value) in enumerate(use_keys_enabled.items()):
                mapping = use_keys_mapping.get(use_key)
                if not mapping:
                    continue  # Skip if no mapping defined

                # Create radio button
                radio_button = QRadioButton(mapping["label"])
                radio_group.addButton(radio_button, id=idx)
                radio_group_layout.addWidget(radio_button)

                # Create a container for the associated widgets
                widget_container = QWidget()
                widget_layout = QVBoxLayout()
                widget_container.setLayout(widget_layout)

                # Add description
                description_label = QLabel(mapping["description"])
                description_label.setWordWrap(True)
                widget_layout.addWidget(description_label)

                # Create the actual widget based on type
                widget = GeestWidgetFactory.create_specific_widget(mapping, layer_data)
                if widget:
                    widget_layout.addWidget(widget)

                # Initially hide all widget containers
                widget_container.setVisible(False)
                widget_containers.append(widget_container)

                # Connect radio button to show/hide widgets
                radio_button.toggled.connect(lambda checked, wc=widget_container: wc.setVisible(checked))

            # Add radio buttons layout to main layout
            main_layout.addLayout(radio_group_layout)

            # Add all widget containers to main layout
            for wc in widget_containers:
                main_layout.addWidget(wc)

            # Select the first radio button by default
            if radio_group.buttons():
                radio_group.buttons()[0].setChecked(True)

        else:
            # Only one 'Use' key is enabled, no radio buttons needed
            use_key, value = next(iter(use_keys_enabled.items()))
            mapping = use_keys_mapping.get(use_key)
            if not mapping:
                return container  # Return empty or handle generically

            # Add description
            description_label = QLabel(mapping["description"])
            description_label.setWordWrap(True)
            main_layout.addWidget(description_label)

            # Create the actual widget based on type
            widget = GeestWidgetFactory.create_specific_widget(mapping, layer_data)
            if widget:
                main_layout.addWidget(widget)

        return container

    @staticmethod
    def create_specific_widget(mapping: dict, layer_data: dict):
        """
        Create a specific widget based on the mapping type.

        :param mapping: Dictionary containing widget specifications.
        :param layer_data: Original layer data dictionary.
        :return: QWidget or subclass instance.
        """
        widget_type = mapping["type"]

        if widget_type == "doublespinbox":
            widget = QDoubleSpinBox()
            widget.setMinimum(mapping.get("min", 0.0))
            widget.setMaximum(mapping.get("max", 100.0))
            widget.setDecimals(mapping.get("decimals", 1))
            widget.setValue(mapping.get("default", 0.0))
            widget.setToolTip(mapping.get("tooltip", ""))
            return widget

        elif widget_type == "spinbox":
            widget = QSpinBox()
            widget.setMinimum(mapping.get("min", 0))
            widget.setMaximum(mapping.get("max", 10000))
            widget.setValue(mapping.get("default", 0))
            widget.setToolTip(mapping.get("tooltip", ""))
            return widget

        elif widget_type == "lineedit":
            widget = QLineEdit()
            widget.setText(mapping.get("default", ""))
            widget.setToolTip(mapping.get("tooltip", ""))
            return widget

        elif widget_type == "layer_selector":
            widget = QgsMapLayerComboBox()
            layer_type = mapping.get("layer_type", "vector")  # 'vector' or 'raster'
            if layer_type == "vector":
                widget.setFilters(QgsMapLayer.VectorLayer)
            elif layer_type == "raster":
                widget.setFilters(QgsMapLayer.RasterLayer)
            elif layer_type == "polygon":
                widget.setFilters(QgsMapLayer.VectorLayer)
                widget.setLayerType(QgsMapLayer.VectorLayer, "polygon")
            elif layer_type == "polyline":
                widget.setFilters(QgsMapLayer.VectorLayer)
                widget.setLayerType(QgsMapLayer.VectorLayer, "polyline")
            elif layer_type == "point":
                widget.setFilters(QgsMapLayer.VectorLayer)
                widget.setLayerType(QgsMapLayer.VectorLayer, "point")
            # Add more layer types as needed

            widget.setToolTip(mapping.get("tooltip", ""))
            return widget

        elif widget_type == "csv_to_point":
            # Create a layout with:
            # - QLineEdit for file path
            # - QPushButton to browse files
            # - Two QComboBox for longitude and latitude fields
            container = QWidget()
            layout = QHBoxLayout()
            container.setLayout(layout)

            # File path line edit
            file_path_edit = QLineEdit()
            file_path_edit.setPlaceholderText("Select CSV file")
            layout.addWidget(file_path_edit)

            # Browse button
            browse_button = QPushButton("Browse")
            layout.addWidget(browse_button)

            # Connect browse button to file dialog
            browse_button.clicked.connect(lambda: GeestWidgetFactory.browse_csv_file(file_path_edit))

            # Dropdowns for longitude and latitude columns
            longitude_combo = QComboBox()
            longitude_combo.setPlaceholderText("Longitude Column")
            longitude_combo.setEnabled(False)  # Initially disabled
            layout.addWidget(longitude_combo)

            latitude_combo = QComboBox()
            latitude_combo.setPlaceholderText("Latitude Column")
            latitude_combo.setEnabled(False)  # Initially disabled
            layout.addWidget(latitude_combo)

            # Connect file path edit to populate combo boxes
            file_path_edit.textChanged.connect(lambda text: GeestWidgetFactory.populate_csv_columns(text, longitude_combo, latitude_combo))

            # Set tooltips
            file_path_edit.setToolTip(mapping.get("tooltip", "Select a CSV file containing longitude and latitude columns."))
            longitude_combo.setToolTip("Select the column for longitude.")
            latitude_combo.setToolTip("Select the column for latitude.")

            return container

        elif widget_type == "download_button":
            # Create a horizontal layout with description and download button
            container = QWidget()
            layout = QHBoxLayout()
            container.setLayout(layout)

            # Description label
            description_label = QLabel(mapping.get("description", ""))
            description_label.setWordWrap(True)
            layout.addWidget(description_label)

            # Download button (non-functional as per instructions)
            download_button = QPushButton(mapping.get("button_text", "Download"))
            download_button.setToolTip(mapping.get("tooltip", ""))
            layout.addWidget(download_button)

            return container

        else:
            # Handle other widget types or return None
            return None

    @staticmethod
    def browse_csv_file(line_edit: QLineEdit):
        """
        Open a file dialog to browse CSV files and set the selected file path to the line edit.

        :param line_edit: QLineEdit widget to set the file path.
        """
        file_path, _ = QFileDialog.getOpenFileName(None, "Select CSV File", "", "CSV Files (*.csv)")
        if file_path:
            line_edit.setText(file_path)

    @staticmethod
    def populate_csv_columns(file_path: str, lon_combo: QComboBox, lat_combo: QComboBox):
        """
        Populate the longitude and latitude combo boxes based on the CSV file's headers.

        :param file_path: Path to the CSV file.
        :param lon_combo: QComboBox for longitude columns.
        :param lat_combo: QComboBox for latitude columns.
        """
        import csv

        if not file_path:
            return

        try:
            with open(file_path, newline='', encoding='utf-8') as csvfile:
                reader = csv.reader(csvfile)
                headers = next(reader)
                lon_combo.clear()
                lat_combo.clear()
                lon_combo.addItems(headers)
                lat_combo.addItems(headers)
                lon_combo.setEnabled(True)
                lat_combo.setEnabled(True)
        except Exception as e:
            # Handle errors (e.g., invalid CSV format)
            lon_combo.clear()
            lat_combo.clear()
            lon_combo.setEnabled(False)
            lat_combo.setEnabled(False)
