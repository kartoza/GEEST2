import os
import shutil
import numpy as np
from osgeo import gdal
from qgis.core import (
    QgsProcessingException,
    QgsCoordinateReferenceSystem,
    QgsGeometry,
    QgsFeature,
    QgsWkbTypes,
    QgsVectorLayer,
    QgsRasterLayer,
    Qgis,
    QgsProcessingFeedback,
)
import processing
from geest.utilities import log_message


# Call QGIS process to assign a CRS to a layer
def assign_crs_to_raster_layer(
    layer: QgsRasterLayer, crs: QgsCoordinateReferenceSystem
) -> QgsVectorLayer:
    """
    Assigns a CRS to a layer and returns the layer.

    Args:
        layer: The layer to assign the CRS to.
        crs: The CRS to assign to the layer.

    Returns:
        The layer with the assigned CRS.
    """
    processing.run("gdal:assignprojection", {"INPUT": layer, "CRS": crs})
    return layer


def assign_crs_to_vector_layer(
    layer: QgsVectorLayer, crs: QgsCoordinateReferenceSystem
) -> QgsVectorLayer:
    """
    Assigns a CRS to a layer and returns the layer.

    Args:
        layer: The layer to assign the CRS to.
        crs: The CRS to assign to the layer.

    Returns:
        The layer with the assigned CRS.
    """
    output = processing.run(
        "native:assignprojection",
        {"INPUT": layer, "CRS": crs, "OUTPUT": "TEMPORARY_OUTPUT"},
    )["OUTPUT"]
    return output


def subset_vector_layer(
    workflow_directory: str,
    features_layer: QgsVectorLayer,
    area_geom: QgsGeometry,
    output_prefix: str,
) -> QgsVectorLayer:
    """
    Select features from the features layer that intersect with the given area geometry.

    Args:
        features_layer (QgsVectorLayer): The input features layer.
        area_geom (QgsGeometry): The current area geometry for which intersections are evaluated.
        output_prefix (str): A name for the output temporary layer to store selected features.

    Returns:
        QgsVectorLayer: A new temporary layer containing features that intersect with the given area geometry.
    """
    if type(features_layer) != QgsVectorLayer:
        return None
    log_message(f"subset_vector_layer Select Features Started")
    output_path = os.path.join(workflow_directory, f"{output_prefix}.shp")

    # Get the WKB type (geometry type) of the input layer (e.g., Point, LineString, Polygon)
    geometry_type = features_layer.wkbType()

    # Determine geometry type name based on input layer's geometry
    if QgsWkbTypes.geometryType(geometry_type) == QgsWkbTypes.PointGeometry:
        geometry_name = "Point"
    elif QgsWkbTypes.geometryType(geometry_type) == QgsWkbTypes.LineGeometry:
        geometry_name = "LineString"
    elif QgsWkbTypes.geometryType(geometry_type) == QgsWkbTypes.PolygonGeometry:
        geometry_name = "Polygon"
    else:
        raise QgsProcessingException(f"Unsupported geometry type: {geometry_type}")

    params = {
        "INPUT": features_layer,
        "PREDICATE": [0],  # Intersects predicate
        "GEOMETRY": area_geom,
        "EXTENT": area_geom.boundingBox(),
        "OUTPUT": output_path,
    }
    result = processing.run("native:extractbyextent", params)
    return QgsVectorLayer(result["OUTPUT"], output_prefix, "ogr")


def geometry_to_memory_layer(
    geometry: QgsGeometry, target_crs: QgsCoordinateReferenceSystem, layer_name: str
):
    """
    Convert a QgsGeometry to a memory layer.

    Args:
        geometry (QgsGeometry): The polygon geometry to convert.
        target_crs (QgsCoordinateReferenceSystem): The CRS to assign to the memory layer
        layer_name (str): The name to assign to the memory layer.

    Returns:
        QgsVectorLayer: The memory layer containing the geometry.
    """
    memory_layer = QgsVectorLayer("Polygon", layer_name, "memory")
    memory_layer.setCrs(target_crs)
    feature = QgsFeature()
    feature.setGeometry(geometry)
    memory_layer.dataProvider().addFeatures([feature])
    memory_layer.commitChanges()
    return memory_layer


