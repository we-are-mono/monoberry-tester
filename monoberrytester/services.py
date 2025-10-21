"""
Collection of services for external communication 
like serial, http, logs, barcode scanner, ...

TODO: replace with actual code when I get the barcode scanner
"""

from datetime import datetime

import logging
import requests
import serial

from PyQt5.QtCore import Qt, QObject, QThread, pyqtSignal
from PyQt5.QtWidgets import QTextEdit

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
            self.serial = None

    def stop(self):
        """Stops the connection and waits for thread to finish"""
        self.running = False
        if self.serial and self.serial.is_open:
            try:
                self.serial.close()
            except serial.SerialException as _:
                pass

        self.serial = None

        if self.isRunning():
            self.wait(1000)
