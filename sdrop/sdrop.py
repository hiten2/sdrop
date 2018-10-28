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
__package__ = "sdrop"

import fcntl
import os
import socket
import sys
import thread
import time
import traceback

from lib import baseserver

__doc__ = "sdrop - a temporary file drop server"#############steps

global AF
AF = socket.AF_INET # latest address family

for addrinfo in socket.getaddrinfo(None, 0):
    AF = addrinfo[0]
    break

global PRINT_LOCK # global synchronization mechanism
PRINT_LOCK = thread.allocate_lock()

def http_bufsize(max):
    """return the highest positive power of 2 <= max"""
    exp = 1
    max = min(4096, max) # keep it reasonable
    
    while 2 << exp <= max:
        exp += 1
    return 2 << (exp - 1)

class Headers(dict):
    """
    a dictionary of strings mapped to values

    useful for loading MIME headers from a file-like object
    """
    
    def __init__(self, **kwargs):
        dict.__init__(self)

        for k in kwargs.keys():
            self.__setitem__(k, kwargs[k])

    def add(self, key, value):
        """same as __setitem__, but preserves multiple, ordered values"""
        if not isinstance(key, str):
            raise KeyError("key must be a str")
        key = key.strip().lower()

        if isinstance(value, tuple):
            value = list(value)
        
        if self.has_key(key):
            current_value = self.__getitem__(key)

            if isinstance(current_value, tuple):
                current_value = list(current_value)
            elif not isinstance(current_value, list):
                current_value = [current_value]

            if not isinstance(value, list):
                value = [value]
            current_value += value
            dict.__setitem__(self, key, current_value)
        else:
            self.__setitem__(key, value)

    def fload(self, fp):
        """load from a file-like object"""
        line = []

        while not "".join(line) in ("\n", "\r\n"): # read the headers
            try:
                line.append(fp.read(1))
            except socket.timeout:
                continue

            if line and line[-1] == '\n':
                if ':' in line:
                    k, v = "".join(line).split(':', 1)
                    v = v.strip()

                    for _type in (int, float): # cast numerics
                        try:
                            v = _type(v)
                            break
                        except ValueError:
                            pass
                    self.add(k.strip(), v)
                    line = []
                elif "".join(line).rstrip("\r\n"):
                    line = list("".join(line).strip() + ' ') # multiline
    
    def get(self, key, default = None):
        if not isinstance(key, str):
            raise KeyError("key must be a str")
        key = key.strip()
        
        if self.has_key(key):
            return self.__getitem__(key)
        return default

    def __getitem__(self, key):
        if not isinstance(key, str):
            raise KeyError("key must be a str")
        return dict.__getitem__(self, key.strip().lower())

    def __setitem__(self, key, value):
        if not isinstance(key, str):
            raise KeyError("key must be a str")
        dict.__setitem__(self, key.strip().lower(), value)

    def __str__(self):
        """convert to string, WITH the empty line terminator"""
        pairs = []
        
        for k, v in sorted(self.items(), key = lambda e: e[0]):
            k = k.capitalize()
            
            if isinstance(v, list):
                for _v in v:
                    pairs.append((k, _v))
            else:
                pairs.append((k, v))
        return "\r\n".join([": ".join((k, str(v))) for k, v in pairs]
            + ["", ""])

class Request:
    def __init__(self, headers = None, method = None, resource = None,
            version = 0):
        if not headers:
            headers = Headers()
        self.headers = headers
        self.method = method
        self.resource = resource
        self.version = version

    def fload(self, fp):
        """load from a file-like object"""
        self.method = []
        self.resource = []
        self.version = []
        
        while not self.method or not self.method[-1] == ' ':
            try:
                self.method.append(fp.read(1))
            except socket.timeout:
                pass
        self.method = "".join(self.method).strip()

        while not self.resource or not self.resource[-1] == ' ':
            try:
                self.resource.append(fp.read(1))
            except socket.timeout:
                pass
        self.resource = "".join(self.resource).strip()
        
        while not self.version or not self.version[-1] == '\n':
            try:
                self.version.append(fp.read(1))
            except socket.timeout:
                pass
        self.version = "".join(self.version).strip()

        if '/' in self.version:
            self.version = self.version[self.version.rfind('/') + 1:]
        self.version = float(self.version)
        self.headers = Headers()
        self.headers.fload(fp)

class RequestEvent(baseserver.event.ConnectionEvent):
    def __init__(self, request, *args, **kwargs):
        baseserver.event.ConnectionEvent.__init__(self, *args, **kwargs)
        self.request = request

class RequestHandler(baseserver.eventhandler.EventHandler):
    def __init__(self, *args, **kwargs):
        baseserver.eventhandler.EventHandler.__init__(self, *args, **kwargs)
        self.code = 200
        self.headers = Headers()
        self.headers["connection"] = "close"
        self.headers["content-length"] = 0
        self.message = "OK"

    def next(self):
        self.respond()
        raise StopIteration()

    def respond(self):
        self.event.conn.sendall("HTTP/%.1f %u %s\r\n" % (
            float(self.event.request.version), int(self.code),
            str(self.message)) + str(self.headers)) # includes terminator