def check_and_reproject_layer(
    features_layer: QgsVectorLayer, target_crs: QgsCoordinateReferenceSystem
):
    """
    Checks if the features layer has valid geometries and the expected CRS.

    Geometry errors are fixed using the native:fixgeometries algorithm.
    If the layer's CRS does not match the target CRS, it is reprojected using the
    native:reprojectlayer algorithm.

    Args:
        features_layer (QgsVectorLayer): The input features layer.
        target_crs (QgsCoordinateReferenceSystem): The target CRS for the layer.

    Returns:
        QgsVectorLayer: The input layer, either reprojected or unchanged.

    Note: Also updates self.features_layer to point to the reprojected layer.
    """
    # check if the layer has a valid CRS
    if not features_layer.crs().isValid():
        raise QgsProcessingException("Layer has no CRS.")

    params = {
        "INPUT": features_layer,
        "METHOD": 1,  # Structure method
        "OUTPUT": "memory:",  # Reproject in memory,
    }
    fixed_features_layer = processing.run("native:fixgeometries", params)["OUTPUT"]
    log_message("Fixed features layer geometries")

    if fixed_features_layer.crs() != target_crs:
        log_message(
            f"Reprojecting layer from {fixed_features_layer.crs().authid()} to {target_crs.authid()}",
            tag="Geest",
            level=Qgis.Info,
        )
        reproject_result = processing.run(
            "native:reprojectlayer",
            {
                "INPUT": fixed_features_layer,
                "TARGET_CRS": target_crs,
                "OUTPUT": "memory:",  # Reproject in memory
            },
            feedback=QgsProcessingFeedback(),
        )
        reprojected_layer = reproject_result["OUTPUT"]
        if not reprojected_layer.isValid():
            raise QgsProcessingException("Reprojected layer is invalid.")
        features_layer = reprojected_layer
    else:
        features_layer = fixed_features_layer
    # If CRS matches, return the original layer
    return features_layer


def combine_rasters_to_vrt(
    rasters: list,
    target_crs: QgsCoordinateReferenceSystem,
    vrt_filepath: str,
    source_qml: str = None,
) -> None:
    """
    Combine all the rasters into a single VRT file.

    Args:
        rasters: The rasters to combine into a VRT.
        target_crs: The CRS to assign to the VRT.
        vrt_filepath: The full path of the output VRT file to create.
        source_qml: The source QML file to apply to the VRT.

    Returns:
        vrtpath (str): The file path to the VRT file.
    """
    if not rasters:
        log_message(
            "No valid raster layers found to combine into VRT.",
            tag="Geest",
            level=Qgis.Warning,
        )
        return

    log_message(f"Creating VRT of layers as '{vrt_filepath}'.")
    checked_rasters = []
    for raster in rasters:
        if raster and os.path.exists(raster) and QgsRasterLayer(raster).isValid():
            checked_rasters.append(raster)
        else:
            log_message(
                f"Skipping invalid or non-existent raster: {raster}",
                tag="Geest",
                level=Qgis.Warning,
            )

    if not checked_rasters:
        log_message(
            "No valid raster layers found to combine into VRT.",
            tag="Geest",
            level=Qgis.Warning,
        )
        return

    # Define the VRT parameters
    params = {
        "INPUT": checked_rasters,
        "RESOLUTION": 0,  # Use highest resolution among input files
        "SEPARATE": False,  # Combine all input rasters as a single band
        "OUTPUT": vrt_filepath,
        "PROJ_DIFFERENCE": False,
        "ADD_ALPHA": False,
        "ASSIGN_CRS": target_crs,
        "RESAMPLING": 0,
        # "SRC_NODATA": "255",
        "EXTRA": "",
    }

    # Run the gdal:buildvrt processing algorithm to create the VRT
    processing.run("gdal:buildvirtualraster", params)
    log_message(f"Created VRT: {vrt_filepath}")

    # Copy the appropriate QML over too
    destination_qml = os.path.splitext(vrt_filepath)[0] + ".qml"
    log_message(f"Copying QML from {source_qml} to {destination_qml}")
    shutil.copyfile(source_qml, destination_qml)

    vrt_layer = QgsRasterLayer(vrt_filepath, "Final VRT")
    if not vrt_layer.isValid():
        log_message("VRT Layer generation failed.", level=Qgis.Critical)
        return False
    del vrt_layer

    return vrt_filepath


# Step 1: Merge layers
log_message(
    "Step 1: Merging input layers into a single raster.", tag="Geest", level=Qgis.Info
)


