import os
import glob
from qgis.core import (
    QgsMessageLog,
    Qgis,
    QgsRasterLayer,
    QgsProject,
)
from qgis.analysis import QgsRasterCalculator, QgsRasterCalculatorEntry
import processing
from .workflow_base import WorkflowBase


class ContextualAggregateWorkflow(WorkflowBase):
    """
    Execute the aggregation workflow.

    Args:
        WorkflowBase (_type_): _description_
    """

    def __init__(self, attributes: dict, feedback):
        super().__init__(attributes, feedback)
        self.layer_id = self.attributes["ID"].lower()

    def scan_working_directory_for_vrt(self, working_directory: str) -> list:
        """
        Scans the provided working directory and its subdirectories recursively for VRT files and returns a list of found VRT file paths.

        :param working_directory: The base directory to scan for VRT files.
        :return: List of found VRT file paths.
        """
        vrt_files = []
        required_vrt_types = [
            "workplace_index_score",
            "pay_parenthood_index_score",
            "entrepeneurship_index _score",
        ]  # Example: we expect these VRT types

        # Recursively scan for VRT files in the working directory
        found_files = glob.glob(
            os.path.join(working_directory, "**", "*.vrt"), recursive=True
        )

        # Filter and collect VRT files based on their type (e.g., WD, RF, FIN)
        for vrt_file in found_files:
            for vrt_type in required_vrt_types:
                if vrt_type in os.path.basename(vrt_file):
                    vrt_files.append(vrt_file)
                    QgsMessageLog.logMessage(
                        f"Found VRT file: {vrt_file}", tag="Geest", level=Qgis.Info
                    )

        return vrt_files

    def get_layer_weights(self, num_layers: int) -> list:
        """
        Retrieve default weights based on the number of layers.
        :param num_layers: Number of raster layers to aggregate.
        :return: List of weights for the layers.
        """
        if num_layers == 1:
            return [1.0]
        elif num_layers == 2:
            return [0.5, 0.5]
        elif num_layers == 3:
            return [0.33, 0.33, 0.34]
        else:
            return [1.0] * num_layers  # Handle unexpected cases

    def aggregate_vrt_files(self, vrt_files: list) -> None:
        """
        Perform weighted raster aggregation on the found VRT files.

        :param vrt_files: List of VRT file paths to aggregate.
        """
        if len(vrt_files) == 0:  # Expecting 3 VRTs: WD, RF, FIN
            QgsMessageLog.logMessage(
                f"Not all required VRT files found. Found {len(vrt_files)} VRT files. Cannot proceed with aggregation.",
                tag="Geest",
                level=Qgis.Warning,
            )
            return

        # Load the VRT layers
        raster_layers = [
            QgsRasterLayer(vf, f"VRT_{i}") for i, vf in enumerate(vrt_files)
        ]

        # Ensure all VRT layers are valid
        if not all(layer.isValid() for layer in raster_layers):
            QgsMessageLog.logMessage(
                "One or more VRT layers are invalid, cannot proceed with aggregation.",
                tag="Geest",
                level=Qgis.Critical,
            )
            return

        # Create QgsRasterCalculatorEntries for each VRT layer
        entries = []
        for i, raster_layer in enumerate(raster_layers):
            entry = QgsRasterCalculatorEntry()
            entry.ref = f"layer_{i+1}@1"  # layer_1@1, layer_2@1, etc.
            entry.raster = raster_layer
            entry.bandNumber = 1
            entries.append(entry)

        # Assign default weights (you can modify this as needed)
        weights = self.get_layer_weights(len(vrt_files))

        # Build the calculation expression
        expression = " + ".join(
            [f"({weights[i]} * layer_{i+1}@1)" for i in range(len(vrt_files))]
        )

        # Define output path for the aggregated raster
        aggregation_output = os.path.join(
            self.workflow_directory, f"contextual_aggregated_score.tif"
        )

        # Set up the raster calculator
        calc = QgsRasterCalculator(
            expression,
            aggregation_output,
            "GTiff",  # Output format
            raster_layers[0].extent(),  # Assuming all layers have the same extent
            raster_layers[0].width(),
            raster_layers[0].height(),
            entries,
        )

        # Run the calculation
        result = calc.processCalculation()

        if result == 0:
            QgsMessageLog.logMessage(
                "Raster aggregation completed successfully.",
                tag="Geest",
                level=Qgis.Info,
            )
            # Add the aggregated raster to the map
            aggregated_layer = QgsRasterLayer(
                aggregation_output, f"contextual_aggregated_score"
            )
            if aggregated_layer.isValid():
                QgsProject.instance().addMapLayer(aggregated_layer)
            else:
                QgsMessageLog.logMessage(
                    "Failed to add the aggregated raster to the map.",
                    tag="Geest",
                    level=Qgis.Critical,
                )
        else:
            QgsMessageLog.logMessage(
                "Error occurred during raster aggregation.",
                tag="Geest",
                level=Qgis.Critical,
            )

    def execute(self):
        # Directories where the VRTs are expected to be found
        # Directory where the VRTs are expected to be found
        self.workflow_directory = self._create_workflow_directory("contextual")

        # Scan the working directory for VRT files
        vrt_files = self.scan_working_directory_for_vrt(self.workflow_directory)

        # Perform aggregation only if all necessary VRTs are found
        if len(vrt_files) > 0:  # Ensure we have all three VRT files
            self.aggregate_vrt_files(vrt_files)
            QgsMessageLog.logMessage(
                "Aggregation Workflow completed successfully.",
                tag="Geest",
                level=Qgis.Info,
            )
            return True
        else:
            QgsMessageLog.logMessage(
                "Aggregation could not proceed. Missing VRT files.",
                tag="Geest",
                level=Qgis.Warning,
            )
            return False
