#
# aionn - asyncio messaging library based on nanomsg and nnpy
#
# Copyright (C) 2016 by Artur Wroblewski <wrobell@riseup.net>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

import asyncio
from errno import EAGAIN, ENOPROTOOPT
import logging
import nnpy

from nnpy import NNError
from nnpy.socket import ffi, nanomsg

logger = logging.getLogger(__name__)


NN_MSG = ffi.cast('size_t', -1)

class Socket(nnpy.Socket):
    def __init__(self, domain, protocol, loop=None):
        super().__init__(domain, protocol)
        if loop == None:
            loop = asyncio.get_event_loop()
        self._loop = loop

        self._reader = None
        self._fd_reader = None
        self._read_flags = 0

        self._writer = None
        self._fd_writer = None
        self._write_flags = 0
        self._data = None

        self._fd_poll = ffi.new('struct nn_pollfd[]', [(self.sock, nnpy.POLLOUT, 0)])

    def bind(self, addr):
        super().bind(addr)
        self._enable_reader()

    def connect(self, addr):
        super().connect(addr)
        self._enable_reader()

    async def recv(self, flags=0):
        """
        Receive data from the socket.

        The method is a coroutine.

        The data is always received with `NN_DONTWAIT` flag enabled.
        Therefore the `flags` parameter is ignored in practice at the
        moment.

        :param flags: Receiving data flags.

        .. seealso:: `ffi.from_buffer <http://cffi.readthedocs.io/en/latest/ref.html#ffi-buffer-ffi-from-buffer>`_
        .. seealso:: `nn_send <http://nanomsg.org/v1.0.0/nn_recv.3.html>`_
        """
        self._read_flags = flags | nnpy.DONTWAIT
        self._reader = self._loop.create_future()
        return (await self._reader)


    def _notify_recv(self):
        reader = self._reader
        if self._reader and not self._reader.done():
            data = ffi.new('char**')
            rc = nanomsg.nn_recv(self.sock, data, NN_MSG, self._read_flags)
            if rc >= 0:
                self._reader.set_result(ffi.buffer(data[0], rc)[:])

                assert rc >= 0, 'nn_freemsg should be called when nn_recv is successful'
                nanomsg.nn_freemsg(data[0])
            elif nanomsg.nn_errno() == EAGAIN:
                if __debug__:
                    # if SUB socket, data was sent to different topic
                    logger.debug('socket temporarily unavailable for reading')
            else:
                assert rc < 0 and nanomsg.nn_errno() != EAGAIN
                self._reader.set_exception(_error(rc))
        else:
            if __debug__:
                logger.debug('recv not awaited, delay reader')
            # if Socket.recv not awaited then simply wait and in the future
            # use NN_RCVTIMEO to timeout socket data retrieval
            self._loop.remove_reader(self._fd_reader)
            self._loop.call_later(1, self._enable_reader)

    def _enable_reader(self):
        try:
            self._fd_reader = self.getsockopt(nnpy.SOL_SOCKET, nnpy.RCVFD)
            self._loop.add_reader(self._fd_reader, self._notify_recv)
        except nnpy.NNError as ex:
            if ex.error_no != ENOPROTOOPT:
                raise

def _error(rc):
    error_no = nanomsg.nn_errno()
    msg = nanomsg.nn_strerror(error_no)
    return NNError(error_no, ffi.string(msg).decode())

# vim: sw=4:et:ai