def merge_rasters(input_files, output_file, nodata_value=-9999):
    """
    Based heavily off the work of the `gdal_merge.py` script,
    this function merges a list of raster files into a single. See
    https://raw.githubusercontent.com/postmates/gdal/refs/heads/master/scripts/gdal_merge.py


    Custom raster merge tool replicating `gdal_merge.py` behavior.
    - Initializes the output raster with NoData.
    - Copies input raster data into the output raster, with later rasters overwriting earlier ones.

    :param input_files: List of input raster file paths.
    :param output_file: Path to the output merged raster file.
    :param nodata_value: NoData value for the output raster.
    """
    log_message(f"Merge Rasters Started", tag="Geest", level=Qgis.Info)
    for raster_path in input_files:
        log_message(f"Checking raster: {raster_path}", tag="Geest", level=Qgis.Info)
        if not os.path.exists(raster_path):
            raise FileNotFoundError(f"Could not open raster file: {raster_path}")

    # Collect raster metadata to compute the union of extents
    ulx, uly, lrx, lry = float("inf"), float("-inf"), float("-inf"), float("inf")
    pixel_size_x, pixel_size_y = None, None
    file_infos = []

    # Process all input files to calculate union extent and pixel sizes
    for raster_path in input_files:
        raster = gdal.Open(raster_path)
        if raster is None:
            raise FileNotFoundError(f"Could not open raster file: {raster_path}")

        geotransform = raster.GetGeoTransform()
        x_size, y_size = raster.RasterXSize, raster.RasterYSize

        ulx = min(ulx, geotransform[0])
        uly = max(uly, geotransform[3])
        lrx = max(lrx, geotransform[0] + x_size * geotransform[1])
        lry = min(lry, geotransform[3] + y_size * geotransform[5])

        pixel_size_x = geotransform[1]
        pixel_size_y = geotransform[5]

        file_infos.append(
            {
                "path": raster_path,
                "geotransform": geotransform,
                "x_size": x_size,
                "y_size": y_size,
            }
        )

        raster = None  # Close the raster to free resources

    # Calculate output raster size and geotransform
    cols = int((lrx - ulx) / pixel_size_x + 0.5)
    rows = int((uly - lry) / abs(pixel_size_y) + 0.5)
    output_geotransform = [ulx, pixel_size_x, 0, uly, 0, pixel_size_y]

    # Create the output raster
    driver = gdal.GetDriverByName("GTiff")
    out_raster = driver.Create(output_file, cols, rows, 1, gdal.GDT_Float32)
    out_raster.SetGeoTransform(output_geotransform)
    out_raster.SetProjection(gdal.Open(input_files[0]).GetProjection())
    out_band = out_raster.GetRasterBand(1)
    out_band.SetNoDataValue(nodata_value)

    # Initialize the output raster with NoData
    out_band.Fill(nodata_value)

    # Copy data from input rasters into the output raster
    for file_info in file_infos:
        raster = gdal.Open(file_info["path"])
        band = raster.GetRasterBand(1)

        # Calculate overlap window
        src_geotransform = file_info["geotransform"]
        src_ulx, src_uly = src_geotransform[0], src_geotransform[3]
        src_lrx = src_ulx + file_info["x_size"] * src_geotransform[1]
        src_lry = src_uly + file_info["y_size"] * src_geotransform[5]

        dst_xoff = int((src_ulx - ulx) / pixel_size_x + 0.5)
        dst_yoff = int((uly - src_uly) / abs(pixel_size_y) + 0.5)
        dst_cols = int((src_lrx - src_ulx) / pixel_size_x + 0.5)
        dst_rows = int((src_uly - src_lry) / abs(pixel_size_y) + 0.5)

        # Read and write data for the overlapping region
        data = band.ReadAsArray(
            0,
            0,
            file_info["x_size"],
            file_info["y_size"],
            buf_xsize=dst_cols,
            buf_ysize=dst_rows,
        )
        out_data = out_band.ReadAsArray(dst_xoff, dst_yoff, dst_cols, dst_rows)
        mask = data != band.GetNoDataValue()

        # Overwrite NoData values in the output with valid data from the source
        out_data[mask] = data[mask]
        out_band.WriteArray(out_data, dst_xoff, dst_yoff)

        raster = None  # Close the raster to free resources

    # Finalize the output raster
    out_band.FlushCache()
    out_raster = None
    log_message(f"Merged raster saved to: {output_file}", tag="Geest", level=Qgis.Info)
