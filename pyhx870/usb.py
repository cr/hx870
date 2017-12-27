# -*- coding: utf-8 -*-

import logging
import time
import usb


logger = logging.getLogger(__name__)


class HX870USB(object):
    """
    USB communication for Standard Horizon HX870 maritime radios

    TODO: This is just a dummy, because the OS's USB Serial module grabs
    the endpoint before we can.
    """

    USB_VENDOR = 0x26aa
    USB_PRODUCT = 0x0010

    def __init__(self, cid=0):
        """
        USB connection class for HX870 handsets
        Per default the first USB device (CID 0) is used.

        :param cid: int (default: 0)
        """
        self.cid = cid
        self.dev = None
        self.cfg = None
        self.int_comm = None
        self.int_data = None
        self.ep_comm = None
        self.ep_data_a = None
        self.ep_data_b = None

    @classmethod
    def find(cls, cid=0):
        """
                Return the USB device object of the HX870 designated by CID.
        Returns None if the CID is not found.


        :param cid: int (default: 0)
        :return: usb.Device or None
        """
        devices = list(usb.core.find(find_all=True, idVendor=cls.USB_VENDOR, idProduct=cls.USB_PRODUCT))
        try:
            return devices[cid]
        except IndexError:
            return None

    def connect(self):
        """
        Connect to device and return whether the connection succeeded.

        :return: bool
        """

        self.dev = self.find()
        if self.dev is None:
            return False

        # so far it has always been like this on my HX870
        assert self.dev.bLength == 18
        assert self.dev.bDescriptorType == 1
        assert self.dev.bDeviceClass == 2  # Communications Device Class
        assert self.dev.bDeviceProtocol == 0
        assert self.dev.bDeviceSubClass == 0
        assert self.dev.bNumConfigurations == 1

        # use default config
        self.dev.set_configuration()
        self.cfg = self.dev.get_active_configuration()

        # two interfaces on my HX870, one comm and one data
        assert self.cfg.bNumInterfaces == 2

        # get communications and data interfaces
        self.int_comm = self.cfg[(0, 0)]  # (interface index, altsetting index)
        self.int_data = self.cfg[(1, 0)]

        assert self.int_comm.bInterfaceClass == 2  # Communications Interface Class
        assert self.int_comm.bInterfaceSubClass == 2  # Abstract Control Model
        assert self.int_comm.bInterfaceProtocol == 1  # AT Commands, see ITU-T V.250
        assert self.int_comm.bNumEndpoints == 1

        assert self.int_data.bInterfaceClass == 10  # Data Interface Class
        assert self.int_data.bInterfaceSubClass == 0  # unused, should be 0
        assert self.int_data.bInterfaceProtocol == 0  # No class specific protocol required
        assert self.int_data.bNumEndpoints == 2

        # get endpoints
        self.ep_comm = self.int_comm[0]
        self.ep_data_a = self.int_data[0]
        self.ep_data_b = self.int_data[1]

        assert self.ep_comm.bDescriptorType == 5  # Telephone Call and Line State Reporting Capabilities
        # assert self.ep_comm.bEndpointAddress == 131
        # assert self.ep_comm.bInterval == 16
        # assert self.ep_comm.bLength == 7
        assert self.ep_comm.bmAttributes == 3  # 00000011  Interrupt

        assert self.ep_data_a.bDescriptorType == 5  # Telephone Call and Line State Reporting Capabilities
        # assert self.ep_data_a.bEndpointAddress == 129
        # assert self.ep_data_a.bInterval == 0
        # assert self.ep_data_a.bLength == 7
        assert self.ep_data_a.bmAttributes == 2  # 00000010 Bulk

        assert self.ep_data_b.bDescriptorType == 5  # Telephone Call and Line State Reporting Capabilities
        # assert self.ep_data_b.bEndpointAddress == 2
        # assert self.ep_data_b.bInterval == 0
        # assert self.ep_data_b.bLength == 7
        assert self.ep_data_b.bmAttributes == 2  # 00000010 Bulk

        return True

    def wait(self, timeout=20, interval=0.5):

        timeout_time = time.time() + timeout

        while time.time() < timeout_time:
            if self.connect():
                return True
            time.sleep(interval)

        return False

    def write(self, data):
        return 0

    def read_all(self, *args, **kwargs):
        return b"#CMDOK\r\n"

    def read_line(self, *args, **kwargs):
        return b"#CMDOK\r\n"
