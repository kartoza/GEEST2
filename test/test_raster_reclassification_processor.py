import unittest
import os
from qgis.core import QgsVectorLayer, QgsRasterLayer, QgsProcessingContext, QgsProject
from geest.core.algorithms.raster_reclassification_processor import (
    RasterReclassificationProcessor,
)


class TestRasterReclassificationProcessor(unittest.TestCase):
    def setUp(self):
        """
        Set up the environment for the test, loading the test data layers.
        """
        self.context = QgsProcessingContext()
        # Manually create a QgsProject instance and set it in the context
        self.project = QgsProject.instance()
        self.context.setProject(self.project)

        # Define working directories
        self.working_directory = os.path.dirname(__file__)
        self.test_data_directory = os.path.join(self.working_directory, "test_data")
        self.output_directory = os.path.join(self.working_directory, "output")

        # Create the output directory if it doesn't exist
        if not os.path.exists(self.output_directory):
            os.makedirs(self.output_directory)

        # Define paths to test layers
        self.input_raster_path = os.path.join(
            self.test_data_directory, "rasters", "env_fire_hazard.tif"
        )
        self.gpkg_path = os.path.join(
            self.test_data_directory, "study_area", "study_area.gpkg"
        )

        # Load the input raster and grid layer
        self.input_raster = QgsRasterLayer(self.input_raster_path, "Input Raster")
        # self.grid_layer = QgsVectorLayer(
        #    f"{self.gpkg_path}|layername=study_area_grid", "Grid Layer", "ogr"
        # )

        # Ensure the input layers are valid
        self.assertTrue(self.input_raster.isValid(), "Failed to load input raster.")

        # Define the reclassification rules for fire hazards
        self.reclassification_rules = [
            0,
            0,
            5,
            0.00,
            1,
            4,
            1.00,
            2,
            3,
            2.00,
            5,
            2,
            5.00,
            8,
            1,
            8.00,
            float("inf"),
            0,
        ]

        # Set the output VRT path
        self.output_vrt = os.path.join(
            self.output_directory, "test_reclassified_output.vrt"
        )

        # Set the pixel size (example: 100 meters)
        self.pixel_size = 100.0

        # Initialize the processor with test data
        self.processor = RasterReclassificationProcessor(
            input_raster=self.input_raster_path,
            output_prefix="test",
            reclassification_table=self.reclassification_rules,
            pixel_size=self.pixel_size,
            gpkg_path=self.gpkg_path,
            workflow_directory=self.output_directory,
            context=self.context,
        )

    def test_reclassify(self):
        """
        Test the main reclassify function to ensure that the raster is reclassified
        and the VRT output is generated correctly.
        """
        # Run the processor
        self.processor.reclassify()

        # Check if the VRT output file was created
        self.assertTrue(
            os.path.exists(self.output_vrt), "The VRT output was not created."
        )

        # Verify the content of the output VRT (ensure it's a valid VRT)
        vrt_layer = QgsRasterLayer(self.output_vrt, "Reclassified VRT")
        self.assertTrue(vrt_layer.isValid(), "The generated VRT is invalid.")


if __name__ == "__main__":
    unittest.main()
