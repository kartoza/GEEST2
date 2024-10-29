import uuid
from qgis.PyQt.QtCore import Qt

# Change to this when implementing in QGIS
# from qgis.PyQt.QtGui import (
from PyQt5.QtGui import QColor, QFont, QIcon
from qgis.core import QgsMessageLog, Qgis
from geest.utilities import resources_path
from geest.core import setting


class JsonTreeItem:
    """A class representing a node in the tree.

    🚩  TAKE NOTE: 🚩

    This class may NOT inherit from QObject, as it has to remain
    thread safe and not be tied to the main thread. Items are passed to
    workflow threads and must be able to be manipulated in the background.

    """

    def __init__(self, data, role, guid=None, parent=None):
        self.parentItem = parent
        self.itemData = data  # name, status, weighting, attributes(dict)
        self.childItems = []
        self.role = role  # Stores whether an item is a dimension, factor, or layer
        self.font_color = QColor(Qt.black)  # Default font color
        # Add a unique guid for each item
        if guid:
            self.guid = guid
        else:
            self.guid = str(uuid.uuid4())  # Generate a unique identifier for this item

        # Define icons for each role
        self.dimension_icon = QIcon(
            resources_path("resources", "icons", "dimension.svg")
        )
        self.factor_icon = QIcon(resources_path("resources", "icons", "factor.svg"))
        self.indicator_icon = QIcon(
            resources_path("resources", "icons", "indicator.svg")
        )

        # Define fonts for each role
        self.dimension_font = QFont()
        self.dimension_font.setBold(True)

        self.factor_font = QFont()
        self.factor_font.setItalic(True)
        self.updateStatus()

    def appendChild(self, item):
        self.childItems.append(item)

    def child(self, row):
        return self.childItems[row]

    def childCount(self):
        return len(self.childItems)

    def columnCount(self):
        return len(self.itemData)

    def data(self, column):
        if column < len(self.itemData):
            return self.itemData[column]
        return None

    def setData(self, column, value):
        if column < len(self.itemData):
            self.itemData[column] = value
            return True
        return False

    def parent(self):
        return self.parentItem

    def row(self):
        if self.parentItem:
            return self.parentItem.childItems.index(self)
        return 0

    def isIndicator(self):
        return self.role == "indicator"

    def isFactor(self):
        return self.role == "factor"

    def isDimension(self):
        return self.role == "dimension"

    def isAnalysis(self):
        return self.role == "analysis"

    def getIcon(self):
        """Retrieve the appropriate icon for the item based on its role."""
        if self.isDimension():
            return self.dimension_icon
        elif self.isFactor():
            return self.factor_icon
        elif self.isIndicator():
            return self.indicator_icon
        return None

    def getItemTooltip(self):
        """Retrieve the appropriate tooltip for the item based on its role."""
        data = self.itemData[3]
        if self.isDimension():
            description = data.get("description", "")
            if description:
                return f"{description}"
            else:
                return "Dimension"
        elif self.isFactor():
            description = data.get("description", "")
            if description:
                return f"{description}"
            else:
                return "Factor"
        elif self.isIndicator():
            description = data.get("description", "")
            if description:
                return f"{description}"
            else:
                return "Indicator"
        return ""

    def getStatusIcon(self):
        """Retrieve the appropriate icon for the item based on its role."""
        status = self.getStatus()
        # Use a case statement to determine the icon based on the status
        match status:
            case "✔️":
                return QIcon(
                    resources_path("resources", "icons", "completed-success.svg")
                )
            case "-":
                return QIcon(
                    resources_path("resources", "icons", "required-not-configured.svg")
                )
            case "!":
                return QIcon(resources_path("resources", "icons", "not-configured.svg"))
            case "x":
                return QIcon(resources_path("resources", "icons", "failed.svg"))
            case "e":
                return QIcon(resources_path("resources", "icons", ".svg"))
            case _:
                return QIcon(resources_path("resources", "icons", ".svg"))

    def getStatusTooltip(self):
        """Retrieve the appropriate tooltip for the item based on its role."""
        status = self.getStatus()
        # Use a case statement to determine the icon based on the status
        match status:
            case "✔️":
                return "Completed successfully"
            case "-":
                return "Required and not configured"
            case "!":
                return "Not configured (optional)"
            case "x":
                return "Workflow failed"
            case "e":
                return "WRITE TOOL TIP"
            case _:
                return ""

    def getStatus(self):
        """Return the status of the item as single character."""
        try:
            data = self.itemData[3]
            # QgsMessageLog.logMessage(f"Data: {data}", tag="Geest", level=Qgis.Info)
            status = ""
            if "Error" in data.get("result", ""):
                return "x"
            if "Failed" in data.get("result", ""):
                return "x"
            # Item required and not configured
            if "Don’t Use" in data.get("analysis_mode", "") and data.get(
                "indicator_required", False
            ):
                return "-"
            # Item not required but not configured
            if "Don’t Use" in data.get("analysis_mode", "") and not data.get(
                "indicator_required", False
            ):
                return "!"
            if "Workflow Completed" not in data.get("result", ""):
                return "x"
            if "Workflow Completed" in data.get("result", ""):
                return "✔️"

        except Exception as e:
            verbose_mode = setting.value("verbose_mode", False)
            if verbose_mode:
                import traceback

                QgsMessageLog.logMessage(
                    f"Error getting status: {e}", tag="Geest", level=Qgis.Warning
                )
                QgsMessageLog.logMessage(
                    traceback.format_exc(), tag="Geest", level=Qgis.Warning
                )
                return "e"  # e for error

    def updateStatus(self, status=None):
        """Update the status of the item.

        If no status is provided we will compute the best status based on the item's attributes.

        :param status: The status to set the item to.

        :return: None

        Note: The status is stored in the second column of the itemData
        """
        try:
            if status is None:
                status = self.getStatus()
            # self.itemData[1] = status - taken care of by decoration role rather
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error updating status: {e}", tag="Geest", level=Qgis.Warning
            )

    def getFont(self):
        """Retrieve the appropriate font for the item based on its role."""
        if self.isDimension():
            return self.dimension_font
        elif self.isFactor():
            return self.factor_font
        return QFont()

    def getPaths(self) -> []:
        """Return the path of the item in the tree in the form dimension/factor/indicator.

        :return: A list of strings representing the path of the item in the tree.
        """
        path = []
        if self.isIndicator():
            path.append(
                self.parentItem.parentItem.itemData[3]
                .get("id", "")
                .lower()
                .replace(" ", "_")
            )
            path.append(
                self.parentItem.itemData[3].get("id", "").lower().replace(" ", "_")
            )
            path.append(self.itemData[3].get("id", "").lower().replace(" ", "_"))
        elif self.isFactor():
            path.append(
                self.parentItem.itemData[3].get("id", "").lower().replace(" ", "_")
            )
            path.append(self.itemData[3].get("id", "").lower().replace(" ", "_"))
        if self.isDimension():
            path.append(self.itemData[3].get("id", "").lower().replace(" ", "_"))
        return path

    def getIndicatorAttributes(self):
        """Return the dict of indicators (or layers) under this indicator."""
        attributes = {}
        if self.isIndicator():
            attributes["Dimension ID"] = self.parentItem.parentItem.itemData[3].get(
                "id", ""
            )
            attributes["Factor ID"] = self.parentItem.itemData[3].get("id", "")
            attributes[indicator_id] = self.itemData[3].get("id", "")
            attributes["Indicator Name"] = self.itemData[3].get("indicator", "")
            attributes["Indicator Weighting"] = self.itemData[3].get(
                "factor_weighting", ""
            )
            attributes["result_file"] = self.itemData[3].get("result_file", "")
            attributes["result"] = self.itemData[3].get("result", "")
        return attributes

    def getFactorAttributes(self):
        """Return the dict of indicators (or layers) under this factor."""
        attributes = {}
        if self.isFactor():
            attributes["Dimension ID"] = self.parentItem.itemData[3].get("id", "")
            attributes["analysis_mode"] = "factor_aggregation"
            attributes["Factor ID"] = self.data(0)
            attributes["Indicators"] = [
                {
                    "Indicator No": i,
                    indicator_id: child.data(3).get("id", ""),
                    "Indicator Name": child.data(0),
                    "Indicator Weighting": child.data(2),
                    "result_file": child.data(3).get("result_file", ""),
                }
                for i, child in enumerate(self.childItems)
            ]
        return attributes

    def getDimensionAttributes(self):
        """Return the dict of factors under this dimension."""
        attributes = {}
        if self.isDimension():
            attributes["analysis_mode"] = "dimension_aggregation"
            attributes["Dimension ID"] = self.data(0)
            attributes["Factors"] = [
                {
                    "Factor No": i,
                    "Factor ID": child.data(3).get("id", ""),
                    "Factor Name": child.data(0),
                    "factor_weighting": child.data(2),
                    "result_file": child.data(3).get(f"result_file", ""),
                }
                for i, child in enumerate(self.childItems)
            ]
        return attributes

    def getAnalysisAttributes(self):
        """Return the dict of dimensions under this analysis."""
        attributes = {}
        if self.isAnalysis():
            attributes["Analysis Name"] = self.data(3).get("Analysis Name", "Not Set")
            attributes["Description"] = self.data(3).get(
                "Analysis Description", "Not Set"
            )
            attributes["Working Folder"] = self.data(3).get("Working Folder", "Not Set")

            attributes["Dimensions"] = [
                {
                    "Dimension No": i,
                    "Dimension ID": child.data(3).get("id", ""),
                    "Dimension Name": child.data(0),
                    "dimension_weighting": child.data(2),
                    "Dimension Result File": child.data(3).get(
                        f"Dimension Result File", ""
                    ),
                }
                for i, child in enumerate(self.childItems)
            ]
        return attributes

    def updateIndicatorWeighting(self, indicator_name, new_weighting):
        """Update the weighting of a specific indicator by its name."""
        try:
            # Search for the indicator by name
            indicator_item = next(
                (child for child in self.childItems if child.data(0) == indicator_name),
                None,
            )

            # If found, update the weighting
            if indicator_item:
                indicator_item.setData(2, f"{new_weighting:.2f}")
            else:
                # Log if the indicator name is not found
                QgsMessageLog.logMessage(
                    f"Indicator '{indicator_name}' not found.",
                    tag="Geest",
                    level=Qgis.Warning,
                )

        except Exception as e:
            # Handle any exceptions and log the error
            QgsMessageLog.logMessage(
                f"Error updating weighting: {e}", tag="Geest", level=Qgis.Warning
            )
