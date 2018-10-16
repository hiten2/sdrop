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
__package__ = "threaded"

import Queue
import thread

__doc__ = "threaded callable representation"

class FuncInfo:
    """information about a function call"""

    def __init__(self, func, output, args, kwargs):
        self.args = args
        self.func = func
        self.kwargs = kwargs
        self.output = output

class Threaded:
    """
    allocates up to N additional threads for function calls (w/ blocking)
    or run function calls in the current thread if nthreads == 0

    output is optionally stored into self.output_queue

    when nthreads == 0, tasks are executed in the calling thread
    when nthreads < 0, tasks are always executed in a new thread
    """
    
    def __init__(self, nthreads = 1, queue_output = False):
        self._allocation_lock = thread.allocate_lock()
        self.nactive_threads = 0
        self._nactive_threads_lock = thread.allocate_lock()
        self.nthreads = nthreads
        self.output_queue = None

        if queue_output:
            self.output_queue = Queue.Queue()

    def allocate_thread(self, func, *args, **kwargs):
        """block until thread allocation is possible"""
        if self.nthreads:
            if self.nthreads > 0:
                with self._allocation_lock: # block
                    while 1:
                        with self._nactive_threads_lock:
                            if self.nactive_threads < self.nthreads:
                                self.nactive_threads += 1
                                break
            # otherwise, self.nthreads < 0, so we don't block
            thread.start_new_thread(self._handle_thread,
                tuple([func] + list(args)), kwargs)
        else:
            with self._allocation_lock: # block
                self._handle_thread(func, *args, **kwargs)

    def _handle_thread(self, func, *args, **kwargs):
        """handle the current thread's execution"""
        try:
            output = func(*args, **kwargs)
        except Exception as output:
            pass

        if isinstance(self.output_queue, FuncQueue):
            self.output_queue.put(FuncInfo(func, output, *args, **kwargs))

        if self.nthreads:
            with self._nactive_threads_lock:
                self.nactive_threads -= 1
