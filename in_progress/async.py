#!/usr/bin/python
"""async - library for asynchronous execution, mapping and iteration.
Distributed with Repel: <http://repel.in-progress.com/>"""

__author__ = "Terje Norderhaug"
__copyright__ = "Copyright (C) 2008 Terje Norderhaug <terje@in-progress.com>"
__version__  = "0.5a" 

# COPYRIGHT AND LICENSE

"""
Copyright (C) 2008 Terje Norderhaug <terje@in-progress.com>

This library is free software; you can redistribute it and/or modify
it under the terms of the GNU Library General Public License version 2
as published by the Free Software Foundation.

This library is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
Library General Public License version 2 for details.
 
The GNU Library General Public License is available on the web from
<http://www.gnu.org/copyleft/lgpl.html> or by writing to the Free
Software Foundation, Inc., 59 temple Place - Suite 330, Boston, MA
02111-1307, USA.

Note that this is a different license than the more restrictive GNU
GPL license. If this license by any reason doesn't suit your needs,
please contact the copyright holder. Please submit modifications of
the library to the same address. Any submitted modifications will
automatically fall under the terms of this license unless otherwise
specified.
"""

# IMPLEMENTATION NOTES

"""
Supposed to be compatible with Python back to 2.3.5, so there are some
old school syntax. For example, 'with' statement first supported in
Python 2.5, so not used; try...finally is nested separate from
try...except; no decorators; etc. Run module for demo/self-check.
"""

####################################################################
# IMPORTS

import time
import sys
import UserDict
import thread
import threading
from threading import Thread, Event
import signal
import Queue
import weakref
import logging

#####################################################################
## CONSTANTS AND SETTINGS

switch_thread_sleep_time = 0.001

#####################################################################
# SHARED IMAP

"""Sharable iterator mapping the items in the source. Creates an
iterator that ensures that the map function is completed in order of
the input to make it sharable between multiple threads even if the
function has side effects. The function is executed in the thread
asking for the next item."""


"""
# Python raised exceptions if implemented as a generator function:
# ValueError: generator already executing.
# Seems like generators aren't allowed to be rentrant, even if this one is...

def imap (function, iterator):

    inlock = threading.Lock()
    def next ():
        inlock.acquire()
        try:
            value = iterator.next()                  
            result = function (value) 
            return result  
        finally:
            inlock.release()
    while 1:
        yield next()
"""

class imap:

    """Iterator that computes the function using arguments from the iterable.
       Like itertools.imap() but can be shared by multiple consumer threads."""

    def __init__ (self, function, iterator):
        self.inlock = threading.Lock()
        self.function = function
        self.iterator = iterator.__iter__()

    def __iter__(self):
        return (self)

    def next (self):
        self.inlock.acquire()
        try:
            value = self.iterator.next()
            if self.function:          
                value = self.function (value)
            return value  
        finally:
            self.inlock.release()

#########################################################################
# PROXYCACHE

class _Dict (UserDict.DictMixin, weakref.WeakValueDictionary):
    """intermediary as super() and get() did not always work with WeakValueDictionary,
    possibly old school class in some versions of Python"""
    pass

class ProxyCache (_Dict):

    """Keeps the values of recently requested items in cache even if
    not referenced elsewhere"""

    counter = 0

    def __init__ (self, size = 1000, *args, **kwds):
        _Dict.__init__(self, *args, **kwds)
        self.size = size
        self.retained = {}

    tmplock = threading.Lock()

    def retain (self, value):
        "Retain the value in the cache until new replaces the old"
        ## consider locking, although the potential skipped caching is ignorable
        # self.tmplock.acquire()
        # try:
        self.retained[self.counter] = value
        self.counter = (self.counter + 1) % self.size
        # finally:
        #    self.tmplock.release()

    def __getitem__ (self, key):
        value = _Dict.__getitem__(self, key)
        self.retain (value)
        return value

    def __setitem__ (self, key, value):
        _Dict.__setitem__(self, key, value)
        self.retain (value)
        return value

