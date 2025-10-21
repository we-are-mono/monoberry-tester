"""
Test definitions for display and update on UI
"""

from enum import Enum, auto

class TestKeys(Enum):
    T0_CONN_TO_UART =           "0_conn_to_uart"
    T1_SCAN_TWO_DM_QR_CODES =   "1_scan_two_dm_qr_codes"
    T2_FETCH_SERIAL_AND_MACS =  "2_fetch_serial_and_macs"
    T3_RECEIVE_DATA_VIA_UART =  "3_receive_data_via_uart"

TEST_DEFS = {
    TestKeys.T0_CONN_TO_UART:           "Connect to UART",
    TestKeys.T1_SCAN_TWO_DM_QR_CODES:   "Scan two data matrix QR codes",
    TestKeys.T2_FETCH_SERIAL_AND_MACS:  "Fetch serial number and MAC addresses from server",
    TestKeys.T3_RECEIVE_DATA_VIA_UART:  "Receive data via UART"
}
