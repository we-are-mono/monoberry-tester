from enum import Enum, auto
from PyQt5.QtCore import QObject, pyqtSignal

import texts
from ui import TestState

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
        logging_service,
        serial_service,
        scanner_service,
        server_client
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