##################################################################
# FUNCTION RESULT PROMISE

class Promise: 
    "Placeholder/promise for the result of an asynchronous function"
    "Deliberately resembles multiprocessing.pool.AsyncResult"
    "http://docs.python.org/dev/library/multiprocessing.html#AsyncResult"
    ## would be nice if this could be a true proxy for the delivered value!
    ## that is, being an implicit promise rather than requiring 'get'.

    time = None
    result = None
    _target = None
    _args = None
    _ready = None
    _runlock = None

    def __init__ (self, target = None, args = None):
        self.time = time.time()
        self._target = target
        self._args = args
        self._ready = threading.Event()
        self._runlock = threading.Lock()
    
    def get (self, timeout = None):
        "Wait for and retrieve the promised value when it is ready"
        "Deliberately resemples multiprocessing.Pool.AsyncResult.get()"
        self.wait (timeout)
        if timeout == None or self.ready(): 
            return self.result
        
    def wait (self, timeout = None):
        "Waits until a result is available or until timeout seconds pass" 
        "Deliberately resemples multiprocessing.Pool.AsyncResult.wait()"
        logging.debug("Waiting for promise")
        return self._ready.wait(timeout)
 
    def ready (self):
        "Whether the call has completed and a result is ready"
        "Deliberately resemples multiprocessing.Pool.AsyncResult.ready()"
        return self._ready.isSet()

    def successful (self):
        "Whether the call completed without raising an exception"
        "Deliberately resemples multiprocessing.Pool.AsyncResult.successful()"
        return self.ready() and not self.exception

    exception = None

    def completion_handler (self):
        "Called when the promise has been fulfilled (whether successful or not)"
        self._ready.set()

    def run (self):
        "Fullfills/forces the promise by completing the call in the current thread"
        "After: a result is ready"
        if self._runlock.acquire (False):
            try:
                try:
                    if not self.time: 
                        self.time = time.time()
                    self.result = self._target (self._args)
                except Exception, exception:
                    self.exception = exception
            finally:
                self.completion_handler()
                # Don't release _runlock as it should only execute once! 
        else:
            self.join()
 

    def start (self):
        "Returns immediately after forcing the promise in a separate thread"
        thread.start_new_thread (self.run, ())

    def join (self, timeout = None):
        "blocks until the promise is fulfilled"
        self._ready.wait()

    def runtime (self):
        "How many seconds it is since the promise was made"
        return (time.time() - self.time)



if __name__ == "__main__":

    import socket

    def lookup(arg):
        logging.debug ("/LOOKUP %s in %s" % (arg, threading.currentThread())) 
        time.sleep (0.3)
        try:
           try:
               value = socket.gethostbyname(arg)
           except (socket.herror, socket.gaierror, ValueError):
               value = "FAILED " + arg
           logging.debug ("FOUND %s in %s" % (value, threading.currentThread()))
        finally:
           logging.debug ("\DONE LOOKUP %s in %s" % (arg, threading.currentThread()))
        return value

    print "---- Demonstrating promises:"

    promise = Promise (lookup, "python.org")
    promise.start()

    while not promise.ready():
        print "Promise %s not yet fulfilled after %f seconds..." % (promise, promise.runtime())
        time.sleep (0.1)

    if promise.successful():
        print "As promised: %s" % promise.get()
    else:
        print "Promise broken: %s" % promise.exception

##################################################################
# ASYNCHRONOUS FUNCTION

"""
Turns synchronous functions into asynchronous ones that don't hold up the main program.
 
Can be used as a function decorator:

@async.Call
def gethostasync (name):
   gethostname (name)

result = gethostasync("hello.com")
print (result.get())
"""

