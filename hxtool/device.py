# -*- coding: utf-8 -*-

from logging import getLogger
import os
import re
from serial.tools import list_ports
from serial.tools.list_ports_common import ListPortInfo
import sys
from typing import Iterable, List, NamedTuple, Optional, Set, Type

from .config import HX870Config, HX890Config, HX891Config, GX1400Config
from .nmea import HX870NMEAProtocol, HX890NMEAProtocol
from .protocol import GenericHXProtocol, GX1400Protocol, MediaTekProtocol, ReadMagicProtocol
from .simulator import HXSimulator, SimulatorError

logger = getLogger(__name__)


# Probing all available ports for the config magic may cause errors and timeout delays,
# so exclude ports with known issues and offer users a way to specify the port list.
include_ports = os.environ.get("HXTOOL_SERIAL_PORTS", "").split()
exclude_ports = [
    # macOS
    "/dev/cu.BLTH",
    "/dev/cu.Bluetooth-Incoming-Port",
    "/dev/cu.URT1",
    "/dev/cu.URT2",
]


class Candidate(NamedTuple):
    """A port and the model class to talk to it with"""
    model: Type["HX870"]
    tty: str
    identified: bool  # known to be that model (USB metadata or forced), not merely probed


def enumerate(force_device=None, force_model=None, add_simulator=False):

    if force_model:
        try:
            model_list = [models[force_model.upper()]]
        except KeyError:
            logger.critical(f"Invalid model specifier `{force_model}`")
            return []
    else:
        model_list = models.values()

    devices = []

    if add_simulator:
        try:
            for model in model_list:
                devices += model.simulators()
        except SimulatorError as e:
            logger.error(e)

    devices += enumerate_devices(model_list, force_device)

    if force_device and force_device.isdecimal():
        try:
            devices = [devices[int(force_device)]]
        except IndexError:
            logger.error(f"Invalid numeric device selector {force_device}")
            return []

    return [c.model(c.tty, identified=c.identified) for c in devices]


def enumerate_devices(models: List[Type["HX870"]], force_device: Optional[str] = None) -> List[Candidate]:

    # The numeric device selector is only applicable as index into this function's
    # result. Therefore, we need to ignore it and generate the full list here.
    if force_device and force_device.isdecimal():
        force_device = None

    if not force_device:
        ports = list(list_ports.comports())
    else:
        ports = list(list_ports.grep(re.escape(force_device)))
        for port in ports:
            if force_device == port.device:
                ports = [port]  # Limit grep result to exact match if there is one

        # A selector that matches none of the ports the system lists is taken
        # literally. This allows for ptys, symlinks, and other virtual ports.
        if not ports:
            logger.debug(f"Device selector {force_device} matches no listed port, using it as port name")
            ports = [ListPortInfo(force_device)]

        # With both force_model and force_device used, skip auto-detection entirely
        if len(models) == 1 and len(ports) == 1:
            return [Candidate(models[0], ports[0].device, identified=True)]

    # Auto-detect based on USB metadata (very fast)

    devices = []
    for port in ports:
        for model in models:
            if model.usb_vendor_id is None and model.usb_product_id is None:
                continue
            if port.vid == model.usb_vendor_id and port.pid == model.usb_product_id:
                devices.append(Candidate(model, port.device, identified=True))
                logger.debug(f"Detected `{model.__name__}` at `{port.device}` by USB metadata")

                if port.description != model.usb_product_name \
                        and port.description != f"{model.usb_product_name} ({port.device})":
                    logger.warning(f"Unexpected serial device description `{port.description}` (BE CAREFUL)")

    # Auto-detect based on config magic (can be slow, skip unless necessary)

    if not force_device:
        if include_ports:
            ports = [p for p in ports if p.device in include_ports]
        else:
            ports = [p for p in ports if p.device not in exclude_ports]

    if devices or not ports:
        return devices

    logger.info("Probing serial ports to detect device")

    baudrates = set({38400})  # Default speed to minimise probing delays
    for model in models:
        baudrates.add(getattr(model.protocol_model, "baudrate", 38400))

    for port in ports:
        magic = read_magic(port.device, baudrates)
        for model in models:
            if model.config_model.CONFIG_MAGIC == magic:
                devices.append(Candidate(model, port.device, identified=False))
                logger.debug(f"Detected `{model.__name__}` at `{port.device}` by config magic")
                break  # Stop at first device to minimise probing delays

    if force_device and not devices:
        logger.error(f"Invalid device selector {force_device}")

    return devices


def read_magic(tty: str, baudrates: Set[int] = {38400}) -> int:
    for baud in baudrates:
        comm = ReadMagicProtocol(tty, baudrate=baud)
        if comm.hx_hardware:
            magic = int.from_bytes(comm.read_config_memory(0, 2), byteorder="big")
            logger.debug(f"Read magic {magic} from `{tty}`")
            return magic

    logger.debug(f"Failed to read magic from `{tty}`")
    return 0


