# pylint: disable=too-many-instance-attributes
# -*- coding: utf-8 -*-
"""
This is an application that will be running on a Raspberry Pi that will act
as a testing device for our boards (to start with). It will the following
peripherals connected:
- Power supply (duh...)
- HDMI touch screen
- USB barcode scanner
- Ethernet cable if we can't use WiFi

If it is run without command line  arguments it uses testing ones that are
hardcoded (server endpoint, serial port). In production run it like this:
    $ python example_google.py

Section breaks are created by resuming unindented text. Section breaks
are also implicitly created anytime a new section starts.
-----
"""

from enum import Enum, auto
from datetime import datetime

import sys
import logging
import requests
import serial

from PyQt5.QtCore import Qt, QObject, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QHBoxLayout, QVBoxLayout, QGroupBox,
    QWidget, QTextEdit, QLineEdit, QLabel, QPushButton, QSizePolicy
)

import texts
import styles
from tests import TEST_DEFS

class State(Enum):
    """Class to define states of the application"""
    IDLE                        = auto()
    STARTED                     = auto()
    CONNECTING_TO_UART          = auto()
    SCANNING_QR_CODES           = auto()
    FETCHING_SERIAL_AND_MACS    = auto()
    CONNECTING_CABLES           = auto()
    DONE                        = auto()
    FAILED                      = auto()

class TestState(Enum):
    """Class to define possible test states"""
    PENDING =   auto()
    RUNNING =   auto()
    FAILED =    auto()
    SUCCEEDED = auto()

class LoggingService(QObject):
    """Class for logging into a file and on screen to QTextEdit widget
    
    Args:
        text_widget (QTextEdit): Text field to append log statements to
    """

    def __init__(self, text_widget: QTextEdit):
        super().__init__()
        self.text_widget = text_widget
        self.filename = self.__generate_log_filename()
        self.__init_logging(self.filename)

    def info(self, text):
        """Logs text as info"""
        self.text_widget.append("INFO > " + text)
        logging.info(text)

    def error(self, text):
        """Logs text as error"""
        self.text_widget.append("ERROR > " + text)
        logging.error(text)

    def __generate_log_filename(self):
        """Generates a log filename based on current time."""
        return "/tmp/mbt-" + datetime.now().strftime('%Y-%m-%d-%H-%M-%S') + ".log"

    def __init_logging(self, filename):
        """Sets up logging"""
        logging.basicConfig(
            filename    = filename,
            level       = logging.INFO,
            format      = '%(asctime)s - %(message)s'
        )

# TODO: replace with actual code when I get the barcode scanner
class ScannerService(QObject):
    """Class that handles communication with the USB barcode scanner
    
    Attributes:
        code_received (pyqtSignal): Signals when a code is scanned
    """

    code_received = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.buffer = ""

    def handle_input(self, key, text):
        """Reads key presses until a return key is pressed"""
        if key in (Qt.Key_Return, Qt.Key_Enter):
            self.code_received.emit(self.buffer)
            self.buffer = ""
        elif text:
            self.buffer += text

class ServerClient(QThread):
    # pylint: disable=line-too-long
    """HTTP Client to call our server

    Args:
        server_endpoint (str): URL base for our server endpoint
        logging_service (LoggingService): Service for logging
    
    Server one liner for testing locally:
        ncat -lk 8000 -c 'sleep 1; echo "HTTP/1.1 200 OK\r\n\r\nS3R14LNUM83R\n02:00:00:00:00:01\n02:00:00:00:00:02\n02:00:00:00:00:03\n02:00:00:00:00:04\n02:00:00:00:00:05"'
    """
    # pylint: enable=line-too-long

    response_received = pyqtSignal(bool, str)
    error_occured = pyqtSignal(str)

    def __init__(self, server_endpoint, logging_service: LoggingService):
        super().__init__()
        self.logger = logging_service
        self.server_endpoint = server_endpoint
        self.qr1 = None
        self.qr2 = None

    def set_codes(self, codes):
        """
        Sets scanned QR data matrix codes (do this before calling `run` method)
        """
        self.qr1 = codes[0]
        self.qr2 = codes[1]

    def run(self):
        """Runs the thread and fetches serial and MACs from our server"""
        url = self.server_endpoint + "/getserial?qr1=" + self.qr1 + "&qr2=" + self.qr2
        try:
            r = requests.get(url, timeout = 10)
            if r.status_code != 200:
                self.response_received.emit(False, r.text)
            else:
                self.response_received.emit(True, r.text)
        except requests.RequestException as e:
            self.error_occured.emit(str(e))
            self.logger.error(str(e))