class Call:
    "Asynchronous function call"
    target = None
    cache = None  # Optional dictionary used to combine calls with identical arguments  

    def __init__ (self, target = None, cache = None):
       self.target = target
       if cache != None:
           self.cache = cache

    def __call__ (self, args):
        "Start an asynchronous call on the arguments and return the promise"
        promise = self.promise (args)
        promise.start()
        return promise

    tmplock = threading.Lock()

    def promise (self, args):
        "Returns a promise for the result of a suspended call"
        # Careful, designed for multiple threads concurrently accessing the cache
        # and to minimize creation of unused Promise instances!
        # Locking might be eliminated for speed, with ignorable consequences.
        # self.tmplock.acquire()
        try:
            if self.cache != None:
                promise = self.cache.get(args)
                if promise: 
                    return promise
                else:
                    return self.cache.setdefault(args, Promise (self.target, args))
            else:
                return Promise (self.target, args)
        finally:
            pass  # self.tmplock.release()

if __name__ == "__main__":

    print "---- Turning a function into an asynchronous call:"

    # like an @async.Call decorator
    lookup_async = Call (lookup, cache = ProxyCache() )

    promise1 = lookup_async ("python.org")
    promise2 = lookup_async ("python.com")
    promise3 = lookup_async ("python.org")

    if promise1 == promise3:
        print "Shared promises for calls with identical arguments!"
    else:
        print "Call caching apparently disabled!"

    promise1.wait(0.01)
    print "Promise1 ready? %s" % promise1.ready() 
    print "promise2 is complete: %s" % promise2.get()
    promise3.join()
    print "promise3 is complete: %s" % promise3.get()
    print "promise1 is the same: %s" % promise1.result

#####################################################################
# THREAD POOL

# See the Pool class of the MultiProcessing module.

class Pool:
 
    def __init__ (self, count, initializer = None, initargs = {}):

        self.workers = []
        self._done = Event()

        def run ():
           self.workers.append (threading.currentThread())
           try:
               try:
                   initializer (*initargs)
               except (KeyboardInterrupt, SystemExit):
                   self._done.set()
                   exit()
           finally:
               self.workers.remove (threading.currentThread())
	       if not self.workers:
                  self._done.set()

        def start_threads ():
            for i in range (0, count):
               thread = Thread (target = run)
               # Consumer can choose whether to wait for threads to complete:
               thread.daemon = True   
               thread.start()
               time.sleep (0.5) 

        # Some versions of Python seems to block during _init_;
        # starting workers in background thread activates them immediately:
        thread.start_new_thread (start_threads, () )
        
    
    def call (fun, *args):
        "Spawn an asynchronous call, returning a promise"
        # lesser implementation, should use thread in the pool.
        promise = Promise (fun, args)
        promise.start()
        return promise

    def join (self):
        "Blocks until all workers are done"
        self._done.wait()

#####################################################################
# COMPLETION QUEUE

class ImapDefer:
    """Iterator that when started, asynchronically computes a function using arguments 
       from an iterable, yielding promises in the sequential order of the input."""

    call = None
    due = None
    pool = None


    def __init__ (self, function, iterator, cache = None):
       self.call = Call (function, cache)
       self.due = Queue.Queue(0)
       self.input = imap (self.receive, iterator)
       self._done = Event()


    def __iter__ (self):
       return self


    def next (self):         
         promise = self.due.get()
         logging.debug ("PROMISE %s" % promise)
         if promise == None:
             self.due.put(None)  # keep single end mark mark in place
             self._done.set()
             raise StopIteration
         return promise


    def receive (self, item):
        "Called in order of items in the input to generate and store a promise in order"
        # synchronized, so don't do anything that is meant to be concurrently executed
        promise = self.call.promise (item)
        if self.due: 
            self.due.put (promise)
        return promise


    def completion_handler (self, promise):
        "Called when a promise has a value ready."
        "Executed asynchronously in the same thread as forced/computed the promise."
        "May not execute in the order of input."
    
    def run (self):
        try:
          for promise in self.input:
            promise.run()
            self.completion_handler (promise)
        finally:
          self.due.put (None)  # end mark, one completed means no more input, don't wait for all!


    def start (self): 
        thread = Thread (target = self.run)
        # Consumer can choose whether to wait for threads to complete:
        thread.setDaemon (True)   
        thread.start()


    def empty (self):
        "True if there are no promises in the iterator,"
        "which does not imply there won't be any in the future" 
        return self.due.empty()


    def wait (self, time = None):
        "Waiting for ImapDefer to be closed/done, at most an optional time is seconds"
        logging.debug("Waiting for ImapDefer done %f" % time)
        self._done.wait(time)


    def done (self):
        "True when there are no more input."
        "Promises may still be in queue but there will be no new ones made."
        return self._done.isSet()
                               

