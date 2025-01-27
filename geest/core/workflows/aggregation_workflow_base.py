import os
import traceback
from osgeo import gdal
from qgis.core import (
    Qgis,
    QgsFeedback,
    QgsProcessingContext,
    QgsGeometry,
)

# from qgis.analysis import QgsRasterCalculator, QgsRasterCalculatorEntry
import processing  # QGIS processing toolbox
from .workflow_base import WorkflowBase
from geest.core import JsonTreeItem
from geest.utilities import log_message
from geest.core.algorithms import merge_rasters


class AggregationWorkflowBase(WorkflowBase):
    """
    Base class for all aggregation workflows (factor, dimension, analysis)
    """

    def __init__(
        self,
        item: JsonTreeItem,
        cell_size_m: float,
        feedback: QgsFeedback,
        context: QgsProcessingContext,
        working_directory: str = None,
    ):
        """
        Initialize the workflow with attributes and feedback.
        :param attributes: Item containing workflow parameters.
        :param feedback: QgsFeedback object for progress reporting and cancellation.
        :context: QgsProcessingContext object for processing. This can be used to pass objects to the thread. e.g. the QgsProject Instance
        :working_directory: Folder containing study_area.gpkg and where the outputs will be placed. If not set will be taken from QSettings.
        """
        super().__init__(
            item, cell_size_m, feedback, context, working_directory
        )  # ⭐️ Item is a reference - whatever you change in this item will directly update the tree
        self.guids = None  # This should be set by the child class - a list of guids of JSONTreeItems to aggregate
        self.id = None  # This should be set by the child class
        self.weight_key = None  # This should be set by the child class
        self.aggregation = True

    def aggregate(self, input_files: dict, index: int) -> str:
        """
        Perform weighted raster aggregation on the found raster files using GDAL Raster Calculator.

        :param input_files: dict of raster file paths to aggregate and their weights.
        :param index: The index of the area being processed.

        :return: Path to the aggregated raster file.
        """
        if len(input_files) == 0:
            log_message(
                "Error: Found no Input files. Cannot proceed with aggregation.",
                tag="Geest",
                level=Qgis.Warning,
            )
            return None

        # Extract layers and weights
        raster_layers = list(input_files.keys())
        weights = list(input_files.values())

        # File paths
        merged_output = os.path.join(
            self.workflow_directory, f"{self.id}_merged_{index}.tif"
        )
        mask_output = os.path.join(
            self.workflow_directory, f"{self.id}_mask_{index}.tif"
        )
        final_outputs = [
            os.path.join(
                self.workflow_directory, f"{self.id}_final_layer_{i}_{index}.tif"
            )
            for i in range(len(raster_layers))
        ]
        aggregation_output = os.path.join(
            self.workflow_directory, f"{self.id}_aggregated_{index}.tif"
        )

        # Step 1: Merge layers using custom logic
        log_message(
            "Step 1: Merging input layers into a single raster.",
            tag="Geest",
            level=Qgis.Info,
        )

        # Merge the input layers
        try:
            merge_rasters(raster_layers, merged_output)
            log_message(
                f"Raster layers merged successfully: {merged_output}",
                tag="Geest",
                level=Qgis.Info,
            )
        except Exception as e:
            log_message(
                f"Error during merging: {str(e)}", tag="Geest", level=Qgis.Critical
            )
            log_message(traceback.format_exc(), tag="Geest", level=Qgis.Critical)
            return None

        # Step 2: Create mask
        log_message(
            "Step 2: Creating a binary mask from the merged raster.",
            tag="Geest",
            level=Qgis.Info,
        )

        # Adjust the formula to explicitly check for NoData
        try:

            params = {
                "INPUT_A": merged_output,
                "BAND_A": 1,
                "FORMULA": "A>=0",
                "NO_DATA": None,
                "EXTENT_OPT": 0,
                "PROJWIN": None,
                "RTYPE": 0,
                "OPTIONS": "",
                "EXTRA": "",
                "OUTPUT": mask_output,
            }
            processing.run("gdal:rastercalculator", params)
            log_message(
                f"Mask raster saved at: {mask_output}", tag="Geest", level=Qgis.Info
            )
        except Exception as e:
            log_message(
                f"Error creating binary mask: {str(e)}",
                tag="Geest",
                level=Qgis.Critical,
            )
            return None

        # Step 3: Merge each layer with the mask
        log_message(
            "Step 3: Merging each input layer with the mask.",
            tag="Geest",
            level=Qgis.Info,
        )
        for raster, final_output in zip(raster_layers, final_outputs):
            processing.run(
                "gdal:rastercalculator",
                {
                    "INPUT_A": mask_output,
                    "BAND_A": 1,
                    "INPUT_B": raster,
                    "BAND_B": 1,
                    "FORMULA": "where(B == -9999, A, B)",
                    "NO_DATA": -9999,
                    "RTYPE": 5,  # Float32
                    "OUTPUT": final_output,
                },
            )
            log_message(
                f"Masked layer saved at: {final_output}", tag="Geest", level=Qgis.Info
            )

        # Step 4: Weighted combination
        log_message(
            "Step 4: Performing weighted combination of masked layers.",
            tag="Geest",
            level=Qgis.Info,
        )

        letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"  # Sequential alphabet for layers
        params = {}

        # Assign letters to each layer and build parameters
        for i, final_output in enumerate(final_outputs):
            if i >= len(letters):
                log_message(
                    "Too many layers for sequential alphabet assignment.",
                    tag="Geest",
                    level=Qgis.Critical,
                )
                return None
            letter = letters[i]
            params[f"INPUT_{letter}"] = final_output
            params[f"BAND_{letter}"] = 1

        # Always assign Z to the mask layer
        params["INPUT_Z"] = mask_output
        params["BAND_Z"] = 1

        # Construct the weighted formula
        weighted_expr = " + ".join(
            [f"({weights[i]} * {letters[i]}@1)" for i in range(len(final_outputs))]
        )
        params["FORMULA"] = (
            f"Z * ({weighted_expr})"  # Apply the mask (Z) to the weighted sum
        )

        # Additional GDAL Raster Calculator parameters
        params["NO_DATA"] = -9999
        params["RTYPE"] = 5  # Float32
        params["OUTPUT"] = aggregation_output

        try:
            processing.run("gdal:rastercalculator", params)
        except Exception as e:
            log_message(
                f"Error during raster aggregation: {str(e)}",
                tag="Geest",
                level=Qgis.Critical,
            )
            return None

        log_message(
            f"Weighted aggregation completed successfully: {aggregation_output}",
            tag="Geest",
            level=Qgis.Info,
        )

        try:
            processing.run("gdal:rastercalculator", params)
        except Exception as e:
            log_message(
                f"Error during raster aggregation: {str(e)}",
                tag="Geest",
                level=Qgis.Critical,
            )
            return None

        log_message(
            f"Weighted aggregation completed successfully: {aggregation_output}",
            tag="Geest",
            level=Qgis.Info,
        )

        # Save the result in attributes for further use
        self.attributes[self.result_file_key] = aggregation_output
        return aggregation_output

    def get_raster_dict(self, index) -> list:
        """
        Get the list of rasters from the attributes that will be aggregated.

        (Factor Aggregation, Dimension Aggregation, Analysis).

        Parameters:
            index (int): The index of the area being processed.

        Returns:
            dict: dict of found raster file paths and their weights.
        """
        raster_files = {}
        if self.guids is None:
            raise ValueError("No GUIDs provided for aggregation")

        for guid in self.guids:

            item = self.item.getItemByGuid(guid)
            status = item.getStatus() == "Completed successfully"
            mode = item.attributes().get("analysis_mode", "Do Not Use") == "Do Not Use"
            excluded = item.getStatus() == "Excluded from analysis"
            id = item.attribute("id").lower()
            if not status and not mode and not excluded:
                raise ValueError(
                    f"{id} is not completed successfully and is not set to 'Do Not Use' or 'Excluded from analysis'"
                )

            if mode:
                log_message(
                    f"Skipping {item.attribute('id')} as it is set to 'Do Not Use'",
                    tag="Geest",
                    level=Qgis.Info,
                )
                continue
            if excluded:
                log_message(
                    f"Skipping {item.attribute('id')} as it is excluded from analysis",
                    tag="Geest",
                    level=Qgis.Info,
                )
                continue
            if not item.attribute(self.result_file_key, ""):
                log_message(
                    f"Skipping {id} as it has no result file",
                    tag="Geest",
                    level=Qgis.Info,
                )
                raise ValueError(f"{id} has no result file")

            layer_folder = os.path.dirname(item.attribute(self.result_file_key, ""))
            path = os.path.join(
                self.workflow_directory, layer_folder, f"{id}_masked_{index}.tif"
            )
            if os.path.exists(path):

                weight = item.attribute(self.weight_key, "")
                try:
                    weight = float(weight)
                except (ValueError, TypeError):
                    weight = 1.0  # Default fallback to 1.0 if weight is invalid

                raster_files[path] = weight

                log_message(f"Adding raster: {path} with weight: {weight}")

        log_message(
            f"Total raster files found: {len(raster_files)}",
            tag="Geest",
            level=Qgis.Info,
        )
        return raster_files

    def _process_aggregate_for_area(
        self,
        current_area: QgsGeometry,
        clip_area: QgsGeometry,
        current_bbox: QgsGeometry,
        index: int,
    ):
        """
        Executes the workflow, reporting progress through the feedback object and checking for cancellation.
        """
        _ = current_area  # Unused in this analysis
        _ = clip_area  # Unused in this analysis
        _ = current_bbox  # Unused in this analysis

        # Log the execution
        log_message(
            f"Executing {self.analysis_mode} Aggregation Workflow",
            tag="Geest",
            level=Qgis.Info,
        )
        raster_files = self.get_raster_dict(index)

        if not raster_files or not isinstance(raster_files, dict):
            error = f"No valid raster files found in '{self.guids}'. Cannot proceed with aggregation."
            log_message(
                error,
                tag="Geest",
                level=Qgis.Warning,
            )
            self.attributes[self.result_key] = (
                f"{self.analysis_mode} Aggregation Workflow Failed"
            )
            self.attributes["error"] = error

        log_message(
            f"Found {len(raster_files)} raster files in 'Result File'. Proceeding with aggregation.",
            tag="Geest",
            level=Qgis.Info,
        )

        # Perform aggregation only if raster files are provided
        result_file = self.aggregate(raster_files, index)

        return result_file

    def _process_features_for_area(self):
        pass

    def _process_raster_for_area(self):
        pass
