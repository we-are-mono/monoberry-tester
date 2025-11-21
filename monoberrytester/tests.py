"""
Test definitions for display and update on UI
"""

from enum import Enum

class TestKeys(Enum):
    """Holds application states"""
    CONN_TO_UART =          "conn_to_uart"
    SCAN_SERIAL_NUM =       "scan_serial_num"
    SCAN_TWO_DM_QR_CODES =  "scan_two_dm_qr_codes"
    REGISTER_DEVICE =       "register_device"
    LOAD_UBOOT_VIA_JTAG =   "load_uboot_via_jtag"
    RECEIVE_UBOOT_PROMPT =  "receive_uboot_prompt"

TEST_DEFS = {
    TestKeys.CONN_TO_UART:           "Connect to UART",
    TestKeys.SCAN_SERIAL_NUM:        "Scan serial number",
    TestKeys.SCAN_TWO_DM_QR_CODES:   "Scan two data matrix QR codes",
    TestKeys.REGISTER_DEVICE:        "Register device and get MAC addresses from server",
    TestKeys.LOAD_UBOOT_VIA_JTAG:    "Load U-Boot via JTAG",
    TestKeys.RECEIVE_UBOOT_PROMPT:   "Receive u-boot prompt"
}
