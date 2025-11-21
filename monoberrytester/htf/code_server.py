from openhtf.core import base_plugs
from openhtf.util import configuration
import requests

configuration.CONF.declare('code_server_endpoint')

class CodeServer(base_plugs.BasePlug):
    @configuration.CONF.inject_positional_args
    def __init__(self, code_server_endpoint: str):
        self._endpoint = code_server_endpoint

    def get_serial_number_and_macs(self, qr1, qr2):
        response = requests.get(
            f"{self._endpoint}/serial-macs", params={"qr1": qr1, "qr2": qr2})
        serial, *macs = response.text.split()
        return serial, macs
