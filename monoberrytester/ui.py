# pylint: disable=too-many-instance-attributes

"""
All (only) UI related code
"""

from enum import Enum, auto

from PyQt5.QtWidgets import (
    QHBoxLayout, QVBoxLayout, QGroupBox,
    QWidget, QTextEdit, QLineEdit, QLabel, QPushButton
)

import texts
import styles

class TestState(Enum):
    """Class to define possible test states"""
    PENDING =   auto()
    RUNNING =   auto()
    FAILED =    auto()
    SUCCEEDED = auto()

class TestWidget(QWidget):
    """Class that represents a test widget (a color indicator and text)
    
    Args:
        description (str): Test description
    """

    def __init__(self, description):
        super().__init__()
        self.indicator = QLabel("●")
        self.indicator.setFixedSize(16, 16)
        self.label = QLabel(description)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(16)
        layout.addWidget(self.indicator)
        layout.addWidget(self.label)

        self.set_idle()

    def set_idle(self):
        """Mark it as idle (gray color)"""
        self.indicator.setStyleSheet("color: gray;")

    def set_running(self):
        """Mark it as running (yellow color)"""
        self.indicator.setStyleSheet("color: yellow;")

    def set_success(self):
        """Mark it as successful (green color)"""
        self.indicator.setStyleSheet("color: green;")

    def set_failure(self):
        """Mark it as failed (red color)"""
        self.indicator.setStyleSheet("color: red;")

class UI(QWidget):
    """Class capturing all UI logic and operations
    
    Args:
        test_defs (dict): dictionary of test names and descriptions
    """

    def __init__(self, test_defs: dict):
        super().__init__()
        self.tests = self.__init_tests_widgets(test_defs)
        self.__init_ui()

    def __init_ui(self):
        self.setContentsMargins(8, 8, 8, 8)

        layout = QHBoxLayout()
        left_panel = QVBoxLayout()
        right_panel = QVBoxLayout()

        # Create UI
        self.reset_btn = QPushButton(texts.UI_RESET_BTN_LABEL)
        self.label = QLabel(texts.STATUS_READY_TO_START)
        self.label.setStyleSheet(styles.STATUS_NORMAL)
        self.label.setContentsMargins(8, 16, 0, 16)

        self.dm_qr_group = QGroupBox()
        self.dm_qr_group_layout = QVBoxLayout()
        self.dm_qr_label_top = QLabel(texts.UI_LABEL_TOP_QR)
        self.dm_qr_line_edit_top = QLineEdit()
        self.dm_qr_line_edit_top.setDisabled(True)
        self.dm_qr_label_bottom = QLabel(texts.UI_LABEL_BOTTOM_QR)
        self.dm_qr_line_edit_bottom = QLineEdit()
        self.dm_qr_line_edit_bottom.setDisabled(True)
        self.dm_qr_group_layout.addWidget(self.dm_qr_label_top)
        self.dm_qr_group_layout.addWidget(self.dm_qr_line_edit_top)
        self.dm_qr_group_layout.addWidget(self.dm_qr_label_bottom)
        self.dm_qr_group_layout.addWidget(self.dm_qr_line_edit_bottom)
        self.dm_qr_group.setLayout(self.dm_qr_group_layout)

        self.log_text_edit = QTextEdit()
        self.log_text_edit.setDisabled(True)

        self.start_btn = QPushButton(texts.UI_START_BTN_LABEL_START)
        self.reset_btn.setEnabled(False)

        # Assemble UI
        left_panel.addWidget(self.reset_btn)
        left_panel.addWidget(self.label)
        left_panel.addWidget(self.dm_qr_group)
        left_panel.addWidget(self.log_text_edit)
        left_panel.addWidget(self.start_btn)

        for t in self.tests.values():
            right_panel.addWidget(t)

        right_panel.addStretch()

        layout.addLayout(left_panel, stretch=1)
        layout.addLayout(right_panel, stretch=2)
        self.setLayout(layout)

    def __init_tests_widgets(self, test_defs: dict) -> dict:
        """Create UI for tests"""
        test_widgets = {}
        for name, desc in test_defs.items():
            test_widgets[name] = TestWidget(desc)

        return test_widgets

    def start_btn_enable(self):
        """Enables start button"""
        self.start_btn.setDisabled(False)

    def start_btn_disable(self):
        """Disables start button"""
        self.start_btn.setDisabled(True)

    def reset_btn_enable(self):
        """Enables reset button"""
        self.reset_btn.setDisabled(False)

    def reset_btn_disable(self):
        """Disables reset button"""
        self.reset_btn.setDisabled(True)

    def update_status(self, text: str, err: bool = False):
        """Updates status label with text and error indicator: err"""
        self.label.setText(text)

        if err:
            self.label.setStyleSheet(styles.STATUS_ERROR)
        else:
            self.label.setStyleSheet(styles.STATUS_NORMAL)

    def set_dm_qr_top(self, code: str):
        """Updates top scanned QR text field"""
        self.dm_qr_line_edit_top.setText(code)

    def set_dm_qr_bottom(self, code: str):
        """Updates bottom scanned QR text field"""
        self.dm_qr_line_edit_bottom.setText(code)

    def clear_qr_codes(self):
        """Clears both QR codes text fields"""
        self.dm_qr_line_edit_top.setText("")
        self.dm_qr_line_edit_bottom.setText("")

    def set_test_state(self, name, state):
        """Sets a state for a single test"""
        if state is TestState.PENDING:
            self.tests[name].set_idle()
        elif state is TestState.RUNNING:
            self.tests[name].set_running()
        elif state is TestState.SUCCEEDED:
            self.tests[name].set_success()
        elif state is TestState.FAILED:
            self.tests[name].set_failure()

    def mark_all_tests_idle(self):
        """Marks all tests as idle (on reset for example)"""
        for t in self.tests.values():
            t.set_idle()
