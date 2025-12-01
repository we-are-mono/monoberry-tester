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
hardcoded (server endpoint, serial port).

TODO: Send logs to our server on success and failure with both QRs
TODO: Put logs somewhere else because /tmp get wiped on reboot
-----
"""

import sys

from PyQt5.QtWidgets import QApplication, QMainWindow

import texts
from ui import UI
from workflow import State, Workflow
from services import *
from tests import TestKeys

class Main(QMainWindow):
    """Class representing PyQt5 window
    
    Args:
        server_endpoint (str): Base url for our server endpoint
        serial_port (str): Path to device (TTY) on disk to connect to
    """
    def __init__(self, server_endpoint, api_key, serial_port, ftx_prog_path, ccs_tools_path):
        super().__init__()

        # Init UI
        self.ui = UI(TestKeys)
        self.setCentralWidget(self.ui)
        self.resize(1920, 1080)

        # Init services
        self.logger             = LoggingService()
        self.serial             = SerialService(serial_port)
        self.serial_controller  = SerialController(self.serial)
        self.scanner            = ScannerService()
        self.server_client      = ServerClient(server_endpoint, api_key, self.logger)
        self.process_runner     = ProcessService(self.logger)
        self.process_controller = ProcessController(self.process_runner)
        self.usb_service        = UsbService(serial_port)
        self.workflow           = Workflow(
                                    self.logger,
                                    self.serial,
                                    self.scanner,
                                    self.server_client,
                                    self.serial_controller,
                                    self.process_runner,
                                    self.process_controller,
                                    self.usb_service,
                                    ftx_prog_path,
                                    ccs_tools_path
                                )

        self.logger.logline_received.connect(self.__update_logs_ui)
        self.ui.start_btn.clicked.connect(self.workflow.start)
        self.ui.reset_btn.clicked.connect(self.workflow.reset)
        self.workflow.code_scanned.connect(self.__update_scanned_codes)
        self.workflow.serial_scanned.connect(self.__update_serial)
        self.workflow.state_changed.connect(self.__update_ui)
        self.workflow.test_state_changed.connect(self.__update_test_ui)

    def __update_logs_ui(self, text, is_error, should_display):
        if not should_display:
            return

        if not is_error:
            self.ui.log_text_edit.append(f"[INFO] {text}")
        else:
            self.ui.log_text_edit.append(f"[ERROR] {text}")

    def __update_scanned_codes(self, codes):
        """Updates UI with both scanned codes"""
        if len(codes) == 1:
            self.ui.update_status(texts.STATUS_SCAN_QR_BOTTOM)
            self.ui.set_dm_qr_top(codes[0])
        elif len(codes) == 2:
            self.ui.set_dm_qr_bottom(codes[1])

    def __update_serial(self, serial):
        """Updates UI for serial number"""
        self.ui.set_dm_qr_serial(serial)

    def __update_test_ui(self, name, state):
        """Updates state for a given test"""
        self.ui.set_test_state(name, state)

    def __update_ui(self, state, message):
        """Generic method to update UI on state change"""
        # Handle state-specific UI changes
        if state == State.IDLE:
            self.ui.clear_qr_codes()
            self.ui.start_btn_enable()
            self.ui.reset_btn_disable()
            self.ui.mark_all_tests_idle()
        elif state == State.RUNNING:
            self.ui.start_btn_disable()
            self.ui.reset_btn_enable()

        # Update status message
        is_error = (state == State.FAILED)
        if message:
            self.ui.update_status(message, is_err=is_error)

    def keyPressEvent(self, event): # pylint: disable=invalid-name
        """Listens for key presses and forward them to workflow class"""
        self.workflow.key_pressed(event)

    def closeEvent(self, event): # pylint: disable=invalid-name
        """Handle window close event to ensure proper cleanup"""
        self.workflow.reset()
        event.accept()

def main():
    """App entrypoint"""
    app = QApplication(sys.argv)

    server_endpoint = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    api_key = sys.argv[2] if len(sys.argv) > 2 else "FAKE-API-KEY"
    serial_port = sys.argv[3] if len(sys.argv) > 3 else "/tmp/ttyMBT01"
    ftx_prog_path = sys.argv[4] if len(sys.argv) > 4 else "~/.local/bin/ftx_prog"
    ccs_tools_path = sys.argv[5] if len(sys.argv) > 5 else "/home/rdme"

    window = Main(server_endpoint, api_key, serial_port, ftx_prog_path, ccs_tools_path)
    window.show()
    # window.showFullScreen()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
