# -*- coding: utf-8 -*-

from binascii import hexlify, unhexlify
from logging import getLogger

from .memory import unpack_waypoint
from .protocol import Message, GenericHXProtocol, ProtocolError

logger = getLogger(__name__)


def receive_until(p: GenericHXProtocol, stop: str) -> Message:
    while True:
        r = p.receive()
        if r.type == stop:
            return r


class GenericNMEAProtocol(object):

    def __init__(self, protocol: GenericHXProtocol):
        self.p = protocol


class HX870NMEAProtocol(GenericNMEAProtocol):
    pass


class HX890NMEAProtocol(GenericNMEAProtocol):
    pass