class SerialService(QThread):
    """UART client to communicate with our BUTT (board under test tool)

    Attributes:
        connected (pyqtSignal): Signals when UART is successfully connected
        failed (pyqtSignal): Signals when there's an error connecting to UART
        received_data (pyqtSignal): Signals when data is received via UART

    Args:
        port (str): Path to device (TTY) on disk to connect to
    """

    connected = pyqtSignal()
    failed = pyqtSignal(str)
    received_data = pyqtSignal(str)

    def __init__(self, port):
        super().__init__()
        self.timeout = 0.2
        self.port = port
        self.baudrate = 115200
        self.running = False
        self.serial = None

    def run(self):
        """Connects to UART and starts reading data"""
        try:
            self.serial = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
            self.connected.emit()
            self.running = True

            while self.running:
                try:
                    line = self.serial.readline().decode().strip()
                    if line:
                        self.received_data.emit(line)
                        print("S> " + line)
                except serial.SerialException as e:
                    if self.running:
                        self.failed.emit(str(e))
                        break
                self.msleep(10)

        except serial.SerialException as e:
            self.failed.emit(str(e))
        finally:
            if self.serial and self.serial.is_open:
                try:
                    self.serial.close()
                except serial.SerialException as _:
                    pass
            self.running = False

    def stop(self):
        """Stops the connection and waits for thread to finish"""
        self.running = False
        if self.serial and self.serial.is_open:
            try:
                self.serial.close()
            except serial.SerialException as _:
                pass

        if self.isRunning():
            self.wait(1000)

