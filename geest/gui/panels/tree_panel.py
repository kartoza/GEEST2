import json
import os
import shutil
from qgis.PyQt.QtWidgets import (
    QTreeView,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QWidget,
    QLabel,
    QMenu,
    QAction,
    QMessageBox,
    QFileDialog,
    QHeaderView,
    QCheckBox,
)
from qgis.PyQt.QtCore import pyqtSlot, QPoint, Qt
from qgis.PyQt.QtGui import QMovie
from qgis.core import QgsMessageLog, Qgis, QgsRasterLayer, QgsProject
from functools import partial
from geest.gui.views import JsonTreeView, JsonTreeModel
from geest.gui.dialogs import IndicatorDetailDialog
from geest.utilities import resources_path
from geest.core import setting
from geest.core import WorkflowQueueManager
from geest.gui.dialogs import FactorAggregationDialog


class TreePanel(QWidget):
    def __init__(self, parent=None, json_file=None):
        super().__init__(parent)

        # Initialize the QueueManager
        self.working_directory = None
        self.queue_manager = WorkflowQueueManager(pool_size=1)
        self.json_file = json_file
        self.tree_view_visible = True
        edit_mode = int(setting(key="edit_mode", default=0))

        layout = QVBoxLayout()

        if json_file:
            # Load JSON data
            self.load_json()
        else:
            self.json_data = {"dimensions": []}

        # Create a CustomTreeView widget to handle editing and reverts
        self.treeView = JsonTreeView()
        self.treeView.setDragDropMode(QTreeView.InternalMove)
        self.treeView.setDefaultDropAction(Qt.MoveAction)

        # Create a model for the QTreeView using custom JsonTreeModel
        self.model = JsonTreeModel(self.json_data)
        self.treeView.setModel(self.model)
        # Connect signals to track changes in the model and save automatically
        self.model.dataChanged.connect(self.save_json_to_working_directory)
        self.model.rowsInserted.connect(self.save_json_to_working_directory)
        self.model.rowsRemoved.connect(self.save_json_to_working_directory)

        self.treeView.setRootIsDecorated(True)  # Ensures tree branches are visible
        self.treeView.setItemsExpandable(True)
        self.treeView.setUniformRowHeights(True)

        # Hide the third column (index 2)
        # Hide the weights column for now - I think later we will remove it completely
        # see https://github.com/kartoza/GEEST2/issues/370
        self.treeView.header().hideSection(2)

        # Enable custom context menu
        self.treeView.setContextMenuPolicy(Qt.CustomContextMenu)
        self.treeView.customContextMenuRequested.connect(self.open_context_menu)

        # Expand the whole tree by default
        self.treeView.expandAll()

        # Set the second and third columns to the exact width of the 🔴 character and weighting
        self.treeView.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.treeView.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)

        # Expand the first column to use the remaining space and resize with the dialog
        self.treeView.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.treeView.header().setStretchLastSection(False)

        # Set layout
        layout.addWidget(self.treeView)

        button_bar = QHBoxLayout()

        # "Add Dimension" button (initially enabled)
        self.add_dimension_button = QPushButton("⭐️ Add Dimension")
        self.add_dimension_button.clicked.connect(self.add_dimension)

        # Load and Save buttons
        self.load_json_button = QPushButton("📂 Load")
        self.load_json_button.clicked.connect(self.load_json_from_file)

        self.export_json_button = QPushButton("💾 Save")
        self.export_json_button.clicked.connect(self.export_json_to_file)

        # Prepare the throbber for the button (hidden initially)
        self.prepare_throbber = QLabel(self)
        movie = QMovie(resources_path("resources", "throbber-small.gif"))
        self.prepare_throbber.setMovie(movie)
        self.prepare_throbber.setVisible(False)  # Hide initially
        button_bar.addWidget(self.prepare_throbber)

        self.prepare_indicators_button = QPushButton("▶️ 1")
        self.prepare_indicators_button.clicked.connect(self.prepare_indicators_pressed)
        self.prepare_factors_button = QPushButton("▶️ 2")
        self.prepare_factors_button.clicked.connect(self.prepare_factors_pressed)
        self.prepare_dimensions_button = QPushButton("▶️ 3")
        self.prepare_dimensions_button.clicked.connect(self.prepare_dimensions_pressed)
        self.prepare_analysis_button = QPushButton("▶️ 4")
        self.prepare_analysis_button.clicked.connect(self.prepare_analysis_pressed)
        movie.start()

        # Add Edit Toggle checkbox
        self.edit_toggle = QCheckBox("Edit")
        self.edit_toggle.setChecked(False)
        self.edit_toggle.stateChanged.connect(self.toggle_edit_mode)
        if edit_mode:
            self.edit_toggle.setVisible(True)
        else:
            self.edit_toggle.setVisible(False)

        button_bar.addWidget(self.add_dimension_button)
        button_bar.addStretch()

        button_bar.addWidget(self.prepare_indicators_button)
        button_bar.addWidget(self.prepare_factors_button)
        button_bar.addWidget(self.prepare_dimensions_button)
        button_bar.addWidget(self.prepare_analysis_button)

        button_bar.addStretch()

        button_bar.addWidget(self.load_json_button)
        button_bar.addWidget(self.export_json_button)
        button_bar.addWidget(self.edit_toggle)  # Add the edit toggle

        # Only allow editing on double-click (initially enabled)
        editing = self.edit_toggle.isChecked()
        if editing:
            self.treeView.setEditTriggers(QTreeView.DoubleClicked)

        layout.addLayout(button_bar)
        self.setLayout(layout)

    @pyqtSlot(str)
    def working_directory_changed(self, new_directory):
        """Change the working directory and load the model.json if available."""
        self.working_directory = new_directory
        model_path = os.path.join(new_directory, "model.json")

        if os.path.exists(model_path):
            try:
                self.json_file = model_path
                self.load_json()
                self.model.loadJsonData(self.json_data)
                self.treeView.expandAll()
                QgsMessageLog.logMessage(
                    f"Loaded model.json from {model_path}", "Geest", level=Qgis.Info
                )
            except Exception as e:
                QgsMessageLog.logMessage(
                    f"Error loading model.json: {str(e)}", "Geest", level=Qgis.Critical
                )
        else:
            QgsMessageLog.logMessage(
                f"No model.json found in {new_directory}, using default.",
                "Geest",
                level=Qgis.Warning,
            )
            # copy the default model.json to the working directory
            master_model_path = resources_path("resources", "model.json")
            if os.path.exists(master_model_path):
                try:
                    shutil.copy(master_model_path, model_path)
                    QgsMessageLog.logMessage(
                        f"Copied master model.json to {model_path}",
                        "Geest",
                        level=Qgis.Info,
                    )
                except Exception as e:
                    QgsMessageLog.logMessage(
                        f"Error copying master model.json: {str(e)}",
                        "Geest",
                        level=Qgis.Critical,
                    )
            self.load_json()
            self.model.loadJsonData(self.json_data)
            self.treeView.expandAll()

    @pyqtSlot()
    def set_working_directory(self, working_directory):
        if working_directory:
            self.working_directory = working_directory
            self.working_directory_changed(working_directory)

    @pyqtSlot()
    def save_json_to_working_directory(self):
        """Automatically save the current JSON model to the working directory."""
        if not self.working_directory:
            QgsMessageLog.logMessage(
                "No working directory set, cannot save JSON.",
                "Geest",
                level=Qgis.Warning,
            )
        try:
            json_data = self.model.to_json()
            save_path = os.path.join(self.working_directory, "model.json")
            with open(save_path, "w") as f:
                json.dump(json_data, f, indent=4)
            QgsMessageLog.logMessage(
                f"Saved JSON model to {save_path}", "Geest", level=Qgis.Info
            )
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error saving JSON: {str(e)}", "Geest", level=Qgis.Critical
            )

    def edit(self, index, trigger, event):
        """
        Override the edit method to enable editing only on the column that was clicked.
        """
        column = index.column()

        # Only allow editing on specific columns (e.g., column 0, 1, etc.)
        if column == 0:  # Only make the first column editable
            return super().edit(index, trigger, event)
        elif column == 2:  # And the third column editable
            return super().edit(index, trigger, event)

        return False

    def load_json(self):
        """Load the JSON data from the file."""
        with open(self.json_file, "r") as f:
            self.json_data = json.load(f)

    def load_json_from_file(self):
        """Prompt the user to load a JSON file and update the tree."""
        json_file, _ = QFileDialog.getOpenFileName(
            self, "Open JSON File", os.getcwd(), "JSON Files (*.json);;All Files (*)"
        )
        if json_file:
            self.json_file = json_file
            self.load_json()
            self.model.loadJsonData(self.json_data)
            self.treeView.expandAll()

    def export_json_to_file(self):
        """Export the current tree data to a JSON file."""
        json_data = self.model.to_json()
        with open("export.json", "w") as f:
            json.dump(json_data, f, indent=4)
        QMessageBox.information(self, "Export Success", "Tree exported to export.json")

    def add_dimension(self):
        """Add a new dimension to the model."""
        self.model.add_dimension()

    def open_context_menu(self, position: QPoint):
        """Handle right-click context menu."""
        editing = self.edit_toggle.isChecked()

        index = self.treeView.indexAt(position)
        if not index.isValid():
            return

        item = index.internalPointer()
        show_json_attributes_action = QAction("Show Attributes", self)
        show_json_attributes_action.triggered.connect(
            lambda: self.show_attributes(item)
        )
        add_to_map_action = QAction("Add to map", self)
        add_to_map_action.triggered.connect(lambda: self.add_to_map(item))

        run_item_action = QAction("Run Item Workflow", self)
        run_item_action.triggered.connect(lambda: self.run_item(item, role=item.role))
        # Check the role of the item directly from the stored role
        if item.role == "dimension":
            # Context menu for dimensions
            add_factor_action = QAction("Add Factor", self)
            remove_dimension_action = QAction("Remove Dimension", self)

            # Connect actions
            add_factor_action.triggered.connect(lambda: self.model.add_factor(item))
            remove_dimension_action.triggered.connect(
                lambda: self.model.remove_item(item)
            )
            clear_action = QAction("Clear Factor Weightings", self)
            clear_action.triggered.connect(
                lambda: self.model.clear_factor_weightings(item)
            )
            auto_assign_action = QAction("Auto Assign Factor Weightings", self)
            auto_assign_action.triggered.connect(
                lambda: self.model.auto_assign_factor_weightings(item)
            )

            # Add actions to menu
            menu = QMenu(self)
            menu.addAction(clear_action)
            menu.addAction(auto_assign_action)
            menu.addAction(show_json_attributes_action)
            menu.addAction(add_to_map_action)
            menu.addAction(run_item_action)

            if editing:
                menu.addAction(add_factor_action)
                menu.addAction(remove_dimension_action)

        elif item.role == "factor":
            # Context menu for factors
            edit_aggregation_action = QAction(
                "Edit Aggregation", self
            )  # New action for contextediting aggregation
            add_layer_action = QAction("Add Layer", self)
            remove_factor_action = QAction("Remove Factor", self)
            clear_action = QAction("Clear Layer Weightings", self)
            auto_assign_action = QAction("Auto Assign Layer Weightings", self)

            # Connect actions
            edit_aggregation_action.triggered.connect(
                lambda: self.edit_aggregation(item)
            )  # Connect to method
            add_layer_action.triggered.connect(lambda: self.model.add_layer(item))
            remove_factor_action.triggered.connect(lambda: self.model.remove_item(item))
            clear_action.triggered.connect(
                lambda: self.model.clear_layer_weightings(item)
            )
            auto_assign_action.triggered.connect(
                lambda: self.model.auto_assign_layer_weightings(item)
            )

            # Add actions to menu
            menu = QMenu(self)
            menu.addAction(edit_aggregation_action)
            menu.addAction(show_json_attributes_action)
            menu.addAction(add_to_map_action)

            if editing:
                menu.addAction(add_layer_action)
                menu.addAction(remove_factor_action)
            menu.addAction(clear_action)
            menu.addAction(auto_assign_action)
            menu.addAction(run_item_action)

        elif item.role == "layer":
            # Context menu for layers
            show_properties_action = QAction("🔘 Show Properties", self)
            remove_layer_action = QAction("❌ Remove Layer", self)

            # Connect actions
            show_properties_action.triggered.connect(
                lambda: self.show_layer_properties(item)
            )
            remove_layer_action.triggered.connect(lambda: self.model.remove_item(item))

            # Add actions to menu
            menu = QMenu(self)
            menu.addAction(show_properties_action)
            menu.addAction(show_json_attributes_action)
            menu.addAction(add_to_map_action)
            menu.addAction(run_item_action)

            if editing:
                menu.addAction(remove_layer_action)

        # Show the menu at the cursor's position
        menu.exec_(self.treeView.viewport().mapToGlobal(position))

    def show_attributes(self, item):
        """Show the attributes of the item in a the message log."""
        QgsMessageLog.logMessage("Item Attributes", tag="Geest", level=Qgis.Info)
        QgsMessageLog.logMessage(
            "----------------------------", tag="Geest", level=Qgis.Info
        )
        if item.role == "factor":
            QgsMessageLog.logMessage(
                "Factor attributes that get passed to workflow:",
                tag="Geest",
                level=Qgis.Info,
            )
            QgsMessageLog.logMessage(
                str(item.getFactorAttributes()), tag="Geest", level=Qgis.Info
            )
        elif item.role == "dimension":
            QgsMessageLog.logMessage(
                "Dimension attributes that get passed to workflow",
                tag="Geest",
                level=Qgis.Info,
            )
            QgsMessageLog.logMessage(
                str(item.getDimensionAttributes()), tag="Geest", level=Qgis.Info
            )
        elif item.role == "layer":
            QgsMessageLog.logMessage(
                "Indicator attributes that get passed to workflow",
                tag="Geest",
                level=Qgis.Info,
            )
            QgsMessageLog.logMessage(
                str(item.getIndicatorAttributes()), tag="Geest", level=Qgis.Info
            )
        QgsMessageLog.logMessage(
            "Attributes stored in tree:", tag="Geest", level=Qgis.Info
        )
        QgsMessageLog.logMessage(str(item.data(3)), tag="Geest", level=Qgis.Info)
        QgsMessageLog.logMessage(
            "----------------------------", tag="Geest", level=Qgis.Info
        )

    def add_to_map(self, item):
        """Add the item to the map."""
        # TODO refactor use of the term Layer everywhere to Indicator
        # for now, some spaghetti code to get the layer_uri
        if item.role == "layer":
            layer_uri = item.data(3).get(f"Indicator Result File")
        else:
            layer_uri = item.data(3).get(
                f"{item.role.title()} Result File"
            )  # title = title case string
        layer_name = item.data(0)
        QgsMessageLog.logMessage(
            f"Adding {layer_uri} to the map.", tag="Geest", level=Qgis.Info
        )
        # Add the aggregated raster to the map
        layer = QgsRasterLayer(layer_uri, layer_name)
        if layer.isValid():
            QgsProject.instance().addMapLayer(layer)
        else:
            QgsMessageLog.logMessage(
                f"Failed to add the {layer_name} raster to the map.",
                tag="Geest",
                level=Qgis.Critical,
            )

    def edit_aggregation(self, factor_item):
        """Open the FactorAggregationDialog for editing the weightings of layers in a factor."""
        editing = self.edit_toggle.isChecked()
        factor_name = factor_item.data(0)
        factor_data = factor_item.data(3)
        if not factor_data:
            factor_data = {}
        dialog = FactorAggregationDialog(
            factor_name, factor_data, factor_item, editing=editing, parent=self
        )
        if dialog.exec_():  # If OK was clicked
            dialog.assignWeightings()
            self.save_json_to_working_directory()  # Save changes to the JSON if necessary

    def show_layer_properties(self, item):
        """Open a dialog showing layer properties and update the tree upon changes."""
        editing = self.edit_toggle.isChecked()
        # Get the current layer name and layer data from the item
        layer_name = item.data(0)  # Column 0: layer name
        layer_data = item.data(3)  # Column 3: layer data (stored as a dict)

        # Create and show the LayerDetailDialog
        dialog = IndicatorDetailDialog(
            layer_name, layer_data, item, editing=editing, parent=self
        )

        # Connect the dialog's dataUpdated signal to handle data updates
        def update_layer_data(updated_data):
            # Update the layer data in the item (column 4)
            item.setData(3, updated_data)

            # Check if the layer name has changed, and if so, update it in column 0
            if updated_data.get("name", layer_name) != layer_name:
                item.setData(0, updated_data.get("name", layer_name))

            # Save the JSON data to the working directory
            self.save_json_to_working_directory()

        # Connect the signal emitted from the dialog to update the item
        dialog.dataUpdated.connect(update_layer_data)

        # Show the dialog (exec_ will block until the dialog is closed)
        dialog.exec_()

    def toggle_edit_mode(self):
        """Enable or disable edit mode based on the 'Edit' toggle state."""
        edit_mode = self.edit_toggle.isChecked()

        # Enable or disable the "Add Dimension" button
        self.add_dimension_button.setVisible(edit_mode)

        # Enable or disable double-click editing in the tree view
        if edit_mode:
            self.treeView.setEditTriggers(QTreeView.DoubleClicked)
        else:
            self.treeView.setEditTriggers(QTreeView.NoEditTriggers)

    def start_workflows(self, type=None):
        """Start a workflow for each 'layer' node in the tree.

        We process in the order of layers, factors, and dimensions since there
        is a dependency between them. For example, a factor depends on its layers.
        """
        if type == "indicators":
            self._start_workflows(self.treeView.model().rootItem, role="layer")
        elif type == "factors":
            self._start_workflows(self.treeView.model().rootItem, role="factor")
        elif type == "dimensions":
            self._start_workflows(self.treeView.model().rootItem, role="dimension")
        elif type == "analysis":
            self._start_workflows(self.treeView.model().rootItem, role="analysis")

    def _start_workflows(self, parent_item, role=None):
        """
        Recursively start workflows for each node in the tree.
        Connect workflow signals to the corresponding slots for updates.
        :param parent_item: The parent item to process.
        :param role: The role of the item to process (i.e., 'dimension', 'factor', 'layer').
        """
        for i in range(parent_item.childCount()):
            child_item = parent_item.child(i)
            self.queue_workflow_task(child_item, role)
            # Recursively process children (dimensions, factors)
            self._start_workflows(child_item, role)

    def queue_workflow_task(self, item, role):
        """Queue a workflow task based on the role of the item.

        ⭐️ These calls all pass a reference of the item to the workflow task.
            The task directly modifies the item's properties to update the tree.
        """
        task = None
        if role == item.role and role == "layer":
            task = self.queue_manager.add_workflow(item)
        if role == item.role and role == "factor":
            item.data(3)["Analysis Mode"] = "Factor Aggregation"
            task = self.queue_manager.add_workflow(item)
        if role == item.role and role == "dimension":
            item.data(3)["Analysis Mode"] = "Dimension Aggregation"
            task = self.queue_manager.add_workflow(item)
        if role == item.role and role == "analysis":
            item.data(3)["Analysis Mode"] = "Analysis Aggregation"
            task = self.queue_manager.add_workflow(item)
        if task is None:
            return

        # Connect workflow signals to TreePanel slots
        task.job_queued.connect(partial(self.on_workflow_created, item))
        task.job_started.connect(partial(self.on_workflow_started, item))
        task.job_canceled.connect(partial(self.on_workflow_completed, item, False))
        task.job_finished.connect(
            lambda success: self.on_workflow_completed(item, success)
        )

    def run_item(self, item, role):
        self.queue_workflow_task(item, role)
        debug_env = int(os.getenv("GEEST_DEBUG", 0))
        if debug_env:
            self.queue_manager.start_processing_in_foreground()
        else:
            self.queue_manager.start_processing()

    @pyqtSlot()
    def on_workflow_created(self, item):
        """
        Slot for handling when a workflow is created.
        Update the tree item to indicate that the workflow is queued.
        """
        self.update_tree_item_status(item, "Q")

    @pyqtSlot()
    def on_workflow_started(self, item):
        """
        Slot for handling when a workflow starts.
        Update the tree item to indicate that the workflow is running.
        """
        self.update_tree_item_status(item, "R")

    @pyqtSlot(bool)
    def on_workflow_completed(self, item, success):
        """
        Slot for handling when a workflow is completed.
        Update the tree item to indicate success or failure.
        """
        if success:
            self.update_tree_item_status(item, "✅")

        else:
            self.update_tree_item_status(item, "❌")
        self.save_json_to_working_directory()

    def update_tree_item_status(self, item, status):
        """
        Update the tree item to show the workflow status.
        :param item: The tree item representing the workflow.
        :param status: The status message or icon to display.
        """
        # Assuming column 1 is where status updates are shown
        item.setData(1, status)

    def prepare_indicators_pressed(self):
        """
        This function processes all nodes in the QTreeView that have the 'layer' role.
        It iterates over the entire tree, collecting nodes with the 'layer' role, and
        processes each one by showing an animated icon, waiting for 2 seconds, and
        then removing the animation.
        """
        self.start_workflows(type="indicators")
        debug_env = int(os.getenv("GEEST_DEBUG", 0))
        if debug_env:
            self.queue_manager.start_processing_in_foreground()
        else:
            self.queue_manager.start_processing()

    def prepare_factors_pressed(self):
        """
        This function processes all nodes in the QTreeView that have the 'factor' role.
        It iterates over the entire tree, collecting nodes with the 'layer' role, and
        processes each one by showing an animated icon, waiting for 2 seconds, and
        then removing the animation.
        """
        self.start_workflows(type="factors")
        debug_env = int(os.getenv("GEEST_DEBUG", 0))
        if debug_env:
            self.queue_manager.start_processing_in_foreground()
        else:
            self.queue_manager.start_processing()

    def prepare_dimensions_pressed(self):
        """
        This function processes all nodes in the QTreeView that have the 'dimension' role.
        It iterates over the entire tree, collecting nodes with the 'layer' role, and
        processes each one by showing an animated icon, waiting for 2 seconds, and
        then removing the animation.
        """
        self.start_workflows(type="dimensions")
        debug_env = int(os.getenv("GEEST_DEBUG", 0))
        if debug_env:
            self.queue_manager.start_processing_in_foreground()
        else:
            self.queue_manager.start_processing()

    def prepare_analysis_pressed(self):
        """
        This function processes all nodes in the QTreeView that have the 'layer' role.
        It iterates over the entire tree, collecting nodes with the 'layer' role, and
        processes each one by showing an animated icon, waiting for 2 seconds, and
        then removing the animation.
        """
        self.start_workflows(type="analysis")
        self.queue_manager.start_processing()