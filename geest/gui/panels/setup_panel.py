import os
import shutil
from PyQt5.QtWidgets import (
    QWidget,
    QFileDialog,
    QMessageBox,
)
from qgis.gui import QgsMapLayerComboBox, QgsFieldComboBox
from qgis.core import (
    QgsMapLayerProxyModel,
    QgsFieldProxyModel,
    QgsVectorLayer,
    QgsProject,
    QgsApplication,
    QgsMessageLog,
    Qgis,
    QgsProject,
)
from qgis.PyQt import uic

from qgis.PyQt.QtCore import QSettings, pyqtSignal
from qgis.PyQt.QtGui import QPixmap
from geest.core.tasks import StudyAreaProcessingTask, OrsCheckerTask
from geest.utilities import get_ui_class, resources_path
from geest.core import WorkflowQueueManager

FORM_CLASS = get_ui_class("setup_panel_base.ui")


class SetupPanel(FORM_CLASS, QWidget):
    switch_to_next_tab = pyqtSignal()  # Signal to notify the parent to switch tabs

    def __init__(self):
        super().__init__()
        self.setWindowTitle("GEEST")
        # For running study area processing in a separate thread
        self.queue_manager = WorkflowQueueManager(pool_size=1)

        self.working_dir = ""
        self.settings = (
            QSettings()
        )  # Initialize QSettings to store and retrieve settings
        # Dynamically load the .ui file
        self.setupUi(self)
        QgsMessageLog.logMessage(f"Loading setup panel", tag="Geest", level=Qgis.Info)
        self.initUI()

    def initUI(self):
        self.banner_label.setPixmap(
            QPixmap(resources_path("resources", "geest-banner.png"))
        )
        self.open_project_group.setVisible(False)
        self.dir_button.clicked.connect(self.select_directory)
        self.open_project_button.clicked.connect(self.load_project)
        # self.layer_combo = QgsMapLayerComboBox()
        self.layer_combo.setFilters(QgsMapLayerProxyModel.PolygonLayer)

        # self.field_combo = QgsFieldComboBox()  # QgsFieldComboBox for selecting fields
        self.field_combo.setFilters(QgsFieldProxyModel.String)

        # Link the map layer combo box with the field combo box
        self.layer_combo.layerChanged.connect(self.field_combo.setLayer)
        self.field_combo.setLayer(self.layer_combo.currentLayer())
        self.world_map_button.clicked.connect(self.add_world_map)
        self.create_project_directory_button.clicked.connect(
            self.create_new_project_folder
        )
        self.prepare_project_button.clicked.connect(self.create_project)
        self.new_project_group.setVisible(False)
        # Set the last used working directory from QSettings
        recent_projects = self.settings.value("recent_projects", [])
        self.previous_project_combo.addItems(
            reversed(recent_projects)
        )  # Add recent projects to the combo
        self.working_dir = self.previous_project_combo.currentText()
        # self.dir_display.setText(self.working_dir)
        self.set_project_directory()

    def update_recent_projects(self, directory):
        """Updates the recent projects list with the new directory."""
        recent_projects = self.settings.value("recent_projects", [])

        if directory in recent_projects:
            recent_projects.remove(
                directory
            )  # Remove if already in the list (to reorder)

        recent_projects.insert(0, directory)  # Add to the top of the list

        # Limit the list to a certain number of recent projects (e.g., 5)
        if len(recent_projects) > 5:
            recent_projects = recent_projects[:5]

        # Save back to QSettings
        self.settings.setValue("recent_projects", recent_projects)

        # Update the combo box
        self.previous_project_combo.clear()
        self.previous_project_combo.addItems(reversed(recent_projects))

    def select_directory(self):
        directory = QFileDialog.getExistingDirectory(
            self, "Select Working Directory", self.working_dir
        )
        if directory:
            self.working_dir = directory
            self.update_recent_projects(directory)  # Update recent projects
            self.settings.setValue("last_working_directory", directory)
            self.set_project_directory()

    def create_new_project_folder(self):
        directory = QFileDialog.getExistingDirectory(
            self, "Create New Project Folder", self.working_dir
        )
        if directory:
            self.working_dir = directory
            self.update_recent_projects(directory)  # Update recent projects
            self.settings.setValue("last_working_directory", directory)
        self.working_dir = directory

    def set_project_directory(self):
        """
        Updates the UI based on the selected working directory.
        If the directory contains 'model.json', shows a message and hides layer/field selectors.
        Otherwise, shows the layer/field selectors.
        """
        model_path = os.path.join(self.working_dir, "model.json")

    def add_world_map(self):
        """Adds the built-in QGIS world map to the canvas."""
        # Use QgsApplication.prefixPath() to get the correct path
        qgis_prefix = QgsApplication.prefixPath()
        layer_path = os.path.join(
            qgis_prefix, "share", "qgis", "resources", "data", "world_map.gpkg"
        )

        if not os.path.exists(layer_path):
            QMessageBox.critical(
                self, "Error", f"Could not find world map file at {layer_path}."
            )
            return

        full_layer_path = f"{layer_path}|layername=countries"
        world_map_layer = QgsVectorLayer(full_layer_path, "World Map", "ogr")

        if not world_map_layer.isValid():
            QMessageBox.critical(self, "Error", "Could not load the world map layer.")
            return

        QgsProject.instance().addMapLayer(world_map_layer)

    def load_project(self):
        self.working_dir = self.previous_project_combo.currentText()
        model_path = os.path.join(self.working_dir, "model.json")
        if os.path.exists(model_path):
            # Switch to the next tab if an existing project is found
            self.switch_to_next_tab.emit()

    def create_project(self):
        """Triggered when the Continue button is pressed."""

        model_path = os.path.join(self.working_dir, "model.json")
        if os.path.exists(model_path):
            # Switch to the next tab if an existing project is found
            self.switch_to_next_tab.emit()
        else:
            # Process the study area if no model.json exists
            layer = self.layer_combo.currentLayer()
            if not layer:
                QMessageBox.critical(self, "Error", "Please select a study area layer.")
                return

            if not self.working_dir:
                QMessageBox.critical(
                    self, "Error", "Please select a working directory."
                )
                return

            field_name = self.field_combo.currentField()
            if not field_name or field_name not in layer.fields().names():
                QMessageBox.critical(
                    self, "Error", f"Invalid area name field '{field_name}'."
                )
                return

            # Copy default model.json if not present
            default_model_path = resources_path("resources", "model.json")
            try:
                shutil.copy(default_model_path, model_path)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to copy model.json: {e}")
                return

            # Create the processor instance and process the features
            debug_env = int(os.getenv("GEEST_DEBUG", 0))
            try:
                processor = StudyAreaProcessingTask(
                    name="Study Area Processing",
                    layer=layer,
                    field_name=field_name,
                    working_dir=self.working_dir,
                )

                if debug_env:
                    processor.process_study_area()
                else:
                    self.queue_manager.add_task(processor)
                    self.queue_manager.start_processing()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Error processing study area: {e}")
                return
            try:
                # This checks we can access Open Route Service
                # and that access works in the background in another thread
                checker = OrsCheckerTask(
                    url="https://api.openrouteservice.org/",
                )
                if debug_env:
                    # Non threaded version
                    checker.run()
                else:
                    checker.run()
                    # Threaded version (crashes QGIS)
                    # self.queue_manager.add_task(checker)
                    # self.queue_manager.start_processing()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Error checking ORS service: {e}")
                return
            self.switch_to_next_tab.emit()