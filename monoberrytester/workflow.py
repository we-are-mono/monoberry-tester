# pylint: disable=too-many-instance-attributes

"""
All 'business' logic
"""

import time
import json
from datetime import datetime
from enum import Enum, auto
from functools import wraps
from PyQt5.QtCore import QObject, QThread, pyqtSignal

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

            def handle_failure():
                ctx.fail()
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

                def fail(ctx_self):
                    """Mark test as failed"""
                    self.test_state_changed.emit(test_key, TestState.FAILED)

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
        self.logger.info("--- Reseting ---")
        self.current_test = None
        self.scanned_codes = []
        self.mac_addresses = []
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
        def handle_process_output_received(text):
            """Called when program outputs something to stdout"""
            self.logger.info(text)

        def handle_process_error_received(err_msg):
            """Called when program outputs something to stderr"""
            self.logger.error(err_msg)

        def handle_process_errored(err_msg):
            """Called when process errors out"""
            self.logger.error(f"{texts.LOG_PROCESS_ERRORED} {err_msg}")
            self.__change_state(State.FAILED, f"{texts.STATUS_PROCESS_ERRORED} {err_msg}")

        def handle_process_finished(return_code):
            """Called when process returns/exits"""
            self.logger.info(f"{texts.LOG_PROCESS_EXITED} {return_code}")
            if return_code == 0:
                pass
            else:
                self.logger.error(texts.LOG_PROCESS_EXITED_NON_0_CODE)

        def confirm_or_continue(result):
            """Either confirm or continue anyways if there's not continue prompt"""
            self.logger.info(f"Reflash UART confirm or continue: {result}")
            self.process_runner.output_received.disconnect(handle_process_output_received)
            self.process_runner.error_received.disconnect(handle_process_error_received)
            self.process_runner.process_errored.disconnect(handle_process_errored)
            self.process_runner.process_finished.disconnect(handle_process_finished)

            self.process_runner.stop()
            self.usb_service.reset_usb(usb_id)
            time.sleep(5)
            ctx.succeed()
            self.connect_to_uart()

        self.process_runner.output_received.connect(handle_process_output_received)
        self.process_runner.error_received.connect(handle_process_error_received)
        self.process_runner.process_errored.connect(handle_process_errored)
        self.process_runner.process_finished.connect(handle_process_finished)

        usb_id = self.usb_service.get_usb_id(self.serial.port_name)
        self.process_controller.wait_for_and_send("Continue? [y|n]:", "y\r\n", confirm_or_continue, timeout_s=2)
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
            self.__change_state(State.FAILED, f"{texts.STATUS_CONN_TO_UART_FAILED} {err_msg}")
            ctx.fail()

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
                ctx.fail()

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
                ctx.fail()

        def handle_server_error(err_msg):
            """Called upon server connection error"""
            self.server_client.response_received.disconnect(handle_server_response)
            self.server_client.error_occured.disconnect(handle_server_error)

            self.server_thread.quit()
            self.server_thread.wait()

            ctx.fail()
            self.__change_state(State.FAILED, f"{texts.CONN_TO_SERVER_FAILED}:\n{err_msg}")

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
            self.__change_state(State.FAILED, f"{texts.STATUS_PROCESS_ERRORED} {err_msg}")

        def handle_process_finished(return_code):
            """Called when process returns/exits"""
            self.logger.info(f"{texts.LOG_PROCESS_EXITED} {return_code}")
            if return_code == 0:
                pass
            else:
                self.logger.error(texts.LOG_PROCESS_EXITED_NON_0_CODE)

        def handle_exiting(result):
            if result is False:
                ctx.fail()
                self.logger.info("Failed or timed out waiting for lsbp.tcl to exit...")
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

        self.process_controller.wait_for("lsbp.tcl is exiting...", handle_exiting, timeout_s=180)
        self.process_runner.start(self.ccs_tools_path + "/CCS/bin/ccs", ["-nogfx", "-console", "-file", self.ccs_tools_path + "/TAP/lsbp.tcl"])

    @test_method(TestKeys.WAIT_FOR_UBOOT_SPL_PROMPT)
    def wait_for_uboot_spl(self, ctx):
        """Wait for u-boot prompt"""

        def callback(result):
            if result is False:
                ctx.fail()
                self.logger.info("Failed or timed out...")
                return
            ctx.succeed()
            self.write_firmware_to_flash()

        self.serial_controller.wait_for_and_send("stop autoboot", "\r\n", callback, timeout_s=10)

    @test_method(TestKeys.WRITE_FIRMWARE_TO_FLASH)
    def write_firmware_to_flash(self, ctx):
        """Write firware to flash"""
        def start_usb():
            self.logger.info("Starting USB")
            self.serial_controller.send_and_expect("usb start\r\n", "Storage Device(s) found", load_firmware_to_mem, timeout_s=10)

        def load_firmware_to_mem(result):
            if result is False:
                ctx.fail()
                self.logger.info("Failed or timed out...")
                return
            self.logger.info("Loading QSPI firmware into memory")
            self.serial_controller.send_and_expect("ext4load usb 0:0 0xC0000000 firmware-qspi.bin\r\n", "bytes read in", flash_probe, timeout_s=30)

        def flash_probe(result):
            if result is False:
                ctx.fail()
                self.logger.info("Failed or timed out...")
                return
            self.logger.info("Probing the flash")
            self.serial_controller.send_and_expect("sf probe 0\r\n", "SF: Detected", flash_erase, timeout_s=10)

        def flash_erase(result):
            if result is False:
                ctx.fail()
                self.logger.info("Failed or timed out...")
                return
            self.logger.info("Erasing the flash")
            self.serial_controller.send_and_expect("sf erase 0x0 0x2000000\r\n", "Erased: OK", flash_write, timeout_s=120)

        def flash_write(result):
            if result is False:
                ctx.fail()
                self.logger.info("Failed or timed out...")
                return
            self.logger.info("Writing QSPI firmware to flash")
            self.serial_controller.send_and_expect("sf write 0xC0000000 0x0 ${filesize}\r\n", "Written: OK", flash_finished, timeout_s=120)

        def flash_finished(result):
            if result is False:
                ctx.fail()
                self.logger.info("Failed or timed out...")
                return
            ctx.succeed()
            self.wait_for_uboot_prompt()

        start_usb()

    @test_method(TestKeys.WAIT_FOR_UBOOT_PROMPT)
    def wait_for_uboot_prompt(self, ctx):
        """Wait for U-Boot prompt"""

        def after_reset(result):
            if result is False:
                ctx.fail()
                self.logger.info("Failed or timed out...")
                return
            self.serial_controller.wait_for_and_send("stop autoboot", "\r\n", uboot_prompt_received, timeout_s=60)

        def uboot_prompt_received(result):
            if result is False:
                ctx.fail()
                self.logger.info("Failed or timed out...")
                return
            ctx.succeed()
            self.set_time_in_uboot()

        self.serial_controller.send_and_expect("reset\r\n", "Model: Mono Gateway Development Kit", after_reset, timeout_s=60)

    @test_method(TestKeys.SET_TIME_IN_UBOOT)
    def set_time_in_uboot(self, ctx):
        """Set time in U-Boot"""

        def prompt_received(result):
            if result is False:
                ctx.fail()
                self.logger.info("Failed or timed out...")
                return
            self.serial_controller.send_and_expect("date " + t + "\r\n", "Date:", time_set, timeout_s=30)

        def time_set(result):
            if result is False:
                ctx.fail()
                self.logger.info("Failed or timed out...")
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
                ctx.fail()
                self.logger.info("Failed or timed out...")
                return
            time.sleep(1)
            self.serial_controller.send_and_expect("mw 2320000 80000080; mw 2320008 40098033; i2c dev 3\r\n", "Setting bus to 3", bus_set)

        def bus_set(result):
            if result is False:
                ctx.fail()
                self.logger.info("Failed or timed out...")
                return
            self.serial_controller.send_and_expect("i2c mw 0x50 0x0000.2 0x00\r\n", "=>", eeprom_erased)

        def eeprom_erased(result):
            if result is False:
                ctx.fail()
                self.logger.info("Failed or timed out...")
                return
            self.serial_controller.send_and_expect(
                f"program_eeprom \"Mono Gateway Development Kit\" \"{self.serial_num}\" {self.mac_addr_hex_strings[0]}\r\n",
                "EEPROM programming successful!",
                eeprom_programmed,
                slow=True)

        def eeprom_programmed(result):
            if result is False:
                ctx.fail()
                self.logger.info("Failed or timed out...")
                return
            ctx.succeed()
            self.wait_for_self_tests()

        self.serial_controller.wait_for("=>", prompt_received)

    @test_method(TestKeys.WAIT_FOR_SELF_TESTS_PASS)
    def wait_for_self_tests(self, ctx):
        """Waits for self tests PASS output"""

        def self_tests_check(result):
            if result is False:
                ctx.fail()
                self.logger.info("Failed or timed out...")
                return
            ctx.succeed()
            self.boot_to_recovery_linux()

        self.serial_controller.send_and_expect("reset\r\n", "On-board devices self test: PASS", self_tests_check, timeout_s=60)

    @test_method(TestKeys.BOOT_TO_RECOVERY_LINUX)
    def boot_to_recovery_linux(self, ctx):
        """Boots into recovery linux to make following setup easier with linux tools"""
        def autoboot_stopped(result):
            if result is False:
                ctx.fail()
                self.logger.info("Failed or timed out...")
                return
            self.serial_controller.wait_for_and_send("=>", "run recovery\r\n", do_login, timeout_s=60)

        def do_login(result):
            if result is False:
                ctx.fail()
                self.logger.info("Failed or timed out...")
                return
            self.serial_controller.wait_for_and_send("recovery login:", "root\r\n", booting_done, timeout_s=60)

        def booting_done(result):
            if result is False:
                ctx.fail()
                self.logger.info("Failed or timed out...")
                return
            ctx.succeed()
            self.partition_emmc()

        self.serial_controller.wait_for_and_send("stop autoboot", "\r\n", autoboot_stopped, timeout_s=60)


    @test_method(TestKeys.PARTITION_EMMC)
    def partition_emmc(self, ctx):
        """Make eMMC partitions"""
        def partitioning_done(result):
            if result is False:
                ctx.fail()
                self.logger.info("Failed or timed out...")
                return
            cmd = "mkfs.ext4 /dev/mmcblk0p1 -F\r\n"
            self.serial_controller.send_and_expect(cmd, "Writing superblocks and filesystem accounting information", wait_for_done, timeout_s=120)

        def wait_for_done(result):
            if result is False:
                ctx.fail()
                self.logger.info("Failed or timed out...")
                return
            self.serial_controller.wait_for("done", filesystem_done)

        def filesystem_done(result):
            if result is False:
                ctx.fail()
                self.logger.info("Failed or timed out...")
                return
            ctx.succeed()
            self.mount_usb_drive()

        cmd = "parted /dev/mmcblk0 mklabel gpt -s && parted /dev/mmcblk0 mkpart primary ext4 32MiB 100% -s\r\n"
        self.serial_controller.send_and_expect(cmd, "root@recovery:~#", partitioning_done)

    @test_method(TestKeys.MOUNT_USB_DRIVE)
    def mount_usb_drive(self, ctx):
        """Mount USB stick where files are"""
        def mounting_done(result):
            if result is False:
                ctx.fail()
                self.logger.info("Failed or timed out...")
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
                ctx.fail()
                self.logger.info("Failed or timed out...")
                return
            self.serial_controller.send_and_expect("echo $?\r\n", "0", dd_successful)

        def dd_successful(result):
            if result is False:
                ctx.fail()
                self.logger.info("Failed or timed out...")
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
                ctx.fail()
                self.logger.info("Failed or timed out...")
                return
            time.sleep(2)
            self.serial_controller.send_and_expect("\r\n", "root@OpenWrt:~#", openwrt_prompt_received)

        def openwrt_prompt_received(result):
            if result is False:
                ctx.fail()
                self.logger.info("Failed or timed out...")
                return
            ctx.succeed()
            self.done()

        self.serial_controller.send_and_expect("reboot\r\n", "kmodloader: done loading kernel modules from /etc/modules.d/*", openwrt_ready, timeout_s=60)

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
