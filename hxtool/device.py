# -*- coding: utf-8 -*-

from distutils.spawn import find_executable
import logging
import subprocess
import serial.tools.list_ports

from .protocol import GenericHXProtocol
from .config import HX870Config, HX890Config

logger = logging.getLogger(__name__)


def enumerate(force_device=None, force_model=None):

    global models

    if force_device is None and force_model is None:
        devices = []
        for model in models.values():
            devices += enumerate_model(model)
        return devices

    elif force_device is not None and force_model is None:

        if force_device.isdecimal():
            # User addressed device by its numeric selector
            devices = []
            for model in models.values():
                devices += enumerate_model(model)
            try:
                return devices[force_device]
            except IndexError:
                logger.critical("You gave a numeric device selector, but there is no such device.")
                return []

        # Device is given as tty spec, so autodetect model
        for m in [HX870, HX890]:
            d = m(force_device)
            if d.check_flash_id():
                return [d]
        else:
            logger.warning(f"Unable to detect model listening on {force_device}. Try specifying --model.")
            return []

    elif force_device is not None and force_model is not None:

        try:
            model = models[force_model.upper()]
        except KeyError:
            logger.critical(f"Invalid model specifier `{force_model}`")
            return []

        return [model(force_device)]

    logger.critical("Unable to detect device")
    return []


def enumerate_model(hx_device) -> list:

    devices = []

    for d in serial.tools.list_ports.comports():
        if d.vid == hx_device.usb_vendor_id and d.pid == hx_device.usb_product_id:
            if not d.description == hx_device.usb_product_name \
                    and not d.description == f"{hx_device.usb_product_name} [{d.device}]":
                logger.warning(f"Unexpected serial device description `{d.description}` (BE CAREFUL)")
            devices.append(hx_device(d.device))

    return devices


class HX870(object):
    """
    Device object for Standard Horizon HX890 maritime radios
    """
    handle = "HX870"
    brand = "Standard Horizon"
    model = "HX870"
    usb_vendor_id = 9898
    usb_vendor_name = "YAESU MUSEN CO.,LTD."
    usb_product_id = 16
    usb_product_name = "HX870"
    flash_id = ["AM057N", "AM057N2"]

    protocol_model = GenericHXProtocol
    config_model = HX870Config
    nmea_model = "GenericHXNMEA"

    def __init__(self, tty):
        self.tty = tty
        self.comm = self.protocol_model(tty=tty)
        self.config = None
        self.nema = None

        # See what we're talking to on that tty
        if self.comm.hx_hardware:
            if self.comm.cp_mode:
                self.config = self.config_model(self.comm)
                self.nmea = None
                fw = self.comm.get_firmware_version()
                logger.info(f"Device on {self.tty} is {self.handle} in CP mode, firmware version {fw}")
            elif self.comm.nmea_mode:
                self.config = None
                # self.nmea = self.nmea_model(self.comm)
                self.nmea = None
                logger.info(f"Device on {self.tty} is {self.handle} in NMEA mode")
            elif not self.comm.cp_mode and not self.comm.nmea_mode:
                self.config = None
                self.nmea = None
                logger.warning(f"Device on {self.tty} is {self.handle} in neither CP nor NMEA mode")
                logger.critical("This should never happen. Please file an issue on GitHub.")
            else:
                self.config = self.config_model(self.comm)
                # self.nmea = self.nmea_model(self.comm)
                self.nmea = None
                logger.warning(f"Device on {self.tty} is {self.handle} reports both CP and NMEA mode")
                logger.critical("This should never happen. Please file an issue on GitHub.")
        else:
            logger.error(f"Device on {self.tty} does not behave like HX hardware")

    @property
    def cp_mode(self) -> bool:
        return self.comm.cp_mode

    def check_flash_id(self, flash_id: list or None = None):
        return self.comm.check_flash_id(flash_id or self.flash_id)

    def __str__(self):
        return f"{self.brand} {self.handle} on `{self.tty} [{'CP Mode' if self.comm.cp_mode else 'NMEA Mode'}]`"


class HX890(HX870):
    """
    Device object for Standard Horizon HX890 maritime radios
    """
    handle = "HX890"
    brand = "Standard Horizon"
    model = "HX890"
    usb_vendor_id = 9898
    usb_vendor_name = "YAESU MUSEN CO.,LTD."
    usb_product_id = 30
    usb_product_name = "HX890"
    flash_id = ["AM063N"]

    protocol_model = GenericHXProtocol
    config_model = HX890Config
    nema_model = "GenericHXNMEA"


models = {}
for model_class in HX870, HX890:
    models[model_class.handle.upper()] = model_class
del model_class
