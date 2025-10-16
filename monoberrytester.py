import sys, logging, requests, serial
from enum import Enum, auto
from datetime import datetime

from PyQt5.QtCore import Qt, QObject, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QHBoxLayout, QVBoxLayout, QGroupBox,
    QWidget, QTextEdit, QLineEdit, QLabel, QPushButton
)

TEST_CASES_DATA = {
    "uart_connect":             "UART: initial connection",
    "both_dm_qrs_scanned":      "SCAN: Both data matrix QR codes scanned correctly",
    "serial_and_macs_received": "SERVER: Serial and MAC addresses received"
}

class Texts:
    status_ready_to_start               = "Plug in UART cable and click START"
    status_conn_to_uart                 = "Connecting to UART"
    status_conn_to_uart_failed          = "Connection to UART failed!"
    status_scan_qr_top                  = "Scan the TOP data matrix QR code"
    status_scan_qr_bottom               = "Scan the BOTTOM data matrix QR code"
    status_get_ser_macs                 = "Fetching serial and MACs"
    status_connect_cables               = "Connect cables"
    status_done                         = "All tests successful!"
    ui_start_btn_label_start            = "Start"
    ui_start_btn_label_cont             = "Continue"
    ui_reset_btn_label                  = "Reset"
    ui_label_top_qr                     = "Top data matrix (QR code)"
    ui_label_bottom_qr                  = "Top data matrix (QR code)"
    ui_label_qr_group                   = "Data matrix QR codes"
    log_info_uart_connected             = "Connected to UART"
    log_error_uart_failed               = "UART connection FAILED: "
    log_info_first_code_scanned         = "First code scanned: "
    log_info_second_code_scanned        = "Second code scanned: "
    log_error_wrong_state_to_start_from = "Can not start from state: "
    log_error_more_than_2_qr_scanned    = "More than 2 dm qr codes scanned somehow!"
    log_info_server_response            = "Recevied response from server:\n"
    log_info_server_error               = "Recevied ERROR from server:\n"
    log_info_done                       = "Done!"

class Styles:
    label_default       = "QLabel { color: gray; }"
    start_btn_idle      = "QPushButton { background-color: darkblue; }"
    start_btn_continue  = "QPushButton { background-color: darkgreen; }"
    start_btn_disabled  = "QPushButton { background-color: #222; }"
    reset_btn           = "QPushButton { background-color: darkred; }"
    status_normal       = "QLabel { font-size: 18px; color: white; }"
    status_error        = "QLabel { color: red; }"

class State(Enum):
    IDLE                        = auto()
    STARTED                     = auto()
    CONNECTING_TO_UART          = auto()
    SCANNING_QR_CODES           = auto()
    FETCHING_SERIAL_AND_MACS    = auto()
    CONNECTING_CABLES           = auto()
    DONE                        = auto()
    FAILED                      = auto()

# Add Log class that adds log statements to the text field
# and writes/appends them also to a log file
class LoggingService(QObject):
    def __init__(self, text_widget: QTextEdit):
        super().__init__()
        self.text_widget = text_widget     
        self.filename = self.__generate_log_filename()
        self.__init_logging(self.filename)

    def info(self, text):
        self.text_widget.append("INFO > " + text)
        logging.info(text)

    def error(self, text):
        self.text_widget.append("ERROR > " + text)
        logging.error(text)

    def __generate_log_filename(self):
        return "/tmp/mbt-" + datetime.now().strftime('%Y-%m-%d-%H-%M-%S') + ".log"

    def __init_logging(self, filename):
        logging.basicConfig(
            filename    = filename,
            level       = logging.INFO,
            format      = '%(asctime)s - %(message)s'
        )

# TODO: replace with actual code when I get the barcode scanner
class ScannerService(QObject):
    code_received = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.buffer = ""

    def handle_input(self, key, text):
        if key in (Qt.Key_Return, Qt.Key_Enter):
            self.code_received.emit(self.buffer)
            self.buffer = ""
        elif text:
            self.buffer += text

