import os
import unittest
from qgis.core import QgsVectorLayer
from qgis.PyQt.QtCore import QEventLoop
from geest.core.multibuffer_point import MultiBufferCreator


class TestMultiBufferCreator(unittest.TestCase):

    def setUp(self):
        """
        Set up the test environment, including paths to input data and output directories.
        """
        # Paths for test data
        self.working_dir = os.path.dirname(__file__)
        self.test_data_dir = os.path.join(self.working_dir, "test_data")
        self.input_file = os.path.join(self.test_data_dir, "points", "points.shp")
        self.output_file = os.path.join(self.working_dir, "output", "output.shp")

        # Ensure the input file exists
        self.assertTrue(os.path.exists(self.input_file), "Input file does not exist")

        # Load the point layer from the test data
        self.point_layer = QgsVectorLayer(self.input_file, "Test Points", "ogr")
        self.assertTrue(self.point_layer.isValid(), "Failed to load the point layer")

        # Initialize MultiBufferCreator with test distances
        self.distances = [500, 1000, 1500, 2000, 2500]
        self.creator = MultiBufferCreator(self.distances)

    def test_create_multibuffers(self):
        """
        Test the create_multibuffers function with real input data.
        """
        # Determine the number of expected requests based on subsets of points
        subset_size = self.creator.subset_size
        total_features = self.point_layer.featureCount()
        self.remaining_requests = (total_features + subset_size - 1) // subset_size

        # Run the buffer creation process
        self.creator.create_multibuffers(
            self.point_layer,
            self.output_file,
            mode="foot-walking",
            measurement="distance",
            crs="EPSG:4326",
        )

        # Now all requests are done, check the final output layer
        output_layer = QgsVectorLayer(self.output_file, "Output Buffers", "ogr")
        self.assertTrue(output_layer.isValid(), "Failed to load the output layer")

        # Check that the output contains features
        features = list(output_layer.getFeatures())
        self.assertGreater(
            len(features), 0, "No features were created in the output layer"
        )


if __name__ == "__main__":
    unittest.main()