class Workflow(QObject):
    """The class capturing the 'business' logic.
    
    Attributes:
        state_changed (pyqtSignal): Signals the application state has changed
        and provides data about it
        code_scanned (pyqtSignal): Signals that a QR code was scanned and 
        data was received
    
    Args:
        logging_service (LoggingService): Service for logging
        serial_service (SerialService): Service to comminucate via UART
        scanner_service (ScannerService): Service to received scanned QR codes
        server_client (ServerClient): Service to communicate with our server
    """

    state_changed = pyqtSignal(dict)
    code_scanned = pyqtSignal(list)
    test_state_changed = pyqtSignal(str, TestState)

    def __init__(
        self,
        logging_service:   LoggingService,
        serial_service:    SerialService,
        scanner_service:   ScannerService,
        server_client:     ServerClient
    ):
        super().__init__()

        # State
        self.state          = State.IDLE
        self.scanned_codes  = []
        self.mac_addresses  = []
        self.serial_num     = None

        # Services
        self.logger         = logging_service
        self.serial         = serial_service
        self.scanner        = scanner_service
        self.server_client  = server_client

        # Connect to external services signals
        self.scanner.code_received.connect(self.__handle_scanned_codes)
        self.server_client.response_received.connect(self.__handle_server_response)
        self.server_client.error_occured.connect(self.__handle_server_error)
        self.serial.connected.connect(self.__handle_serial_connected)
        self.serial.failed.connect(self.__handle_serial_failed)
        self.serial.received_data.connect(self.__handle_serial_received_data)

    def reset(self):
        """Resets back to idle state in order to do retry upon failure"""
        self.logger.info("--- Reseting ---")
        self.scanned_codes = []
        self.mac_addresses = []
        self.serial_num = None

        if self.serial.isRunning():
            self.serial.stop()

        self.__change_state(State.IDLE)

    def start(self):
        """Entry point to start testing"""
        if self.state != State.IDLE:
            self.logger.info(texts.LOG_WRONG_STATE_TO_START_FROM + str(self.state))
            return

        self.__change_state(State.STARTED)
        self.connect_to_uart()

    def connect_to_uart(self):
        """Tests UART connection to the board"""
        self.__change_state(State.CONNECTING_TO_UART)
        self.test_state_changed.emit("0_conn_to_uart", TestState.RUNNING)
        self.serial.start()

    def scan_qr_codes(self):
        """Prompts user to scan two data matrix codes
        
        Continues in __handle_scanned_codes method"""
        self.test_state_changed.emit("0_conn_to_uart", TestState.SUCCEEDED)
        self.__change_state(State.SCANNING_QR_CODES)
        self.test_state_changed.emit("1_scan_two_dm_qr_codes", TestState.RUNNING)

    def fetch_serial_and_macs(self):
        """Connect to our server to fetch serial and MAC addresses
        based on the provided data matrix QR codes
        
        Continues in __handle_server_response method"""

        self.test_state_changed.emit("1_scan_two_dm_qr_codes", TestState.SUCCEEDED)
        self.__change_state(State.FETCHING_SERIAL_AND_MACS)
        self.test_state_changed.emit("2_fetch_serial_and_macs", TestState.RUNNING)
        self.server_client.set_codes(self.scanned_codes)
        self.server_client.start()

    def connect_cables(self):
        """Prompts user to connect the rest of the cables"""
        self.test_state_changed.emit("2_fetch_serial_and_macs", TestState.SUCCEEDED)
        self.__change_state(State.CONNECTING_CABLES)
        self.test_state_changed.emit("3_receive_data_via_uart", TestState.RUNNING)

    def done(self):
        """Done, all tests have successfull passed and the board is
        fully functional (according to our knowledge)"""
        self.test_state_changed.emit("3_receive_data_via_uart", TestState.SUCCEEDED)
        self.__change_state(State.DONE)
        self.logger.info(texts.LOG_INFO_DONE)

    def key_pressed(self, event):
        """Handler for all key presses.
        But it only forwards to scanner service if scanning QR codes state"""
        if self.state == State.SCANNING_QR_CODES:
            self.scanner.handle_input(event.key(), event.text())

    def __change_state(self, state, msgs = None):
        """Helper to make sure state_changed is emited also on state change"""
        if msgs is None:
            msgs = {}
        self.state = state
        self.state_changed.emit(msgs)

    def __handle_scanned_codes(self, code):
        """Called upon successfully receiving a code from the scanner"""
        self.scanned_codes.append(code)
        self.code_scanned.emit(self.scanned_codes)

        if len(self.scanned_codes) == 1:
            self.logger.info(texts.LOG_INFO_FIRST_CODE_SCANNED + code)
        elif len(self.scanned_codes) == 2:
            self.logger.info(texts.LOG_INFO_SECOND_CODE_SCANNED + code)
            self.fetch_serial_and_macs()
        else:
            self.logger.error(texts.LOG_ERROR_MORE_THAN_2_QR_SCANNED)
            self.test_state_changed.emit("1_scan_two_dm_qr_codes", TestState.FAILED)

    def __handle_server_response(self, success: bool, response: str):
        """Called upon receiving a response from the server"""
        if success:
            self.logger.info(texts.LOG_INFO_SERVER_RESPONSE + response)
            r = response.split()
            self.serial_num = r[0]
            self.mac_addresses = r[1:]
            self.connect_cables()
        else:
            self.logger.error(texts.LOG_INFO_SERVER_ERROR + response)
            self.test_state_changed.emit("2_fetch_serial_and_macs", TestState.FAILED)

    def __handle_server_error(self, err_msg):
        self.test_state_changed.emit("2_fetch_serial_and_macs", TestState.FAILED)
        self.__change_state(State.FAILED, {
            "status": texts.CONN_TO_SERVER_FAILED,
            "err_msg": err_msg
        })

    def __handle_serial_connected(self):
        """Called on successful serial connection"""
        self.logger.info(texts.LOG_INFO_UART_CONNECTED)
        self.scan_qr_codes()

    def __handle_serial_failed(self, err_msg):
        """Called on failed serial connection"""
        self.logger.error(texts.LOG_ERROR_UART_FAILED + err_msg)
        self.__change_state(State.FAILED, {
            "status": texts.STATUS_CONN_TO_UART_FAILED,
            "err_msg": err_msg
        })
        self.test_state_changed.emit("0_conn_to_uart", TestState.FAILED)

    def __handle_serial_received_data(self, data: str):
        """Called when data is received via serial connection"""
        if self.state == State.CONNECTING_CABLES:
            self.logger.info("Serial working. Data was received: " + data)
            self.__change_state(State.DONE)
            self.done()

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

    def __init__(self, test_defs):
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
        self.dm_gr_group_layout = QVBoxLayout()
        self.dm_qr_label_top = QLabel(texts.UI_LABEL_TOP_QR)
        self.dm_qr_line_edit_top = QLineEdit()
        self.dm_qr_line_edit_top.setDisabled(True)
        self.dm_qr_label_bottom = QLabel(texts.UI_LABEL_BOTTOM_QR)
        self.dm_qr_line_edit_bottom = QLineEdit()
        self.dm_qr_line_edit_bottom.setDisabled(True)
        self.dm_gr_group_layout.addWidget(self.dm_qr_label_top)
        self.dm_gr_group_layout.addWidget(self.dm_qr_line_edit_top)
        self.dm_gr_group_layout.addWidget(self.dm_qr_label_bottom)
        self.dm_gr_group_layout.addWidget(self.dm_qr_line_edit_bottom)
        self.dm_qr_group.setLayout(self.dm_gr_group_layout)

        self.log_text_edit = QTextEdit()
        self.log_text_edit.setDisabled(True)
        self.log_text_edit.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.log_text_edit.setDisabled(True)

        self.start_btn = QPushButton(texts.UI_START_BTN_LABEL_START)
        self.reset_btn.setEnabled(False)

        # Assemble UI
        left_panel.addWidget(self.reset_btn)
        left_panel.addWidget(self.label)
        left_panel.addWidget(self.dm_qr_group)
        left_panel.addWidget(self.log_text_edit)
        left_panel.addWidget(self.start_btn)

        for name in self.tests:
            right_panel.addWidget(self.tests[name])

        right_panel.addStretch()

        layout.addLayout(left_panel, stretch=1)
        layout.addLayout(right_panel, stretch=2)
        self.setLayout(layout)

    def __init_tests_widgets(self, test_defs):
        """Create UI for tests"""
        test_widgets = {}
        for name in test_defs:
            desc = test_defs[name]
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

    def update_status(self, text, err=False):
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
        match state:
            case TestState.PENDING:
                self.tests[name].set_idle()
            case TestState.RUNNING:
                self.tests[name].set_running()
            case TestState.SUCCEEDED:
                self.tests[name].set_success()
            case TestState.FAILED:
                self.tests[name].set_failure()

    def mark_all_tests_idle(self):
        """Marks all tests as idle (on reset for example)"""
        for name, _ in self.tests:
            self.tests[name].set_idle()

