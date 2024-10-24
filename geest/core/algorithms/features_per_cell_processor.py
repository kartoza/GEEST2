from qgis.core import (
    edit,
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsCoordinateTransformContext,
    QgsFeature,
    QgsFeatureRequest,
    QgsFields,
    QgsField,
    QgsGeometry,
    QgsMessageLog,
    QgsProcessingException,
    QgsProcessingFeedback,
    QgsProject,
    QgsRasterLayer,
    QgsSpatialIndex,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)
import processing
from qgis.PyQt.QtCore import QVariant
from .area_iterator import AreaIterator
from typing import List
import os


class FeaturesPerCellProcessor:
    """
    A class to process spatial areas and perform spatial analysis using QGIS API.

    This class iterates over areas (polygons) and corresponding bounding boxes within a GeoPackage.
    For each area, it performs spatial operations on the input layer representing pedestrian or other feature-based data,
    and a grid layer from the same GeoPackage. The results are processed and rasterized.

    The following steps are performed for each area:

    1. Reproject the features layer to match the CRS of the grid layer.
    2. Select features (from a reprojected features layer) that intersect with the current area.
    3. Select grid cells (from the `study_area_grid` layer in the GeoPackage) that intersect with the features, ensuring no duplicates.
    4. Assign values to the grid cells based on the number of intersecting features:
        - A value of 3 if the grid cell intersects only one feature.
        - A value of 5 if the grid cell intersects more than one feature.
    5. Rasterize the grid cells, using their assigned values to create a raster for each area.
    6. Convert the resulting raster to byte format to minimize space usage.
    7. After processing all areas, combine the resulting byte rasters into a single VRT file.

    Attributes:
        output_prefix (str): Prefix to be used for naming output files. Based on the layer ID.
        gpkg_path (str): Path to the GeoPackage containing the study areas, bounding boxes, and grid.
        features_layer (QgsVectorLayer): A layer representing pedestrian crossings or other feature-based data.
        workflow_directory (str): Directory where temporary and output files will be stored.
        grid_layer (QgsVectorLayer): A grid layer (study_area_grid) loaded from the GeoPackage.

    Example:
        ```python
        processor = FeaturesPerCellProcessor(features_layer, '/path/to/workflow_directory', '/path/to/your/geopackage.gpkg')
        processor.process_areas()
        ```
    """

    def __init__(
        self,
        output_prefix: str,
        features_layer: QgsVectorLayer,
        workflow_directory: str,
        gpkg_path: str,
    ) -> None:
        """
        Initialize the FeaturesPerCellProcessor with the features layer, working directory, and the GeoPackage path.

        Args:
            features_layer (QgsVectorLayer): The input feature layer representing features like pedestrian crossings.
            workflow_directory (str): Directory where temporary and final output files will be stored.
            gpkg_path (str): Path to the GeoPackage file containing the study areas, bounding boxes, and grid layer.
        """
        QgsMessageLog.logMessage(
            "Features per Cell Processor Initialising", tag="Geest", level=Qgis.Info
        )
        self.output_prefix = output_prefix
        self.features_layer = features_layer
        self.workflow_directory = workflow_directory
        self.gpkg_path = gpkg_path  # top-level folder where the GeoPackage is stored

        # Load the grid layer from the GeoPackage
        self.grid_layer = QgsVectorLayer(
            f"{self.gpkg_path}|layername=study_area_grid", "study_area_grid", "ogr"
        )
        if not self.grid_layer.isValid():
            raise QgsProcessingException(
                f"Failed to load 'study_area_grid' layer from the GeoPackage at {self.gpkg_path}"
            )
        if not self.features_layer.isValid():
            raise QgsProcessingException(
                f"Failed to load features layer for Features per Cell Processor at {self.features_layer.source()}"
            )
        QgsMessageLog.logMessage(
            "Features per Cell Processor Initialised", tag="Geest", level=Qgis.Info
        )

    def process_areas(self) -> None:
        """
        Main function to iterate over areas from the GeoPackage and perform the analysis for each area.

        This function processes areas (defined by polygons and bounding boxes) from the GeoPackage using
        the provided input layers (features, grid). It applies the steps of selecting intersecting
        features, assigning values to grid cells, rasterizing the grid, in byte format, and finally
        combining the rasters into a VRT.

        Raises:
            QgsProcessingException: If any processing step fails during the execution.

        Returns:
            str: The file path to the VRT file containing the combined rasters

        """
        QgsMessageLog.logMessage(
            "Features per Cell Process Areas Started", tag="Geest", level=Qgis.Info
        )
        total_features = self.features_layer.featureCount()
        QgsMessageLog.logMessage(
            f"Features layer loaded with {total_features} features.",
            tag="Geest",
            level=Qgis.Info,
        )
        # Step 1: Reproject the features layer to match the CRS of the grid layer
        reprojected_features_layer = self._reproject_layer(
            self.features_layer, self.grid_layer.crs()
        )
        total_features = reprojected_features_layer.featureCount()
        QgsMessageLog.logMessage(
            f"Reprojected features layer loaded with {total_features} features.",
            tag="Geest",
            level=Qgis.Info,
        )

        feedback = QgsProcessingFeedback()
        area_iterator = AreaIterator(
            self.gpkg_path
        )  # Use the class-level GeoPackage path

        # Iterate over areas and perform the analysis for each
        for index, (current_area, current_bbox, progress) in enumerate(area_iterator):
            feedback.pushInfo(
                f"Processing area {index + 1} with progress {progress:.2f}%"
            )

            # Step 2: Select features that intersect with the current area and store in a temporary layer
            area_features = self._select_features(
                reprojected_features_layer,
                current_area,
                f"{self.output_prefix}_area_features_{index+1}",
            )
            area_features_count = area_features.featureCount()
            QgsMessageLog.logMessage(
                f"Features layer for area {index+1} loaded with {area_features_count} features.",
                tag="Geest",
                level=Qgis.Info,
            )
            # Step 3: Select grid cells that intersect with features
            area_grid = self._select_grid_cells(self.grid_layer, area_features)

            # Step 4: Assign values to grid cells
            grid = self._assign_values_to_grid(area_grid)

            # Step 5: Rasterize the grid layer using the assigned values
            raster_output = self._rasterize_grid(grid, current_bbox, index)

        # Step 7: Combine the resulting byte rasters into a single VRT
        vrt_filepath = self._combine_rasters_to_vrt(index + 1)
        return vrt_filepath

    def _reproject_layer(
        self, layer: QgsVectorLayer, target_crs: QgsCoordinateReferenceSystem
    ) -> QgsVectorLayer:
        """
        Reproject the given layer to the target CRS and save the reprojected layer to a new GeoPackage, writing features
        to disk as they are processed to avoid memory overflow.

        Args:
            layer (QgsVectorLayer): The input layer to be reprojected.
            target_crs (QgsCoordinateReferenceSystem): The target CRS for the reprojection.

        Returns:
            QgsVectorLayer: A new layer that has been reprojected and saved to the working directory GeoPackage.
        """
        QgsMessageLog.logMessage(
            f"Reprojecting {layer.name()} to {target_crs.authid()}",
            tag="Geest",
            level=Qgis.Info,
        )

        # Define the output GPKG path
        output_layer_name = f"{self.output_prefix}_{layer.name()}_reprojected"
        output_gpkg_path = os.path.join(
            self.workflow_directory, f"{self.output_prefix}_reprojected_layers.gpkg"
        )

        # Remove the GeoPackage if it already exists
        if os.path.exists(output_gpkg_path):
            os.remove(output_gpkg_path)

        # Get the WKB type of the input layer
        geometry_type = layer.wkbType()

        # Create the output layer with the correct CRS
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.fileEncoding = "UTF-8"
        options.layerName = output_layer_name

        writer = QgsVectorFileWriter.create(
            fileName=output_gpkg_path,
            fields=layer.fields(),
            geometryType=geometry_type,
            srs=target_crs,
            transformContext=QgsCoordinateTransformContext(),
            options=options,
        )
        if writer.hasError() != QgsVectorFileWriter.NoError:
            QgsMessageLog.logMessage(
                f"Error when creating layer: {writer.errorMessage()}",
                tag="Geest",
                level=Qgis.Critical,
            )
            raise QgsProcessingException(
                f"Failed to create output layer: {writer.errorMessage()}"
            )

        # Set up the transformation object
        transform = QgsCoordinateTransform(
            layer.crs(), target_crs, QgsProject.instance()
        )
        QgsMessageLog.logMessage(
            f"Transforming from {layer.crs().authid()} to {target_crs.authid()}",
            tag="Geest",
            level=Qgis.Info,
        )

        # Iterate through features, reproject their geometries, and write them directly to disk
        for feature in layer.getFeatures():
            geom = QgsGeometry(feature.geometry())  # Make a copy of the geometry
            geom.transform(transform)  # Transform the copied geometry

            new_feature = QgsFeature(feature)  # Make a copy of the feature
            new_feature.setGeometry(
                geom
            )  # Set the reprojected geometry to the new feature

            # Write the feature directly to disk
            writer.addFeature(new_feature)

        del writer  # Finalize the writer and close the file

        QgsMessageLog.logMessage(
            f"Reprojection of {layer.name()} completed. Saved to {output_gpkg_path}",
            tag="Geest",
            level=Qgis.Info,
        )

        # Return the reprojected layer loaded from the GPKG
        reprojected_layer = QgsVectorLayer(
            f"{output_gpkg_path}|layername={output_layer_name}",
            output_layer_name,
            "ogr",
        )
        if not reprojected_layer.isValid():
            QgsMessageLog.logMessage(
                f"Failed to load reprojected layer from {output_gpkg_path}.",
                tag="Geest",
                level=Qgis.Critical,
            )
            raise QgsProcessingException(
                "Reprojected layer is invalid or the CRS is not recognized."
            )

        return reprojected_layer

    def _select_features(
        self, layer: QgsVectorLayer, area_geom: QgsGeometry, output_name: str
    ) -> QgsVectorLayer:
        """
        Select features from the input layer that intersect with the given area geometry
        using the QGIS API. The selected features are stored in a temporary layer.

        Args:
            layer (QgsVectorLayer): The input layer to select features from (e.g., points, lines, polygons).
            area_geom (QgsGeometry): The current area geometry for which intersections are evaluated.
            output_name (str): A name for the output temporary layer to store selected features.

        Returns:
            QgsVectorLayer: A new temporary layer containing features that intersect with the given area geometry.
        """
        QgsMessageLog.logMessage(
            "Features per Cell Select Features Started", tag="Geest", level=Qgis.Info
        )
        output_path = os.path.join(self.workflow_directory, f"{output_name}.shp")

        # Get the WKB type (geometry type) of the input layer (e.g., Point, LineString, Polygon)
        geometry_type = layer.wkbType()

        # Determine geometry type name based on input layer's geometry
        if QgsWkbTypes.geometryType(geometry_type) == QgsWkbTypes.PointGeometry:
            geometry_name = "Point"
        elif QgsWkbTypes.geometryType(geometry_type) == QgsWkbTypes.LineGeometry:
            geometry_name = "LineString"
        else:
            raise QgsProcessingException(f"Unsupported geometry type: {geometry_type}")

        # Create a memory layer to store the selected features with the correct geometry type
        crs = layer.crs().authid()
        temp_layer = QgsVectorLayer(f"{geometry_name}?crs={crs}", output_name, "memory")
        temp_layer_data = temp_layer.dataProvider()

        # Add fields to the temporary layer
        temp_layer_data.addAttributes(layer.fields())
        temp_layer.updateFields()

        # Iterate through features and select those that intersect with the area
        request = QgsFeatureRequest(area_geom.boundingBox()).setFilterRect(
            area_geom.boundingBox()
        )
        selected_features = [
            feat
            for feat in layer.getFeatures(request)
            if feat.geometry().intersects(area_geom)
        ]
        temp_layer_data.addFeatures(selected_features)

        QgsMessageLog.logMessage(
            f"Features per Cell writing {len(selected_features)} features",
            tag="Geest",
            level=Qgis.Info,
        )

        # Save the memory layer to a file for persistence
        QgsVectorFileWriter.writeAsVectorFormat(
            temp_layer, output_path, "UTF-8", temp_layer.crs(), "ESRI Shapefile"
        )

        QgsMessageLog.logMessage(
            "Features per Cell Select Features Ending", tag="Geest", level=Qgis.Info
        )

        return QgsVectorLayer(output_path, output_name, "ogr")

    def _select_grid_cells(
        self,
        grid_layer: QgsVectorLayer,
        features_layer: QgsVectorLayer,
    ) -> QgsVectorLayer:
        """
        Select grid cells that intersect with features, count the number of intersecting features for each cell,
        and create a new grid layer with the count information. This supports features of any geometry type (points, lines, polygons).

        Args:
            grid_layer (QgsVectorLayer): The input grid layer containing polygon cells.
            features_layer (QgsVectorLayer): The input layer containing features (e.g., points, lines, polygons).

        Returns:
            QgsVectorLayer: A new layer with grid cells containing a count of intersecting features.
        """
        QgsMessageLog.logMessage(
            "Selecting grid cells that intersect with features and counting intersections.",
            tag="Geest",
            level=Qgis.Info,
        )

        # Create a spatial index for the grid layer to optimize intersection queries
        grid_index = QgsSpatialIndex(grid_layer.getFeatures())

        # Create a dictionary to hold the count of intersecting features for each grid cell ID
        grid_feature_counts = {}

        # Iterate over each feature and use the spatial index to find the intersecting grid cells
        for feature in features_layer.getFeatures():
            feature_geom = feature.geometry()

            # Use bounding box only for point geometries; otherwise, use the actual geometry for intersection checks
            if feature_geom.isEmpty():
                continue

            if feature_geom.type() == QgsWkbTypes.PointGeometry:
                # For point geometries, use bounding box to find intersecting grid cells
                intersecting_ids = grid_index.intersects(feature_geom.boundingBox())
            else:
                # For line and polygon geometries, check actual geometry against grid cells
                intersecting_ids = grid_index.intersects(
                    feature_geom.boundingBox()
                )  # Initial rough filter
                QgsMessageLog.logMessage(
                    f"{len(intersecting_ids)} rough intersections found.",
                    tag="Geest",
                    level=Qgis.Info,
                )
                intersecting_ids = [
                    grid_id
                    for grid_id in intersecting_ids
                    if grid_layer.getFeature(grid_id)
                    .geometry()
                    .intersects(feature_geom)
                ]
                QgsMessageLog.logMessage(
                    f"{len(intersecting_ids)} refined intersections found.",
                    tag="Geest",
                    level=Qgis.Info,
                )

            # Iterate over the intersecting grid cell IDs and count intersections
            for grid_id in intersecting_ids:
                if grid_id in grid_feature_counts:
                    grid_feature_counts[grid_id] += 1
                else:
                    grid_feature_counts[grid_id] = 1

        QgsMessageLog.logMessage(
            f"{len(grid_feature_counts)} intersections found.",
            tag="Geest",
            level=Qgis.Info,
        )

        # Create a new layer to store the grid cells with feature counts
        output_path = os.path.join(
            self.workflow_directory, f"{self.output_prefix}_grid_with_counts.gpkg"
        )
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.fileEncoding = "UTF-8"
        options.layerName = "grid_with_feature_counts"

        # Define fields for the new layer: only 'id' and 'intersecting_features'
        fields = QgsFields()
        fields.append(QgsField("id", QVariant.Int))
        fields.append(QgsField("intersecting_features", QVariant.Int))
        # Will be used to hold the scaled value from 0-5
        fields.append(QgsField("value", QVariant.Int))

        writer = QgsVectorFileWriter.create(
            fileName=output_path,
            fields=fields,
            geometryType=grid_layer.wkbType(),
            srs=grid_layer.crs(),
            transformContext=QgsCoordinateTransformContext(),
            options=options,
        )
        if writer.hasError() != QgsVectorFileWriter.NoError:
            raise QgsProcessingException(
                f"Failed to create output layer: {writer.errorMessage()}"
            )

        # Select only grid cells based on the keys (grid IDs) in the grid_feature_counts dictionary
        request = QgsFeatureRequest().setFilterFids(list(grid_feature_counts.keys()))
        QgsMessageLog.logMessage(
            f"Looping over {len(grid_feature_counts.keys())} grid polygons",
            "Geest",
            Qgis.Info,
        )
        counter = 0
        for grid_feature in grid_layer.getFeatures(request):
            QgsMessageLog.logMessage(f"Writing Feature #{counter}", "Geest", Qgis.Info)
            counter += 1
            new_feature = QgsFeature()
            new_feature.setGeometry(
                grid_feature.geometry()
            )  # Use the original geometry

            # Set the 'id' and 'intersecting_features' attributes
            new_feature.setFields(fields)
            new_feature.setAttribute("id", grid_feature.id())  # Set the grid cell ID
            new_feature.setAttribute(
                "intersecting_features", grid_feature_counts[grid_feature.id()]
            )
            new_feature.setAttribute("value", None)

            # Write the feature to the new layer
            writer.addFeature(new_feature)

        del writer  # Finalize the writer and close the file

        QgsMessageLog.logMessage(
            f"Grid cells with feature counts saved to {output_path}",
            tag="Geest",
            level=Qgis.Info,
        )

        return QgsVectorLayer(
            f"{output_path}|layername=grid_with_feature_counts",
            "grid_with_feature_counts",
            "ogr",
        )

    def _assign_values_to_grid(self, grid_layer: QgsVectorLayer) -> QgsVectorLayer:
        """
        Assign values to grid cells based on the number of intersecting features.

        A value of 3 is assigned to cells that intersect with one feature, and a value of 5 is assigned to
        cells that intersect with more than one feature.

        Args:
            grid_layer (QgsVectorLayer): The input grid layer containing polygon cells.

        Returns:
            QgsVectorLayer: The grid layer with values assigned to the 'value' field.
        """
        with edit(grid_layer):
            for feature in grid_layer.getFeatures():
                intersecting_features = feature["intersecting_features"]
                if intersecting_features == 1:
                    feature["value"] = 3
                elif intersecting_features > 1:
                    feature["value"] = 5
                grid_layer.updateFeature(feature)
        return grid_layer

    def _rasterize_grid(
        self, grid_layer: QgsVectorLayer, bbox: QgsGeometry, index: int
    ) -> str:
        """

        ⭐️🚩⭐️ Warning this is not DRY - almost same function exists in study_area.py

        Rasterize the grid layer based on the 'value' attribute.

        Args:
            grid_layer (QgsVectorLayer): The grid layer to rasterize.
            bbox (QgsGeometry): The bounding box for the raster extents.
            index (int): The current index used for naming the output raster.

        Returns:
            str: The file path to the rasterized output.
        """
        QgsMessageLog.logMessage("--- Rasterizing grid", tag="Geest", level=Qgis.Info)
        QgsMessageLog.logMessage(f"--- bbox {bbox}", tag="Geest", level=Qgis.Info)
        QgsMessageLog.logMessage(f"--- index {index}", tag="Geest", level=Qgis.Info)

        output_path = os.path.join(
            self.workflow_directory,
            f"{self.output_prefix}_features_per_cell_output_{index}.tif",
        )

        # Ensure resolution parameters are properly formatted as float values
        x_res = 100.0  # 100m pixel size in X direction
        y_res = 100.0  # 100m pixel size in Y direction
        bbox = bbox.boundingBox()
        # Define rasterization parameters for the temporary layer
        params = {
            "INPUT": grid_layer,
            "FIELD": "value",
            "BURN": -9999,
            "USE_Z": False,
            "UNITS": 1,
            "WIDTH": x_res,
            "HEIGHT": y_res,
            "EXTENT": f"{bbox.xMinimum()},{bbox.xMaximum()},"
            f"{bbox.yMinimum()},{bbox.yMaximum()}",  # Extent of the aligned bbox
            "NODATA": -9999,
            "OPTIONS": "",
            #'OPTIONS':'COMPRESS=DEFLATE|PREDICTOR=2|ZLEVEL=9',
            "DATA_TYPE": 0,  # byte
            "INIT": None,
            "INVERT": False,
            "EXTRA": "",
            "OUTPUT": output_path,
        }

        processing.run("gdal:rasterize", params)
        QgsMessageLog.logMessage(
            f"Created grid for Features Per Cell: {output_path}",
            tag="Geest",
            level=Qgis.Info,
        )
        return output_path

    def _combine_rasters_to_vrt(self, num_rasters: int) -> None:
        """
        Combine all the rasters into a single VRT file.

        Args:
            num_rasters (int): The number of rasters to combine into a VRT.

        Returns:
            vrtpath (str): The file path to the VRT file.
        """
        raster_files = []
        for i in range(num_rasters):
            raster_path = os.path.join(
                self.workflow_directory,
                f"{self.output_prefix}_features_per_cell_output_{i}.tif",
            )
            if os.path.exists(raster_path) and QgsRasterLayer(raster_path).isValid():
                raster_files.append(raster_path)
            else:
                QgsMessageLog.logMessage(
                    f"Skipping invalid or non-existent raster: {raster_path}",
                    tag="Geest",
                    level=Qgis.Warning,
                )

        if not raster_files:
            QgsMessageLog.logMessage(
                "No valid raster masks found to combine into VRT.",
                tag="Geest",
                level=Qgis.Warning,
            )
            return
        vrt_filepath = os.path.join(
            self.workflow_directory,
            f"{self.output_prefix}_features_per_cell_output_combined.vrt",
        )

        QgsMessageLog.logMessage(
            f"Creating VRT of masks '{vrt_filepath}' layer to the map.",
            tag="Geest",
            level=Qgis.Info,
        )

        if not raster_files:
            QgsMessageLog.logMessage(
                "No raster masks found to combine into VRT.",
                tag="Geest",
                level=Qgis.Warning,
            )
            return

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
        vrt_layer = QgsRasterLayer(vrt_filepath, f"{self.output_prefix}_combined VRT")

        if vrt_layer.isValid():
            QgsProject.instance().addMapLayer(vrt_layer)
            QgsMessageLog.logMessage(
                "Added VRT layer to the map.", tag="Geest", level=Qgis.Info
            )
        else:
            QgsMessageLog.logMessage(
                "Failed to add VRT layer to the map.", tag="Geest", level=Qgis.Critical
            )
        return vrt_filepath
