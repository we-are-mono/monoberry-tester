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
    RECEIVE_DATA_VIA_UART = "receive_data_via_uart"
    RECEIVE_UBOOT_PROMPT =  "receive_uboot_prompt"

TEST_DEFS = {
    TestKeys.CONN_TO_UART:           "Connect to UART",
    TestKeys.SCAN_SERIAL_NUM:        "Scan serial number",
    TestKeys.SCAN_TWO_DM_QR_CODES:   "Scan two data matrix QR codes",
    TestKeys.REGISTER_DEVICE:        "Register device and get MAC addresses from server",
    TestKeys.RECEIVE_DATA_VIA_UART:  "Receive data via UART",
    TestKeys.RECEIVE_UBOOT_PROMPT:   "Receive u-boot prompt"
}
