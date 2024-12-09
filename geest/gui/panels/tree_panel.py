import json
import os
import shutil
from typing import Union, Dict, List
from qgis.PyQt.QtWidgets import (
    QAction,
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)
from qgis.PyQt.QtCore import (
    pyqtSlot,
    QPoint,
    Qt,
    QSettings,
    pyqtSignal,
    QModelIndex,
)
from qgis.PyQt.QtGui import QMovie
from qgis.PyQt.QtWidgets import QSizePolicy
from qgis.core import (
    Qgis,
    QgsRasterLayer,
    QgsProject,
    QgsVectorLayer,
    QgsLayerTreeGroup,
)
from functools import partial
from geest.gui.views import JsonTreeView, JsonTreeModel
from geest.utilities import resources_path
from geest.core import setting, set_setting
from geest.core import WorkflowQueueManager
from geest.gui.dialogs import (
    FactorAggregationDialog,
    DimensionAggregationDialog,
    AnalysisAggregationDialog,
)
from geest.utilities import log_message


class TreePanel(QWidget):
    switch_to_next_tab = pyqtSignal()  # Signal to notify the parent to switch tabs
    switch_to_previous_tab = pyqtSignal()  # Signal to notify the parent to switch tabs

    def __init__(self, parent=None, json_file=None):
        super().__init__(parent)

        # Initialize the QueueManager
        self.working_directory = None
        self.queue_manager = WorkflowQueueManager(pool_size=1)
        self.json_file = json_file
        self.tree_view_visible = True
        self.run_only_incomplete = (
            True  # saves time by not running models that have already been run
        )
        self.items_to_run = 0  # Count of items that need to be run

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
        self.active_model = "default"  # or "promotion"
        self.treeView.setModel(
            self.model
        )  # Simple model where we allow single childred

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

        # Set the second and third columns to the exact width of their contents
        self.treeView.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.treeView.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)

        # Expand the first column to use the remaining space and resize with the dialog
        self.treeView.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.treeView.header().setStretchLastSection(False)
        # Now hide the header
        self.treeView.header().hide()
        # Action fow when we double click an item
        self.treeView.setExpandsOnDoubleClick(
            False
        )  # Prevent double-click from collapsing the tree view
        self.treeView.doubleClicked.connect(
            self.on_item_double_clicked
        )  # Will show properties dialogs

        # Set layout
        layout.addWidget(self.treeView)

        button_bar = QHBoxLayout()

        # Create the split tool button
        self.prepare_analysis_button = QToolButton()
        self.prepare_analysis_button.setText("▶️ Run all")
        self.prepare_analysis_button.setPopupMode(QToolButton.MenuButtonPopup)

        # Connect the main button click to run all
        self.prepare_analysis_button.clicked.connect(self.run_all)

        # Create the menu for additional options
        prepare_analysis_menu = QMenu(self.prepare_analysis_button)

        # Add "Run all" action
        run_all_action = QAction("Run all", self)
        run_all_action.triggered.connect(self.run_all)
        prepare_analysis_menu.addAction(run_all_action)

        # Add "Run incomplete" action
        run_incomplete_action = QAction("Run incomplete", self)
        run_incomplete_action.triggered.connect(self.run_incomplete)
        prepare_analysis_menu.addAction(run_incomplete_action)

        # Set the menu on the tool button
        self.prepare_analysis_button.setMenu(prepare_analysis_menu)

        # Add the button to the button bar
        button_bar.addWidget(self.prepare_analysis_button)

        self.project_button = QPushButton("Project")
        self.project_button.clicked.connect(self.switch_to_previous_tab)
        button_bar.addWidget(self.project_button)
        self.help_button = QPushButton("Help")
        self.help_button.clicked.connect(self.switch_to_next_tab)
        button_bar.addWidget(self.help_button)
        # Add two progress bars to monitor all workflow progress and individual progress
        self.overall_progress_bar = QProgressBar()
        self.overall_progress_bar.setRange(0, 100)
        self.overall_progress_bar.setValue(0)
        self.overall_progress_bar.setFormat("Overall Progress: %p%")
        self.overall_progress_bar.setAlignment(Qt.AlignCenter)
        self.overall_progress_bar.setVisible(False)
        self.overall_progress_bar.setFixedHeight(20)
        self.overall_progress_bar.setFixedWidth(200)
        button_bar.addWidget(self.overall_progress_bar)
        self.workflow_progress_bar = QProgressBar()
        self.workflow_progress_bar.setRange(0, 100)
        self.workflow_progress_bar.setValue(0)
        self.workflow_progress_bar.setFormat("Task Progress: %p%")
        self.workflow_progress_bar.setAlignment(Qt.AlignCenter)
        self.workflow_progress_bar.setVisible(False)
        self.workflow_progress_bar.setFixedHeight(20)
        self.workflow_progress_bar.setFixedWidth(200)
        button_bar.addWidget(self.workflow_progress_bar)

        self.treeView.setEditTriggers(QTreeView.NoEditTriggers)

        layout.addLayout(button_bar)
        self.setLayout(layout)

        # Connect the working directory changed signal to the slot
        # Workflows need to be run in batches: first indicators, then factors, then dimensions
        # to prevent race conditions
        self.workflow_queue = []
        self.queue_manager.processing_completed.connect(self.run_next_workflow_queue)

    def on_item_double_clicked(self, index):
        # Action to trigger on double-click
        item = index.internalPointer()
        if item.role == "indicator":
            self.edit_factor_aggregation(item.parent())
        elif item.role == "factor":
            self.edit_factor_aggregation(item)
        elif item.role == "dimension":
            self.edit_dimension_aggregation(item)
        elif item.role == "analysis":
            self.edit_analysis_aggregation(item)

    def on_previous_button_clicked(self):
        self.switch_to_previous_tab.emit()

    def on_next_button_clicked(self):
        self.switch_to_next_tab.emit()

    def clear_workflows(self):
        """
        Recursively mark workflows as not done, delete their working directories and their file_paths.

        It will reset the self.run_only_incomplete flag to only clear incomplete workflows if requested.

        :param parent_item: The parent item to process. If none, start from the root.
        """
        self.run_only_incomplete = False
        # Remove every file in self.working_directory except
        # mode.json and the study_area folder
        for filename in os.listdir(self.working_directory):
            file_path = os.path.join(self.working_directory, filename)
            if filename != "model.json" and filename != "study_area":
                try:
                    if os.path.isfile(file_path) or os.path.islink(file_path):
                        os.unlink(file_path)
                    elif os.path.isdir(file_path):
                        shutil.rmtree(file_path)
                except Exception as e:
                    log_message(
                        f"Failed to delete {file_path}. Reason: {e}",
                        level=Qgis.Critical,
                    )
        # Also remove the Geest layer group in the QGIS Layers List
        root = QgsProject.instance().layerTreeRoot()
        for child in root.children():
            if child.name() == "Geest":
                root.removeChildNode(child)
        # Mark all items in the data model as not run
        self.clear_all_items()
        self.save_json_to_working_directory()

    def clear_all_items(self, parent_item=None):
        if parent_item is None:
            parent_item = self.model.rootItem
        for i in range(parent_item.childCount()):
            child_item = parent_item.child(i)
            self.clear_all_items(child_item)
            child_item.clear()  # sets status to not run and blanks file path
        parent_item.clear()  # sets status to not run and blanks file path

    @pyqtSlot(str)
    def working_directory_changed(self, new_directory):
        """Change the working directory and load the model.json if available."""
        log_message(
            f"Working directory changed to {new_directory}",
            tag="Geest",
            level=Qgis.Info,
        )
        self.working_directory = new_directory
        model_path = os.path.join(new_directory, "model.json")

        project_path = QgsProject.instance().fileName()
        if project_path:
            checksum = hash(project_path)
        else:
            checksum = None

        if os.path.exists(model_path):
            try:
                self.json_file = model_path
                self.load_json()  # sets the class member json_data
                self.model.loadJsonData(self.json_data)
                self.treeView.expandAll()
                log_message(f"Loaded model.json from {model_path}")

                # If this is a first time use of the analysis project lets set some things up
                analysis_item = self.model.rootItem.child(0)
                analysis_data = analysis_item.attributes()
                log_message(str(analysis_data))
                if analysis_data.get("working_folder", "Not Set"):
                    analysis_data["working_folder"] = self.working_directory
                else:
                    if not os.path.exists(analysis_data["working_folder"]):
                        analysis_data["working_folder"] = self.working_directory
                # Use the last dir in the working directory path as the analysis name
                if analysis_data.get("analysis_name", "Not Set"):
                    analysis_name = os.path.basename(self.working_directory)
                    analysis_data["analysis_name"] = (
                        f"Women's Economic Empowerment - {analysis_name}"
                    )
                # analysis_item.setData(0, analysis_data.get("analysis_name", "Analysis"))
                analysis_item.setData(0, "Score by Population and Job Distribution")
                settings = QSettings()
                # This is the top level folder for work files
                settings.setValue("last_working_directory", self.working_directory)
                # Use QGIS internal settings for the association between model path and QGIS project
                set_setting(
                    str(checksum), self.working_directory, store_in_project=True
                )

            except Exception as e:
                log_message(
                    f"Error loading model.json: {str(e)}",
                    tag="Geest",
                    level=Qgis.Critical,
                )
        else:
            log_message(
                f"No model.json found in {new_directory}, using default.",
                "Geest",
                level=Qgis.Warning,
            )
            # copy the default model.json to the working directory
            master_model_path = resources_path("resources", "model.json")
            if os.path.exists(master_model_path):
                try:
                    shutil.copy(master_model_path, model_path)
                    log_message(f"Copied master model.json to {model_path}")
                except Exception as e:
                    log_message(
                        f"Error copying master model.json: {str(e)}",
                        "Geest",
                        level=Qgis.Critical,
                    )
            self.load_json()
            self.model.loadJsonData(self.json_data)
            self.treeView.expandAll()
        # Collapse any factors that have only a single indicator
        self.treeView.collapse_single_nodes()

    @pyqtSlot()
    def set_working_directory(self, working_directory):
        if working_directory:
            self.working_directory = working_directory
            self.working_directory_changed(working_directory)

    @pyqtSlot()
    def save_json_to_working_directory(self):
        """Automatically save the current JSON model to the working directory."""
        if not self.working_directory:
            log_message(
                "No working directory set, cannot save JSON.",
                "Geest",
                level=Qgis.Warning,
            )
        try:
            json_data = self.model.to_json()

            save_path = os.path.join(self.working_directory, "model.json")
            with open(save_path, "w") as f:
                json.dump(json_data, f, indent=4)
            log_message(f"Saved JSON model to {save_path}")
        except Exception as e:
            log_message(f"Error saving JSON: {str(e)}", level=Qgis.Critical)

    def load_json(self):
        """Load the JSON data from the file."""
        with open(self.json_file, "r") as f:
            self.json_data = json.load(f)
            log_message(f"Loaded JSON data from {self.json_file}")

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

        index = self.treeView.indexAt(position)
        if not index.isValid():
            return

        item = index.internalPointer()
        show_json_attributes_action = QAction("Show Attributes", self)
        show_json_attributes_action.triggered.connect(
            lambda: self.show_attributes(item)
        )
        # We disable items by setting their weight to 0
        if item.getStatus() == "Excluded from analysis":
            disable_action = QAction("Enable", self)
            disable_action.triggered.connect(lambda: self.enable_item(item))
        else:
            disable_action = QAction("Disable", self)
            disable_action.triggered.connect(lambda: self.disable_item(item))

        add_to_map_action = QAction("Add to map", self)
        add_to_map_action.triggered.connect(lambda: self.add_to_map(item))

        run_item_action = QAction("Run Item Workflow", self)

        def update_action_text():
            text = (
                "Rerun Item Workflow"
                if QApplication.keyboardModifiers() & Qt.ShiftModifier
                else "Run Item Workflow"
            )
            run_item_action.setText(text)

        # Update initially
        update_action_text()

        clear_results_action = QAction("Clear Results", self)
        clear_results_action.triggered.connect(self.clear_workflows)

        # Update when menu shows
        menu = QMenu(self)
        menu.aboutToShow.connect(update_action_text)
        # Add event filter to menu to update when shift is pressed while menu is open
        menu.installEventFilter(self)
        run_item_action.triggered.connect(
            lambda: self.run_item(
                item,
                shift_pressed=QApplication.keyboardModifiers() & Qt.ShiftModifier,
            )
        )
        if item.role == "analysis":
            menu = QMenu(self)
            edit_analysis_action = QAction("🔘 Edit Weights and Settings", self)
            edit_analysis_action.triggered.connect(
                lambda: self.edit_analysis_aggregation(item)
            )  # Connect to method
            menu.addAction(edit_analysis_action)
            menu.addAction(show_json_attributes_action)
            menu.addAction(clear_results_action)
            menu.addAction(run_item_action)
            menu.addAction(add_to_map_action)
            add_study_area_layers_action = QAction("Add Study Area to Map", self)
            add_study_area_layers_action.triggered.connect(self.add_study_area_to_map)
            menu.addAction(add_study_area_layers_action)

        # Check the role of the item directly from the stored role
        if item.role == "dimension":
            # Context menu for dimensions
            edit_aggregation_action = QAction("🔘 Edit Weights", self)
            edit_aggregation_action.triggered.connect(
                lambda: self.edit_dimension_aggregation(item)
            )  # Connect to method
            add_factor_action = QAction("Add Factor", self)
            remove_dimension_action = QAction("Remove Dimension", self)

            # Connect actions
            add_factor_action.triggered.connect(lambda: self.model.add_factor(item))
            remove_dimension_action.triggered.connect(
                lambda: self.model.remove_item(item)
            )

            # Add actions to menu
            menu = QMenu(self)
            menu.addAction(edit_aggregation_action)
            menu.addAction(show_json_attributes_action)
            menu.addAction(add_to_map_action)
            menu.addAction(run_item_action)
            menu.addAction(disable_action)

        elif item.role == "factor":
            # Context menu for factors
            edit_aggregation_action = QAction(
                "🔘 Edit Weights", self
            )  # New action for contextediting aggregation
            add_indicator_action = QAction("Add Indicator", self)
            remove_factor_action = QAction("Remove Factor", self)

            # Connect actions
            edit_aggregation_action.triggered.connect(
                lambda: self.edit_factor_aggregation(item)
            )  # Connect to method
            add_indicator_action.triggered.connect(
                lambda: self.model.add_indicator(item)
            )
            remove_factor_action.triggered.connect(lambda: self.model.remove_item(item))

            # Add actions to menu
            menu = QMenu(self)
            menu.addAction(edit_aggregation_action)
            menu.addAction(show_json_attributes_action)
            menu.addAction(add_to_map_action)
            menu.addAction(run_item_action)
            menu.addAction(disable_action)

        elif item.role == "indicator":
            # Context menu for layers
            # Editing an indicator will open the attributes dialog
            # of its parent factor...
            show_properties_action = QAction("🔘 Edit Weights", self)
            remove_indicator_action = QAction("❌ Remove Indicator", self)

            # Connect actions
            show_properties_action.triggered.connect(
                lambda: self.edit_factor_aggregation(item.parent())
            )
            remove_indicator_action.triggered.connect(
                lambda: self.model.remove_item(item)
            )

            # Add actions to menu
            menu = QMenu(self)
            menu.addAction(show_properties_action)
            menu.addAction(show_json_attributes_action)
            menu.addAction(add_to_map_action)
            menu.addAction(run_item_action)
            menu.addAction(disable_action)

        # Show the menu at the cursor's position
        menu.exec_(self.treeView.viewport().mapToGlobal(position))

    def disable_item(self, item):
        """Disable the item and its children."""
        item.disable()

    def enable_item(self, item):
        """Enable the item and its children."""
        item.enable()

    def show_attributes(self, item):
        """Show the attributes of the item in a table."""
        attributes = item.attributes()
        # Sort the data alphabetically by key name
        sorted_data = dict(sorted(attributes.items()))

        dialog = QDialog()
        dialog.setWindowState(Qt.WindowMaximized)
        dialog.setWindowTitle("Attributes")
        dialog.resize(600, 400)

        layout = QVBoxLayout()
        dialog.setLayout(layout)

        # Create a table to display the data
        table = QTableWidget()
        table.setRowCount(len(sorted_data))
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(["Key", "Value"])
        table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch
        )  # Only the second column stretches
        # Track if "error_file" exists
        error_file_content = None
        # Populate the table with the sorted data
        for row, (key, value) in enumerate(sorted_data.items()):
            key_item = QTableWidgetItem(key)
            key_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            table.setItem(row, 0, key_item)

            if isinstance(value, dict):
                # Create a nested table for dictionary values
                nested_table = self.create_nested_table(value)
                table.setCellWidget(row, 1, nested_table)
                # Adjust row height to fit nested table
                table.setRowHeight(row, nested_table.height() + 10)  # Add 10px padding
            else:
                value_item = QTableWidgetItem(str(value))
                value_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                table.setItem(row, 1, value_item)
            # Check if this row contains "error_file"
            if key == "error_file" and isinstance(value, str):
                try:
                    with open(value, "r") as file:
                        error_file_content = file.read()
                except (OSError, IOError):
                    error_file_content = f"Unable to read file: {value}"
                except Exception as e:
                    error_file_content = f"Error reading file: {e}"

        layout.addWidget(table)

        # Add buttons
        button_layout = QHBoxLayout()

        # Close button
        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.close)
        button_layout.addWidget(close_button)

        # Maximize button
        maximize_button = QPushButton("AutoSize Columns")
        maximize_button.clicked.connect(lambda: self.maximize_dialog(dialog, table))
        button_layout.addWidget(maximize_button)

        # Copy button
        copy_button = QPushButton("Copy to Clipboard")
        copy_button.clicked.connect(lambda: self.copy_to_clipboard_as_markdown(table))
        button_layout.addWidget(copy_button)

        # Show Error File button
        if error_file_content is not None:
            show_error_file_button = QPushButton("Show Error File")
            button_layout.addWidget(show_error_file_button)
            show_error_file_button.clicked.connect(
                lambda: self.show_error_file_popup(error_file_content)
            )
        layout.addLayout(button_layout)

        # Enable custom context menu for the table
        table.setContextMenuPolicy(Qt.CustomContextMenu)
        table.customContextMenuRequested.connect(
            lambda pos: self.show_context_menu(table, pos)
        )

        dialog.exec_()

    def show_error_file_popup(self, error_file_content):
        """Show a popup message with the contents of the error file."""
        msg_box = QMessageBox()
        msg_box.setWindowTitle("Error File Contents")
        msg_box.setText(error_file_content)
        msg_box.setStandardButtons(QMessageBox.Ok)
        msg_box.exec_()

    def copy_to_clipboard_as_markdown(self, table: QTableWidget):
        """Copy the table content as Markdown to the clipboard."""
        headers = [
            table.horizontalHeaderItem(i).text() for i in range(table.columnCount())
        ]
        markdown_lines = ["| " + " | ".join(headers) + " |"]
        markdown_lines.append("| " + " | ".join("---" for _ in headers) + " |")

        for row in range(table.rowCount()):
            row_data = []
            for col in range(table.columnCount()):
                item = table.item(row, col)
                if item:
                    row_data.append(item.text())
                else:
                    # Handle cell widgets like nested tables
                    cell_widget = table.cellWidget(row, col)
                    if isinstance(cell_widget, QTableWidget):
                        nested_headers = [
                            cell_widget.horizontalHeaderItem(i).text()
                            for i in range(cell_widget.columnCount())
                        ]
                        nested_data = []
                        for nested_row in range(cell_widget.rowCount()):
                            nested_row_data = [
                                cell_widget.item(nested_row, nested_col).text()
                                for nested_col in range(cell_widget.columnCount())
                            ]
                            nested_data.append(", ".join(nested_row_data))
                        row_data.append(
                            f"Nested: {', '.join(nested_headers)} ({'; '.join(nested_data)})"
                        )
                    else:
                        row_data.append("")
            markdown_lines.append("| " + " | ".join(row_data) + " |")

        # Copy the Markdown content to the clipboard
        clipboard = QApplication.clipboard()
        clipboard.setText("\n".join(markdown_lines))

        log_message("Table copied to clipboard as Markdown.")

    def create_nested_table(self, nested_data: dict) -> QTableWidget:
        """Create a QTableWidget to display nested dictionary data."""
        nested_table = QTableWidget()
        nested_table.setRowCount(len(nested_data))
        nested_table.setColumnCount(2)
        nested_table.setHorizontalHeaderLabels(["Key", "Value"])
        nested_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        for row, (key, value) in enumerate(nested_data.items()):
            key_item = QTableWidgetItem(str(key))  # Convert key to string
            value_item = QTableWidgetItem(str(value))  # Convert value to string
            key_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            value_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)

            nested_table.setItem(row, 0, key_item)
            nested_table.setItem(row, 1, value_item)

        nested_table.setFixedHeight(
            len(nested_data) * 25
        )  # Adjust height based on the number of rows
        nested_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        nested_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        nested_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        return nested_table

    def maximize_dialog(self, dialog, table):
        """Maximize the dialog and adjust the table column widths."""
        dialog.showMaximized()
        # Adjust the first column to fit its content
        table.resizeColumnToContents(0)

    def show_context_menu(self, table, pos):
        """Show a context menu with a copy option on right-click."""
        # Get the cell at the position where the right-click occurred
        item = table.itemAt(pos)
        if not item:
            return  # If no cell is clicked, do nothing

        # Create the context menu
        menu = QMenu()
        copy_action = menu.addAction("Copy")

        # Execute the menu at the position and check if an action was selected
        action = menu.exec_(table.viewport().mapToGlobal(pos))
        if action == copy_action:
            # If "Copy" was selected, copy the cell's content to the clipboard
            clipboard = QApplication.clipboard()
            clipboard.setText(item.text())

    def add_study_area_to_map(self):
        """Add the study area layers to the map.

        Note that the area grid layer can be slow to draw!.
        """
        gpkg_path = os.path.join(
            self.working_directory, "study_area", "study_area.gpkg"
        )
        project = QgsProject.instance()

        # Check if 'Geest' group exists, otherwise create it
        root = project.layerTreeRoot()
        geest_group = root.findGroup("Geest Study Area")
        if geest_group is None:
            geest_group = root.insertGroup(
                0, "Geest Study Area"
            )  # Insert at the top of the layers panel

        layers = [
            "study_area_bbox",
            "study_area_bboxes",
            "study_area_polygons",
            "study_area_grid",
        ]
        for layer_name in layers:
            gpkg_layer_path = f"{gpkg_path}|layername={layer_name}"
            layer = QgsVectorLayer(gpkg_layer_path, layer_name, "ogr")

            if layer.isValid():
                QgsProject.instance().addMapLayer(layer)
                log_message(f"Added '{layer_name}' layer to the map.")
            else:
                log_message(
                    f"Failed to add '{layer_name}' layer to the map.",
                    tag="Geest",
                    level=Qgis.Critical,
                )

            # Check if a layer with the same data source exists in the correct group
            existing_layer = None
            for child in geest_group.children():
                if isinstance(child, QgsLayerTreeGroup):
                    continue
                if child.layer().source() == gpkg_layer_path:
                    existing_layer = child.layer()
                    break

            # If the layer exists, refresh it instead of removing and re-adding
            if existing_layer is not None:
                log_message(f"Refreshing existing layer: {existing_layer.name()}")
                existing_layer.reload()
            else:
                # Add the new layer to the appropriate subgroup
                QgsProject.instance().addMapLayer(layer, False)
                layer_tree_layer = geest_group.addLayer(layer)
                log_message(
                    f"Added layer: {layer.name()} to group: {geest_group.name()}"
                )

    def add_to_map(self, item):
        """Add the item to the map."""

        layer_uri = item.attribute(f"result_file")

        if layer_uri:
            layer_name = item.data(0)
            layer = QgsRasterLayer(layer_uri, layer_name)

            if not layer.isValid():
                log_message(
                    f"Layer {layer_name} is invalid and cannot be added.",
                    tag="Geest",
                    level=Qgis.Warning,
                )
                return

            project = QgsProject.instance()

            # Check if 'Geest' group exists, otherwise create it
            root = project.layerTreeRoot()
            geest_group = root.findGroup("Geest")
            if geest_group is None:
                geest_group = root.insertGroup(
                    0, "Geest"
                )  # Insert at the top of the layers panel
                geest_group.setIsMutuallyExclusive(
                    True
                )  # Make the group mutually exclusive

            # Traverse the tree view structure to determine the appropriate subgroup based on paths
            path_list = item.getPaths()
            parent_group = geest_group
            # truncate the last item from the path list
            # as we want to add the layer to the group
            # that is the parent of the layer
            path_list = path_list[:-1]

            for path in path_list:
                sub_group = parent_group.findGroup(path)
                if sub_group is None:
                    sub_group = parent_group.addGroup(path)
                    sub_group.setIsMutuallyExclusive(
                        True
                    )  # Make each subgroup mutually exclusive

                parent_group = sub_group

            # Check if a layer with the same data source exists in the correct group
            existing_layer = None
            for child in parent_group.children():
                if isinstance(child, QgsLayerTreeGroup):
                    continue
                if child.layer().source() == layer_uri:
                    existing_layer = child.layer()
                    break

            # If the layer exists, refresh it instead of removing and re-adding
            if existing_layer is not None:
                log_message(
                    f"Refreshing existing layer: {existing_layer.name()}",
                    tag="Geest",
                    level=Qgis.Info,
                )
                existing_layer.reload()
            else:
                # Add the new layer to the appropriate subgroup
                QgsProject.instance().addMapLayer(layer, False)
                layer_tree_layer = parent_group.addLayer(layer)
                layer_tree_layer.setExpanded(
                    False
                )  # Collapse the legend for the layer by default
                log_message(
                    f"Added layer: {layer.name()} to group: {parent_group.name()}"
                )

                # Ensure the layer and its parent groups are visible
                current_group = parent_group
                while current_group is not None:
                    current_group.setExpanded(True)  # Expand the group
                    current_group.setItemVisibilityChecked(
                        True
                    )  # Ensure the group is visible
                    current_group = current_group.parent()

                # Set the layer itself to be visible
                layer_tree_layer.setItemVisibilityChecked(True)

            log_message(
                f"Layer {layer.name()} and its parent groups are now visible.",
                tag="Geest",
                level=Qgis.Info,
            )

    def edit_analysis_aggregation(self, analysis_item):
        """Open the AnalysisAggregationDialog for editing the weightings of factors in the analysis."""
        dialog = AnalysisAggregationDialog(analysis_item, parent=self)
        if dialog.exec_():  # If OK was clicked
            dialog.saveWeightingsToModel()
            self.save_json_to_working_directory()  # Save changes to the JSON if necessary

    def edit_dimension_aggregation(self, dimension_item):
        """Open the DimensionAggregationDialog for editing the weightings of factors in a dimension."""
        dimension_name = dimension_item.data(0)
        dimension_data = dimension_item.attributes()
        if not dimension_data:
            dimension_data = {}
        dialog = DimensionAggregationDialog(
            dimension_name, dimension_data, dimension_item, parent=self
        )
        if dialog.exec_():  # If OK was clicked
            dialog.saveWeightingsToModel()
            self.save_json_to_working_directory()  # Save changes to the JSON if necessary

    def edit_factor_aggregation(self, factor_item):
        """Open the FactorAggregationDialog for editing the weightings of layers in a factor."""
        factor_name = factor_item.data(0)
        factor_data = factor_item.attributes()
        if not factor_data:
            factor_data = {}
        dialog = FactorAggregationDialog(
            factor_name, factor_data, factor_item, parent=self
        )
        if dialog.exec_():  # If OK was clicked
            dialog.save_weightings_to_model()
            self.save_json_to_working_directory()  # Save changes to the JSON if necessary

    def start_workflows(self, type=None):
        """Start a workflow for each 'layer' node in the tree.

        We process in the order of layers, factors, and dimensions since there
        is a dependency between them. For example, a factor depends on its layers.
        """
        if type == "indicators":
            self._start_workflows(self.treeView.model().rootItem, role="indicator")
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
            if child_item.getStatus() == "Excluded from analysis":
                continue
            self.queue_workflow_task(child_item, role)
            # Recursively process children (dimensions, factors)
            self._start_workflows(child_item, role)

    def _count_workflows_to_run(self, parent_item=None):
        """
        Recursively count workflows that need to be run visiting each node in the tree.

        :param parent_item: The parent item to process. If none, start from the root.
        """
        if parent_item is None:
            parent_item = self.model.rootItem

        for i in range(parent_item.childCount()):
            child_item = parent_item.child(i)
            self._count_workflows_to_run(child_item)
            is_complete = child_item.getStatus() == "Workflow Completed"
            is_disabled = child_item.getStatus() == "Excluded from analysis"
            if is_disabled:
                continue
            elif not is_complete:
                self.items_to_run += 1
            elif is_complete and not self.run_only_incomplete:
                self.items_to_run += 1

    def queue_workflow_task(self, item, role):
        """Queue a workflow task based on the role of the item.

        ⭐️ These calls all pass a reference of the item to the workflow task.
            The task directly modifies the item's properties to update the tree.
        """
        task = None

        cell_size_m = (
            self.model.get_analysis_item()
            .attributes()
            .get("analysis_cell_size_m", 100.0)
        )
        attributes = item.attributes()
        if attributes.get("result_file", None) and self.run_only_incomplete:
            return
        if role == item.role and role == "indicator":
            task = self.queue_manager.add_workflow(item, cell_size_m)
        if role == item.role and role == "factor":
            attributes["analysis_mode"] = "factor_aggregation"
            task = self.queue_manager.add_workflow(item, cell_size_m)
        if role == item.role and role == "dimension":
            attributes["analysis_mode"] = "dimension_aggregation"
            task = self.queue_manager.add_workflow(item, cell_size_m)
        if role == item.role and role == "analysis":
            attributes["analysis_mode"] = "analysis_aggregation"
            task = self.queue_manager.add_workflow(item, cell_size_m)
        if task is None:
            return

        # Connect workflow signals to TreePanel slots
        task.job_queued.connect(partial(self.on_workflow_created, item))
        task.job_started.connect(partial(self.on_workflow_started, item))
        task.job_canceled.connect(partial(self.on_workflow_completed, item, False))
        task.job_finished.connect(
            lambda success: self.on_workflow_completed(item, success)
        )
        # Hook up the QTask feedback signal to the progress bar
        task.progressChanged.connect(self.task_progress_updated)

    def run_item(self, item, shift_pressed):
        """Run the item and the ones below it.

        If the user holds shift whilst running the item, it will force the
        recalculation of all workflows under the item, regardless of their status.

        Args:
            item (TreeItem): The item to run.
            shift_pressed (bool): Whether the shift key is pressed.

        """
        self.items_to_run = 0
        if shift_pressed:
            self.run_only_incomplete = False
        else:
            self.run_only_incomplete = True

        for i in range(item.childCount()):
            child_item = item.child(i)
            if child_item.childCount() > 0:
                self.run_item(child_item, shift_pressed)
            # If you change the logic below, dont forget to also
            # change the logic in _count_workflows_to_run
            is_complete = child_item.getStatus() == "Workflow Completed"
            if not is_complete:
                self.queue_workflow_task(child_item, child_item.role)
            if is_complete and not self.run_only_incomplete:
                self.queue_workflow_task(child_item, child_item.role)

        self.queue_workflow_task(item, item.role)
        self._count_workflows_to_run(item)

        debug_env = int(os.getenv("GEEST_DEBUG", 0))
        if debug_env:
            self.queue_manager.start_processing_in_foreground()
        else:
            self.queue_manager.start_processing()

    @pyqtSlot()
    def on_workflow_created(self, item):
        """
        Slot for handling when a workflow is created.
        Does nothing right now...
        """
        pass

    @pyqtSlot()
    def on_workflow_started(self, item):
        """
        Slot for handling when a workflow starts.
        Update the tree item to indicate that the workflow is running.
        """
        # Get the node index for the item
        node_index = self.model.itemIndex(item)
        if not node_index.isValid():
            log_message(
                f"Failed to find index for item {item} - animation not started",
                tag="Geest",
                level=Qgis.Warning,
            )
            return

        # Ensure we work with QModelIndex instead of QPersistentModelIndex
        child_index = QModelIndex(node_index)

        # Get row height and prepare movies
        row_height = self.treeView.rowHeight(child_index)
        self.child_movie = QMovie(resources_path("resources", "throbber.gif"))
        self.parent_movie = QMovie(resources_path("resources", "throbber.gif"))

        # Scale movies
        self.child_movie.setScaledSize(
            self.child_movie.currentPixmap()
            .size()
            .scaled(row_height, row_height, Qt.KeepAspectRatio)
        )
        self.parent_movie.setScaledSize(
            self.parent_movie.currentPixmap()
            .size()
            .scaled(row_height, row_height, Qt.KeepAspectRatio)
        )

        # Set animated icon for the child
        child_label = QLabel()
        child_label.setMovie(self.child_movie)
        self.child_movie.start()

        # Place child animation
        second_column_index = self.model.index(
            child_index.row(), 1, child_index.parent()
        )
        self.treeView.setIndexWidget(second_column_index, child_label)

        # Always show parent animation if this is an indicator
        if item.role == "indicator":
            parent_item = item.parent()
            if parent_item:
                parent_index = self.model.itemIndex(parent_item)
                if parent_index.isValid():
                    # Create parent animation
                    parent_label = QLabel()
                    parent_label.setMovie(self.parent_movie)
                    self.parent_movie.start()

                    # Get parent's second column index
                    parent_second_column_index = self.model.index(
                        parent_index.row(), 1, parent_index.parent()
                    )

                    # Set parent animation and ensure it's visible
                    self.treeView.setIndexWidget(
                        parent_second_column_index, parent_label
                    )
                    parent_label.show()

                    # Force immediate update
                    self.treeView.viewport().update()

    def task_progress_updated(self, progress):
        """Slot to be called when the task progress is updated."""
        log_message(f"Task progress: {progress}")
        self.workflow_progress_bar.setValue(int(progress))

    @pyqtSlot(bool)
    def on_workflow_completed(self, item, success):
        """
        Slot for handling when a workflow is completed.
        Update the tree item to indicate success or failure.
        """
        self.overall_progress_bar.setValue(self.overall_progress_bar.value() + 1)
        self.workflow_progress_bar.setValue(0)
        self.save_json_to_working_directory()

        self.add_to_map(item)

        # Now cancel the animated icon
        node_index = self.model.itemIndex(item)

        if not node_index.isValid():
            log_message(
                f"Failed to find index for item {item} - animation not started",
                tag="Geest",
                level=Qgis.Warning,
            )
            return

        parent_second_column_index = None
        if item.role == "indicator":
            # Show an animation on its parent too
            parent_index = node_index.parent()
            parent_second_column_index = self.model.index(
                parent_index.row(), 1, parent_index.parent()
            )

        self.child_movie.stop()
        self.parent_movie.stop()

        second_column_index = self.model.index(node_index.row(), 1, node_index.parent())
        self.treeView.setIndexWidget(second_column_index, None)
        if parent_second_column_index:
            self.treeView.setIndexWidget(parent_second_column_index, None)

        # Emit dataChanged to refresh the decoration
        self.model.dataChanged.emit(second_column_index, second_column_index)

    def update_tree_item_status(self, item, status):
        """
        Update the tree item to show the workflow status.
        :param item: The tree item representing the workflow.
        :param status: The status message or icon to display.
        """
        # Assuming column 1 is where status updates are shown
        item.setData(1, status)

    def run_all(self):
        """Run all workflows in the tree, regardless of their status."""
        self.run_only_incomplete = False
        self.clear_workflows()
        self.items_to_run = 0
        self._count_workflows_to_run()
        log_message(f"Total items to process: {self.items_to_run}")
        self._queue_workflows()

    def run_incomplete(self):
        """
        This function processes all nodes in the QTreeView that have the 'indicator' role.
        It iterates over the entire tree, collecting nodes with the 'indicator' role, and
        processes each one whilst showing an animated icon.
        """
        self.run_only_incomplete = True
        self.items_to_run = 0
        self._count_workflows_to_run()
        self._queue_workflows()

    def _queue_workflows(self):
        """
        This function processes all nodes in the QTreeView working through them in
        logical order of indicators then factors then dimensions, then the whole analysis.
        """
        self.workflow_queue = ["indicators", "factors", "dimensions", "analysis"]
        self.overall_progress_bar.setVisible(True)
        self.workflow_progress_bar.setVisible(True)
        self.help_button.setVisible(False)
        self.project_button.setVisible(False)
        self.overall_progress_bar.setValue(0)
        self.overall_progress_bar.setMaximum(self.items_to_run)
        self.workflow_progress_bar.setValue(0)
        self.run_next_workflow_queue()

    def run_next_workflow_queue(self):
        """
        Run the next group of workflows in the queue.
        If self.workflow_queue is empty, the function will return.
        """
        if len(self.workflow_queue) == 0:
            self.overall_progress_bar.setVisible(False)
            self.workflow_progress_bar.setVisible(False)
            self.help_button.setVisible(True)
            self.project_button.setVisible(True)
            return
        # pop the first item from the queue
        next_workflow = self.workflow_queue.pop(0)
        self.start_workflows(type=next_workflow)
        debug_env = int(os.getenv("GEEST_DEBUG", 0))
        if debug_env:
            self.queue_manager.start_processing_in_foreground()
        else:
            self.queue_manager.start_processing()

    def expand_all_nodes(self, index=None):
        """
        :param index: QModelIndex - if None the root index is used

        Recursively expand all nodes in the tree view starting from the root.
        """
        if self.treeView.model() is None:
            return
        else:
            model = self.treeView.model()
        if index is None:
            index = model.index(0, 0, QModelIndex())

        if not index.isValid():
            return

        self.treeView.expand(index)

        # Loop through all children and expand them as well
        row_count = self.treeView.model().rowCount(index)
        for row in range(row_count):
            child_index = self.treeView.model().index(row, 0, index)
            self.expand_all_nodes(child_index)
