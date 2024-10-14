import os
from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsGeometry,
    QgsVectorLayer,
    QgsField,
    QgsSpatialIndex,
    QgsProcessingFeedback,
)
import processing
from .utilities import GridAligner


class RasterPolygonGridScore:
    def __init__(
        self,
        country_boundary,
        pixel_size,
        working_dir,
        crs,
        input_polygons,
        output_path,
    ):
        self.country_boundary = country_boundary
        self.pixel_size = pixel_size
        self.working_dir = working_dir
        self.crs = crs
        self.input_polygons = input_polygons
        self.output_path = output_path
        # Initialize GridAligner with grid size
        self.grid_aligner = GridAligner(grid_size=100)

    def load_layers(self):
        """Load the grid and area layers from the Geopackage."""
        geopackage_path = os.path.join(
            self.working_dir, "study_area", "study_area.gpkg"
        )
        if not os.path.exists(geopackage_path):
            raise ValueError(f"Geopackage not found at {geopackage_path}.")

        grid_layer = QgsVectorLayer(
            f"{geopackage_path}|layername=study_area_grid", "merged_grid", "ogr"
        )
        # area_layer = QgsVectorLayer(
        #    f"{geopackage_path}|layername=study_area_polygons",
        #    "study_area_polygons",
        #    "ogr",
        # )

        return grid_layer

    def align_grid_bbox(self, area_geometry: QgsGeometry, grid_layer: QgsVectorLayer):
        """Align the bounding box of the grid with the country boundary."""
        return self.grid_aligner.align_bbox(
            area_geometry.boundingBox(), grid_layer.extent()
        )

    def extract_by_location(self, grid_layer: QgsVectorLayer):
        """Extract the polygons that intersect with grid cells."""
        return processing.run(
            "native:extractbylocation",
            {
                "INPUT": grid_layer,
                "PREDICATE": [0],
                "INTERSECT": self.input_polygons,
                "OUTPUT": "TEMPORARY_OUTPUT",
            },
            feedback=QgsProcessingFeedback(),
        )["OUTPUT"]

    def reproject_polygons(self):
        """Reproject the input polygons if needed."""
        if self.input_polygons.crs() != self.crs:
            self.input_polygons = processing.run(
                "native:reprojectlayer",
                {
                    "INPUT": self.input_polygons,
                    "TARGET_CRS": self.crs,
                    "OUTPUT": "memory:",
                },
                feedback=QgsProcessingFeedback(),
            )["OUTPUT"]

    def calculate_grid_scores(self, grid_layer: QgsVectorLayer):
        """Calculate the score for each grid cell based on intersecting polygons."""
        provider = grid_layer.dataProvider()
        field_name = "poly_score"

        # Add score field if it doesn't exist
        if not grid_layer.fields().indexFromName(field_name) >= 0:
            provider.addAttributes([QgsField(field_name, QVariant.Int)])
            grid_layer.updateFields()

        polygon_index = QgsSpatialIndex(self.input_polygons.getFeatures())
        reclass_vals = {}

        for grid_feat in grid_layer.getFeatures():
            grid_geom = grid_feat.geometry()
            intersecting_ids = polygon_index.intersects(grid_geom.boundingBox())

            unique_intersections = set()
            max_perimeter = 0

            for poly_id in intersecting_ids:
                poly_feat = self.input_polygons.getFeature(poly_id)
                poly_geom = poly_feat.geometry()

                if grid_geom.intersects(poly_geom):
                    unique_intersections.add(poly_id)
                    perimeter = poly_geom.length()

                    # Update max_perimeter if this perimeter is larger
                    if perimeter > max_perimeter:
                        max_perimeter = perimeter

            # Assign reclassification value based on the maximum perimeter
            if max_perimeter > 1000:
                reclass_val = 1  # Very large blocks
            elif 751 <= max_perimeter <= 1000:
                reclass_val = 2  # Large blocks
            elif 501 <= max_perimeter <= 750:
                reclass_val = 3  # Moderate blocks
            elif 251 <= max_perimeter <= 500:
                reclass_val = 4  # Small blocks
            elif 0 < max_perimeter <= 250:
                reclass_val = 5  # Very small blocks
            else:
                reclass_val = 0  # No intersection

            reclass_vals[grid_feat.id()] = reclass_val

        # Apply score values to the grid
        grid_layer.startEditing()
        for grid_feat in grid_layer.getFeatures():
            grid_layer.changeAttributeValue(
                grid_feat.id(),
                provider.fieldNameIndex(field_name),
                reclass_vals[grid_feat.id()],
            )
        grid_layer.commitChanges()

    def merge_and_rasterize(
        self, grid_layer: QgsVectorLayer, aligned_bbox: QgsGeometry
    ):
        """Merge vector layers and rasterize the result."""
        raster_output_path = "TEMPORARY_OUTPUT"

        # Merge the output vector layers
        merge = processing.run(
            "native:mergevectorlayers",
            {"LAYERS": [grid_layer], "CRS": self.crs, "OUTPUT": "TEMPORARY_OUTPUT"},
            feedback=QgsProcessingFeedback(),
        )["OUTPUT"]

        xmin, xmax, ymin, ymax = (
            aligned_bbox.xMinimum(),
            aligned_bbox.xMaximum(),
            aligned_bbox.yMinimum(),
            aligned_bbox.yMaximum(),
        )  # Extent of the aligned bbox

        # Rasterize the clipped grid layer to generate the raster
        rasterize_params = {
            "INPUT": merge,
            "FIELD": "poly_score",
            "BURN": 0,
            "USE_Z": False,
            "UNITS": 1,
            "WIDTH": self.pixel_size,
            "HEIGHT": self.pixel_size,
            "EXTENT": f"{xmin},{ymin},{xmax},{ymax}",
            "NODATA": None,
            "OPTIONS": "",
            "DATA_TYPE": 5,  # Use Int32 for scores
            "OUTPUT": raster_output_path,
        }

        return processing.run(
            "gdal:rasterize", rasterize_params, feedback=QgsProcessingFeedback()
        )["OUTPUT"]

    def clip_raster(self, raster_output):
        """Clip the raster to the country boundary."""
        return processing.run(
            "gdal:cliprasterbymasklayer",
            {
                "INPUT": raster_output,
                "MASK": self.country_boundary,
                "NODATA": -9999,
                "CROP_TO_CUTLINE": True,
                "OUTPUT": self.output_path,
            },
            feedback=QgsProcessingFeedback(),
        )

    def raster_polygon_grid_score(self):
        """Main function to orchestrate the entire raster generation process."""
        grid_layer = self.load_layers()

        geometries = [feature.geometry() for feature in grid_layer.getFeatures()]
        area_geometry = QgsGeometry.unaryUnion(geometries)

        aligned_bbox = self.align_grid_bbox(area_geometry, grid_layer)

        self.reproject_polygons()

        grid_layer = self.extract_by_location(grid_layer)
        self.calculate_grid_scores(grid_layer)

        raster_output = self.merge_and_rasterize(grid_layer, aligned_bbox)
        self.clip_raster(raster_output)
