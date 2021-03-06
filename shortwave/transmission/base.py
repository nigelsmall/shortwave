#!/usr/bin/env python
# coding: utf-8

# Copyright 2011-2016, Nigel Small
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from errno import ENOTCONN, EBADF
from logging import getLogger
from socket import error as socket_error, SHUT_RD, SHUT_WR
from threading import Thread
from weakref import ref

from shortwave.concurrency import synchronized
from shortwave.uri import parse_authority

log = getLogger("shortwave.transmission")

default_buffer_size = 524288


class BaseTransmitter(object):
    """ A Transmitter handles the outgoing half of a network conversation.
    Transmission is synchronous and will block until all data has been
    sent.
    """

    def __init__(self, socket):
        self.socket = socket
        self.fd = self.socket.fileno()

    def transmit(self, *data):
        joined = b"".join(data)
        log.info("T[%d]: %s", self.fd, joined)
        self.socket.sendall(joined)


class BaseReceiver(Thread):
    """ A Receiver handles the incoming halves of one or more network
    conversations.
    """

    buffer_size = default_buffer_size

    _stopped = False

    def __init__(self):
        super(BaseReceiver, self).__init__()
        self.setDaemon(True)
        self.clients = {}

    def __del__(self):
        for transceiver_ref, _, _ in self.clients.values():
            transceiver = transceiver_ref()
            if transceiver:
                transceiver.stop_rx()

    def __repr__(self):
        return "<%s at 0x%x>" % (self.__class__.__name__, id(self))

    def attach(self, transceiver):
        fd = transceiver.socket.fileno()
        buffer = bytearray(self.buffer_size)
        view = memoryview(buffer)
        self.clients[fd] = (ref(transceiver), buffer, view)
        log.debug("Attached %r (buffer_size=%d) to %r", transceiver, self.buffer_size, self)

    def run(self):
        # TODO: select-based default receiver
        raise NotImplementedError("No receiver implementation is available for this platform")

    @synchronized
    def stop(self):
        if not self._stopped:
            log.debug("Stopping %r", self)
            self._stopped = True

    def stopped(self):
        return self._stopped


class BaseTransceiver(object):
    """ A Transceiver represents a two-way conversation by blending a
    Transmitter with a Receiver.
    """

    Tx = BaseTransmitter
    Rx = BaseReceiver

    transmitter = None
    receiver = None

    default_port = 0

    @classmethod
    def new_socket(cls, host, port, secure=False):
        from socket import socket, AF_INET, SOCK_STREAM, IPPROTO_TCP, TCP_NODELAY
        s = socket(AF_INET, SOCK_STREAM)
        s.setsockopt(IPPROTO_TCP, TCP_NODELAY, 1)
        s.connect((host, port))
        if secure:
            from ssl import SSLContext, HAS_SNI, PROTOCOL_SSLv23
            ssl_context = SSLContext(PROTOCOL_SSLv23)
            try:
                from ssl import OP_NO_SSLv2, OP_NO_SSLv3
            except ImportError:
                pass
            else:
                ssl_context.options |= OP_NO_SSLv2 | OP_NO_SSLv3
            ssl_kwargs = {}
            if HAS_SNI:
                ssl_kwargs["server_hostname"] = host
            s = ssl_context.wrap_socket(s, **ssl_kwargs)
        s.setblocking(False)
        return s

    def __init__(self, authority, default_port=0, secure=False, receiver=None):
        self.user_info, self.host, port = parse_authority(authority)
        self.port = port or default_port or self.default_port
        self.socket = self.new_socket(self.host, self.port, secure=secure)
        self.fd = self.socket.fileno()
        log.info("X[%d]: Connected to %s on port %d", self.fd, self.host, self.port)
        self.transmitter = self.Tx(self.socket)
        if receiver:
            self.receiver = receiver
        else:
            self.receiver = self.Rx()
            self.receiver.stopped = lambda: self.stopped()
            self.receiver.start()
        self.receiver.attach(self)

    def __del__(self):
        self.close()

    def __repr__(self):
        if hasattr(self.socket, "cipher"):
            return "<%s #%d cipher=%r compression=%r>" % (self.__class__.__name__, self.fd,
                                                          self.socket.cipher(),
                                                          self.socket.compression())
        else:
            return "<%s #%d>" % (self.__class__.__name__, self.fd)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def transmit(self, *data):
        self.transmitter.transmit(*data)

    def stopped(self):
        return not self.transmitter and not self.receiver

    @synchronized
    def stop_tx(self):
        if self.transmitter:
            log.info("T[%d]: STOP", self.fd)
            try:
                self.socket.shutdown(SHUT_WR)
            except socket_error as error:
                if error.errno not in (EBADF, ENOTCONN):
                    log.error("T[%d]: %s", self.fd, error)
            finally:
                self.transmitter = None
                if self.stopped() and not self.close.locked():
                    self.close()

    @synchronized
    def stop_rx(self):
        if self.receiver:
            try:
                self.on_stop()
            finally:
                log.info("R[%d]: STOP", self.fd)
                try:
                    self.socket.shutdown(SHUT_RD)
                except socket_error as error:
                    if error.errno not in (EBADF, ENOTCONN):
                        log.error("R[%d]: %s", self.fd, error)
                finally:
                    self.receiver = None
                    if self.stopped() and not self.close.locked():
                        self.close()

    @synchronized
    def close(self):
        if self.socket:
            if not self.stop_tx.locked():
                self.stop_tx()
            if not self.stop_rx.locked():
                self.stop_rx()
            try:
                self.socket.close()
            except socket_error:
                pass
            finally:
                self.socket = None
                log.info("X[%d]: Closed", self.fd)

    def on_receive(self, view):
        pass

    def on_stop(self):
        pass