# One liner server with 1s delay for testing:
#   ncat -lk 8000 -c 'sleep 1; echo "HTTP/1.1 200 OK\r\n\r\nS3R14LNUM83R\n02:00:00:00:00:01\n02:00:00:00:00:02\n02:00:00:00:00:03\n02:00:00:00:00:04\n02:00:00:00:00:05"'
class ServerClient(QThread):
    response_received = pyqtSignal(bool, str)

    def __init__(self, logging_service: LoggingService):
        super().__init__()
        self.logger = logging_service

    def set_codes(self, codes):
        self.qr1 = codes[0]
        self.qr2 = codes[1]

    def run(self):
        url = SERVER_ENDPOINT + "/getserial?qr1=" + self.qr1 + "&qr2=" + self.qr2
        try:
            r = requests.get(url)
            if(r.status_code != 200):
                self.response_received.emit(False, r.text)
            else:
                self.response_received.emit(True, r.text)
        except Exception as e:
            self.logger.error(str(e))

# For local testing:
#   1. Create 2 PTYs: socat -d -d pty,raw,echo=0,link=/tmp/ttyMBT01 pty,raw,echo=0,link=/tmp/ttyMBT02
#   2. Run this app with the first TTY as the argument
#   3. Pipe some text (file) to the second TTY:
class SerialService(QThread):
    connected   = pyqtSignal()
    failed      = pyqtSignal(str)
    received_data = pyqtSignal(str)

    def __init__(self, port, baudrate):
        super().__init__()
        self.timeout = 0.2
        self.port = port
        self.baudrate = baudrate
        self.running = False

    def run(self):
        try:
            self.serial = serial.Serial(self.port, self.baudrate, timeout = self.timeout)
            self.connected.emit()
            self.running = True

            while(self.running):
                line = self.serial.readline().decode().strip()
                if line:
                    self.received_data.emit(line)
                    print("S> " + line)
                self.msleep(10)

        except Exception as e:
            self.failed.emit(str(e))
        finally:
            self.stop()

    def stop(self):
        if self.serial and self.serial.is_open:
            self.serial.close()
        self.running = False
        self.wait()

