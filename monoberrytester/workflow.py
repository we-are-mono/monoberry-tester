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
    SCANNING_SERIAL_NUM         = auto()
    SCANNING_QR_CODES           = auto()
    REGISTERING_DEVICE          = auto()
    LOADING_UBOOT_VIA_JTAG      = auto()
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
    serial_scanned = pyqtSignal(str)
    code_scanned = pyqtSignal(list)
    test_state_changed = pyqtSignal(TestKeys, TestState)

    def __init__(
        self,
        logging_service: LoggingService,
        serial_service: SerialService,
        scanner_service: ScannerService,
        server_client: ServerClient,
        serial_controller: SerialController,
        process_runner: ProcessService,
        process_controller: ProcessController
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
        self.process_controller = process_controller

        # Setup threads for services
        self.server_thread = QThread()
        self.server_client.moveToThread(self.server_thread)
        self.server_thread.started.connect(self.server_client.run)

        self.serial_thread = QThread()
        self.serial.moveToThread(self.serial_thread)
        self.serial_thread.started.connect(self.serial.run)

        # Connect persistent logging handler
        self.serial.line_received.connect(self.__log_serial)

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
        self.process_runner.stop()

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

        def handle_serial_connected():
            """Called on successful serial connection"""
            self.serial.connected.disconnect(handle_serial_connected)
            self.serial.error_occurred.disconnect(handle_serial_error_occurred)

            self.logger.info(texts.LOG_INFO_UART_CONNECTED)
            self.scan_serial_num()

        def handle_serial_error_occurred(err_msg):
            """Called on failed serial connection"""
            self.serial.connected.disconnect(handle_serial_connected)
            self.serial.error_occurred.disconnect(handle_serial_error_occurred)

            self.logger.error(f"{texts.LOG_ERROR_UART_FAILED} {err_msg}")
            self.__change_state(State.FAILED, {
                "status": texts.STATUS_CONN_TO_UART_FAILED,
                "err_msg": err_msg
            })
            self.test_state_changed.emit(TestKeys.CONN_TO_UART, TestState.FAILED)

        self.__change_state(State.CONNECTING_TO_UART)
        self.test_state_changed.emit(TestKeys.CONN_TO_UART, TestState.RUNNING)

        self.serial.connected.connect(handle_serial_connected)
        self.serial.error_occurred.connect(handle_serial_error_occurred)

        self.serial_thread.start()

    def scan_serial_num(self):
        """Prompts the user to scan the serial number"""

        def handle_scanned_serial(code):
            """Called upon successfully receiving serial number from scanner"""
            self.scanner.code_received.disconnect(handle_scanned_serial)

            self.serial_num = code
            self.serial_scanned.emit(self.serial_num)
            self.scan_qr_codes()

        self.test_state_changed.emit(TestKeys.CONN_TO_UART, TestState.SUCCEEDED)
        self.__change_state(State.SCANNING_SERIAL_NUM)
        self.test_state_changed.emit(TestKeys.SCAN_SERIAL_NUM, TestState.RUNNING)

        self.scanner.code_received.connect(handle_scanned_serial)

    def scan_qr_codes(self):
        """Prompts user to scan two data matrix codes"""

        def handle_scanned_qr(code):
            """Called upon successfully receiving QR code from scanner"""
            self.scanned_codes.append(code)
            self.code_scanned.emit(self.scanned_codes)

            if len(self.scanned_codes) == 1:
                self.logger.info(f"{texts.LOG_INFO_FIRST_CODE_SCANNED} {code}")
            elif len(self.scanned_codes) == 2:
                self.scanner.code_received.disconnect(handle_scanned_qr)

                self.logger.info(f"{texts.LOG_INFO_SECOND_CODE_SCANNED} {code}")
                self.register_device_and_get_macs()
            else:
                self.scanner.code_received.disconnect(handle_scanned_qr)

                self.logger.error(texts.LOG_ERROR_MORE_THAN_2_QR_SCANNED)
                self.test_state_changed.emit(TestKeys.SCAN_TWO_DM_QR_CODES, TestState.FAILED)

        self.test_state_changed.emit(TestKeys.SCAN_SERIAL_NUM, TestState.SUCCEEDED)
        self.__change_state(State.SCANNING_QR_CODES)
        self.test_state_changed.emit(TestKeys.SCAN_TWO_DM_QR_CODES, TestState.RUNNING)

        self.scanner.code_received.connect(handle_scanned_qr)

    def register_device_and_get_macs(self):
        """Connect to our server to register device and get MAC addresses
        based on the serial and provided data matrix QR codes"""

        def handle_server_response(success: bool, response: str):
            """Called upon receiving a response from the server"""
            self.server_client.response_received.disconnect(handle_server_response)
            self.server_client.error_occured.disconnect(handle_server_error)

            self.server_thread.quit()
            self.server_thread.wait()

            if success:
                self.logger.info(f"{texts.LOG_INFO_SERVER_RESPONSE} {response}")
                r = response.split()
                self.serial_num = r[0]
                self.mac_addresses = r[1:]
                self.load_uboot_via_jtag()
            else:
                self.logger.error(f"{texts.LOG_INFO_SERVER_ERROR} {response}")
                self.test_state_changed.emit(TestKeys.REGISTER_DEVICE, TestState.FAILED)

        def handle_server_error(err_msg):
            """Called upon server connection error"""
            self.server_client.response_received.disconnect(handle_server_response)
            self.server_client.error_occured.disconnect(handle_server_error)

            self.server_thread.quit()
            self.server_thread.wait()

            self.test_state_changed.emit(TestKeys.REGISTER_DEVICE, TestState.FAILED)
            self.__change_state(State.FAILED, {
                "status": texts.CONN_TO_SERVER_FAILED,
                "err_msg": err_msg
            })

        self.test_state_changed.emit(TestKeys.SCAN_TWO_DM_QR_CODES, TestState.SUCCEEDED)
        self.__change_state(State.REGISTERING_DEVICE)
        self.test_state_changed.emit(TestKeys.REGISTER_DEVICE, TestState.RUNNING)

        self.server_client.response_received.connect(handle_server_response)
        self.server_client.error_occured.connect(handle_server_error)

        self.server_client.set_params(self.serial_num, self.scanned_codes)
        self.server_client.send_qrs()
        if not self.server_thread.isRunning():
            self.server_thread.start()

    def load_uboot_via_jtag(self):
        """Init board and load U-Boot in memory via external program"""

        def handle_process_output_received(text):
            """Called when program outputs something to stdout"""
            self.logger.info(text)

        def handle_process_error_received(err_msg):
            """Called when program outputs something to stderr"""
            self.logger.error(err_msg)

        def handle_process_errored(err_msg):
            """Called when process errors out"""
            self.logger.error(f"{texts.LOG_PROCESS_ERRORED} {err_msg}")
            self.__change_state(State.FAILED, {
                "status": texts.STATUS_PROCESS_ERRORED,
                "err_msg": err_msg
            })

        def handle_process_finished(return_code):
            """Called when process returns/exits"""
            self.logger.info(f"{texts.LOG_PROCESS_EXITED} {return_code}")
            if return_code == 0:
                pass
            else:
                self.logger.error(texts.LOG_PROCESS_EXITED_NON_0_CODE)

        def handle_exiting():
            self.process_runner.stop()
            self.wait_for_uboot()

        self.test_state_changed.emit(TestKeys.REGISTER_DEVICE, TestState.SUCCEEDED)
        self.__change_state(State.LOADING_UBOOT_VIA_JTAG)
        self.test_state_changed.emit(TestKeys.LOAD_UBOOT_VIA_JTAG, TestState.RUNNING)

        self.process_runner.output_received.connect(handle_process_output_received)
        self.process_runner.error_received.connect(handle_process_error_received)
        self.process_runner.process_errored.connect(handle_process_errored)
        self.process_runner.process_finished.connect(handle_process_finished)

        self.process_controller.wait_for("lsbp.tcl is exiting...", handle_exiting)
        self.process_runner.start("/home/rdme/CCS/bin/ccs", ["-nogfx", "-console", "-file", "/home/rdme/TAP/lsbp.tcl"])

    def wait_for_uboot(self):
        """Wait for u-boot prompt"""
        self.test_state_changed.emit(TestKeys.LOAD_UBOOT_VIA_JTAG, TestState.SUCCEEDED)
        # self.serial_controller.wait_for("=>", self.done)
        # self.serial_controller.send("\r\n")
        self.serial_controller.wait_for_and_send("stop autoboot", "\r\n", self.done)
        self.test_state_changed.emit(TestKeys.RECEIVE_UBOOT_PROMPT, TestState.RUNNING)

    def done(self):
        """Done, all tests have successfull passed and the board is
        fully functional (according to our knowledge)"""
        self.test_state_changed.emit(TestKeys.RECEIVE_UBOOT_PROMPT, TestState.SUCCEEDED)
        self.__change_state(State.DONE)
        self.logger.info(texts.LOG_INFO_DONE)

    def key_pressed(self, event):
        """Handler for all key presses.
        But it only forwards to scanner service if scanning QR codes state"""
        if self.state in (State.SCANNING_QR_CODES, State.SCANNING_SERIAL_NUM):
            self.scanner.handle_input(event.key(), event.text())

    def __change_state(self, state, msgs=None):
        """Helper to make sure state_changed is emited also on state change"""
        if msgs is None:
            msgs = {}
        self.state = state
        self.state_changed.emit(msgs)

    def __log_serial(self, data: str):
        """Persistent handler for logging all serial data"""
        self.logger.info(data, False)
