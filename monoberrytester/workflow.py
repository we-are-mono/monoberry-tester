# pylint: disable=too-many-instance-attributes

"""
All 'business' logic
"""

import time
import json
from datetime import datetime
from enum import Enum, auto
from functools import wraps
from PyQt5.QtCore import QObject, QThread, pyqtSignal, QTimer

import texts
from ui import TestState
from tests import TestKeys

from services import *

def test_method(test_key):
    """Decorator that automatically emits test state changes.

    Emits RUNNING when the method starts, and provides a TestContext
    object that callbacks can use to emit SUCCEEDED or FAILED states.

    Args:
        test_key: The TestKeys enum value for this test

    Usage:
        @test_method(TestKeys.CONN_TO_UART)
        def connect_to_uart(self, ctx):
            def handle_success():
                ctx.succeed()

            def handle_failure(err_msg):
                ctx.fail(f"{texts.STATUS_CONN_TO_UART_FAILED}")
    """
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            """Wraps the test function to add additional functionality and reduce repetitive code"""
            self.test_state_changed.emit(test_key, TestState.RUNNING)

            class TestContext:
                """Makes it nicer to mark test as successful or failed"""
                def succeed(ctx_self):
                    """Mark test as successful"""
                    self.test_state_changed.emit(test_key, TestState.SUCCEEDED)

                def fail(ctx_self, message=""):
                    """Mark test as failed and update workflow state"""
                    self.test_state_changed.emit(test_key, TestState.FAILED)
                    if self.state != State.FAILED:
                        failure_msg = message if message else f"Test failed: {test_key.name}"
                        self._Workflow__change_state(State.FAILED, failure_msg)

            ctx = TestContext()
            return func(self, ctx, *args, **kwargs)
        return wrapper
    return decorator

