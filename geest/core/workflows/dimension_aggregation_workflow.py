import os
from qgis.core import (
    QgsFeedback,
)
from qgis.analysis import QgsRasterCalculator, QgsRasterCalculatorEntry
from .aggregation_workflow_base import AggregationWorkflowBase
from geest.utilities import resources_path
from geest.gui.treeview import JsonTreeItem


class DimensionAggregationWorkflow(AggregationWorkflowBase):
    """
    Concrete implementation of a 'Dimension Aggregation' workflow.

    It will aggregate the factors within a dimension to create a single raster output.

    """

    def __init__(self, item: JsonTreeItem, feedback: QgsFeedback):
        """
        Initialize the Dimension Aggregation with attributes and feedback.

        ⭐️ Item is a reference - whatever you change in this item will directly update the tree

        :param item: JsonTreeItem containing workflow parameters.
        :param feedback: QgsFeedback object for progress reporting and cancellation.
        """
        super().__init__(item, feedback)
        self.aggregation_attributes = self.item.getDimensionAttributes()
        self.id = self.attributes["id"].lower().replace(" ", "_")
        self.layers = self.aggregation_attributes.get(f"Factors", [])
        self.weight_key = "Factor Weighting"
        self.result_file_tag = "Dimension Result File"
        self.raster_path_key = "Factor Result File"

    def output_path(self, extension: str) -> str:
        """
        Define output path for the aggregated raster based on the analysis mode.

        Parameters:
            extension (str): The file extension for the output file.

        Returns:
            str: Path to the aggregated raster file.

        """
        directory = os.path.join(self.workflow_directory, self.id)
        # Create the directory if it doesn't exist
        if not os.path.exists(directory):
            os.makedirs(directory)

        return os.path.join(
            directory,
            f"aggregate_{self.id}" + f".{extension}",
        )