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
    WRITE_FIRMWARE_TO_FLASH = "Load QSPI firmware into memory"
    WAIT_FOR_UBOOT_PROMPT =     "Receive U-Boot prompt"
    SET_TIME_IN_UBOOT =         "Set time in U-Boot"
    PROGRAM_EEPROM =            "Program EEPROM with serial number and MACs"
    WAIT_FOR_SELF_TESTS_PASS =  "Pass self tests"
    BOOT_TO_RECOVERY_LINUX =    "Boot to recovery Linux"
    PARTITION_EMMC =            "Partition eMMC"
    MOUNT_USB_DRIVE =           "Mount USB drive"
    WRITE_IMAGE_TO_EMMC =       "Write image to eMMC"
    BOOT_TO_OPENWRT =           "Boot to OpenWRT"

    @property
    def description(self):
        """Returns the test description"""
        return self.value