class State(Enum):
    """Class to define states of the application"""
    IDLE    = auto()
    RUNNING = auto()
    DONE    = auto()
    FAILED  = auto()

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

    state_changed = pyqtSignal(State, str)
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
        process_controller: ProcessController,
        usb_service: UsbService,
        ftx_prog_path: str,
        ccs_tools_path: str
    ):
        super().__init__()

        # State
        self.state          = State.IDLE
        self.current_test   = None
        self.scanned_codes  = []
        self.mac_addresses  = []
        self.mac_addr_hex_strings = []
        self.serial_num     = None

        # Services
        self.logger             = logging_service
        self.serial             = serial_service
        self.scanner            = scanner_service
        self.server_client      = server_client
        self.serial_controller  = serial_controller
        self.process_runner     = process_runner
        self.process_controller = process_controller
        self.usb_service        = usb_service
        self.ftx_prog_path      = ftx_prog_path
        self.ccs_tools_path     = ccs_tools_path

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
        self.logger.info("--- Resetting ---")
        self.current_test = None
        self.scanned_codes = []
        self.mac_addresses = []
        self.mac_addr_hex_strings = []
        self.serial_num = None
        self.logger.reinit()
        self.serial.stop()
        self.serial_thread.quit()
        self.serial_thread.wait()
        self.process_runner.stop()

        self.__change_state(State.IDLE, texts.STATUS_READY_TO_START)

    def start(self):
        """Entry point to start testing"""
        if self.state != State.IDLE:
            self.logger.info(f"{texts.LOG_WRONG_STATE_TO_START_FROM} {self.state}")
            return

        self.__change_state(State.RUNNING, texts.STATUS_CONN_TO_UART)
        self.reflash_uart_chip()

    @test_method(TestKeys.REFLASH_UART_CHIP)
    def reflash_uart_chip(self, ctx):
        """Reflash the UART pin to change the configuration"""
        # Track if we've already completed to avoid running finish steps twice
        completed = [False]

        def handle_process_output_received(text):
            """Called when program outputs something to stdout"""
            self.logger.info(text)

        def handle_process_error_received(err_msg):
            """Called when program outputs something to stderr"""
            self.logger.error(err_msg)

        def handle_process_errored(err_msg):
            """Called when process errors out"""
            self.logger.error(f"{texts.LOG_PROCESS_ERRORED} {err_msg}")
            ctx.fail(f"{texts.STATUS_PROCESS_ERRORED}")

        def handle_process_finished(return_code):
            """Called when process returns/exits"""
            self.logger.info(f"{texts.LOG_PROCESS_EXITED} {return_code}")
            if return_code == 0:
                pass
            else:
                self.logger.error(texts.LOG_PROCESS_EXITED_NON_0_CODE)

        def disconnect_signals():
            """Disconnects all process runner signals"""
            self.process_runner.output_received.disconnect(handle_process_output_received)
            self.process_runner.error_received.disconnect(handle_process_error_received)
            self.process_runner.process_errored.disconnect(handle_process_errored)
            self.process_runner.process_finished.disconnect(handle_process_finished)

        def finish_and_continue():
            """Finishes the reflash process and continues to next step"""
            self.process_runner.stop()
            self.usb_service.reset_usb(usb_id)
            time.sleep(5)

            # Update serial port to first available device
            new_port = self.usb_service.find_first_available_tty()
            if new_port:
                self.logger.info(f"Found available serial port: {new_port}")
                self.serial.port_name = new_port
            else:
                self.logger.error("No USB serial port found")
                ctx.fail("No USB serial port available")
                return

            ctx.succeed()
            self.connect_to_uart()

        def confirm(result):
            """Handles confirmation prompt"""
            self.logger.info(f"Reflash UART confirm: {result}")

            if not completed[0]:
                completed[0] = True
                disconnect_signals()
                finish_and_continue()

        def no_changes(result):
            """Handles no changes scenario when eeprom contents match"""
            self.logger.info(f"Reflash UART no changes: {result}")

            if not completed[0]:
                completed[0] = True
                disconnect_signals()
                finish_and_continue()

        # Find first available ttyUSB device
        available_port = self.usb_service.find_first_available_tty()
        if not available_port:
            self.logger.error("No USB serial port found")
            ctx.fail("No USB serial port available")
            return

        # Update serial port if different from current
        if self.serial.port_name != available_port:
            self.logger.info(f"Updating serial port from {self.serial.port_name} to {available_port}")
            self.serial.port_name = available_port

        self.process_runner.output_received.connect(handle_process_output_received)
        self.process_runner.error_received.connect(handle_process_error_received)
        self.process_runner.process_errored.connect(handle_process_errored)
        self.process_runner.process_finished.connect(handle_process_finished)

        usb_id = self.usb_service.get_usb_id(self.serial.port_name)
        self.process_controller.wait_for_and_send("Continue? [y|n]:", "y\r\n", confirm, timeout_s=2)
        self.process_controller.wait_for("No change from existing eeprom contents", no_changes, timeout_s=2)
        self.process_runner.start(self.ftx_prog_path, ["--cbus", "0", "TxRxLED"])

    @test_method(TestKeys.CONN_TO_UART)
    def connect_to_uart(self, ctx):
        """Tests UART connection to the board"""

        def handle_serial_connected():
            """Called on successful serial connection"""
            self.serial.connected.disconnect(handle_serial_connected)
            self.serial.error_occurred.disconnect(handle_serial_error_occurred)

            self.logger.info(texts.LOG_INFO_UART_CONNECTED)
            ctx.succeed()
            self.scan_serial_num()

        def handle_serial_error_occurred(err_msg):
            """Called on failed serial connection"""
            self.serial.connected.disconnect(handle_serial_connected)
            self.serial.error_occurred.disconnect(handle_serial_error_occurred)

            self.logger.error(f"{texts.LOG_ERROR_UART_FAILED} {err_msg}")
            ctx.fail(f"{texts.STATUS_CONN_TO_UART_FAILED}")

        self.serial.connected.connect(handle_serial_connected)
        self.serial.error_occurred.connect(handle_serial_error_occurred)

        self.serial_thread.start()

    @test_method(TestKeys.SCAN_SERIAL_NUM)
    def scan_serial_num(self, ctx):
        """Prompts the user to scan the serial number"""

        def handle_scanned_serial(code):
            """Called upon successfully receiving serial number from scanner"""
            self.scanner.code_received.disconnect(handle_scanned_serial)

            self.serial_num = code
            self.serial_scanned.emit(self.serial_num)
            ctx.succeed()
            self.scan_qr_codes()

        self.current_test = TestKeys.SCAN_SERIAL_NUM
        self.scanner.code_received.connect(handle_scanned_serial)

    @test_method(TestKeys.SCAN_TWO_DM_QR_CODES)
    def scan_qr_codes(self, ctx):
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
                ctx.succeed()
                self.register_device_and_get_macs()
            else:
                self.scanner.code_received.disconnect(handle_scanned_qr)

                self.logger.error(texts.LOG_ERROR_MORE_THAN_2_QR_SCANNED)
                ctx.fail(texts.ERROR_MORE_THAN_2_QR_SCANNED)

        self.current_test = TestKeys.SCAN_TWO_DM_QR_CODES
        self.scanner.code_received.connect(handle_scanned_qr)

    @test_method(TestKeys.REGISTER_DEVICE)
    def register_device_and_get_macs(self, ctx):
        """Connect to our server to register device and get MAC addresses
        based on the serial and provided data matrix QR codes"""

        def int_to_mac_hex(num):
            return ":".join(f"{b:02x}" for b in num.to_bytes(6, 'big'))

        def handle_server_response(success: bool, response: str):
            """Called upon receiving a response from the server"""
            self.server_client.response_received.disconnect(handle_server_response)
            self.server_client.error_occured.disconnect(handle_server_error)

            self.server_thread.quit()
            self.server_thread.wait()

            if success:
                self.logger.info(f"{texts.LOG_INFO_SERVER_RESPONSE} {response}")
                r = json.loads(response)
                mac_ints = [m['addr'] for m in r["macs"]]
                self.mac_addr_hex_strings = list(map(int_to_mac_hex, mac_ints))
                ctx.succeed()
                self.load_uboot_spl_via_jtag()
            else:
                self.logger.error(f"{texts.LOG_INFO_SERVER_ERROR} {response}")
                ctx.fail(f"{texts.ERROR_SERVER_ERROR}")

        def handle_server_error(err_msg):
            """Called upon server connection error"""
            self.server_client.response_received.disconnect(handle_server_response)
            self.server_client.error_occured.disconnect(handle_server_error)

            self.server_thread.quit()
            self.server_thread.wait()

            ctx.fail(f"{texts.CONN_TO_SERVER_FAILED}")

        self.server_client.response_received.connect(handle_server_response)
        self.server_client.error_occured.connect(handle_server_error)

        self.server_client.set_params(self.serial_num, self.scanned_codes)
        self.server_client.send_qrs()
        if not self.server_thread.isRunning():
            self.server_thread.start()

    @test_method(TestKeys.LOAD_UBOOT_SPL_VIA_JTAG)
    def load_uboot_spl_via_jtag(self, ctx):
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
            ctx.fail(f"{texts.STATUS_PROCESS_ERRORED}")

        def handle_process_finished(return_code):
            """Called when process returns/exits"""
            self.logger.info(f"{texts.LOG_PROCESS_EXITED} {return_code}")
            if return_code == 0:
                pass
            else:
                self.logger.error(texts.LOG_PROCESS_EXITED_NON_0_CODE)

        def handle_exiting(result):
            if result is False:
                self.logger.info("Failed or timed out waiting for lsbp.tcl to exit...")
                ctx.fail(texts.ERROR_TIMEOUT_LSBP_TCL)
                return

            self.process_runner.output_received.disconnect(handle_process_output_received)
            self.process_runner.error_received.disconnect(handle_process_error_received)
            self.process_runner.process_errored.disconnect(handle_process_errored)
            self.process_runner.process_finished.disconnect(handle_process_finished)

            self.process_runner.stop()
            ctx.succeed()
            self.wait_for_uboot_spl()

        self.process_runner.output_received.connect(handle_process_output_received)
        self.process_runner.error_received.connect(handle_process_error_received)
        self.process_runner.process_errored.connect(handle_process_errored)
        self.process_runner.process_finished.connect(handle_process_finished)

        self.process_controller.wait_for("lsbp.tcl is exiting...", handle_exiting, timeout_s=360)
        self.process_runner.start(self.ccs_tools_path + "/CCS/bin/ccs", ["-nogfx", "-console", "-file", self.ccs_tools_path + "/TAP/lsbp.tcl"])

    @test_method(TestKeys.WAIT_FOR_UBOOT_SPL_PROMPT)
    def wait_for_uboot_spl(self, ctx):
        """Wait for u-boot prompt"""

        def callback(result):
            if result is False:
                self.logger.info("Failed or timed out waiting for U-Boot SPL prompt...")
                ctx.fail(texts.ERROR_TIMEOUT_UBOOT_SPL_PROMPT)
                return
            ctx.succeed()
            self.write_firmware_to_flash()

        self.serial_controller.wait_for_and_send("stop autoboot", "\r\n", callback, timeout_s=30)

    @test_method(TestKeys.WRITE_FIRMWARE_TO_FLASH)
    def write_firmware_to_flash(self, ctx):
        """Write firware to flash"""
        # Track whether USB start has been handled
        usb_handled = [False]

        def start_usb():
            self.logger.info("Starting USB")
            # Wait for both success (1 or more devices) and failure (0 devices) in parallel
            self.serial_controller.wait_for("1 Storage Device(s) found", usb_started_success, timeout_s=10)
            self.serial_controller.wait_for("0 Storage Device(s) found", usb_started_failure, timeout_s=10)
            self.serial_controller.send("usb start\r\n")

        def usb_started_success(result):
            if not usb_handled[0] and result:
                usb_handled[0] = True
                self.logger.info("USB started successfully")
                load_firmware_to_mem(True)

        def usb_started_failure(result):
            if not usb_handled[0] and result:
                usb_handled[0] = True
                self.logger.info("USB start failed with 0 Storage Devices, attempting to restart...")
                # Run usb stop then usb start again
                self.serial_controller.send_and_expect("usb stop\r\n", "=>", usb_stopped, timeout_s=10)

        def usb_stopped(result):
            if result is False:
                self.logger.info("Failed or timed out stopping USB...")
                ctx.fail(texts.ERROR_FAILED_START_USB)
                return
            self.logger.info("USB stopped, restarting...")
            self.serial_controller.send_and_expect("usb start\r\n", "1 Storage Device(s) found", load_firmware_to_mem, timeout_s=10)

        def load_firmware_to_mem(result):
            if result is False:
                self.logger.info("Failed or timed out starting USB...")
                ctx.fail(texts.ERROR_FAILED_START_USB)
                return
            self.logger.info("Loading QSPI firmware into memory")
            self.serial_controller.send_and_expect("ext4load usb 0:0 0xC0000000 firmware-qspi.bin\r\n", "bytes read in", flash_probe, timeout_s=60)

        def flash_probe(result):
            if result is False:
                self.logger.info("Failed or timed out loading firmware to memory...")
                ctx.fail(texts.ERROR_FAILED_LOAD_FIRMWARE_TO_MEM)
                return
            self.logger.info("Probing the flash")
            self.serial_controller.send_and_expect("sf probe 0\r\n", "SF: Detected", flash_erase, timeout_s=10)

        def flash_erase(result):
            if result is False:
                self.logger.info("Failed or timed out probing flash...")
                ctx.fail(texts.ERROR_FAILED_PROBE_FLASH)
                return
            self.logger.info("Erasing the flash")
            self.serial_controller.send_and_expect("sf erase 0x0 0x2000000\r\n", "Erased: OK", flash_write, timeout_s=180)

        def flash_write(result):
            if result is False:
                self.logger.info("Failed or timed out erasing flash...")
                ctx.fail(texts.ERROR_FAILED_ERASE_FLASH)
                return
            self.logger.info("Writing QSPI firmware to flash")
            self.serial_controller.send_and_expect("sf write 0xC0000000 0x0 ${filesize}\r\n", "Written: OK", flash_finished, timeout_s=180)

        def flash_finished(result):
            if result is False:
                self.logger.info("Failed or timed out writing firmware to flash...")
                ctx.fail(texts.ERROR_FAILED_WRITE_FIRMWARE_TO_FLASH)
                return
            ctx.succeed()
            self.wait_for_uboot_prompt()

        start_usb()

    @test_method(TestKeys.WAIT_FOR_UBOOT_PROMPT)
    def wait_for_uboot_prompt(self, ctx):
        """Wait for U-Boot prompt"""

        def after_reset(result):
            if result is False:
                self.logger.info("Failed or timed out waiting for reset...")
                ctx.fail(texts.ERROR_FAILED_RESET_DEVICE)
                return
            self.serial_controller.wait_for_and_send("stop autoboot", "\r\n", uboot_prompt_received, timeout_s=60)

        def uboot_prompt_received(result):
            if result is False:
                self.logger.info("Failed or timed out waiting for U-Boot prompt...")
                ctx.fail(texts.ERROR_TIMEOUT_UBOOT_PROMPT)
                return
            ctx.succeed()
            self.set_time_in_uboot()

        self.serial_controller.send_and_expect("reset\r\n", "Model: Mono Gateway Development Kit", after_reset, timeout_s=60)

    @test_method(TestKeys.SET_TIME_IN_UBOOT)
    def set_time_in_uboot(self, ctx):
        """Set time in U-Boot"""

        def prompt_received(result):
            if result is False:
                self.logger.info("Failed or timed out waiting for U-Boot prompt...")
                ctx.fail(texts.ERROR_TIMEOUT_UBOOT_PROMPT)
                return
            self.serial_controller.send_and_expect("date " + t + "\r\n", "Date:", time_set, timeout_s=30)

        def time_set(result):
            if result is False:
                self.logger.info("Failed or timed out setting time...")
                ctx.fail(texts.ERROR_FAILED_SET_TIME)
                return
            ctx.succeed()
            self.program_eeprom()

        t = datetime.now().strftime("%m%d%H%M%y")
        self.logger.info("Setting time to: " + t)
        self.serial_controller.wait_for("=>", prompt_received)

    @test_method(TestKeys.PROGRAM_EEPROM)
    def program_eeprom(self, ctx):
        """Program EEPROM with serial number and MACs"""
        def prompt_received(result):
            if result is False:
                self.logger.info("Failed or timed out waiting for U-Boot prompt...")
                ctx.fail(texts.ERROR_TIMEOUT_UBOOT_PROMPT)
                return
            time.sleep(1)
            self.serial_controller.send_and_expect("mw 2320000 80000080; mw 2320008 40098033; i2c dev 3\r\n", "Setting bus to 3", bus_set)

        def bus_set(result):
            if result is False:
                self.logger.info("Failed or timed out setting I2C bus...")
                ctx.fail(texts.ERROR_FAILED_SET_I2C_BUS)
                return
            self.serial_controller.send_and_expect("i2c mw 0x50 0x0000.2 0x00\r\n", "=>", eeprom_erased)

        def eeprom_erased(result):
            if result is False:
                self.logger.info("Failed or timed out erasing EEPROM...")
                ctx.fail(texts.ERROR_FAILED_ERASE_EEPROM)
                return
            self.serial_controller.send_and_expect(
                f"program_eeprom \"Mono Gateway Development Kit\" \"{self.serial_num}\" {self.mac_addr_hex_strings[0]}\r\n",
                "EEPROM programming successful!",
                eeprom_programmed,
                slow=True)

        def eeprom_programmed(result):
            if result is False:
                self.logger.info("Failed or timed out programming EEPROM...")
                ctx.fail(texts.ERROR_FAILED_PROGRAM_EEPROM)
                return
            ctx.succeed()
            self.wait_for_self_tests()

        self.serial_controller.wait_for("=>", prompt_received)

    @test_method(TestKeys.WAIT_FOR_SELF_TESTS_PASS)
    def wait_for_self_tests(self, ctx):
        """Waits for self tests PASS output"""

        # Track if RTC warning is detected
        rtc_warning_detected = [False]

        def check_for_rtc_warning(line):
            """Temporary handler to check each line for RTC warning"""
            if "### Warning: RTC Low Voltage" in line:
                rtc_warning_detected[0] = True
                # Disconnect immediately and fail
                self.serial.line_received.disconnect(check_for_rtc_warning)
                self.logger.error("RTC Low Voltage warning detected during self tests")
                ctx.fail(texts.ERROR_RTC_LOW_VOLTAGE)

        def self_tests_check(result):
            # Disconnect the RTC warning handler
            try:
                self.serial.line_received.disconnect(check_for_rtc_warning)
            except TypeError:
                pass  # Already disconnected

            if result is False:
                self.logger.info("Failed or timed out waiting for self tests...")
                ctx.fail(texts.ERROR_SELF_TESTS_FAILED)
                return

            # Double-check flag in case warning came after PASS
            if rtc_warning_detected[0]:
                ctx.fail(texts.ERROR_RTC_LOW_VOLTAGE)
                return

            ctx.succeed()
            self.boot_to_recovery_linux()

        # Connect temporary handler to check all lines
        self.serial.line_received.connect(check_for_rtc_warning)

        self.serial_controller.send_and_expect("reset\r\n", "On-board devices self test: PASS", self_tests_check, timeout_s=60)

    @test_method(TestKeys.BOOT_TO_RECOVERY_LINUX)
    def boot_to_recovery_linux(self, ctx):
        """Boots into recovery linux to make following setup easier with linux tools"""
        def autoboot_stopped(result):
            if result is False:
                self.logger.info("Failed or timed out stopping autoboot...")
                ctx.fail(texts.ERROR_FAILED_STOP_AUTOBOOT)
                return
            self.serial_controller.wait_for_and_send("=>", "run recovery\r\n", do_login, timeout_s=60)

        def do_login(result):
            if result is False:
                self.logger.info("Failed or timed out running recovery command...")
                ctx.fail(texts.ERROR_FAILED_RUN_RECOVERY)
                return
            self.serial_controller.wait_for_and_send("recovery login:", "root\r\n", booting_done, timeout_s=60)

        def booting_done(result):
            if result is False:
                self.logger.info("Failed or timed out logging into recovery...")
                ctx.fail(texts.ERROR_FAILED_LOGIN_RECOVERY)
                return
            ctx.succeed()
            self.partition_emmc()

        self.serial_controller.wait_for_and_send("stop autoboot", "\r\n", autoboot_stopped, timeout_s=60)


    @test_method(TestKeys.PARTITION_EMMC)
    def partition_emmc(self, ctx):
        """Make eMMC partitions"""
        def partitioning_done(result):
            if result is False:
                self.logger.info("Failed or timed out creating partitions...")
                ctx.fail(texts.ERROR_FAILED_PARTITION_EMMC)
                return
            cmd = "mkfs.ext4 /dev/mmcblk0p1 -F\r\n"
            self.serial_controller.send_and_expect(cmd, "Writing superblocks and filesystem accounting information", wait_for_done, timeout_s=120)

        def wait_for_done(result):
            if result is False:
                self.logger.info("Failed or timed out creating filesystem...")
                ctx.fail(texts.ERROR_FAILED_CREATE_FILESYSTEM)
                return
            self.serial_controller.wait_for("done", filesystem_done)

        def filesystem_done(result):
            if result is False:
                self.logger.info("Failed or timed out waiting for filesystem creation to complete...")
                ctx.fail(texts.ERROR_FILESYSTEM_CREATION_INCOMPLETE)
                return
            ctx.succeed()
            self.mount_usb_drive()

        time.sleep(5)
        cmd = "parted /dev/mmcblk0 mklabel gpt -s && parted /dev/mmcblk0 mkpart primary ext4 32MiB 100% -s\r\n"
        self.serial_controller.send_and_expect(cmd, "root@recovery:~#", partitioning_done)

    @test_method(TestKeys.MOUNT_USB_DRIVE)
    def mount_usb_drive(self, ctx):
        """Mount USB stick where files are"""
        def mounting_done(result):
            if result is False:
                self.logger.info("Failed or timed out mounting USB drive...")
                ctx.fail(texts.ERROR_FAILED_MOUNT_USB)
                return
            ctx.succeed()
            self.write_image_to_emmc()

        cmd = "mkdir -p /mnt/usb && (mountpoint -q /mnt/usb || mount -t ext4 /dev/sda /mnt/usb) && ls /mnt/usb\r\n"
        self.serial_controller.send_and_expect(cmd, "firmware-qspi.bin", mounting_done)

    @test_method(TestKeys.WRITE_IMAGE_TO_EMMC)
    def write_image_to_emmc(self, ctx):
        """Write image to eMMC partition"""
        def dd_done(result):
            if result is False:
                self.logger.info("Failed or timed out writing image to eMMC...")
                ctx.fail(texts.ERROR_FAILED_WRITE_IMAGE_TO_EMMC)
                return
            self.serial_controller.send_and_expect("echo $?\r\n", "0", dd_successful)

        def dd_successful(result):
            if result is False:
                self.logger.info("dd command failed with non-zero exit code...")
                ctx.fail(texts.ERROR_DD_COMMAND_FAILED)
                return
            ctx.succeed()
            self.boot_to_openwrt()

        cmd = "dd if=/mnt/usb/openwrt.ext4 of=/dev/mmcblk0p1 bs=4M\r\n"
        self.serial_controller.send_and_expect(cmd, "root@recovery:~#", dd_done)

    @test_method(TestKeys.BOOT_TO_OPENWRT)
    def boot_to_openwrt(self, ctx):
        """Reboot and wait for OpenWRT prompt"""
        def openwrt_ready(result):
            if result is False:
                self.logger.info("Failed or timed out waiting for OpenWrt to boot...")
                ctx.fail(texts.ERROR_FAILED_BOOT_OPENWRT)
                return
            time.sleep(5)
            self.serial_controller.send_and_expect("\r\n", "root@OpenWrt:~#", openwrt_prompt_received)

        def openwrt_prompt_received(result):
            if result is False:
                self.logger.info("Failed or timed out waiting for OpenWrt prompt...")
                ctx.fail(texts.ERROR_FAILED_GET_OPENWRT_PROMPT)
                return
            ctx.succeed()
            self.test_network_config()

        self.serial_controller.send_and_expect("reboot\r\n", "kmodloader: done loading kernel modules from /etc/modules.d/*", openwrt_ready, timeout_s=60)

    @test_method(TestKeys.TEST_NETWORK_CONFIG)
    def test_network_config(self, ctx):
        """Test network configuration by applying test config and pinging gateways"""

        # Hardcoded network configuration
        network_config = """config interface 'loopback'
\toption device 'lo'
\toption proto 'static'
\toption ipaddr '127.0.0.1'
\toption netmask '255.0.0.0'

config interface 'eth0'
\toption device 'eth0'
\toption proto 'static'
\toption ipaddr '10.0.2.2'
\toption netmask '255.255.255.0'

config interface 'eth1'
\toption device 'eth1'
\toption proto 'static'
\toption ipaddr '10.0.5.2'
\toption netmask '255.255.255.0'

config interface 'eth2'
\toption device 'eth2'
\toption proto 'static'
\toption ipaddr '10.0.6.2'
\toption netmask '255.255.255.0'

config interface 'eth3'
\toption device 'eth3'
\toption proto 'static'
\toption ipaddr '10.0.9.2'
\toption netmask '255.255.255.0'

config interface 'eth4'
\toption device 'eth4'
\toption proto 'static'
\toption ipaddr '10.0.10.2'
\toption netmask '255.255.255.0'
"""

        # Interface and gateway pairs to test (interface, gateway)
        interface_gateways = [
            ("eth0", "10.0.2.1"),
            ("eth1", "10.0.5.1"),
            ("eth2", "10.0.6.1"),
            ("eth3", "10.0.9.1"),
            ("eth4", "10.0.10.1"),
        ]

        # Track the error to report after restore completes
        failure_error = [None]

        # Retry counters
        MAX_RETRIES = 3
        backup_retries = [0]
        write_retries = [0]

        def do_backup():
            """Execute the backup command with retry support."""
            self.logger.info(f"Backing up network config (attempt {backup_retries[0] + 1}/{MAX_RETRIES})...")
            self.serial_controller.send_and_expect(
                "cp /etc/config/network /etc/config/network.backup\r\n",
                "root@OpenWrt:~#",
                self.__check_exit_code(
                    on_success=write_new_config,
                    on_failure=on_backup_failure,
                    settle_delay_ms=5000
                ),
                timeout_s=10
            )

        def on_backup_failure(result):
            """Handle backup failure with retry logic."""
            backup_retries[0] += 1
            if backup_retries[0] < MAX_RETRIES:
                self.logger.info(f"Backup failed, retrying ({backup_retries[0]}/{MAX_RETRIES})...")
                # Wait a bit before retrying
                QTimer.singleShot(500, do_backup)
            else:
                self.logger.info(f"Backup failed after {MAX_RETRIES} attempts")
                ctx.fail(texts.ERROR_FAILED_BACKUP_NETWORK_CONFIG)

        def write_new_config(result):
            if result is False:
                self.logger.info("Failed to backup network config...")
                ctx.fail(texts.ERROR_FAILED_BACKUP_NETWORK_CONFIG)
                return
            do_write_config()

        def do_write_config():
            """Execute the write config command with retry support."""
            self.logger.info(f"Writing new network configuration (attempt {write_retries[0] + 1}/{MAX_RETRIES})...")
            # Use cat with heredoc to write the configuration
            cmd = f"cat > /etc/config/network << 'EOF'\n{network_config}EOF\r\n"
            self.serial_controller.send_and_expect(
                cmd,
                "root@OpenWrt:~#",
                self.__check_exit_code(
                    on_success=run_uci_commit,
                    on_failure=on_write_failure,
                    settle_delay_ms=5000
                ),
                timeout_s=10
            )

        def on_write_failure(result):
            """Handle write config failure with retry logic."""
            write_retries[0] += 1
            if write_retries[0] < MAX_RETRIES:
                self.logger.info(f"Write config failed, retrying ({write_retries[0]}/{MAX_RETRIES})...")
                # Wait a bit before retrying
                QTimer.singleShot(500, do_write_config)
            else:
                self.logger.info(f"Write config failed after {MAX_RETRIES} attempts")
                ctx.fail(texts.ERROR_FAILED_WRITE_NETWORK_CONFIG)

        def run_uci_commit(result):
            if result is False:
                self.logger.info("Failed to write network config...")
                ctx.fail(texts.ERROR_FAILED_WRITE_NETWORK_CONFIG)
                return
            self.logger.info("Running uci commit...")
            self.serial_controller.send_and_expect(
                "uci commit\r\n",
                "root@OpenWrt:~#",
                self.__check_exit_code(
                    on_success=restart_network,
                    on_failure=lambda r: (
                        failure_error.__setitem__(0, texts.ERROR_FAILED_UCI_COMMIT),
                        restore_config_on_failure(True)
                    )[1],
                    settle_delay_ms=5000
                ),
                timeout_s=10
            )

        def restart_network(result):
            if result is False:
                self.logger.info("uci commit failed...")
                failure_error[0] = texts.ERROR_FAILED_UCI_COMMIT
                restore_config_on_failure(True)
                return
            self.logger.info("Restarting network service...")
            self.serial_controller.send_and_expect(
                "service network restart\r\n",
                "root@OpenWrt:~#",
                self.__check_exit_code(
                    on_success=lambda r: start_ping_tests(r, 0),
                    on_failure=lambda r: (
                        failure_error.__setitem__(0, texts.ERROR_FAILED_RESTART_NETWORK),
                        restore_config_on_failure(True)
                    )[1],
                    settle_delay_ms=10000  # Longer delay - kernel messages flood during network restart
                ),
                timeout_s=30
            )

        def start_ping_tests(result, index):
            if result is False:
                self.logger.info("Network restart failed...")
                failure_error[0] = texts.ERROR_FAILED_RESTART_NETWORK
                restore_config_on_failure(True)
                return

            # Wait for interfaces to come up before first ping
            if index == 0:
                self.logger.info("Waiting 10s for interfaces to come up...")
                time.sleep(10)

            if index >= len(interface_gateways):
                # All pings successful, restore config and apply it
                restore_config_on_success(True)
                return

            time.sleep(5)
            interface, gateway = interface_gateways[index]
            self.logger.info(f"Pinging gateway {gateway} via {interface}...")
            self.serial_controller.send_and_expect(
                f"ping -c 3 -W 2 -I {interface} {gateway}\r\n",
                "root@OpenWrt:~#",
                self.__check_exit_code(
                    on_success=lambda r: ping_success(r, index),
                    on_failure=lambda r: (
                        self.logger.info(f"Failed to ping gateway {gateway} via {interface}..."),
                        failure_error.__setitem__(0, texts.ERROR_FAILED_PING_GATEWAY),
                        restore_config_on_failure(True)
                    )[2],
                    settle_delay_ms=5000
                ),
                timeout_s=15
            )

        def ping_success(result, index):
            if result is False:
                interface, gateway = interface_gateways[index]
                self.logger.info(f"Ping to {gateway} via {interface} failed...")
                failure_error[0] = texts.ERROR_FAILED_PING_GATEWAY
                restore_config_on_failure(True)
                return
            interface, gateway = interface_gateways[index]
            self.logger.info(f"Successfully pinged {gateway} via {interface}")
            # Proceed to the next ping test
            start_ping_tests(True, index + 1)

        def restore_config_on_failure(result):
            """Restore config after test failure - includes uci commit and service restart"""
            if result is False:
                self.logger.info("Failed to get prompt for restore after failure...")
                ctx.fail(texts.ERROR_FAILED_RESTORE_NETWORK_CONFIG)
                return
            self.logger.info("Test failed - restoring original network configuration...")
            self.serial_controller.send_and_expect(
                "mv /etc/config/network.backup /etc/config/network\r\n",
                "root@OpenWrt:~#",
                self.__check_exit_code(
                    on_success=uci_commit_after_restore_failure,
                    on_failure=lambda r: ctx.fail(texts.ERROR_FAILED_RESTORE_NETWORK_CONFIG),
                    settle_delay_ms=5000
                ),
                timeout_s=10
            )

        def uci_commit_after_restore_failure(result):
            if result is False:
                self.logger.info("Failed to restore network config file...")
                ctx.fail(texts.ERROR_FAILED_RESTORE_NETWORK_CONFIG)
                return
            self.logger.info("Running uci commit to apply restored config...")
            self.serial_controller.send_and_expect(
                "uci commit\r\n",
                "root@OpenWrt:~#",
                self.__check_exit_code(
                    on_success=restart_after_restore_failure,
                    on_failure=lambda r: ctx.fail(texts.ERROR_FAILED_UCI_COMMIT),
                    settle_delay_ms=5000
                ),
                timeout_s=10
            )

        def restart_after_restore_failure(result):
            if result is False:
                self.logger.info("uci commit failed after restore...")
                ctx.fail(texts.ERROR_FAILED_UCI_COMMIT)
                return
            self.logger.info("Restarting network service to apply restored config...")
            self.serial_controller.send_and_expect(
                "service network restart\r\n",
                "root@OpenWrt:~#",
                self.__check_exit_code(
                    on_success=restore_failure_complete,
                    on_failure=lambda r: ctx.fail(texts.ERROR_FAILED_RESTART_NETWORK),
                    settle_delay_ms=10000  # Longer delay - kernel messages flood during network restart
                ),
                timeout_s=30
            )

        def restore_failure_complete(result):
            if result is False:
                self.logger.info("Network restart failed after restore...")
                ctx.fail(texts.ERROR_FAILED_RESTART_NETWORK)
                return
            self.logger.info("Original config restored after test failure")
            # Report the original error that caused the test to fail
            ctx.fail(failure_error[0] if failure_error[0] else texts.ERROR_FAILED_PING_GATEWAY)

        def restore_config_on_success(result):
            """Restore config after successful tests - includes uci commit and service restart"""
            if result is False:
                self.logger.info("Failed to get prompt after ping tests...")
                ctx.fail(texts.ERROR_FAILED_RESTORE_NETWORK_CONFIG)
                return
            self.logger.info("All pings successful - restoring original network configuration...")
            self.serial_controller.send_and_expect(
                "mv /etc/config/network.backup /etc/config/network\r\n",
                "root@OpenWrt:~#",
                self.__check_exit_code(
                    on_success=uci_commit_after_restore_success,
                    on_failure=lambda r: ctx.fail(texts.ERROR_FAILED_RESTORE_NETWORK_CONFIG),
                    settle_delay_ms=5000
                ),
                timeout_s=10
            )

        def uci_commit_after_restore_success(result):
            if result is False:
                self.logger.info("Failed to restore network config file...")
                ctx.fail(texts.ERROR_FAILED_RESTORE_NETWORK_CONFIG)
                return
            self.logger.info("Running uci commit to apply restored config...")
            self.serial_controller.send_and_expect(
                "uci commit\r\n",
                "root@OpenWrt:~#",
                self.__check_exit_code(
                    on_success=restart_after_restore_success,
                    on_failure=lambda r: ctx.fail(texts.ERROR_FAILED_UCI_COMMIT),
                    settle_delay_ms=5000
                ),
                timeout_s=10
            )

        def restart_after_restore_success(result):
            if result is False:
                self.logger.info("uci commit failed after restore...")
                ctx.fail(texts.ERROR_FAILED_UCI_COMMIT)
                return
            self.logger.info("Restarting network service to apply restored config...")
            self.serial_controller.send_and_expect(
                "service network restart\r\n",
                "root@OpenWrt:~#",
                self.__check_exit_code(
                    on_success=test_complete,
                    on_failure=lambda r: ctx.fail(texts.ERROR_FAILED_RESTART_NETWORK),
                    settle_delay_ms=10000  # Longer delay - kernel messages flood during network restart
                ),
                timeout_s=30
            )

        def test_complete(result):
            if result is False:
                self.logger.info("Network restart after restore failed...")
                ctx.fail(texts.ERROR_FAILED_RESTART_NETWORK)
                return
            self.logger.info("Network configuration test completed successfully")
            ctx.succeed()
            self.done()

        # Start the backup process (with retry support)
        do_backup()

    def done(self):
        """Done, all tests have successfully passed and the board is
        fully functional (according to our knowledge)"""
        self.__change_state(State.DONE, texts.STATUS_DONE)
        self.logger.info(texts.LOG_INFO_DONE)

    def key_pressed(self, event):
        """Handler for all key presses.
        But it only forwards to scanner service if scanning QR codes state"""
        if self.current_test in (TestKeys.SCAN_SERIAL_NUM, TestKeys.SCAN_TWO_DM_QR_CODES):
            self.scanner.handle_input(event.key(), event.text())

    def __change_state(self, state, message=""):
        """Helper to make sure state_changed is emited also on state change"""
        self.state = state
        self.state_changed.emit(state, message)

    def __log_serial(self, data: str):
        """Persistent handler for logging all serial data"""
        self.logger.info(data, False)

    def __check_exit_code(self, on_success, on_failure, timeout_s=10, settle_delay_ms=100):
        """Helper to check command exit code and call appropriate callback.

        Args:
            on_success: Callback to call if exit code is 0 (receives True)
            on_failure: Callback to call if exit code is non-zero or timeout (receives False)
            timeout_s: Timeout in seconds for the exit code check
            settle_delay_ms: Delay in ms before checking exit code (increase for noisy commands)

        Returns:
            A callback function that can be used with send_and_expect
        """
        # Use unique markers that won't appear in kernel logs
        MARKER_PREFIX = "###EC:"
        MARKER_SUFFIX = "###"

        def check_exit_code(result):
            if result is False:
                # Timeout waiting for prompt
                self.logger.info("Timeout waiting for prompt")
                on_failure(False)
                return

            def parse_exit_code(line):
                """Parse exit code from captured line and call appropriate callback."""
                if line is False:
                    # Timeout waiting for exit code response
                    self.logger.info("Timeout waiting for exit code response")
                    on_failure(False)
                    return

                # Skip the echoed command line - we want the output line
                # The echoed command contains "$?" literally, while the output has the actual number
                if "$?" in line:
                    # This is the echoed command, wait for the actual output
                    self.serial_controller.wait_for_with_capture(
                        MARKER_PREFIX,
                        parse_exit_code,
                        timeout_s=timeout_s
                    )
                    return

                # Parse the exit code from line like "###EC:0###" or "###EC:1###"
                try:
                    # Find marker and extract the number
                    idx = line.find(MARKER_PREFIX)
                    if idx != -1:
                        after_prefix = line[idx + len(MARKER_PREFIX):]
                        # Extract digits until we hit the suffix or non-digit
                        code_str = ""
                        for ch in after_prefix:
                            if ch.isdigit():
                                code_str += ch
                            else:
                                break
                        if code_str:
                            exit_code = int(code_str)
                            if exit_code == 0:
                                on_success(True)
                            else:
                                self.logger.info(f"Command failed with exit code: {exit_code}")
                                on_failure(False)
                        else:
                            self.logger.info(f"No digits found after marker in: {line}")
                            on_failure(False)
                    else:
                        self.logger.info(f"Could not find exit code marker in: {line}")
                        on_failure(False)
                except (ValueError, IndexError) as e:
                    self.logger.info(f"Failed to parse exit code from '{line}': {e}")
                    on_failure(False)

            def send_exit_code_check():
                # Use unique markers unlikely to appear in kernel logs
                self.serial_controller.send_and_expect_with_capture(
                    f'echo "{MARKER_PREFIX}$?{MARKER_SUFFIX}"\r\n',
                    MARKER_PREFIX,
                    parse_exit_code,
                    timeout_s=timeout_s
                )

            def get_clean_prompt_then_check(result):
                # After noisy commands, the prompt may be buried in output
                # Now that we have a clean prompt, send the exit code check
                if result is False:
                    self.logger.info("Timeout waiting for clean prompt")
                    on_failure(False)
                    return
                send_exit_code_check()

            def send_enter_for_clean_prompt():
                # Send Enter to get a clean prompt line after noisy commands
                # This ensures we have a clear prompt before checking exit code
                self.serial_controller.send_and_expect(
                    "\r\n",
                    "root@OpenWrt:~#",
                    get_clean_prompt_then_check,
                    timeout_s=timeout_s
                )

            # Got prompt, add delay before checking exit code to allow
            # serial buffer to settle and shell to fully process the command
            # Use longer delay for commands that produce lots of output (like network restart)
            QTimer.singleShot(settle_delay_ms, send_enter_for_clean_prompt)
        return check_exit_code