class Workflow(QObject):
    state_changed = pyqtSignal(dict)
    code_scanned = pyqtSignal(list)

    def __init__(
        self,
        logging_service:   LoggingService,
        serial_service:    SerialService,
        scanner_service:   ScannerService,
        server_client:     ServerClient
    ):
        super().__init__()

        # State
        self.state              = State.IDLE
        self.scanned_codes      = []
        self.serial_num         = None
        self.mac_addresses      = []

        # Services
        self.logger             = logging_service
        self.serial             = serial_service
        self.scanner            = scanner_service
        self.server_client      = server_client

        # Connect to external services signals
        self.scanner.code_received.connect(self.__handle_scanned_codes)
        self.server_client.response_received.connect(self.__handle_server_response)
        self.serial.connected.connect(self.__handle_serial_connected)
        self.serial.failed.connect(self.__handle_serial_failed)
        self.serial.received_data.connect(self.__handle_serial_received_data)

    # Reset back to idle state in order to do retry upon failure
    def reset(self):
        self.scanned_codes = []
        self.__change_state(State.IDLE)

    # Entry point into testing
    def start(self):
        if self.state != State.IDLE:
            self.logger.info(Texts.log_wrong_state_to_start_from + self.state)
            return

        self.__change_state(State.STARTED)
        self.connect_to_uart()

    # Test UART connection to the board
    def connect_to_uart(self):
        self.__change_state(State.CONNECTING_TO_UART)
        self.serial.start()

    # Prompt user to scan two data matrix codes
    def scan_qr_codes(self):
        self.__change_state(State.SCANNING_QR_CODES)
        # Scanned codes are handled in __handle_scanner_codes

    # Connect to our server to fetch serial and MAC addresses
    # based on the provided data matrix QR codes
    def fetch_serial_and_macs(self):
        self.__change_state(State.FETCHING_SERIAL_AND_MACS)
        self.server_client.set_codes(self.scanned_codes)
        self.server_client.start()

    # Prompt user to connect the rest of the cables
    def connect_cables(self):
        self.__change_state(State.CONNECTING_CABLES)
        # Capture UART text until your get something then change state?

    # Done, all tests have successfull passed and
    # the board is fully functional (to our knowledge)
    def done(self):
        self.__change_state(State.DONE)
        self.logger.info(Texts.log_info_done)

    # Handler for all key presses. But it only forwards it to
    # scaner service if it is at the scanning step
    def key_pressed(self, event):
        if self.state == State.SCANNING_QR_CODES:
            self.scanner.handle_input(event.key(), event.text())

    # Helper function to make sure state_changed is emited also on state change
    def __change_state(self, state, msgs = {}):
        self.state = state
        self.state_changed.emit(msgs)

    # Called upon successfully receiving a code from the scanner
    def __handle_scanned_codes(self, code):
        self.scanned_codes.append(code)
        self.code_scanned.emit(self.scanned_codes)

        if len(self.scanned_codes) == 1:
            self.logger.info(Texts.log_info_first_code_scanned + code)
        elif len(self.scanned_codes) == 2:
            self.logger.info(Texts.log_info_second_code_scanned + code)
            self.fetch_serial_and_macs()
        else:
            self.logger.error(Texts.log_error_more_than_2_qr_scanned)
    
    # Called upon receiving a response from the server
    def __handle_server_response(self, success: bool, response: str):
        if success:
            self.logger.info(Texts.log_info_server_response + response)
            r = response.split()
            self.serial_num = r[0]
            self.mac_addresses = r[1:]
            self.connect_cables()
        else:
            self.logger.error(Texts.log_info_server_error + response)

    def __handle_serial_connected(self):
        self.logger.info(Texts.log_info_uart_connected)
        self.scan_qr_codes()

    def __handle_serial_failed(self, err_msg):
        self.logger.error(Texts.log_error_uart_failed + err_msg)
        self.__change_state(State.FAILED, {
            "status": Texts.status_conn_to_uart_failed,
            "err_msg": err_msg
        })

    def __handle_serial_received_data(self, data: str):
        if self.state == State.CONNECTING_CABLES:
            self.logger.info("Serial working. Data was received: " + data)
            self.__change_state(State.DONE)

class UI(QWidget):
    def __init__(self):
        super().__init__()
        self.__init_ui()

    def __init_ui(self): 
        self.setContentsMargins(8, 8, 8, 8)

        layout = QHBoxLayout()
        left_panel = QVBoxLayout()
        right_panel = QVBoxLayout()

        # Create UI
        self.reset_btn = QPushButton(Texts.ui_reset_btn_label)
        self.label = QLabel(Texts.status_ready_to_start)
        self.label.setStyleSheet(Styles.status_normal)
        
        self.__create_dm_qr_group()

        self.log_text_edit = QTextEdit()
        self.log_text_edit.setDisabled(True)

        self.start_btn = QPushButton(Texts.ui_start_btn_label_start)
        self.reset_btn.setEnabled(False)

        # Assemble UI
        left_panel.addWidget(self.reset_btn)
        left_panel.addWidget(self.label)
        left_panel.addStretch()
        left_panel.addWidget(self.dm_qr_group)
        left_panel.addStretch()
        left_panel.addWidget(self.log_text_edit)
        left_panel.addWidget(self.start_btn)
        layout.addLayout(left_panel, stretch=1)
        layout.addLayout(right_panel, stretch=2)
        self.setLayout(layout)
    
    def start_btn_enable(self):
        self.start_btn.setDisabled(False)

    def start_btn_disable(self):
        self.start_btn.setDisabled(True)

    def reset_btn_enable(self):
        self.reset_btn.setDisabled(False)

    def reset_btn_disable(self):
        self.reset_btn.setDisabled(True)

    def update_status(self, text):
        self.label.setText(text)

    def set_dm_qr_top(self, code: str):
        self.dm_qr_line_edit_top.setText(code)
        
    def set_dm_qr_bottom(self, code: str):
        self.dm_qr_line_edit_bottom.setText(code)

    def clear_qr_codes(self):
        self.dm_qr_line_edit_top.setText("")
        self.dm_qr_line_edit_bottom.setText("")

    def __create_dm_qr_group(self):
        self.dm_qr_group = QGroupBox(Texts.ui_label_qr_group)
        self.dm_gr_group_layout = QVBoxLayout()
        self.dm_qr_label_top = QLabel(Texts.ui_label_top_qr)
        self.dm_qr_line_edit_top = QLineEdit()
        self.dm_qr_line_edit_top.setDisabled(True)
        self.dm_qr_label_bottom = QLabel(Texts.ui_label_bottom_qr)
        self.dm_qr_line_edit_bottom = QLineEdit()
        self.dm_qr_line_edit_bottom.setDisabled(True)
        self.dm_gr_group_layout.addWidget(self.dm_qr_label_top)
        self.dm_gr_group_layout.addWidget(self.dm_qr_line_edit_top)
        self.dm_gr_group_layout.addWidget(self.dm_qr_label_bottom)
        self.dm_gr_group_layout.addWidget(self.dm_qr_line_edit_bottom)
        self.dm_qr_group.setLayout(self.dm_gr_group_layout)

