"""
Collection of services for external communication 
like serial, http, logs, barcode scanner, ...

TODO: replace with actual code when I get the barcode scanner
"""

from datetime import datetime

import logging
import requests
import urllib
from queue import Queue

from PyQt5.QtSerialPort import QSerialPort
from PyQt5.QtCore import Qt, QObject, QIODevice, pyqtSignal

import texts

THREAD_WAIT_TIMEOUT_MS = 1000

class LoggingService(QObject):
    """Class for logging into a file and on screen to QTextEdit widget"""

    logline_received = pyqtSignal(str, bool, bool) # text line, error, should_display

    def __init__(self):
        super().__init__()
        self.filename = self.__generate_log_filename()
        self.__init_logging(self.filename)

    def info(self, text, should_display=True):
        """Logs text as info"""
        self.logline_received.emit(text, False, should_display)
        logging.info(text)

    def error(self, text, should_display=True):
        """Logs text as error"""
        self.logline_received.emit(text, True, should_display)
        logging.error(text)

    def __generate_log_filename(self):
        """Generates a log filename based on current time."""
        time_str = datetime.now().strftime('%Y-%m-%d-%H-%M-%S')
        return f"/tmp/mbt-{time_str}.log"

    def __init_logging(self, filename):
        """Sets up logging"""
        logging.basicConfig(
            filename=filename,
            level=logging.INFO,
            format='%(asctime)s - %(message)s'
        )

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

    def __init__(self, server_endpoint, logging_service: LoggingService):
        super().__init__()
        self.logger = logging_service
        self.server_endpoint = server_endpoint
        self.qr1 = None
        self.qr2 = None
        self.method = None
        self.path = None
        self.request_params = {}

    def set_codes(self, codes):
        """
        Sets scanned QR data matrix codes (do this before calling `run` method)
        """
        self.qr1 = codes[0]
        self.qr2 = codes[1]

    def send_qrs(self):
        self.__config_request("GET", "/serial-macs", {"qr1": self.qr1, "qr2": self.qr2})

    def run(self):
        """Runs the thread and fetches serial and MACs from our server"""
        url = urllib.parse.urljoin(self.server_endpoint, self.path)
        try:
            r = requests.request(method=self.method.upper(), url=url, params=self.request_params, timeout=10)

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
    error_occurred = pyqtSignal()
    line_received = pyqtSignal(str)

    def __init__(self, port_name, baud_rate = 115200):
        super().__init__()
        self.port_name = port_name
        self.baud_rate = baud_rate
        self.write_queue = Queue()

    def stop(self):
        self.is_running = False

    def send(self, data: str):
        if self.serial_port.isOpen():
            self.write_queue.put(data)
        else:
            self.error_occurred.emit(texts.LOG_ERROR_UART_WRITE_NOT_OPEN)

    def run(self):
        self.serial_port = QSerialPort()
        self.serial_port.setPortName(self.port_name)
        self.serial_port.setBaudRate(self.baud_rate)

        if not self.serial_port.open(QSerialPort.ReadWrite):
            self.error_occurred.emit(f"{texts.STATUS_CONN_TO_UART_FAILED} {self.serial_port.errorString()}")
            return

        self.is_running = True
        self.connected.emit()

        while self.is_running:
            if self.serial_port.waitForReadyRead(100):
                line = bytes(self.serial_port.readLine()).decode('utf-8', errors='ignore').strip()
                if line:
                    self.line_received.emit(str(line))

        self.serial_port.close()