class Main(QMainWindow):
    """Class representing PyQt5 window
    
    Args:
        server_endpoint (str): Base url for our server endpoint
        serial_port (str): Path to device (TTY) on disk to connect to
    """
    def __init__(self, server_endpoint, serial_port):
        super().__init__()

        # Init UI
        self.ui = UI(TEST_DEFS)
        self.setCentralWidget(self.ui)
        self.resize(1280, 720)

        # Init services
        self.logger         = LoggingService(self.ui.log_text_edit)
        self.serial         = SerialService(serial_port)
        self.scanner        = ScannerService()
        self.server_client  = ServerClient(server_endpoint, self.logger)
        self.workflow       = Workflow(self.logger, self.serial, self.scanner, self.server_client)

        self.ui.start_btn.clicked.connect(self.workflow.start)
        self.ui.reset_btn.clicked.connect(self.workflow.reset)
        self.workflow.code_scanned.connect(self.__update_scanned_codes)
        self.workflow.state_changed.connect(self.__update_ui)
        self.workflow.test_state_changed.connect(self.__update_test_ui)

        self.state_handlers = {
            State.IDLE:                     self.__update_ui_idle,
            State.STARTED:                  self.__update_ui_started,
            State.CONNECTING_TO_UART:       self.__update_ui_connecting_to_uart,
            State.SCANNING_QR_CODES:        self.__update_ui_scanning_qr_codes,
            State.FETCHING_SERIAL_AND_MACS: self.__update_ui_fetching_serial_and_macs,
            State.CONNECTING_CABLES:        self.__update_ui_connecting_cables,
            State.DONE:                     self.__update_ui_done,
            State.FAILED:                   self.__update_ui_failed
        }

    def __update_scanned_codes(self, codes):
        """Updates UI with both scanned codes"""
        if len(codes) == 1:
            self.ui.update_status(texts.STATUS_SCAN_QR_BOTTOM)
            self.ui.set_dm_qr_top(codes[0])
        elif len(codes) == 2:
            self.ui.set_dm_qr_bottom(codes[1])

    def __update_test_ui(self, name, state):
        self.ui.set_test_state(name, state)

    def __update_ui(self, msgs):
        """Generic method to update UI on state change"""
        state = self.workflow.state
        handler = self.state_handlers.get(state)
        if msgs:
            handler(msgs)
        else:
            handler()

    def __update_ui_idle(self):
        """Updates UI to reflect idle state"""
        self.ui.update_status(texts.STATUS_READY_TO_START)
        self.ui.clear_qr_codes()
        self.ui.start_btn_enable()
        self.ui.reset_btn_disable()
        self.ui.mark_all_tests_idle()

    def __update_ui_started(self):
        """Updates UI to reflect started state"""
        self.ui.start_btn_disable()
        self.ui.reset_btn_enable()

    def __update_ui_connecting_to_uart(self):
        """Updates UI to reflect connecting to UART state"""
        self.ui.update_status(texts.STATUS_CONN_TO_UART)

    def __update_ui_scanning_qr_codes(self):
        """Updates UI to reflect scanning QR codes state"""
        self.ui.update_status(texts.STATUS_SCAN_QR_TOP)

    def __update_ui_fetching_serial_and_macs(self):
        """Updates UI to reflect fetching serial and macs state"""
        self.ui.update_status(texts.STATUS_GET_SER_MACS)

    def __update_ui_connecting_cables(self):
        """Updates UI to reflect connecting cables state"""
        self.ui.update_status(texts.STATUS_CONNECT_CABLES)

    def __update_ui_done(self):
        """Updates UI to reflect done state"""
        self.ui.update_status(texts.STATUS_DONE)

    def __update_ui_failed(self, msgs):
        """Updates UI to reflect failed state"""
        self.ui.update_status(msgs["status"], err = True)

    def keyPressEvent(self, event): # pylint: disable=invalid-name
        """Listens for key presses and forward them to workflow class"""
        self.workflow.key_pressed(event)

def main():
    """App entrypoint"""
    app = QApplication(sys.argv)

    server_endpoint = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    serial_port = sys.argv[2] if len(sys.argv) > 2 else "/tmp/ttyMBT01"

    window = Main(server_endpoint, serial_port)
    window.show()
    # window.showFullScreen()
    app.exec()

if __name__ == "__main__":
    main()