class Main(QMainWindow):
    def __init__(self):
        super().__init__()

        # Init UI
        self.ui = UI()
        self.setCentralWidget(self.ui)
        self.resize(1280, 720)

        # Init services
        self.logger         = LoggingService(self.ui.log_text_edit)
        self.serial         = SerialService(SERIAL_PORT, 115200)
        self.scanner        = ScannerService()
        self.server_client  = ServerClient(self.logger)
        self.workflow       = Workflow(self.logger, self.serial, self.scanner, self.server_client)

        self.ui.start_btn.clicked.connect(self.workflow.start)
        self.ui.reset_btn.clicked.connect(self.workflow.reset)
        self.workflow.code_scanned.connect(self.__update_scanned_codes)
        self.workflow.state_changed.connect(self.__update_ui)

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
        if len(codes) == 1:
            self.ui.update_status(Texts.status_scan_qr_bottom)
            self.ui.set_dm_qr_top(codes[0])
        elif len(codes) == 2:
            self.ui.set_dm_qr_bottom(codes[1])

    def __update_ui(self, msg):
        state = self.workflow.state
        handler = self.state_handlers.get(state)
        handler(msg)

    def __update_ui_idle(self, msg):
        self.ui.update_status(Texts.status_ready_to_start)
        self.ui.clear_qr_codes()
        self.ui.start_btn_enable()
        self.ui.reset_btn_disable()

    def __update_ui_started(self, msg):
        self.ui.start_btn_disable()
        self.ui.reset_btn_enable()

    def __update_ui_connecting_to_uart(self, msg):
        self.ui.update_status(Texts.status_conn_to_uart)

    def __update_ui_scanning_qr_codes(self, msg):
        self.ui.update_status(Texts.status_scan_qr_top)

    def __update_ui_fetching_serial_and_macs(self, msg):
        self.ui.update_status(Texts.status_get_ser_macs)

    def __update_ui_connecting_cables(self, msg):
        self.ui.update_status(Texts.status_connect_cables)

    def __update_ui_done(self, msg):
        self.ui.update_status(Texts.status_done)
    
    def __update_ui_failed(self, msgs):
        self.ui.update_status(msgs["status"])

    def keyPressEvent(self, event):
        self.workflow.key_pressed(event)

app = QApplication(sys.argv)

SERVER_ENDPOINT = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
SERIAL_PORT = sys.argv[2] if len(sys.argv) > 2 else "/tmp/ttyMBT01"

window = Main()
window.show()
# window.showFullScreen()
app.exec()