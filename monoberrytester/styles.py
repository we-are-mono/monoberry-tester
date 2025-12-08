"""
Styles used on some widgets.
"""

LABEL_DEFAULT       = "QLabel { color: gray; }"
START_BTN           = "QPushButton { background-color: darkgreen; }"
RESET_BTN           = "QPushButton { background-color: darkblue; }"
STATUS_NORMAL       = "QLabel { font-size: 18px; color: white; }"
STATUS_ERROR        = "QLabel { font-size: 18px; color: red; }"

DARK_MODE = """
QWidget {
    background-color: #2b2b2b;
    color: #e0e0e0;
}

QMainWindow {
    background-color: #2b2b2b;
}

QLabel {
    color: #e0e0e0;
    background-color: transparent;
}

QLineEdit {
    background-color: #3c3f41;
    color: #e0e0e0;
    border: 1px solid #555555;
    padding: 4px;
    selection-background-color: #4a4a4a;
}

QLineEdit:disabled {
    background-color: #2b2b2b;
    color: #808080;
    border: 1px solid #3c3f41;
}

QTextEdit {
    background-color: #1e1e1e;
    color: #d4d4d4;
    border: 1px solid #3c3f41;
    selection-background-color: #264f78;
}

QPushButton {
    background-color: #3c3f41;
    color: #e0e0e0;
    border: 1px solid #555555;
    padding: 8px;
    border-radius: 4px;
}

QPushButton:hover {
    background-color: #4a4d50;
    border: 1px solid #6b6b6b;
}

QPushButton:pressed {
    background-color: #2b2b2b;
}

QPushButton:disabled {
    background-color: #2b2b2b;
    color: #606060;
    border: 1px solid #3c3f41;
}

QGroupBox {
    background-color: #2b2b2b;
    border: 1px solid #3c3f41;
    border-radius: 4px;
    margin-top: 8px;
    padding-top: 8px;
    color: #e0e0e0;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 4px;
    color: #e0e0e0;
}

QScrollBar:vertical {
    background-color: #2b2b2b;
    width: 14px;
    border: none;
}

QScrollBar::handle:vertical {
    background-color: #4a4d50;
    min-height: 20px;
    border-radius: 7px;
}

QScrollBar::handle:vertical:hover {
    background-color: #5a5d60;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar:horizontal {
    background-color: #2b2b2b;
    height: 14px;
    border: none;
}

QScrollBar::handle:horizontal {
    background-color: #4a4d50;
    min-width: 20px;
    border-radius: 7px;
}

QScrollBar::handle:horizontal:hover {
    background-color: #5a5d60;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}
"""