if __name__ == "__main__":

    print "---- Asynchronous mapping executing function in multiple threads:"

    deferred = ImapDefer(lookup, iter(["python.org", "python.net", "python.com"]))

    Pool (2, deferred.run)

    print "Results:"
    for promise in deferred:
        print promise.get() 

#####################################################################
# MAPPER

"""
Turns target function into an async iterator of the function over an iterable:

@Mapper
def lookup (key):
    return gethostname (key)

for value in lookup (["python.org", "python.net", "python.com"])

"""

class Mapper:

    """Concurrent transformation of lines from input, providing result in the sequential 
       order of the input. Provides optional timeout of transformations, and caching to avoid 
       redundant transforms. Use as iterator or with callbacks to handle the results."""

    timeout = 5.0
    maxworkers = 30
    source = sys.stdin  # any iterable
    cache = None

    def target (self, value):
        """Generates the result to report. The returned values should match 
           the arguments to the report method.""" 
        return value

    def report (self, *result):
        """Callback to process the result of the transformation -
        usually specialized/customized"""
        print result

    def expire (self, promise, time):
        "callback to notify about an expired promise. Returned value will be reported."
        return promise

    def __init__ (self, target = None, source = sys.stdin, workers = 8, 
                        expire = None, timeout = None, cache = None):
        if target != None:
            self.target = target
        if timeout:
            self.timeout = timeout
        self.workers = workers
        if expire:
            self.expire = expire
        if cache:
            self.cache = ProxyCache (cache)
        self.source = source

    def __iter__ (self):
        state = self._IterState (self)
        state.start()
        return state

    def __call__ (self, source):
        "Returns iterator across values transformed from the iterable source"
        state = self._IterState (self, source)
        state.start()
        return state

    def iterate (self, action, source = None):
       "Apply the action sequentially to each item of the transformed source for side effects;"
       "should be quicker that conventional iteration as the function is called in the same thread as transformed the input, reducing context switching"
       "Alternative to:  for x in self(source): action (x)"
       state = self._AdvancedState (self, source)
       state.process_promises (action, expire = self.expire)
       return state  # to optionally give access to the stats after completion  


    class _State:

        current = None
        total = 0
        sumlatency = 0.0  # less is better
        maxlatency = 0.0
        minlatency = 100.0
        loss = 0
        reused = 0

        def __init__ (self, parent, source = None):
           self.parent = parent
           self.outlock = threading.Lock()
           if source == None:
                source = iter (parent.source)  # default source is restarted
           self.source = source
           self.promises = ImapDefer (parent.target, source, cache = parent.cache) 
           self.timeout = parent.timeout
           self.expire = self.parent.expire
           self.stats_done = weakref.WeakKeyDictionary()

        def start (self):
            Pool (self.parent.workers, self.promises.run)

        tmplock = threading.Lock()

        def update_stats (self, promise):
            "Update statistics when the promise is ready for delivery"
            # self.tmplock.acquire() - speedup with ignorable consequences
            assert promise
            if promise not in self.stats_done:
                self.stats_done[promise] = True
                latency = promise.runtime()
                self.total += 1
                self.sumlatency += latency
                self.maxlatency = max (self.maxlatency, latency) 
                self.minlatency = min (self.minlatency, latency)
            else:
                self.reused += 1
            # self.tmplock.release()

        def _expire (self, promise):
            self.loss += 1
            if self.parent.cache:
                self.parent.cache.pop (promise._args, True)
            return self.expire (promise, promise.runtime())

    class _IterState (_State):

        "Completed promises are made available sequentially in iterator."

        def __iter__ (self):
            return self

        def next (self):
            promise = self.promises.next()
            latency = promise.runtime()
            expiration = self.timeout - latency
            if expiration > 0:
                promise.wait (expiration)
            self.update_stats (promise)
            if promise.ready():
                return promise.result
            else:  
                return self._expire (promise)

    class _AdvancedState (_State):

        """Completed promises are delivered sequentially in callbacks. Attempts to minimize
           context switching to reduce latency and get other performance benefits."""

        def process_promises (self, action = None, expire = None):
           "Process all completed promises, optionally expiring those timing out"
           if action != None:
               self.provide = action
           if expire == None:
               expire = self.parent.expire
           self.expire = expire
           self.promises.completion_handler = self.advance_handler
           self.start()
           self.maintain()

        def advance_handler (self, promise = None):
            try:
                self.advance (promise)
            except StopIteration:
                pass

        def provide (self, result):
           "Callback when a promise is ready"
           self.parent.report (result)

        def advance (self, promise = None, block = 0): 
          "Reports the result of the calls in order of input, advancing and deferring as needed"
          "Flushes all ready and expired responses. Returns the time remaining before next expires."
          "On return, self.current is None if all promises have been completed,"
          "or the next incompleted call that hasn't already expired"
          logging.debug ("ADVANCE %s" % threading.currentThread())
          if self.outlock.acquire(block):
           try:
            if not self.current and not self.promises.empty():
                self.current = self.promises.next()
            while self.current:
                latency = self.current.runtime()
                if self.current.ready():
                    self.provide (self.current.result)
                elif latency > self.timeout:
                    # Don't expire current if newer than the promise in this thread:
                    if promise and self.current.time > promise.time:
                        return (switch_thread_sleep_time)  
                    self.provide (self._expire (self.current) )
                else:
                    return (self.timeout - latency)
                self.update_stats (self.current)
                self.current = None  # as self.promises.next may fail with a stopiteration
                if not self.promises.empty(): 
                    self.current =  self.promises.next()
           finally:
               self.outlock.release()
        # at this point it is possible that another thread completed the next
        # and bypassed advance, so perhaps we should cover that unlikely case?

        def maintain (self):
            "Makes sure promises are timed out even if workers are all busy"            
            while 1:
                logging.debug ("MAINTAIN")
                try:  ## should be handled in advance() !!
                    delay = self.advance()
                except StopIteration:
                    self.current = None
                    return 
                if not delay: 
                    delay = self.timeout
                    if not delay:
                        delay = switch_thread_sleep_time
                self.promises.wait (delay)  # sleep makes it linger when finished


if __name__ == "__main__":

    print "---- Mapper in multiple threads:"

    print "1. Mapper as iterator over default input:" 

    resolved = Mapper (lookup, ["python.org", "python.net", "python.com"], timeout = 10.0)

    for result in resolved:
        print result

    print "2. Mapper instance as factory for iterators on alternative sources:" 

    newfilter = resolved ( iter (["python.info", "python.com", "python.org"]) )

    for result in newfilter:
        print result

    print "3. Using the optimized Mapper.iterate:"

    def print1 (item): # print is not a function in 2.3.5 :-(
        print item

    # resolved.iterate (print1)

    resolved.iterate (print1, iter(["python.com", "python.org", "python.info"]) )
