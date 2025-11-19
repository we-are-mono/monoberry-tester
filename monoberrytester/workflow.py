# pylint: disable=too-many-instance-attributes

"""
All 'business' logic
"""

from enum import Enum, auto
from PyQt5.QtCore import QObject, QThread, pyqtSignal

import texts
from ui import TestState
from tests import TestKeys

from services import *

class State(Enum):
    """Class to define states of the application"""
    IDLE                        = auto()
    STARTED                     = auto()
    CONNECTING_TO_UART          = auto()
    SCANNING_QR_CODES           = auto()
    FETCHING_SERIAL_AND_MACS    = auto()
    CONNECTING_CABLES           = auto()
    WAITING_FOR_UBOOT           = auto()
    DONE                        = auto()
    FAILED                      = auto()

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
        serial_controller (SerialController): Service to wait for text and send text to serial
        process_runner (ProcessService): Service managing running processes and reading and sending data to/from them
    """

    state_changed = pyqtSignal(dict)
    code_scanned = pyqtSignal(list)
    test_state_changed = pyqtSignal(TestKeys, TestState)

    def __init__(
        self,
        logging_service: LoggingService,
        serial_service: SerialService,
        scanner_service: ScannerService,
        server_client: ServerClient,
        serial_controller: SerialController,
        process_runner: ProcessService
    ):
        super().__init__()

        # State
        self.state          = State.IDLE
        self.scanned_codes  = []
        self.mac_addresses  = []
        self.serial_num     = None

        # Services
        self.logger             = logging_service
        self.serial             = serial_service
        self.scanner            = scanner_service
        self.server_client      = server_client
        self.serial_controller  = serial_controller
        self.process_runner     = process_runner

        # Connect to external services signals
        self.scanner.code_received.connect(self.__handle_scanned_codes)
        self.server_client.response_received.connect(self.__handle_server_response)
        self.server_client.error_occured.connect(self.__handle_server_error)
        self.serial.connected.connect(self.__handle_serial_connected)
        self.serial.error_occurred.connect(self.__handle_serial_error_occured)
        self.serial.line_received.connect(self.__log_serial)

        self.server_thread = QThread()
        self.server_client.moveToThread(self.server_thread)
        self.server_thread.started.connect(self.server_client.run)

        self.serial_thread = QThread()
        self.serial.moveToThread(self.serial_thread)
        self.serial_thread.started.connect(self.serial.run)

    def reset(self):
        """Resets back to idle state in order to do retry upon failure"""
        self.logger.info("--- Reseting ---")
        self.scanned_codes = []
        self.mac_addresses = []
        self.serial_num = None
        self.logger.reinit()
        self.serial.stop()
        self.serial_thread.quit()
        self.serial_thread.wait()

        self.__change_state(State.IDLE)

    def start(self):
        """Entry point to start testing"""
        if self.state != State.IDLE:
            self.logger.info(f"{texts.LOG_WRONG_STATE_TO_START_FROM} {self.state}")
            return

        self.__change_state(State.STARTED)
        self.connect_to_uart()

    def connect_to_uart(self):
        """Tests UART connection to the board"""
        self.__change_state(State.CONNECTING_TO_UART)
        self.test_state_changed.emit(TestKeys.T0_CONN_TO_UART, TestState.RUNNING)
        self.serial_thread.start()

    def scan_qr_codes(self):
        """Prompts user to scan two data matrix codes

        Continues in __handle_scanned_codes method"""
        self.test_state_changed.emit(TestKeys.T0_CONN_TO_UART, TestState.SUCCEEDED)
        self.__change_state(State.SCANNING_QR_CODES)
        self.test_state_changed.emit(TestKeys.T1_SCAN_TWO_DM_QR_CODES, TestState.RUNNING)

    def fetch_serial_and_macs(self):
        """Connect to our server to fetch serial and MAC addresses
        based on the provided data matrix QR codes
        Continues in __handle_server_response method"""
        self.test_state_changed.emit(TestKeys.T1_SCAN_TWO_DM_QR_CODES, TestState.SUCCEEDED)
        self.__change_state(State.FETCHING_SERIAL_AND_MACS)
        self.test_state_changed.emit(TestKeys.T2_FETCH_SERIAL_AND_MACS, TestState.RUNNING)
        self.server_client.set_codes(self.scanned_codes)
        self.server_client.send_qrs()
        if not self.server_thread.isRunning():
            self.server_thread.start()

    def connect_cables(self):
        """Prompts user to connect the rest of the cables"""
        self.test_state_changed.emit(TestKeys.T2_FETCH_SERIAL_AND_MACS, TestState.SUCCEEDED)
        self.__change_state(State.CONNECTING_CABLES)
        self.test_state_changed.emit(TestKeys.T3_RECEIVE_DATA_VIA_UART, TestState.RUNNING)
        self.serial_controller.wait_for("", self.__handle_serial_line_received)

    def wait_for_uboot(self):
        """Wait for u-boot prompt"""
        self.test_state_changed.emit(TestKeys.T3_RECEIVE_DATA_VIA_UART, TestState.SUCCEEDED)
        self.serial_controller.wait_for_and_send("stop autoboot", "STOP!\r\n", self.done)
        self.test_state_changed.emit(TestKeys.T4_RECEIVE_UBOOT_PROMPT, TestState.RUNNING)

    def done(self):
        """Done, all tests have successfull passed and the board is
        fully functional (according to our knowledge)"""
        self.test_state_changed.emit(TestKeys.T4_RECEIVE_UBOOT_PROMPT, TestState.SUCCEEDED)
        self.__change_state(State.DONE)
        self.logger.info(texts.LOG_INFO_DONE)

    def key_pressed(self, event):
        """Handler for all key presses.
        But it only forwards to scanner service if scanning QR codes state"""
        if self.state == State.SCANNING_QR_CODES:
            self.scanner.handle_input(event.key(), event.text())

    def __change_state(self, state, msgs=None):
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
            self.logger.info(f"{texts.LOG_INFO_FIRST_CODE_SCANNED} {code}")
        elif len(self.scanned_codes) == 2:
            self.logger.info(f"{texts.LOG_INFO_SECOND_CODE_SCANNED} {code}")
            self.fetch_serial_and_macs()
        else:
            self.logger.error(texts.LOG_ERROR_MORE_THAN_2_QR_SCANNED)
            self.test_state_changed.emit(TestKeys.T1_SCAN_TWO_DM_QR_CODES, TestState.FAILED)

    def __handle_server_response(self, success: bool, response: str):
        """Called upon receiving a response from the server"""
        self.server_thread.quit()
        self.server_thread.wait()

        if success:
            self.logger.info(f"{texts.LOG_INFO_SERVER_RESPONSE} {response}")
            r = response.split()
            self.serial_num = r[0]
            self.mac_addresses = r[1:]
            self.connect_cables()
        else:
            self.logger.error(f"{texts.LOG_INFO_SERVER_ERROR} {response}")
            self.test_state_changed.emit(TestKeys.T2_FETCH_SERIAL_AND_MACS, TestState.FAILED)

    def __handle_server_error(self, err_msg):
        self.server_thread.quit()
        self.server_thread.wait()

        self.test_state_changed.emit(TestKeys.T2_FETCH_SERIAL_AND_MACS, TestState.FAILED)
        self.__change_state(State.FAILED, {
            "status": texts.CONN_TO_SERVER_FAILED,
            "err_msg": err_msg
        })

    def __handle_serial_connected(self):
        """Called on successful serial connection"""
        self.logger.info(texts.LOG_INFO_UART_CONNECTED)
        self.scan_qr_codes()

    def __handle_serial_error_occured(self, err_msg):
        """Called on failed serial connection"""
        self.logger.error(f"{texts.LOG_ERROR_UART_FAILED} {err_msg}")
        self.__change_state(State.FAILED, {
            "status": texts.STATUS_CONN_TO_UART_FAILED,
            "err_msg": err_msg
        })
        self.test_state_changed.emit(TestKeys.T0_CONN_TO_UART, TestState.FAILED)

    def __handle_serial_line_received(self):
        """Called when data is received via serial connection"""
        if self.state == State.CONNECTING_CABLES:
            self.logger.info(texts.LOG_INFO_UART_DATA_RECEIVED)
            self.__change_state(State.WAITING_FOR_UBOOT)
            self.wait_for_uboot()

    def __log_serial(self, data: str):
        self.logger.info("S> " + data, False)
