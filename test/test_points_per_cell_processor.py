import unittest
from qgis.core import QgsVectorLayer, QgsGeometry, QgsProject
from pathlib import Path
import os
import processing
from geest.core.algorithms.point_per_cell_processor import PointPerCellProcessor


class TestPointPerCellProcessor(unittest.TestCase):

    def setUp(self):
        """
        Setup method to initialize the environment for each test.

        Loads necessary layers from the 'test_data/study_area' directory.
        """
        # Get the working directory of the current test file
        self.test_file_dir = Path(__file__).parent

        # Define paths to the test data directory and GeoPackage
        self.test_data_dir = os.path.join(self.test_file_dir, "test_data", "study_area")
        self.gpkg_path = os.path.join(self.test_data_dir, "study_area.gpkg")

        # Ensure the GeoPackage exists for testing
        self.assertTrue(
            os.path.exists(self.gpkg_path), "Test GeoPackage does not exist"
        )

        # Define the path to the points layer (a shapefile or another supported format)
        points_layer_dir = os.path.join(
            self.test_file_dir, "test_data", "points", "points.shp"
        )

        # Load the points layer and grid layer from the GeoPackage
        self.points_layer = QgsVectorLayer(points_layer_dir, "points_layer", "ogr")
        self.assertTrue(self.points_layer.isValid(), "Points layer is invalid")

        self.grid_layer = QgsVectorLayer(
            f"{self.gpkg_path}|layername=study_area_grid", "study_area_grid", "ogr"
        )
        self.assertTrue(self.grid_layer.isValid(), "Grid layer is invalid")

        if self.points_layer.crs().authid() != self.grid_layer.crs().authid():
            # Reproject points_layer to match the grid_layer CRS
            params = {
                "INPUT": self.points_layer,
                "TARGET_CRS": self.grid_layer.crs(),
                "OUTPUT": "memory:",  # Output to an in-memory layer
            }

            result = processing.run("native:reprojectlayer", params)
            self.points_layer = result["OUTPUT"]

        # Initialize the processor
        self.processor = PointPerCellProcessor(
            self.points_layer, str(self.test_data_dir), str(self.gpkg_path)
        )

    def test_select_features(self):
        """
        Test the _select_features method for selecting points intersecting an area.
        """
        # Define a sample area geometry for testing (a simple bounding box for instance)
        extent = self.grid_layer.extent()
        bbox_geom = QgsGeometry.fromRect(extent)

        # Call the function to select features
        selected_layer = self.processor._select_features(
            self.points_layer, bbox_geom, "test_area_points"
        )

        # Assert that the output is a valid layer
        self.assertTrue(
            selected_layer.isValid(), "The selected features layer is invalid"
        )

        # Check that some features are selected
        selected_features = [f for f in selected_layer.getFeatures()]
        self.assertGreater(len(selected_features), 0, "No features were selected")

    def test_final_output_vrt(self):
        """
        Test the final output VRT after processing all areas.
        """
        # Run the full processing pipeline
        self.processor.process_areas()

        # Check if the final VRT file exists in the working directory
        vrt_output_path = os.path.join(self.test_data_dir, "combined_rasters.vrt")
        self.assertTrue(
            os.path.exists(vrt_output_path), "The final VRT output was not created"
        )

        file_size = os.path.getsize(vrt_output_path)
        self.assertGreater(file_size, 0, "The VRT file is empty")


if __name__ == "__main__":
    unittest.main()
