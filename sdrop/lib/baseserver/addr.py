# Copyright 2018 Bailey Defino
# <https://bdefino.github.io>

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
import socket

__doc__ = "address manipulation"

def atos(addr):
    """
    convert an address to a string using URL domain representation

    for IPv4, this means: HOST:PORT
    for IPv6, this means: [HOST]:PORT
    """
    host, port = addr[:2]

    if ':' in host:
        host = "[%s]" % host
    return ':'.join((host, str(port)))

def stoa(string):
    """convert a string to an address"""
    host, port = string.rsplit(':', 1)
    port = int(port)
    
    if host.startswith('['):
        return host[1:-1], port, 0, 0
    return host, port

def best(port = 0):
    """return the best address for a given port"""
    for addrinfo in socket.getaddrinfo(None, port):
        return addrinfo [-1]
    raise socket.gaierror("socket.getaddrinfo failed")
