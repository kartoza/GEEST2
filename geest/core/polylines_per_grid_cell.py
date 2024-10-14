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


class RasterPolylineGridScore:
    def __init__(
        self,
        country_boundary,
        pixel_size,
        working_dir,
        crs,
        input_polylines,
        output_path,
    ):
        self.country_boundary = country_boundary
        self.pixel_size = pixel_size
        self.working_dir = working_dir
        self.crs = crs
        self.input_polylines = input_polylines
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
        aligned_bbox = self.grid_aligner.align_bbox(
            area_geometry.boundingBox(), grid_layer.extent()
        )
        return aligned_bbox

    def extract_by_location(self, grid_layer: QgsVectorLayer):
        """Extract the polylines that intersect with grid cells."""
        grid_output = processing.run(
            "native:extractbylocation",
            {
                "INPUT": grid_layer,
                "PREDICATE": [0],
                "INTERSECT": self.input_polylines,
                "OUTPUT": "TEMPORARY_OUTPUT",
            },
            feedback=QgsProcessingFeedback(),
        )["OUTPUT"]
        return grid_output

    def reproject_polylines(self):
        """Reproject the input polylines if needed."""
        if self.input_polylines.crs() != self.crs:
            self.input_polylines = processing.run(
                "native:reprojectlayer",
                {
                    "INPUT": self.input_polylines,
                    "TARGET_CRS": self.crs,
                    "OUTPUT": "memory:",
                },
                feedback=QgsProcessingFeedback(),
            )["OUTPUT"]

    def calculate_grid_scores(self, grid_layer: QgsVectorLayer):
        """Calculate the score for each grid cell based on intersecting polylines."""
        provider = grid_layer.dataProvider()
        field_name = "line_score"

        # Add score field if it doesn't exist
        if not grid_layer.fields().indexFromName(field_name) >= 0:
            provider.addAttributes([QgsField(field_name, QVariant.Int)])
            grid_layer.updateFields()

        polyline_index = QgsSpatialIndex(self.input_polylines.getFeatures())
        reclass_vals = {}

        for grid_feat in grid_layer.getFeatures():
            grid_geom = grid_feat.geometry()
            intersecting_ids = polyline_index.intersects(grid_geom.boundingBox())

            unique_intersections = set()
            for line_id in intersecting_ids:
                line_feat = self.input_polylines.getFeature(line_id)
                line_geom = line_feat.geometry()
                if grid_geom.intersects(line_geom):
                    unique_intersections.add(line_id)

            num_polylines = len(unique_intersections)
            reclass_val = 5 if num_polylines >= 2 else 3 if num_polylines == 1 else 0
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

    def rasterize_grid(self, grid_layer: QgsVectorLayer, aligned_bbox: QgsGeometry):
        """Rasterize the grid layer to create a raster output."""
        xmin, xmax, ymin, ymax = (
            aligned_bbox.xMinimum(),
            aligned_bbox.xMaximum(),
            aligned_bbox.yMinimum(),
            aligned_bbox.yMaximum(),
        )

        rasterize_params = {
            "INPUT": grid_layer,
            "FIELD": "line_score",
            "BURN": 0,
            "USE_Z": False,
            "UNITS": 1,
            "WIDTH": self.pixel_size,
            "HEIGHT": self.pixel_size,
            "EXTENT": f"{xmin},{ymin},{xmax},{ymax}",
            "NODATA": None,
            "OPTIONS": "",
            "DATA_TYPE": 5,  # Use Int32 for scores
            "OUTPUT": "TEMPORARY_OUTPUT",
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

    def raster_polyline_grid_score(self):
        """Main function to orchestrate the entire raster generation process."""
        grid_layer = self.load_layers()

        geometries = [feature.geometry() for feature in grid_layer.getFeatures()]
        area_geometry = QgsGeometry.unaryUnion(geometries)

        aligned_bbox = self.align_grid_bbox(area_geometry, grid_layer)

        self.reproject_polylines()

        grid_layer = self.extract_by_location(grid_layer)
        self.calculate_grid_scores(grid_layer)

        raster_output = self.rasterize_grid(grid_layer, aligned_bbox)
        self.clip_raster(raster_output)
