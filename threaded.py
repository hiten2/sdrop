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
import time

__doc__ = "threaded callable representation"

class FuncInfo:
    """information about a function call"""

    def __init__(self, func, output, *args, **kwargs):
        self.args = args
        self.func = func
        self.kwargs = kwargs
        self.output = output

class Threaded(Queue.Queue):
    """
    allocates up to N additional threads for function calls (w/ blocking)
    or run function calls in the current thread if nthreads == 0

    when nthreads == 0, tasks are executed in the calling thread
    when nthreads < 0, tasks are always executed in a new thread

    when queue_output evaluates to True, function call information is
    queued into .output_queue as FuncInfo instances
    """

    def __init__(self, nthreads = -1, queue_output = False):
        self._allocation_lock = thread.allocate_lock()
        self.nactive_threads = 0
        self._nactive_threads_lock = thread.allocate_lock()
        self.nthreads = nthreads
        self.output_queue = None

        if queue_output:
            self.output_queue = Queue.Queue()

    def __init__(self, nthreads = 1, queue_output = False):
        self._allocation_lock = thread.allocate_lock()
        self.nactive_threads = 0
        self._nactive_threads_lock = thread.allocate_lock()
        self.nthreads = nthreads
        self.output_queue = None

        if queue_output:
            self.output_queue = Queue.Queue()

    def execute(self, func, *args, **kwargs):
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
                with self._nactive_threads_lock:
                    self.nactive_threads += 1
                self._handle_thread(func, *args, **kwargs)
    
    def _handle_thread(self, func, *args, **kwargs):
        """handle the current thread's execution"""
        try:
            output = func(*args, **kwargs)
        except Exception as output:
            pass

        if isinstance(self.output_queue, Queue.Queue):
            self.output_queue.put(FuncInfo(func, output, *args, **kwargs))

        if self.nthreads:
            with self._nactive_threads_lock:
                self.nactive_threads -= 1

class Iterative(Threaded):
    def __init__(self, nthreads = -1, queue_output = False, sleep = 0.001):
        Threaded.__init__(self, nthreads, queue_output)
        self.alive = True
        self._alive_lock = thread.allocate_lock()
        self._input_queue = Queue.Queue()
        self.sleep = sleep

        # don't change behavior to match changes in self.nthreads
        
        if self.nthreads > 0:
            for n in range(self.nthreads):
                thread.start_new_thread(self._slave, ())
        else: # use base behavior
            self.execute = lambda *a, **k: Threaded.execute(self, *a, **k)

    def execute(self, func, *args, **kwargs):
        """add the task to the queue"""
        self._input_queue.put(FuncInfo(func, None, *args, **kwargs))

    def kill_all(self):
        """passively attempt to kill all the threads"""
        with self._alive_lock:
            self.alive = False

    def _slave(self):
        """continuously execute tasks"""
        while 1:
            with self._alive_lock:
                if not self.alive:
                    break
                funcinfo = None
                
                while not funcinfo:
                    try:
                        funcinfo = self._input_queue.get()
                    except ValueError:
                        time.sleep(self.sleep)

                try:
                    funcinfo.output = funcinfo.func(*funcinfo.args,
                        **funcinfo.kwargs)
                except Exception as funcinfo.output:
                    pass

                if isinstance(self.output_queue, Queue.Queue):
                    self.output_queue.put(funcinfo)
