"""
Test definitions for display and update on UI
"""

from enum import Enum

class TestKeys(Enum):
    """Holds application test definitions with description for UI display"""
    CONN_TO_UART =              "Connect to UART"
    SCAN_SERIAL_NUM =           "Scan serial number"
    SCAN_TWO_DM_QR_CODES =      "Scan two data matrix QR codes"
    REGISTER_DEVICE =           "Register device and get MAC addresses from server"
    LOAD_UBOOT_SPL_VIA_JTAG =   "Load U-Boot SPL via JTAG"
    WAIT_FOR_UBOOT_SPL_PROMPT = "Receive U-Boot SPL prompt"
    LOAD_QSPI_FIRMWARE_TO_MEM = "Loading QSPI firmware into memory"
    WAIT_FOR_SELF_TESTS_PASS =  "Self tests PASS"
    WAIT_FOR_UBOOT_PROMPT =     "Receive U-Boot prompt"

    @property
    def description(self):
        """Returns the test description"""
        return self.value
