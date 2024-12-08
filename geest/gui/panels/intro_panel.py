from PyQt5.QtWidgets import (
    QWidget,
)
from qgis.core import Qgis

from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtGui import QPixmap
from geest.core.tasks import OrsCheckerTask
from geest.utilities import get_ui_class, resources_path
from geest.utilities import log_message

FORM_CLASS = get_ui_class("intro_panel_base.ui")


class IntroPanel(FORM_CLASS, QWidget):
    switch_to_next_tab = pyqtSignal()  # Signal to notify the parent to switch tabs

    def __init__(self):
        super().__init__()
        self.setWindowTitle("GEEST")
        # Dynamically load the .ui file
        self.setupUi(self)
        log_message(f"Loading intro panel")
        self.initUI()

    def initUI(self):
        self.banner_label.setPixmap(
            QPixmap(resources_path("resources", "geest-banner.png"))
        )
        self.next_button.clicked.connect(self.on_next_button_clicked)

    def on_next_button_clicked(self):
        self.switch_to_next_tab.emit()
