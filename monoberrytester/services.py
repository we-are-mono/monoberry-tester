"""
Collection of services for external communication 
like serial, http, logs, barcode scanner, ...

TODO: replace with actual code when I get the barcode scanner
"""

from queue import Queue
from datetime import datetime

import urllib
import logging
import requests

from PyQt5.QtSerialPort import QSerialPort
from PyQt5.QtCore import Qt, QObject, QProcess, pyqtSignal

import texts

class LoggingService(QObject):
    """Class for logging into a file and on screen to QTextEdit widget"""

    logline_received = pyqtSignal(str, bool, bool) # text line, error, should_display

    def __init__(self):
        super().__init__()
        self.__init_logging()

    def reinit(self):
        """Re-init the logging (for resets)"""
        self.__init_logging()

    def info(self, text, should_display=True):
        """Logs text as info"""
        self.logline_received.emit(text, False, should_display)
        logging.info(text)

    def error(self, text, should_display=True):
        """Logs text as error"""
        self.logline_received.emit(text, True, should_display)
        logging.error(text)

    def __init_logging(self):
        time_str = datetime.now().strftime('%Y-%m-%d-%H-%M-%S')
        filename = f"/tmp/mbt-{time_str}.log"

        logger = logging.getLogger()

        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)

        handler = logging.FileHandler(filename)
        formatter = logging.Formatter('%(asctime)s - %(message)s')
        handler.setFormatter(formatter)
        handler.setLevel(logging.INFO)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

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

class ServerClient(QObject):
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

    def __init__(self, server_endpoint, api_key, logging_service: LoggingService):
        super().__init__()
        self.logger = logging_service
        self.server_endpoint = server_endpoint
        self.api_key = api_key
        self.serial = None
        self.qr1 = None
        self.qr2 = None
        self.method = None
        self.path = None
        self.request_params = {}

    def set_params(self, serial, codes):
        """
        Sets scanned QR data matrix codes (do this before calling `run` method)
        """
        self.serial = serial
        self.qr1 = codes[0]
        self.qr2 = codes[1]

    def send_qrs(self):
        self.__config_request("POST", f"/api/devices/{self.serial}/register?api_key={self.api_key}", {"qr1": self.qr1, "qr2": self.qr2})

    def run(self):
        """Runs the thread to registers device and MACs from our server"""
        url = urllib.parse.urljoin(self.server_endpoint, self.path)
        try:
            r = requests.request(
                method=self.method.upper(),
                url=url, params=self.request_params,
                timeout=10
            )

            if r.status_code != 200:
                self.response_received.emit(False, r.text)
            else:
                self.response_received.emit(True, r.text)
        except requests.RequestException as e:
            self.error_occured.emit(str(e))
            self.logger.error(str(e))

    def __config_request(self, method: str, path: str, request_params: dict):
        self.method = method
        self.path = path
        self.request_params = request_params

class SerialService(QObject):
    """Serial service to comminucate with the board via UART"""

    connected = pyqtSignal()
    error_occurred = pyqtSignal(str)
    line_received = pyqtSignal(str)

    def __init__(self, port_name, baud_rate = 115200):
        super().__init__()
        self.port_name = port_name
        self.baud_rate = baud_rate
        self.write_queue = Queue()
        self.is_running = False
        self.serial_port = None

    def stop(self):
        """Stop serial service"""
        self.is_running = False

    def send(self, data: str):
        """Send data via serial (writes to queue then the run loop sends it from queue)"""
        if self.serial_port.isOpen():
            self.write_queue.put(data)
        else:
            self.error_occurred.emit(texts.LOG_ERROR_UART_WRITE_NOT_OPEN)

    def run(self):
        """Runs a loop for reading and writing to serial"""
        self.serial_port = QSerialPort()
        self.serial_port.setPortName(self.port_name)
        self.serial_port.setBaudRate(self.baud_rate)

        if not self.serial_port.open(QSerialPort.ReadWrite):
            self.error_occurred.emit(f"{texts.STATUS_CONN_TO_UART_FAILED} {self.serial_port.errorString()}")
            return

        self.is_running = True
        self.connected.emit()

        while self.is_running:
            if self.serial_port.waitForReadyRead(10):
                line = bytes(self.serial_port.readAll()).decode('utf-8', errors='ignore').strip()
                if line:
                    self.line_received.emit(str(line))

            while not self.write_queue.empty():
                data = self.write_queue.get()
                self.serial_port.write(data.encode('utf-8'))
                self.serial_port.flush()

        self.serial_port.close()

