import os
import re
import glob
import traceback
import datetime

from typing import List, Optional
from qgis.core import (
    QgsTask,
    QgsRectangle,
    QgsFeedback,
    QgsFeature,
    QgsGeometry,
    QgsField,
    QgsPointXY,
    QgsProcessingContext,
    QgsCoordinateTransform,
    QgsCoordinateReferenceSystem,
    QgsRasterLayer,
    QgsSpatialIndex,
    QgsWkbTypes,
    QgsVectorLayer,
    QgsVectorFileWriter,
    QgsFields,
    QgsCoordinateTransformContext,
    QgsWkbTypes,
    Qgis,
)
from qgis.PyQt.QtCore import QVariant
import processing  # QGIS processing toolbox
from geest.utilities import log_message


class StudyAreaProcessingTask(QgsTask):
    """
    A QgsTask subclass for processing study area features.

    It works through the (multi)part geometries in the input layer, creating bounding boxes and masks.
    The masks are stored as individual tif files and then a vrt file is created to combine them.
    The grids are in two forms - the entire bounding box and the individual parts.
    The grids are aligned to cell_size_m intervals and saved as vector features in a GeoPackage.
    Any invalid geometries are discarded, and fixed geometries are processed.

    Args:
        QgsTask (_type_): _description_

    Returns:
        _type_: _description_
    """

    def __init__(
        self,
        layer: QgsVectorLayer,
        field_name: str,
        cell_size_m: float,
        working_dir: str,
        mode: str = "raster",
        crs: Optional[QgsCoordinateReferenceSystem] = None,
        context: QgsProcessingContext = None,
        feedback: QgsFeedback = None,
    ):
        """
        Initializes the StudyAreaProcessingTask.

        :param layer: The vector layer containing study area features.
        :param field_name: The name of the field containing area names.
        :param cell_size: The size of the grid cells in meters.
        :param working_dir: Directory path where outputs will be saved.
        :param mode: Processing mode, either 'vector' or 'raster'. Default is raster.
        :param crs: Optional CRS for the output CRS. If None, a UTM zone
                          is calculated based on layer extent or extent of selected features.
        :param context: QgsProcessingContext for the task. Default is None.
        :param feedback: QgsFeedback object for task cancelling. Default is None.
        """
        super().__init__("Study Area Preparation", QgsTask.CanCancel)
        self.feedback = feedback
        self.layer: QgsVectorLayer = layer
        self.field_name: str = field_name
        self.cell_size_m: float = cell_size_m
        self.working_dir: str = working_dir
        self.mode: str = mode
        self.context: QgsProcessingContext = context
        self.gpkg_path: str = os.path.join(
            self.working_dir, "study_area", "study_area.gpkg"
        )
        self.counter: int = 0
        # Remove the GeoPackage if it already exists to start with a clean state
        if os.path.exists(self.gpkg_path):
            try:
                os.remove(self.gpkg_path)
                log_message(
                    f"Existing GeoPackage removed: {self.gpkg_path}",
                    tag="Geest",
                    level=Qgis.Info,
                )
            except Exception as e:
                log_message(
                    f"Error removing existing GeoPackage: {e}",
                    tag="Geest",
                    level=Qgis.Critical,
                )

        self.create_study_area_directory(self.working_dir)

        # Determine the correct CRS and layer bounding box based on selected features
        selected_features = self.layer.selectedFeatures()
        self.layer_bbox = QgsRectangle()

        if selected_features:
            # Calculate bounding box based on selected features only
            self.layer_bbox: QgsRectangle = QgsRectangle()
            for feature in selected_features:
                self.layer_bbox.combineExtentWith(feature.geometry().boundingBox())
        else:
            # No features selected, use full layer extent
            self.layer_bbox: QgsRectangle = self.layer.extent()

        # Determine EPSG code based on provided input or calculated UTM zone
        if crs is None:
            self.epsg_code: int = self.calculate_utm_zone(self.layer_bbox)
            self.output_crs: QgsCoordinateReferenceSystem = (
                QgsCoordinateReferenceSystem(f"EPSG:{self.epsg_code}")
            )
        else:
            self.output_crs = crs

        log_message(
            f"Project CRS Set to: {self.output_crs.authid()}",
            tag="Geest",
            level=Qgis.Info,
        )
        # Reproject and align the transformed layer_bbox to a cell_size_m grid and output crs
        self.layer_bbox = self.grid_aligned_bbox(self.layer_bbox)

    def run(self) -> bool:
        """
        Runs the task in the background.
        """
        try:
            result = self.process_study_area()
            return result  # false if the task was canceled
        except Exception as e:
            log_message(f"Task failed: {e}", level=Qgis.Critical)
            # Print the traceback to the QgsMessageLog
            log_message(traceback.format_exc(), level=Qgis.Critical)
            # And write it to a text file called error.txt in the working directory
            with open(os.path.join(self.working_dir, "error.txt"), "w") as f:
                # first the date and time
                f.write(f"{datetime.datetime.now()}\n")
                # then the traceback
                f.write(traceback.format_exc())
            return False

    def finished(self, result: bool) -> None:
        """
        Called when the task completes successfully.
        """
        if result:
            log_message(
                "Study Area Processing completed successfully.",
                tag="Geest",
                level=Qgis.Info,
            )
        else:
            if self.feedback.isCanceled():
                log_message(
                    "Study Area Processing was canceled by the user.",
                    tag="Geest",
                    level=Qgis.Warning,
                )
            else:
                log_message(
                    "Study Area Processing encountered an error.",
                    tag="Geest",
                    level=Qgis.Critical,
                )

    def cancel(self) -> None:
        """
        Called when the task is canceled.
        """
        super().cancel()
        self.feedback.cancel()
        log_message("Study Area Processing was canceled.", level=Qgis.Warning)

    def process_study_area(self) -> None:
        """
        Processes each feature in the input layer, creating bounding boxes and grids.
        It handles the CRS transformation and calls appropriate processing functions based on geometry type.
        """
        # First, write the layer_bbox to the GeoPackage
        self.save_to_geopackage(
            layer_name="study_area_bbox",
            geom=QgsGeometry.fromRect(self.layer_bbox),
            area_name="Study Area Bounding Box",
        )

        # Initialize counters for tracking valid and invalid features
        invalid_feature_count = 0
        valid_feature_count = 0
        fixed_feature_count = 0

        # Process individual features
        selected_features = self.layer.selectedFeatures()
        # count how many features are selected
        total_features = len(selected_features)

        features = selected_features if selected_features else self.layer.getFeatures()

        for feature in features:
            if self.feedback.isCanceled():
                return False
            geom: QgsGeometry = feature.geometry()
            area_name: str = feature[self.field_name]
            normalized_name: str = re.sub(r"\s+", "_", area_name.lower())

            # Check for geometry validity
            if geom.isEmpty() or not geom.isGeosValid():
                log_message(
                    f"Feature ID {feature.id()} has an invalid geometry. Attempting to fix.",
                    tag="Geest",
                    level=Qgis.Warning,
                )

                # Try to fix the geometry
                fixed_geom = geom.makeValid()

                # Check if the fixed geometry is valid
                if fixed_geom.isEmpty() or not fixed_geom.isGeosValid():
                    invalid_feature_count += 1
                    log_message(
                        f"Feature ID {feature.id()} could not be fixed. Skipping.",
                        tag="Geest",
                        level=Qgis.Critical,
                    )
                    continue

                # Use the fixed geometry if it is valid
                geom = fixed_geom
                fixed_feature_count += 1
                log_message(
                    f"Feature ID {feature.id()} geometry fixed successfully.",
                    tag="Geest",
                    level=Qgis.Info,
                )

            # Process valid geometry
            try:
                valid_feature_count += 1
                if geom.isMultipart():
                    self.process_multipart_geometry(geom, normalized_name, area_name)
                else:
                    self.process_singlepart_geometry(geom, normalized_name, area_name)
            except Exception as e:
                # Log any unexpected errors during processing
                invalid_feature_count += 1
                log_message(
                    f"Error processing geometry for feature {feature.id()}: {e}",
                    tag="Geest",
                    level=Qgis.Critical,
                )

            # Update progress (for example, as percentage)
            progress = int((valid_feature_count / self.layer.featureCount()) * 100)
            self.setProgress(progress)

        # Log the count of valid, fixed, and invalid features processed
        log_message(
            f"Processing completed. Valid features: {valid_feature_count}, Fixed features: {fixed_feature_count}, Invalid features: {invalid_feature_count}",
            tag="Geest",
            level=Qgis.Info,
        )
        # Create and add the VRT of all generated raster masks if in raster mode
        if self.mode == "raster":
            self.create_raster_vrt()
        return True

    def process_singlepart_geometry(
        self, geom: QgsGeometry, normalized_name: str, area_name: str
    ) -> None:
        """
        Processes a singlepart geometry feature. Creates vector grids or raster masks based on mode.

        :param geom: Geometry of the feature.
        :param normalized_name: Name normalized for file storage.
        :param area_name: Name of the study area.
        """

        # Compute the aligned bounding box based on the transformed geometry
        # This will do the CRS transform too
        bbox: QgsRectangle = self.grid_aligned_bbox(geom.boundingBox())

        # Create a feature for the aligned bounding box
        # Always save the study area bounding boxes regardless of mode
        self.save_to_geopackage(
            layer_name="study_area_bboxes",
            geom=QgsGeometry.fromRect(bbox),
            area_name=normalized_name,
        )

        # Transform the geometry to the output CRS
        crs_src: QgsCoordinateReferenceSystem = self.layer.crs()
        transform: QgsCoordinateTransform = QgsCoordinateTransform(
            crs_src, self.output_crs, self.context.project()
        )
        if crs_src != self.output_crs:
            geom.transform(transform)

        # Create a feature for the original part
        # Always save the study area bounding boxes regardless of mode
        self.save_to_geopackage(
            layer_name="study_area_polygons", geom=geom, area_name=normalized_name
        )
        # Process the geometry based on the selected mode
        if self.mode == "vector":
            log_message(f"Creating vector grid for {normalized_name}.")
            self.create_and_save_grid(geom, bbox)
        elif self.mode == "raster":
            # Grid must be made first as it is used when creating the clipping vector!
            log_message(f"Creating vector grid for {normalized_name}.")
            self.create_and_save_grid(geom, bbox)
            log_message(f"Creating clip polygon for {normalized_name}.")
            self.create_clip_polygon(geom, bbox, normalized_name)
            log_message(f"Creating raster mask for {normalized_name}.")
            self.create_raster_mask(geom, bbox, normalized_name)

        self.counter += 1

    def process_multipart_geometry(
        self, geom: QgsGeometry, normalized_name: str, area_name: str
    ) -> None:
        """
        Processes each part of a multipart geometry by exploding the parts and delegating
        to process_singlepart_geometry, ensuring the part index is included in the output name.

        :param geom: Geometry of the multipart feature.
        :param normalized_name: Name normalized for file storage.
        :param area_name: Name of the study area.
        """
        parts: List[QgsGeometry] = geom.asGeometryCollection()

        # Iterate over each part and delegate to process_singlepart_geometry
        for part_index, part in enumerate(parts):
            # Create a unique name for the part by appending the part index
            part_normalized_name = f"{normalized_name}_part{part_index}"

            # Delegate to process_singlepart_geometry
            self.process_singlepart_geometry(part, part_normalized_name, area_name)

    def grid_aligned_bbox(self, bbox: QgsRectangle) -> QgsRectangle:
        """
        Transforms and aligns the bounding box to the grid in the output CRS.
        The alignment ensures that the bbox aligns with the study area grid, offset by an exact multiple of
        the grid size in m.

        :param bbox: The bounding box to be aligned, in the CRS of the input layer.
        :return: A new bounding box aligned to the grid, in the output CRS.
        """
        # Transform the bounding box to the output CRS
        crs_src: QgsCoordinateReferenceSystem = self.layer.crs()
        transform: QgsCoordinateTransform = QgsCoordinateTransform(
            crs_src, self.output_crs, self.context.project()
        )
        if crs_src != self.output_crs:
            bbox_transformed = transform.transformBoundingBox(bbox)
        else:
            bbox_transformed = bbox

        # Align the bounding box to a grid aligned at 100m intervals, offset by the study area origin
        study_area_origin_x = (
            int(self.layer_bbox.xMinimum() // self.cell_size_m) * self.cell_size_m
        )
        study_area_origin_y = (
            int(self.layer_bbox.yMinimum() // self.cell_size_m) * self.cell_size_m
        )

        # Align bbox to the grid based on the study area origin
        x_min = (
            study_area_origin_x
            + int(
                (bbox_transformed.xMinimum() - study_area_origin_x) // self.cell_size_m
            )
            * self.cell_size_m
        )
        y_min = (
            study_area_origin_y
            + int(
                (bbox_transformed.yMinimum() - study_area_origin_y) // self.cell_size_m
            )
            * self.cell_size_m
        )
        x_max = (
            study_area_origin_x
            + (
                int(
                    (bbox_transformed.xMaximum() - study_area_origin_x)
                    // self.cell_size_m
                )
                + 1
            )
            * self.cell_size_m
        )
        y_max = (
            study_area_origin_y
            + (
                int(
                    (bbox_transformed.yMaximum() - study_area_origin_y)
                    // self.cell_size_m
                )
                + 1
            )
            * self.cell_size_m
        )

        y_min -= (
            self.cell_size_m
        )  # Offset to ensure the grid covers the entire geometry
        y_max += (
            self.cell_size_m
        )  # Offset to ensure the grid covers the entire geometry
        x_min -= (
            self.cell_size_m
        )  # Offset to ensure the grid covers the entire geometry
        x_max += (
            self.cell_size_m
        )  # Offset to ensure the grid covers the entire geometry

        # Return the aligned bbox in the output CRS
        return QgsRectangle(x_min, y_min, x_max, y_max)

    def save_to_geopackage(
        self, layer_name: str, geom: QgsGeometry, area_name: str
    ) -> None:
        """
        Save features to GeoPackage. Create or append the layer as necessary.
        :param layer_name: Name of the layer in the GeoPackage.
        :param geom: Feature to append.
        :param area_name: Name of the study area.

        """
        self.create_layer_if_not_exists(layer_name)
        self.append_to_layer(layer_name, geom, area_name)

    def append_to_layer(
        self, layer_name: str, geom: QgsGeometry, area_name: str
    ) -> None:
        """
        Append feature to an existing layer in the GeoPackage.

        :param layer_name: Name of the layer in the GeoPackage.
        :param geom: Feature to append.
        :param area_name: Name of the study area.
        """
        gpkg_layer_path = f"{self.gpkg_path}|layername={layer_name}"
        gpkg_layer = QgsVectorLayer(gpkg_layer_path, layer_name, "ogr")
        fields = gpkg_layer.fields()
        # Create a list of placeholder values based on field count
        attributes = [None] * len(fields)

        feature = QgsFeature()
        feature.setGeometry(geom)
        attributes[fields.indexFromName("area_name")] = area_name
        feature.setAttributes(attributes)

        if gpkg_layer.isValid():
            log_message(
                f"Appending to existing layer: {layer_name}",
                tag="Geest",
                level=Qgis.Info,
            )
            provider = gpkg_layer.dataProvider()
            provider.addFeatures([feature])
            gpkg_layer.updateExtents()
            # Do not remove this line, QGIS will crash during the
            # study area creation process.
            del provider
        else:
            log_message(
                f"Layer '{layer_name}' is not valid for appending.",
                tag="Geest",
                level=Qgis.Critical,
            )

    def create_layer_if_not_exists(self, layer_name: str) -> None:
        """
        Create a new layer in the GeoPackage if it doesn't already exist.

        It is assumed that all layers have the same structure of

        fid, area_name, geometry (Polygon)

        :param layer_name: Name of the layer to create.
        """

        fields = QgsFields()
        fields.append(QgsField("area_name", QVariant.String))
        geometry_type = QgsWkbTypes.Polygon

        gpkg_layer_path = f"{self.gpkg_path}|layername={layer_name}"
        layer = QgsVectorLayer(gpkg_layer_path, layer_name, "ogr")

        append = True
        # Check if the GeoPackage file exists
        if not os.path.exists(self.gpkg_path):
            append = False
            log_message(
                f"GeoPackage does not exist. Creating: {self.gpkg_path}",
                tag="Geest",
                level=Qgis.Info,
            )

        # If the layer doesn't exist, create it
        if not layer.isValid():
            log_message(
                f"Layer '{layer_name}' does not exist. Creating it.",
                tag="Geest",
                level=Qgis.Info,
            )
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.fileEncoding = "UTF-8"
            options.layerName = layer_name
            if append:
                options.actionOnExistingFile = (
                    QgsVectorFileWriter.CreateOrOverwriteLayer
                )

            # Create a new GeoPackage layer
            QgsVectorFileWriter.create(
                fileName=self.gpkg_path,
                fields=fields,
                geometryType=geometry_type,
                srs=self.output_crs,
                transformContext=QgsCoordinateTransformContext(),
                options=options,
            )
            return

    def create_and_save_grid(self, geom: QgsGeometry, bbox: QgsRectangle) -> None:
        """
        Creates a vector grid over the bounding box of a geometry and streams it directly to the GeoPackage.

        :param geom: Geometry to create grid over.
        :param bbox: Bounding box for the grid.
        """
        grid_layer_name = "study_area_grid"
        grid_fields = [QgsField("id", QVariant.Int)]

        self.create_layer_if_not_exists(grid_layer_name)
        # Access the GeoPackage layer to append features
        gpkg_layer_path = f"{self.gpkg_path}|layername={grid_layer_name}"
        gpkg_layer = QgsVectorLayer(gpkg_layer_path, grid_layer_name, "ogr")

        # get the highest fid from the vector layer
        if gpkg_layer.isValid():
            provider = gpkg_layer.dataProvider()
            feature_id = provider.featureCount()
        else:
            log_message(
                f"Failed to access layer '{grid_layer_name}' in the GeoPackage.",
                tag="Geest",
                level=Qgis.Critical,
            )
            return

        step = self.cell_size_m  # cell_size_mm grid cells
        feature_id += 1
        feature_batch = []
        log_message("Checking for meridian wrapping...")
        try:
            # Handle bounding box for meridian wrapping cases
            x_min, x_max = bbox.xMinimum(), bbox.xMaximum()
            y_min, y_max = bbox.yMinimum(), bbox.yMaximum()
            if x_min > x_max:
                # If spanning the meridian, adjust range to handle wraparound
                x_ranges = [(x_min, 180), (-180, x_max)]
            else:
                x_ranges = [(x_min, x_max)]
        except Exception as e:
            log_message(
                f"Error handling meridian wrapping: {str(e)}", level=Qgis.Critical
            )
            import traceback

            log_message(traceback.format_exc(), level=Qgis.Critical)
            raise
        log_message("Meridian wrapping handled.")

        step = self.cell_size_m  # Grid cell size
        total_cells = ((x_max - x_min) // step) * ((y_max - y_min) // step)
        cell_count = 0
        features_per_batch = 10000
        progress_log_interval = 10000
        log_message("Preparing spatial index...")

        # Spatial index for efficient intersection checks
        spatial_index = QgsSpatialIndex()
        feature = QgsFeature()
        feature.setGeometry(geom)
        spatial_index.addFeature(feature)
        log_message("Spatial index prepared.")

        try:
            log_message("Creating grid features...")
            # Iterate through defined ranges for x to handle wraparounds
            for x_range in x_ranges:
                for x in range(int(x_range[0]), int(x_range[1]), step):
                    for y in range(int(y_min), int(y_max), step):
                        if self.feedback.isCanceled():
                            return False

                        # Create cell rectangle
                        rect = QgsRectangle(x, y, x + step, y + step)
                        grid_geom = QgsGeometry.fromRect(rect)
                        # log_message(f"Creating rect: {rect}")
                        # Intersect check
                        if spatial_index.intersects(
                            grid_geom.boundingBox()
                        ) and grid_geom.intersects(geom):
                            # Create the grid feature
                            feature = QgsFeature()
                            feature.setGeometry(grid_geom)
                            feature.setAttributes([feature_id])
                            feature_batch.append(feature)
                            feature_id += 1
                            # log_message(f"Feature ID {feature_id} created.")

                            # Commit in batches
                            if len(feature_batch) >= features_per_batch:
                                provider.addFeatures(feature_batch)
                                # gpkg_layer.updateExtents()
                                feature_batch.clear()
                                log_message(
                                    f"Committed {feature_id} features to {grid_layer_name}."
                                )
                                gpkg_layer.commitChanges()
                                # Reset provider to free memory
                                # del provider
                                # gpkg_layer = QgsVectorLayer(
                                #    gpkg_layer_path, grid_layer_name, "ogr"
                                # )
                                # provider = gpkg_layer.dataProvider()

                        # Log progress periodically
                        cell_count += 1
                        if cell_count % progress_log_interval == 0:
                            progress = (cell_count / total_cells) * 100
                            log_message(
                                f"Processed {cell_count}/{total_cells} grid cells ({progress:.2f}% complete)."
                            )
                            self.setProgress(int(progress))

            # Commit any remaining features
            if feature_batch:
                provider.addFeatures(feature_batch)
            gpkg_layer.commitChanges()
            gpkg_layer.updateExtents()
            provider.forceReload()
            del gpkg_layer
            log_message(
                f"Final commit: {feature_id} features written to {grid_layer_name}."
            )

        except Exception as e:
            log_message(f"Error during grid creation: {str(e)}", level=Qgis.Critical)
            import traceback

            log_message(traceback.format_exc(), level=Qgis.Critical)
            return

        log_message(f"Grid creation completed. Total features written: {feature_id}.")

    def create_clip_polygon(
        self, geom: QgsGeometry, aligned_box: QgsRectangle, normalized_name: str
    ) -> str:
        """
        Creates a polygon like the study area geometry, but with each
        area extended to completely cover the grid cells that intersect with the geometry.

        We do this by combining the area polygon and all the cells that occur along
        its edge. This is necessary because gdalwarp clip only includes cells that
        have 50% coverage or more and it has no -at option like gdalrasterize has.

        The cells and the original area polygon are dissolved into a single polygon
        representing the outer boundary of all the edge cells and the original area polygon.

        :param geom: Geometry to be processed.
        :param aligned_box: Aligned bounding box for the geometry.
        :param normalized_name: Name for the output area

        :return: None.
        """
        # Create a memory layer to hold the geometry
        temp_layer = QgsVectorLayer(
            f"Polygon?crs={self.output_crs.authid()}", "temp_mask_layer", "memory"
        )
        temp_layer_data_provider = temp_layer.dataProvider()
        # get the geometry as a linestring
        linestring = geom.coerceToType(QgsWkbTypes.LineString)[0]
        # The linestring and the original polygon geom should have the same bbox
        if linestring.boundingBox() != geom.boundingBox():
            raise Exception("Bounding boxes of linestring and polygon do not match.")

        # we are going to select all grid cells that intersect the linestring
        # so that we can ensure gdal rasterize does not miss any land areas
        gpkg_layer_path = f"{self.gpkg_path}|layername=study_area_grid"
        gpkg_layer = QgsVectorLayer(gpkg_layer_path, "study_area_grid", "ogr")

        # Create a spatial index for efficient spatial querying
        spatial_index = QgsSpatialIndex(gpkg_layer.getFeatures())

        # Get feature IDs of candidates that may intersect with the multiline geometry
        candidate_ids = spatial_index.intersects(geom.boundingBox())

        if len(candidate_ids) == 0:
            raise Exception(
                f"No candidate cells on boundary of the geometry: {self.working_dir}"
            )

        # Filter candidates by precise geometry intersection
        intersecting_ids = []
        for feature_id in candidate_ids:
            feature = gpkg_layer.getFeature(feature_id)
            if feature.geometry().intersects(linestring):
                intersecting_ids.append(feature_id)

        if len(intersecting_ids) == 0:
            raise Exception("No cells on boundary of the geometry")
        # Select intersecting features in the layer
        gpkg_layer.selectByIds(intersecting_ids)

        log_message(
            f"Selected {len(intersecting_ids)} features that intersect with the multiline geometry."
        )

        # Define a field to store the area name
        temp_layer_data_provider.addAttributes(
            [QgsField(self.field_name, QVariant.String)]
        )
        temp_layer.updateFields()

        # Add the geometry to the memory layer
        temp_feature = QgsFeature()
        temp_feature.setGeometry(geom)
        temp_feature.setAttributes(
            [normalized_name]
        )  # Setting an arbitrary value for the mask

        # Add the main geometry for this part of the country
        temp_layer_data_provider.addFeature(temp_feature)

        # Now all the grid cells get added that intersect with the geometry border
        # since gdal rasterize only includes cells that have 50% coverage or more
        # by the looks of things.
        selected_features = gpkg_layer.selectedFeatures()
        new_features = []

        for feature in selected_features:
            # Create a new feature for emp_layer
            new_feature = QgsFeature()
            new_feature.setGeometry(feature.geometry())
            new_feature.setAttributes([normalized_name])
            new_features.append(new_feature)

        # Add the features to temp_layer
        temp_layer_data_provider.addFeatures(new_features)

        # commit all changes
        temp_layer.updateExtents()
        temp_layer.commitChanges()
        # check how many features we have
        feature_count = temp_layer.featureCount()
        log_message(
            f"Added {feature_count} features to the temp layer for mask creation."
        )

        output = processing.run(
            "native:dissolve",
            {
                "INPUT": temp_layer,
                "FIELD": [],
                "SEPARATE_DISJOINT": False,
                "OUTPUT": "TEMPORARY_OUTPUT",
            },
        )["OUTPUT"]
        # get the first feature from the output layer
        feature = next(output.getFeatures())
        # get the geometry
        clip_geom = feature.geometry()

        self.save_to_geopackage(
            layer_name="study_area_clip_polygons",
            geom=clip_geom,
            area_name=normalized_name,
        )
        log_message(f"Created clip polygon: {normalized_name}")
        return

    def create_raster_mask(
        self, geom: QgsGeometry, aligned_box: QgsRectangle, mask_name: str
    ) -> str:
        """
        Creates a 1-bit raster mask for a single geometry.

        :param geom: Geometry to be rasterized.
        :param aligned_box: Aligned bounding box for the geometry.
        :param mask_name: Name for the output raster file.

        :return: The path to the created raster mask.
        """
        mask_filepath = os.path.join(self.working_dir, "study_area", f"{mask_name}.tif")

        # Create a memory layer to hold the geometry
        temp_layer = QgsVectorLayer(
            f"Polygon?crs={self.output_crs.authid()}", "temp_mask_layer", "memory"
        )
        temp_layer_data_provider = temp_layer.dataProvider()

        # Define a field to store the mask value
        temp_layer_data_provider.addAttributes(
            [QgsField(self.field_name, QVariant.String)]
        )
        temp_layer.updateFields()

        # Add the geometry to the memory layer
        temp_feature = QgsFeature()
        temp_feature.setGeometry(geom)
        temp_feature.setAttributes(["1"])  # Setting an arbitrary value for the mask

        # Add the main geometry for this part of the country
        temp_layer_data_provider.addFeature(temp_feature)

        # commit all changes
        temp_layer.updateExtents()
        temp_layer.commitChanges()

        # Ensure resolution parameters are properly formatted as float values
        x_res = self.cell_size_m  # 100m pixel size in X direction
        y_res = self.cell_size_m  # 100m pixel size in Y direction

        # Define rasterization parameters for the temporary layer
        params = {
            "INPUT": temp_layer,
            "FIELD": None,
            "BURN": 1,
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
            "EXTRA": "-co NBITS=1 -at",  # -at is for all touched cells
            "OUTPUT": mask_filepath,
        }
        processing.run("gdal:rasterize", params)
        log_message(f"Created raster mask: {mask_filepath}")
        return mask_filepath

    def calculate_utm_zone(self, bbox: QgsRectangle) -> int:
        """
        Calculates the UTM zone based on the centroid of the bounding box.
        The calculation is based on transforming the centroid to WGS84 (EPSG:4326).

        :param bbox: The bounding box of the layer.
        :return: The EPSG code for the UTM zone.
        """
        # Get the source CRS (from the input layer)
        crs_src: QgsCoordinateReferenceSystem = self.layer.crs()
        crs_wgs84: QgsCoordinateReferenceSystem = QgsCoordinateReferenceSystem(
            "EPSG:4326"
        )

        # Create the transform object
        transform: QgsCoordinateTransform = QgsCoordinateTransform(
            crs_src, crs_wgs84, self.context.project()
        )

        # Transform the centroid to WGS84
        centroid: QgsPointXY = bbox.center()
        centroid_wgs84 = transform.transform(centroid)

        lon = centroid_wgs84.x()
        lat = centroid_wgs84.y()

        # Calculate the UTM zone based on the longitude
        utm_zone = int((lon + 180) / 6) + 1

        # EPSG code for the UTM zone
        if lat >= 0:
            epsg_code = 32600 + utm_zone  # Northern Hemisphere
        else:
            epsg_code = 32700 + utm_zone  # Southern Hemisphere

        return epsg_code

    def create_study_area_directory(self, working_dir: str) -> None:
        """
        Creates the 'study_area' directory if it doesn't already exist.

        :param working_dir: Path to the working directory.
        """
        study_area_dir = os.path.join(working_dir, "study_area")
        if not os.path.exists(study_area_dir):
            try:
                os.makedirs(study_area_dir)
                log_message(
                    f"Created study area directory: {study_area_dir}",
                    tag="Geest",
                    level=Qgis.Info,
                )
            except Exception as e:
                log_message(f"Error creating directory: {e}", level=Qgis.Critical)

    def create_raster_vrt(self, output_vrt_name: str = "combined_mask.vrt") -> None:
        """
        Creates a VRT file from all generated raster masks and adds it to the QGIS map.

        :param output_vrt_name: The name of the VRT file to create.
        """
        log_message(
            f"Creating VRT of masks '{output_vrt_name}' layer to the map.",
            tag="Geest",
            level=Qgis.Info,
        )
        # Directory containing raster masks
        raster_dir = os.path.join(self.working_dir, "study_area")
        raster_files = glob.glob(os.path.join(raster_dir, "*.tif"))

        if not raster_files:
            log_message(
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
        log_message(f"Created VRT: {vrt_filepath}")

        # Add the VRT to the QGIS map
        vrt_layer = QgsRasterLayer(vrt_filepath, "Combined Mask VRT")

        if vrt_layer.isValid():
            # Not thread safe, use signal instead
            # QgsProject.instance().addMapLayer(vrt_layer)
            log_message("Added VRT layer to the map.")
        else:
            log_message("Failed to add VRT layer to the map.", level=Qgis.Critical)
