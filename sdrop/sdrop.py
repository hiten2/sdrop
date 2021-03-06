# Copyright (C) 2018 Bailey Defino
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
import fcntl
import os
import socket
import sys

from lib import baseserver
from lib import conf

__doc__ = "sdrop - a temporary file drop server"

class GETHandler(baseserver.HTTPRequestHandler):
    """identical to its parent, though it shreds and unlinks the resource"""
    
    def __init__(self, *args, **kwargs):
        baseserver.HTTPRequestHandler.__init__(self, *args,
            **kwargs)
        self.content_length = -1
        self.fp = None
        self.locked = False
        self.path = self.event.server.resolve(self.event.request.resource)
        
        if os.path.exists(self.path) and not os.path.isdir(self.path):
            try:
                self.fp = open(self.path, "r+b")
                self.fp.seek(0, os.SEEK_END)
                self.content_length = self.fp.tell()
                self.headers["content-length"] = self.content_length
                self.fp.seek(0, os.SEEK_SET)
            except (IOError, OSError):
                self.code = 500
                self.message = "Internal Server Error"
        else:
            self.code = 404
            self.message = "Not Found"
        
        if self.fp: # path is inherently nonexistent
            try:
                fcntl.flock(self.fp.fileno(), fcntl.LOCK_EX)
                self.locked = True
            except IOError:
                self.code = 500
                self.message = "Internal Server Error"

        try: # send response header
            baseserver.HTTPRequestHandler.respond(self)
        except socket.error: # the file will eventually be closed
            self.locked = False

    def next(self):
        if self.locked:
            if self.content_length: # fp is inherently open
                try:
                    chunk = self.fp.read(
                        baseserver.http_bufsize(self.content_length))
                    self.content_length -= len(chunk)
                    self.fp.seek(-len(chunk))
                    self.fp.write(os.urandom(len(chunk)))
                    self.fp.flush()
                    os.fdatasync(self.fp.fileno())
                except IOError:
                    pass
                
                try:
                    self.event.conn.sendall(chunk)
                except IOError:
                    pass
                return
            
            try:
                fcntl.flock(self.fp.fileno(), fcntl.LOCK_UN)
            except IOError:
                pass
            self.locked = False
        
        if self.fp: # may not have been locked
            try:
                self.fp.close()
            except (IOError, OSError):
                pass
            self.fp = None

            try:
                os.unlink(self.path)
            except OSError:
                pass
        raise StopIteration()

class POSTHandler(baseserver.HTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        baseserver.HTTPRequestHandler.__init__(self, *args, **kwargs)
        self.content_length = -1
        
        try:
            self.content_length = self.event.request.headers["content-length"]
        except KeyError:
            self.code = 411
            self.message = "Length Required"
        self.fp = None
        self.locked = False
        self.path = self.event.server.resolve(self.event.request.resource)
        
        if os.path.exists(self.path):
            self.code = 409
            self.message = "Conflict"
        elif self.content_length > -1: # we're actually receiving a file
            try:
                self.fp = open(self.path, "wb")
            except (IOError, OSError):
                self.code = 500
                self.message = "Internal Server Error"
        
        if self.fp: # path is inherently nonexistent
            try:
                fcntl.flock(self.fp.fileno(), fcntl.LOCK_EX)
                self.locked = True
            except IOError:
                self.code = 500
                self.message = "Internal Server Error"
    
    def next(self):
        if self.locked:
            if self.content_length: # fp is inherently open
                try:
                    chunk = self.event.conn.recv(
                        baseserver.http_bufsize(self.content_length))
                    self.content_length -= len(chunk)
                except socket.error:
                    return

                try:
                    self.fp.write(chunk)
                    self.fp.flush()
                    os.fdatasync(self.fp.fileno())
                    return
                except IOError:
                    self.code = 500
                    self.message = "Internal Server Error"
            
            try:
                fcntl.flock(self.fp.fileno(), fcntl.LOCK_UN)
            except IOError:
                pass
            self.locked = False
        
        if self.fp: # may not have been locked
            try:
                self.fp.close()
            except (IOError, OSError):
                pass
            self.fp = None
        baseserver.HTTPRequestHandler.next(self) # respond/stop

for k, v in (("GET", GETHandler), ("POST", POSTHandler)):
    baseserver.HTTPConnectionHandler.METHOD_TO_HANDLER[k] = v

class SDropServer(baseserver.BaseHTTPServer):
    def __init__(self, *args, **kwargs):
        baseserver.BaseHTTPServer.__init__(self, *args, **kwargs)

if __name__ == "__main__":
    class AddressConfig(baseserver.TCPConfig):
        ADDRESS = ("::1", 8000, 0 , 0)
    
    #mkconfig
    
    server = SDropServer(sock_config = AddressConfig)
    server.thread(baseserver.threaded.Pipelining(nthreads = 1))
    server()