class GETHandler(RequestHandler):
    def next(self):
        content_length = -1
        fp = None
        locked = False
        path = self.event.server.resolver(self.event.request.resource)
        
        if os.path.exists(path) and not os.path.isdir(path):
            try:
                fp = open(path, "r+b")
                fp.seek(0, os.SEEK_END)
                content_length = fp.tell()
                self.headers["content-length"] = content_length
                fp.seek(0, os.SEEK_SET)
            except (IOError, OSError):
                self.code = 500
                self.message = "Internal Server Error"
        else:
            self.code = 404
            self.message = "Not Found"
        
        if fp: # path is inherently nonexistent
            try:
                fcntl.flock(fp.fileno(), fcntl.LOCK_EX)
                locked = True
            except IOError:
                self.code = 500
                self.message = "Internal Server Error"
        RequestHandler.respond(self) # send response header
        
        if locked: # fp is inherently open
            while content_length:
                try:
                    chunk = fp.read(http_bufsize(content_length))
                    fp.seek(-len(chunk), os.SEEK_CUR)
                    fp.write(os.urandom(len(chunk))) # shred
                    fp.flush()
                    os.fdatasync(fp)
                except IOError:
                    break
                
                try:
                    self.event.conn.sendall(chunk)
                except IOError:
                    break
                content_length -= len(chunk)
                time.sleep(self.server.sleep)
            
            try:
                os.unlink(path)
            except OSError:
                pass
            
            try:
                fcntl.flock(fp.fileno(), fcntl.LOCK_UN)
            except IOError:
                pass
        
        if fp: # may not have been locked
            try:
                fp.close()
            except (IOError, OSError):
                pass
        raise StopIteration()

class POSTHandler(RequestHandler):
    def next(self):
        content_length = -1
        
        try:
            content_length = self.event.request.headers["content-length"]
        except KeyError:
            self.code = 411
            self.message = "Length Required"
        fp = None
        locked = False
        path = self.event.server.resolver(self.event.request.resource)
        
        if os.path.exists(path):
            self.code = 409
            self.message = "Conflict"
        elif content_length > -1: # we're actually receiving a file
            try:
                fp = open(path, "wb")
            except (IOError, OSError):
                self.code = 500
                self.message = "Internal Server Error"
        
        if fp: # path is inherently nonexistent
            try:
                fcntl.flock(fp.fileno(), fcntl.LOCK_EX)
                locked = True
            except IOError:
                self.code = 500
                self.message = "Internal Server Error"
        
        if locked: # fp is inherently open
            while content_length:
                try:
                    chunk = self.event.conn.recv(http_bufsize(content_length))
                except socket.error:
                    break

                try:
                    fp.write(chunk)
                    fp.flush()
                    os.fdatasync(fp.fileno())
                except IOError:
                    self.code = 500
                    self.message = "Internal Server Error"
                    break
                content_length -= len(chunk)
                time.sleep(self.event.server.sleep)
            
            try:
                fcntl.flock(fp.fileno(), fcntl.LOCK_UN)
            except IOError:
                pass
        
        if fp: # may not have been locked
            try:
                fp.close()
            except (IOError, OSError):
                pass
        RequestHandler.next(self) # send response header and stop iteration

class HTTPConnectionHandler(baseserver.eventhandler.EventHandler):
    METHOD_TO_HANDLER = {"GET": GETHandler, "POST": POSTHandler}
    
    def next(self):
        """parse an HTTP header and execute the appropriate handler"""
        address_string = baseserver.straddress.straddress(self.event.remote)
        request = Request()
        
        try:
            self.event.conn.settimeout(self.event.server.timeout)
            request.fload(self.event.conn.makefile())

            self.event.server.sprint("Handling", request.method, "request for",
                request.resource, "from", address_string)
            HTTPConnectionHandler.METHOD_TO_HANDLER[request.method](
                RequestEvent(request, self.event.conn, self.event.remote,
                    self.event.server))()
        except Exception as e:
            try:
                self.event.server.sfprint(sys.stderr,
                    "ERROR while handling connection with %s:\n" % address_string,
                    traceback.format_exc())
            except Exception as e:
                print e
        finally:
            self.event.server.sprint("Closing connection with", address_string)
            self.event.conn.close()
        raise StopIteration()

class Server(baseserver.server.BaseTCPServer):
    """
    simple, pure-python HTTP server

    a POST is stored, and shredded then deleted after its initial GET

    the timeout argument is only used for the server socket;
    connection timeouts default to None
    """
    
    def __init__(self, event_class = baseserver.event.ConnectionEvent,
            event_handler_class = HTTPConnectionHandler, address = None,
            backlog = 100, buflen = 65536, conn_inactive = None,
            conn_sleep = 0.001, isolate = True, name = "sdrop", nthreads = -1,
            root = os.getcwd(), timeout = 0.001):
        baseserver.server.BaseTCPServer.__init__(self, event_class,
            event_handler_class, address, backlog, buflen, conn_inactive,
            conn_sleep, name, nthreads, timeout)
        resolver = lambda r: r
        
        if isolate:
            resolver = lambda r: os.path.normpath(r)
        self.resolver = lambda r: os.path.join(root, resolver(r))
        self.root = root
        self.timeout = timeout

class IterativeServer(Server, baseserver.server.threaded.Iterative):
    def __init__(self, *args, **kwargs):
        Server.__init__(self, *args, **kwargs)
        baseserver.server.threaded.Iterative.__init__(self, self.nthreads)

if __name__ == "__main__":
    Server()()#address = ("", 8000))()
