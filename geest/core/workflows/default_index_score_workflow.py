import os
import glob
from qgis.core import (
    QgsMessageLog,
    Qgis,
    QgsFeedback,
    QgsFeature,
    QgsVectorLayer,
    QgsField,
    QgsGeometry,
    QgsRectangle,
    QgsRasterLayer,
    QgsProject,
)
from qgis.PyQt.QtCore import QVariant
import processing  # QGIS processing toolbox
from .workflow_base import WorkflowBase


class DefaultIndexScoreWorkflow(WorkflowBase):
    """
    Concrete implementation of a 'Use Default Index Score' workflow.
    """

    def __init__(self, attributes: dict, feedback: QgsFeedback):
        """
        Initialize the TemporalAnalysisWorkflow with attributes and feedback.
        :param attributes: Dictionary containing workflow parameters.
        :param feedback: QgsFeedback object for progress reporting and cancellation.
        """
        super().__init__(attributes, feedback)

    def execute(self):
        """
        Executes the workflow, reporting progress through the feedback object and checking for cancellation.
        """

        QgsMessageLog.logMessage(
            "Executing Use Default Index Score", tag="Geest", level=Qgis.Info
        )
        QgsMessageLog.logMessage(
            "----------------------------------", tag="Geest", level=Qgis.Info
        )
        for item in self.attributes.items():
            QgsMessageLog.logMessage(
                f"{item[0]}: {item[1]}", tag="Geest", level=Qgis.Info
            )
        QgsMessageLog.logMessage(
            "----------------------------------", tag="Geest", level=Qgis.Info
        )

        self.workflow_directory = self._create_workflow_directory(
            "contextual",
            self.attributes["ID"].lower(),
        )

        # loop through self.bboxes_layer and the self.areas_layer  and create a raster mask for each feature
        index_score = self.attributes["Default Index Score"]
        for feature in self.bboxes_layer.getFeatures():
            if (
                self.feedback.isCanceled()
            ):  # Check for cancellation before each major step
                QgsMessageLog.logMessage(
                    "Workflow canceled before processing feature.",
                    tag="Geest",
                    level=Qgis.Warning,
                )
                return False
            geom = feature.geometry()  # todo this shoudl come from the areas layer
            aligned_box = geom
            mask_name = f"bbox_{feature.id()}"
            self.create_raster(
                geom=geom,
                aligned_box=aligned_box,
                mask_name=mask_name,
                index_score=index_score,
            )
        # TODO Jeff copy create_raster_vrt from study_area.py
        # Create and add the VRT of all generated raster masks if in raster mode
        self.create_raster_vrt(
            output_vrt_name=os.path.join(self.workflow_directory, "combined_mask.vrt")
        )

        self.attributes["result"] = "Use Default Index Score Workflow Completed"
        QgsMessageLog.logMessage(
            "Use Default Index Score workflow workflow completed",
            tag="Geest",
            level=Qgis.Info,
        )
        return True

    def create_raster(
        self,
        geom: QgsGeometry,
        aligned_box: QgsGeometry,
        mask_name: str,
        index_score: float,
    ) -> None:
        """
        Creates a byte raster mask for a single geometry.

        :param geom: Geometry to be rasterized.
        :param aligned_box: Aligned bounding box geometry for the geometry.
        :param mask_name: Name for the output raster file.
        """
        if self.feedback.isCanceled():  # Check for cancellation before starting
            QgsMessageLog.logMessage(
                "Workflow canceled before creating raster.",
                tag="Geest",
                level=Qgis.Warning,
            )
            return

        aligned_box = QgsRectangle(aligned_box.boundingBox())
        mask_filepath = os.path.join(self.workflow_directory, f"{mask_name}.tif")
        index_score = (self.attributes["Default Index Score"] / 100) * 5

        # Create a memory layer to hold the geometry
        temp_layer = QgsVectorLayer(
            f"Polygon?crs={self.output_crs.authid()}", "temp_mask_layer", "memory"
        )
        temp_layer_data_provider = temp_layer.dataProvider()

        # Define a field to store the mask value
        temp_layer_data_provider.addAttributes([QgsField("area_name", QVariant.String)])
        temp_layer.updateFields()

        # Add the geometry to the memory layer
        temp_feature = QgsFeature()
        temp_feature.setGeometry(geom)
        temp_feature.setAttributes(["1"])  # Setting an arbitrary value for the mask
        temp_layer_data_provider.addFeature(temp_feature)

        # Ensure resolution parameters are properly formatted as float values
        x_res = 100.0  # 100m pixel size in X direction
        y_res = 100.0  # 100m pixel size in Y direction

        # Define rasterization parameters for the temporary layer
        params = {
            "INPUT": temp_layer,
            "FIELD": None,
            "BURN": index_score,  # todo Jeff put on likert scale properly
            "USE_Z": False,
            "UNITS": 1,
            "WIDTH": x_res,
            "HEIGHT": y_res,
            "EXTENT": f"{aligned_box.xMinimum()},{aligned_box.xMaximum()},"
            f"{aligned_box.yMinimum()},{aligned_box.yMaximum()}",  # Extent of the aligned bbox
            "NODATA": 0,
            "OPTIONS": "",
            "DATA_TYPE": 0,  # byte
            "INIT": None,
            "INVERT": False,
            "EXTRA": "",
            "OUTPUT": mask_filepath,
        }
        # Run the rasterize algorithm
        processing.run("gdal:rasterize", params)
        QgsMessageLog.logMessage(
            f"Created raster mask: {mask_filepath}", tag="Geest", level=Qgis.Info
        )

    def create_raster_vrt(self, output_vrt_name: str = "combined_mask.vrt") -> None:
        """
        Creates a VRT file from all generated raster masks and adds it to the QGIS map.

        :param output_vrt_name: The name of the VRT file to create.
        """
        if self.feedback.isCanceled():  # Check for cancellation before starting
            QgsMessageLog.logMessage(
                "Workflow canceled before creating VRT.",
                tag="Geest",
                level=Qgis.Warning,
            )
            return

        QgsMessageLog.logMessage(
            f"Creating VRT of masks '{output_vrt_name}' layer to the map.",
            tag="Geest",
            level=Qgis.Info,
        )
        # Directory containing raster masks
        raster_dir = os.path.dirname(output_vrt_name)
        raster_files = glob.glob(os.path.join(raster_dir, "*.tif"))

        if not raster_files:
            QgsMessageLog.logMessage(
                "No raster masks found to combine into VRT.",
                tag="Geest",
                level=Qgis.Warning,
            )
            return

        vrt_filepath = os.path.join(raster_dir, output_vrt_name)

        # Define the VRT parameters
        params = {
            "INPUT": raster_files,
            "RESOLUTION": 0,  # Use highest resolution among input files
            "SEPARATE": False,  # Combine all input rasters as a single band
            "OUTPUT": vrt_filepath,
            "PROJ_DIFFERENCE": False,
            "ADD_ALPHA": False,
            "ASSIGN_CRS": None,
            "RESAMPLING": 0,
            "SRC_NODATA": "0",
            "EXTRA": "",
        }

        # Run the gdal:buildvrt processing algorithm to create the VRT
        processing.run("gdal:buildvirtualraster", params)
        QgsMessageLog.logMessage(
            f"Created VRT: {vrt_filepath}", tag="Geest", level=Qgis.Info
        )

        # Add the VRT to the QGIS map
        vrt_layer = QgsRasterLayer(vrt_filepath, "Combined Mask VRT")

        if vrt_layer.isValid():
            QgsProject.instance().addMapLayer(vrt_layer)
            QgsMessageLog.logMessage(
                "Added VRT layer to the map.", tag="Geest", level=Qgis.Info
            )
        else:
            QgsMessageLog.logMessage(
                "Failed to add VRT layer to the map.", tag="Geest", level=Qgis.Critical
            )