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

TODO: Send logs to our server on success and failure with both QRs
TODO: Put logs somewhere else because /tmp get wiped on reboot
-----
"""

import sys

from PyQt5.QtWidgets import QApplication, QMainWindow

import texts
from ui import UI
from workflow import State, Workflow
from services import LoggingService, ScannerService, SerialService, ServerClient
from tests import TEST_DEFS

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
