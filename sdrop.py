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
import thread

__doc__ = "sdrop - a temporary file drop server"

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

        while not ''.join(line) in ("\n", "\r\n"): # read the headers
            line.append(fp.read(1))

            if line and line[-1] == '\n':
                if ':' in line:
                    k, v = ''.join(line).split(':', 1)
                    v = v.strip()

                    for _type in (int, float): # cast numerics
                        try:
                            v = _type(v)
                            break
                        except ValueError:
                            pass
                    self.add(k.strip(), v)
                    line = []
                elif ''.join(line).rstrip("\r\n"):
                    line = list(''.join(line).strip() + ' ') # multiline
    
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
            + ['', ''])

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
            self.method.append(fp.read(1))
        self.method = ''.join(self.method).strip()

        while not self.resource or not self.resource[-1] == ' ':
            self.resource.append(fp.read(1))
        self.resource = ''.join(self.resource).strip()
        
        while not self.version or not self.version[-1] == '\n':
            self.version.append(fp.read(1))
        self.version = ''.join(self.version).strip()

        if '/' in self.version:
            self.version = self.version[self.version.rfind('/') + 1:]
        self.version = float(self.version)
        self.headers = Headers()
        self.headers.fload(self.fp)

class RequestHandler:
    def __init__(self, conn, remote, request, resolver = None):
        self.code = 200
        self.conn = conn
        self.headers = Headers()
        self.headers["content-length"] = 0
        self.message = "OK"
        self.remote = remote
        self.request = request

        if not resolver:
            resolver = self.default_resolver
        self.resolver = resolver
        self.version = request.version

    def __call__(self):
        """subclasses must call or override this function"""
        self.respond()
    
    def default_resolver(self, resource):
        """UNSAFE resource resolver"""
        return os.path.realpath(resource)

    def respond(self):
        self.request.fp.write("HTTP/%.1f %u %s\r\n" % (
            float(self.version), int(self.code), str(self.message)))
        self.request.fp.write(str(self.headers)) # includes the terminator
        self.request.fp.flush()

class GETHandler(RequestHandler):
    def __init__(self, *args, **kwargs):
        RequestHandler.__init__(self, *args, **kwargs)

    def __call__(self):
        content_length = -1
        fp = None
        locked = False
        path = self.resolver(self.request.resource)
        
        if os.path.exists(path):
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
        RequestHandler.__call__(self) # send response header
        
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
                    self.conn.sendall(chunk)
                except IOError:
                    break
                content_length -= len(chunk)
            self.headers["content-length"] -= content_length
            
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

class POSTHandler(RequestHandler):
    def __init__(self, *args, **kwargs):
        RequestHandler.__init__(self, *args, **kwargs)

    def __call__(self):
        content_length = -1

        try:
            content_length = self.request.headers["content-length"]
        except KeyError:
            self.code = 411
            self.message = "Length Required"
        fp = None
        locked = False
        path = self.resolver(self.request.resource)
        
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
                    chunk = self.request.fp.read(http_bufsize(content_length))
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
            
            try:
                fcntl.flock(fp.fileno(), fcntl.LOCK_UN)
            except IOError:
                pass
        
        if fp: # may not have been locked
            try:
                fp.close()
            except (IOError, OSError):
                pass
        RequestHandler.__call__(self) # send response header

class HTTPConnectionHandler:
    METHOD_TO_HANDLER = {"GET": GETHandler, "POST": POSTHandler}

    def __init__(self, conn, remote, resolver = None, timeout = None):
        self.conn = conn
        self.remote = remote
        self.resolver = resolver
        self.timeout = timeout

    def __call__(self):
        """parse an HTTP header and execute the appropriate handler"""
        request = Request()
        
        try:
            self.conn.settimeout(self.timeout)
            request.fload(self.conn.makefile())

            with PRINT_LOCK:
                print "Handling %s request for %s from %s:%u" % (
                    request.method, request.resource, self.remote[0],
                    self.remote[1])
            HTTPConnectionHandler.METHOD_TO_HANDLER[request.method](self.conn,
                self.remote, request, self.resolver)()
        except Exception as e:
            with PRINT_LOCK:
                print >> sys.stderr, "HTTPConnectionHandler.__call__:", e
        self.conn.close()

class SDropServer:
    """
    simple, pure-python HTTP server

    a POST is stored, and shredded then deleted after its initial GET

    the timeout argument is only used for the server socket;
    connection timeouts default to None
    """
    
    def __init__(self, address = ('', 8000), backlog = 1, timeout = 0.1,
            isolate = True, root = os.getcwd()):
        self.address = address
        self.backlog = backlog
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(self.address)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        self._sock.settimeout(timeout)
        resolver = lambda r: os.path.join(root, r)

        if isolate:
            resolver = lambda r: os.path.join(root,
                os.path.normpath(r.lstrip('/')))
        self.resolver = resolver
        self.timeout = timeout

    def serve_forever(self):
        self._sock.listen(self.backlog)

        with PRINT_LOCK:
            print "Serving sdrop HTTP requests on %s:%u" % self.address

        try:
            while 1:
                try:
                    conn, remote = self._sock.accept()
                except socket.timeout:
                    continue
                except socket.error as e:
                    with PRINT_LOCK:
                        print >> sys.stderr, "SDropServer.serve_forever:", e
                    continue
                thread.start_new_thread(HTTPConnectionHandler(conn, remote,
                    self.resolver, self.timeout).__call__, ())
        except KeyboardInterrupt:
            pass

        with PRINT_LOCK:
            print "Shutting down sdrop server..."
        self._sock.shutdown(socket.SHUT_RDWR)
        self._sock.close()

if __name__ == "__main__":
    address = ('', 8000)
    backlog = 1
    isolate = True
    root = os.getcwd()
    timeout = 0.1
    SDropServer(address, backlog, timeout, isolate, root).serve_forever()
