from .base_indicator_widget import BaseIndicatorWidget


class DontUseRadioButton(BaseIndicatorWidget):
    """
    A specialized radio button with additional widgets for IndexScore.
    """

    def add_internal_widgets(self) -> None:
        """
        Adds internal widgets specific to Dont Use - in this case there are none.
        """
        pass

    def get_data(self) -> dict:
        """
        Return the data as a dictionary, updating attributes with current value.
        """
        return self.attributes

    def set_internal_widgets_enabled(self, enabled: bool) -> None:
        """
        Enables or disables the internal widgets based on the state of the radio button.
        """
        pass
