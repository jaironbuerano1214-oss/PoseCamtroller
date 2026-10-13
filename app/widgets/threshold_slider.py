"""ThresholdSlider — QSlider + percentage label."""
from PySide6.QtWidgets import QWidget, QHBoxLayout, QSlider, QLabel
from PySide6.QtCore import Signal, Qt


class ThresholdSlider(QWidget):
    value_changed = Signal(float)  # emits 0.0–1.0

    def __init__(self, value: float = 0.75, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(10, 100)
        self._slider.setValue(int(value * 100))
        self._slider.setTickInterval(10)

        self._label = QLabel(f"{int(value * 100)}%")
        self._label.setFixedWidth(38)

        layout.addWidget(self._slider)
        layout.addWidget(self._label)

        self._slider.valueChanged.connect(self._on_change)

    def _on_change(self, v: int):
        self._label.setText(f"{v}%")
        self.value_changed.emit(v / 100.0)

    def get_value(self) -> float:
        return self._slider.value() / 100.0

    def set_value(self, v: float):
        self._slider.setValue(int(v * 100))
