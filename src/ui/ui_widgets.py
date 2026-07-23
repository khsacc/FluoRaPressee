from PyQt6.QtWidgets import QSpinBox, QDoubleSpinBox, QComboBox, QAbstractSpinBox

class CustomSpinBox(QSpinBox):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    def wheelEvent(self, event):
        event.ignore()

class CustomDoubleSpinBox(QDoubleSpinBox):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    def wheelEvent(self, event):
        event.ignore()

class CustomComboBox(QComboBox):
    def wheelEvent(self, event):
        event.ignore()
