from .workflows import (
    RasterLayerWorkflow,
    DontUseWorkflow,
    DefaultIndexScoreWorkflow,
    ContextualAggregateWorkflow,
)
from qgis.core import QgsFeedback, QgsMessageLog, Qgis


class WorkflowFactory:
    """
    A factory class that creates workflow objects based on the attributes.
    The workflows accept a QgsFeedback object to report progress and handle cancellation.
    """

    def __init__(self):
        # Keep track of how many workflows have completed
        self.workflow_completed = 0

    def create_workflow(self, attributes, feedback: QgsFeedback):
        """
        Determines the workflow to return based on 'Analysis Mode' in the attributes.
        Passes the feedback object to the workflow for progress reporting.
        """
        analysis_mode = attributes.get("Analysis Mode")

        if analysis_mode == "Spatial Analysis":
            return RasterLayerWorkflow(attributes, feedback)
        elif analysis_mode == "Use Default Index Score":
            self.workflow_completed += 1  # Increment the workflow count
            QgsMessageLog.logMessage(
                f"Workflow completed: {self.workflow_completed}",
                tag="Geest",
                level=Qgis.Info,
            )
            return DefaultIndexScoreWorkflow(attributes, feedback)
        elif self.workflow_completed == 1:
            return ContextualAggregateWorkflow(attributes, feedback)
        elif analysis_mode == "Don’t Use":
            return DontUseWorkflow(attributes, feedback)
        elif analysis_mode == "Temporal Analysis":
            return RasterLayerWorkflow(attributes, feedback)
        else:
            raise ValueError(f"Unknown Analysis Mode: {analysis_mode}")
