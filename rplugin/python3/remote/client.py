# =============================================================================
# FILE: client.py
# AUTHOR: Chip Senkbeil <chip.senkbeil at gmail.com>
# License: Apache 2.0 License
# =============================================================================
import asyncio
from asyncio import DatagramProtocol
from . import logger
from .packet import Packet
from .security import new_hmac_from_key
from .messages import packet_to_message


class RemoteClient(logger.LoggingMixin):
    def __init__(self, nvim, addr, port, key=None):
        self.nvim = nvim
        self.is_debug_enabled = True

        self.info = {}
        self.info['addr'] = addr
        self.info['port'] = port
        self.info['key'] = key

        self.hmac = new_hmac_from_key(key)
        self.loop = None
        self.transport = None
        self.protocol = None

    def is_running(self):
        return self.transport is not None

    def send(self, data):
        if (not self.is_running()):
            raise Exception('Client is not running or connected!')

        if isinstance(data, str):
            data = data.encode()

        self.transport.sendto(data)
        self.nvim.out_write('Sent "{}"\n'.format(data))

    def run(self, cb):
        """Starts the remote client, adding it to the event loop and running
           forever if the loop has not been started elsewhere. If the loop is
           already running, this will only add the datagram endpoint to the
           loop.

        :param cb: The callback to invoke when the client is ready
        """
        self.loop = asyncio.get_event_loop()
        connect = self.loop.create_datagram_endpoint(
            lambda: RemoteClientProtocol(self.nvim, self.hmac),
            remote_addr=(self.info['addr'], self.info['port'])
        )

        def ready(future):
            transport, protocol = future.result()
            self.transport = transport
            self.protocol = protocol

            err = None
            if (transport is None or protocol is None):
                err = Exception('Failed to connect to {}:{}'
                                .format(self.info['addr'], self.info['port']))
            cb(err)

        self.loop.create_task(connect).add_done_callback(ready)

    def stop(self):
        """Stops the remote client, removing it from the event loop."""
        if (self.transport is not None):
            self.transport.close()
            self.transport = None
        self.protocol = None


class RemoteClientProtocol(DatagramProtocol, logger.LoggingMixin):
    def __init__(self, nvim, hmac):
        self.nvim = nvim
        self.hmac = hmac
        self.is_debug_enabled = True
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport
        self.nvim.async_call(lambda nvim, transport: nvim.out_write(
            'Established connection to %s\n' % transport),
            self.nvim, transport)

    def connection_lost(self, exc):
        self.transport = None

    def datagram_received(self, data, addr):
        # If no transport, drop the packet
        if (self.transport is not None):
            packet = None

            try:
                packet = Packet.read(data)
                is_valid = packet.is_signature_valid(self.hmac)
                msg = packet_to_message(packet)
                self.info('New data: %s\nValid: %s' % (msg, is_valid))
                #self.transport.sendto(packet.to_bytes(), addr)
                self.info('New data: %s' % msg)
                self.nvim.async_call(lambda nvim, msg, addr, valid: nvim.out_write(
                    'Received %r from %s\nValid: %s\n' % (msg, addr, valid)),
                                     self.nvim, msg, addr, is_valid)
            except Exception as ex:
                self.nvim.async_call(lambda nvim, ex: nvim.err_write(
                                     'Exception %s\n' % ex),
                                     self.nvim, ex)
