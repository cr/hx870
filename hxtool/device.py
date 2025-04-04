# -*- coding: utf-8 -*-

from logging import getLogger
from serial.tools import list_ports

from .config import HX870Config, HX890Config, HX891Config
from .nmea import HX870NMEAProtocol, HX890NMEAProtocol
from .protocol import GenericHXProtocol, MediaTekProtocol
from .simulator import HXSimulator

logger = getLogger(__name__)


def enumerate(force_device=None, force_model=None, add_simulator=False):

    global models

    devices = []

    if add_simulator:
        sim = HXSimulator(HX870Config, mode="CP")
        sim.start()
        devices.append(HX870Sim(sim.tty))
        sim = HXSimulator(HX870Config, mode="NMEA")
        sim.start()
        devices.append(HX870Sim(sim.tty))

        sim = HXSimulator(HX890Config, mode="CP")
        sim.start()
        devices.append(HX890Sim(sim.tty))
        sim = HXSimulator(HX890Config, mode="NMEA")
        sim.start()
        devices.append(HX890Sim(sim.tty))

        sim = HXSimulator(HX891Config, mode="CP")
        sim.start()
        devices.append(HX891Sim(sim.tty))
        sim = HXSimulator(HX891Config, mode="NMEA")
        sim.start()
        devices.append(HX891Sim(sim.tty))

    if force_device is None and force_model is None:
        for model in models.values():
            devices += enumerate_model(model)
        return devices

    elif force_device is not None and force_model is None:

        if force_device.isdecimal():
            # User addressed device by its numeric selector
            for model in models.values():
                devices += enumerate_model(model)
            try:
                return [devices[int(force_device)]]
            except IndexError:
                logger.error(f"Invalid numeric device selector {force_device}")
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

    for d in list_ports.comports():
        if d.vid == hx_device.usb_vendor_id and d.pid == hx_device.usb_product_id:
            if not d.description == hx_device.usb_product_name \
                    and not d.description == f"{hx_device.usb_product_name} ({d.device})":
                logger.warning(f"Unexpected serial device description `{d.description}` (BE CAREFUL)")
            devices.append(hx_device(d.device))

    return devices


class HX870(object):
    """
    Device object for Standard Horizon HX870 maritime radios
    """
    handle = "HX870"
    brand = "Standard Horizon"
    model = "HX870"
    usb_vendor_id = 9898
    usb_vendor_name = "YAESU MUSEN CO.,LTD."
    usb_product_id = 16
    usb_product_name = "HX870"

    protocol_model = GenericHXProtocol
    config_model = HX870Config
    nmea_model = HX870NMEAProtocol
    gps_model = MediaTekProtocol

    def __init__(self, tty):
        self.tty = tty
        self.comm = self.protocol_model(tty=tty)
        self.config = None
        self.nmea = None
        self.gps = None
        self.__init_config()

    def __init_config(self):
        # See what we're talking to on that tty
        if self.comm.hx_hardware:
            if self.comm.cp_mode:
                self.config = self.config_model(self.comm)
                self.nmea = None
                self.gps = self.gps_model(self.comm)
                fw = self.comm.get_firmware_version()
                logger.info(f"Device on {self.tty} is {self.handle} in CP mode, firmware version {fw}")
            elif self.comm.nmea_mode:
                self.config = None
                self.nmea = self.nmea_model(self.comm)
                self.gps = self.gps_model(self.comm)
                logger.info(f"Device on {self.tty} is {self.handle} in NMEA mode")
            elif not self.comm.cp_mode and not self.comm.nmea_mode:
                self.config = None
                self.nmea = None
                self.gps = None
                logger.warning(f"Device on {self.tty} is {self.handle} in neither CP nor NMEA mode")
                logger.critical("This should never happen. Please file an issue on GitHub.")
            else:
                self.config = self.config_model(self.comm)
                self.nmea = self.nmea_model(self.comm)
                self.gps = self.gps_model(self.comm)
                logger.warning(f"Device on {self.tty} is {self.handle} reports both CP and NMEA mode")
                logger.critical("This should never happen. Please file an issue on GitHub.")
        else:
            logger.error(f"Device on {self.tty} does not behave like HX hardware")

    @property
    def cp_mode(self) -> bool:
        return self.comm.cp_mode

    def check_flash_id(self, flash_id: list = None):
        return self.comm.check_flash_id(flash_id or self.config_model.FLASH_ID)

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

    config_model = HX890Config
    nmea_model = HX890NMEAProtocol


class HX891(HX890):
    """
    Device object for Standard Horizon HX890 maritime radios
    """
    handle = "HX891"
    brand = "Standard Horizon"
    model = "HX891BT"
    usb_vendor_id = 0x26aa
    usb_vendor_name = "YAESU MUSEN CO.,LTD."
    usb_product_id = 0x2e
    usb_product_name = "HX890"

    config_model = HX891Config
    nmea_model = HX890NMEAProtocol


class HX870Sim(HX870):
    """
    Device object for Standard Horizon HX870 maritime radio simulator
    """
    handle = "HX870SIM"
    model = "HX870S Simulator"
    usb_product_id = 1616
    usb_product_name = "HX870S"


class HX890Sim(HX890):
    """
    Device object for Standard Horizon HX890 maritime radio simulator
    """
    handle = "HX890SIM"
    model = "HX890S Simulator"
    usb_product_id = 3030
    usb_product_name = "HX890S"


class HX891Sim(HX891):
    """
    Device object for Standard Horizon HX891 maritime radio simulator
    """
    handle = "HX891SIM"
    model = "HX891BT Simulator"
    usb_product_id = 4242
    usb_product_name = "HX891S"


models = {}
for model_class in HX870, HX890, HX891:
    models[model_class.handle.upper()] = model_class
del model_class