class SerialController(QObject):
    """Serial controller to make working with UART easier"""

    def __init__(self, serial_service: SerialService):
        super().__init__()
        self.serial_service = serial_service
        self.serial_service.line_received.connect(self.__on_line_received)
        self.wait_text = None
        self.callback = None
        self.waiting_list = []

    def wait_for(self, wait_text, callback) -> bool:
        """Adds a text to wait for in the waiting_list"""
        self.waiting_list.append((wait_text, callback))

    def wait_for_and_send(self, wait_text, send_text, callback) -> bool:
        """Adds a text to wait for and text to send after in the waiting_list"""
        self.waiting_list.append((wait_text, callback, send_text))

    def __on_line_received(self, line):
        """Handler for when data is received via serial"""
        for wait_item in self.waiting_list:
            wait_text, callback, send_text = None, None, None
            if len(wait_item) == 2:
                wait_text, callback = wait_item
            else:
                wait_text, callback, send_text = wait_item

            if wait_text in line:
                self.waiting_list.remove(wait_item)
                if send_text:
                    self.serial_service.send(send_text)
                callback()

class ProcessService(QObject):
    """Service for running, reading from and writing to processes"""
    output_received = pyqtSignal(str)
    error_received = pyqtSignal(str)
    process_finished = pyqtSignal(int)
    process_errored = pyqtSignal(str)

    def __init__(self, logging_service: LoggingService):
        super().__init__()
        self.logger = logging_service
        self.process = QProcess()
        self.is_stopping = False
        self.process.readyReadStandardOutput.connect(self.__handle_stdout)
        self.process.readyReadStandardError.connect(self.__handle_stderr)
        self.process.finished.connect(self.__handle_finished)
        self.process.errorOccurred.connect(self.__handle_error)

    def start(self, program, args=None):
        """Starts the process"""
        if args is None:
            args = []
        self.is_stopping = False
        self.process.start(program, args)

    def stop(self):
        """Stops the process gracefully"""
        self.is_stopping = True
        self.process.terminate()

    def write_to_process(self, data):
        """Writes to the process"""
        data = data.encode("utf-8")
        self.process.write(data)
        self.process.write(b"\n")

    def __handle_stdout(self):
        """Handler for receiving data via stdout"""
        data = bytes(self.process.readAllStandardOutput())
        self.logger.info(f"ProcessService: {self.process.program()} {' '.join(self.process.arguments())} received:\n{data}")
        self.output_received.emit(data.decode("utf-8"))

    def __handle_stderr(self):
        """Handler for receiving data via stderr"""
        data = bytes(self.process.readAllStandardError())
        self.logger.error(f"ProcessService: {self.process.program()} {' '.join(self.process.arguments())} error:\n{data}")
        self.error_received.emit(data.decode("utf-8"))

    def __handle_finished(self, exit_code, exit_status):
        """Handler for when process finishes"""
        self.logger.info(f"ProcessService: {self.process.program()} {' '.join(self.process.arguments())} exited with {exit_code} {exit_status}")
        self.process_finished.emit(exit_code)

    def __handle_error(self, error):
        """Handler for when process errors"""
        # Don't emit error if we're intentionally stopping the process
        if self.is_stopping and error == QProcess.Crashed:
            self.logger.info(f"ProcessService: {self.process.program()} {' '.join(self.process.arguments())} stopped by user")
            return

        error_messages = {
            QProcess.FailedToStart: "Process failed to start (file not found or no permissions)",
            QProcess.Crashed: "Process crashed",
            QProcess.Timedout: "Process timed out",
            QProcess.WriteError: "Write error",
            QProcess.ReadError: "Read error",
            QProcess.UnknownError: "Unknown error"
        }

        err_str = error_messages.get(error, "Unknown error")
        self.logger.info(f"ProcessService: {self.process.program()} {' '.join(self.process.arguments())} error occured: {err_str}")
        self.process_errored.emit(err_str)

class ProcessController(QObject):
    """Process controller to make working with processes easier"""

    def __init__(self, process_service: ProcessService):
        super().__init__()
        self.process_service = process_service
        self.process_service.output_received.connect(self.__on_output_received)
        self.waiting_list = []

    def wait_for(self, wait_text, callback):
        """Adds a text to wait for in the waiting_list"""
        self.waiting_list.append((wait_text, callback))

    def wait_for_and_send(self, wait_text, send_text, callback):
        """Adds a text to wait for and text to send after in the waiting_list"""
        self.waiting_list.append((wait_text, callback, send_text))

    def __on_output_received(self, output):
        """Handler for when output is received from process"""
        for wait_item in self.waiting_list:
            wait_text, callback, send_text = None, None, None
            if len(wait_item) == 2:
                wait_text, callback = wait_item
            else:
                wait_text, callback, send_text = wait_item

            if wait_text in output:
                print(1)
                self.waiting_list.remove(wait_item)
                if send_text:
                    self.process_service.write_to_process(send_text)
                callback()