from logging import getLogger

from .protocol import GenericHXProtocol

logger = getLogger(__name__)


class GenericNMEAProtocol:
    """
    A radio in NMEA mode. Nothing is implemented yet beyond holding the
    connection; the classes exist so that every model names its NMEA
    protocol, like its config and GPS protocol.
    """

    def __init__(self, protocol: GenericHXProtocol):
        self.p = protocol


class HX870NMEAProtocol(GenericNMEAProtocol):
    pass


class HX890NMEAProtocol(GenericNMEAProtocol):
    pass