class HX870(object):
    """
    Device object for Standard Horizon HX870 maritime radios
    """
    handle = "HX870"
    brand = "Standard Horizon"
    model = "HX870"
    usb_vendor_id = 0x26aa
    usb_vendor_name = "YAESU MUSEN CO.,LTD."
    usb_product_id = 0x0010
    usb_product_name = "HX870"

    protocol_model = GenericHXProtocol
    config_model = HX870Config
    nmea_model = HX870NMEAProtocol
    gps_model = MediaTekProtocol

    def __init__(self, tty, identified=False):
        self.tty = tty
        self.comm = self.protocol_model(tty=tty, identified=identified)
        self.config = None
        self.nmea = None
        self.gps = None
        self.init_config()

    def init_config(self):
        # See what we're talking to on that tty
        if self.comm.hx_hardware:
            if self.comm.cp_mode:
                self.config = self.config_model(self.comm)
                self.nmea = None
                self.gps = self.gps_model(self.comm)
                fw = self.config.firmware_version()
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

    @classmethod
    def simulators(cls) -> Iterable[Candidate]:
        sim_cls = getattr(sys.modules[__name__], cls.__name__ + "Sim")
        for mode in "CP", "NMEA":
            sim = HXSimulator(cls.config_model, mode)
            sim.start()
            yield Candidate(sim_cls, sim.tty, identified=True)

    def __str__(self):
        return f"{self.brand} {self.handle} on `{self.tty} [{'CP Mode' if self.comm.cp_mode else 'NMEA Mode'}]`"


class HX890(HX870):
    """
    Device object for Standard Horizon HX890 maritime radios
    """
    handle = "HX890"
    brand = "Standard Horizon"
    model = "HX890"
    usb_vendor_id = 0x26aa
    usb_vendor_name = "YAESU MUSEN CO.,LTD."
    usb_product_id = 0x001e
    usb_product_name = "HX890"

    config_model = HX890Config
    nmea_model = HX890NMEAProtocol


class HX891(HX890):
    """
    Device object for Standard Horizon HX891BT maritime radios
    """
    handle = "HX891"
    brand = "Standard Horizon"
    model = "HX891BT"
    usb_vendor_id = 0x26aa
    usb_vendor_name = "YAESU MUSEN CO.,LTD."
    usb_product_id = 0x002e
    usb_product_name = "HX890"

    config_model = HX891Config
    nmea_model = HX890NMEAProtocol


class GX1400(HX870):
    """
    Device object for Standard Horizon GX1400 maritime radios
    """
    handle = "GX1400"
    brand = "Standard Horizon"
    model = "GX1400"
    usb_vendor_id = None
    usb_vendor_name = None
    usb_product_id = None
    usb_product_name = None

    protocol_model = GX1400Protocol
    config_model = GX1400Config
    nmea_model = None
    gps_model = None

    def init_config(self):
        # A serial link has no USB identity, so verify we're talking to a GX1400
        # by its flash ID
        config = self.config_model(self.comm)
        self.comm.hx_hardware = self.comm.hx_hardware and config.check_flash_id()
        if self.comm.hx_hardware and self.comm.cp_mode:
            self.config = config
            # There are multiple GX1400 variants, named in config memory
            self.handle = config.variant() or self.handle
            fw = config.firmware_version()
            logger.info(f"Device on {self.tty} is {self.handle}, firmware version {fw}")
        else:
            logger.error(f"Device on {self.tty} does not behave or look like GX1400")

    @classmethod
    def simulators(cls) -> Iterable[Candidate]:
        sim = HXSimulator(GX1400.config_model, "CP")
        sim.start()
        yield Candidate(cls, sim.tty, identified=True)


class HX870Sim(HX870):
    """
    Device object for Standard Horizon HX870 maritime radio simulator
    """
    handle = "HX870SIM"
    model = "HX870S Simulator"
    usb_product_id = 0x0650
    usb_product_name = "HX870S"


class HX890Sim(HX890):
    """
    Device object for Standard Horizon HX890 maritime radio simulator
    """
    handle = "HX890SIM"
    model = "HX890S Simulator"
    usb_product_id = 0x0bd6
    usb_product_name = "HX890S"


class HX891Sim(HX891):
    """
    Device object for Standard Horizon HX891 maritime radio simulator
    """
    handle = "HX891SIM"
    model = "HX891BT Simulator"
    usb_product_id = 0x1092
    usb_product_name = "HX891S"


models = {}
for model_class in HX870, HX890, HX891, GX1400:
    models[model_class.handle.upper()] = model_class
del model_class
