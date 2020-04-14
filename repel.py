#!/usr/bin/python
"""
HTTP:BL filter to identify search engines and detect malicious web bots
Home: <http://repel.in-progress.com/>
"""

__author__ = "Terje Norderhaug"
__copyright__ = "Copyright (C) 2008-2009 Terje Norderhaug <terje@in-progress.com>"
__version__  = "1.0"

# LICENSE

"""
This library is free software; you can redistribute it and/or
modify it under the terms of the GNU Library General Public License
version 2 as published by the Free Software Foundation.

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
please contact the copyright holder of this library. Please submit
modifications of the library to the same address. Any submitted
modifications will automatically fall under the terms of this license
unless otherwise specified.
"""

# IMPLEMENTATION NOTES

"""
Intended to be compatible with Python 2.x back to 2.3.5, so there are some
old school syntax. Python lacks a built-in portable way to do
asynchronous DNS lookups with timeouts, which this implementation
implements using threads. Future version may implement this issue
differently.
"""

################################################################
# IMPORTS

import sys
import os
import re
import time
import socket
from socket import gethostbyname, gaierror, herror
import fileinput
import weakref
import optparse
from optparse import OptionParser
import ConfigParser
from ConfigParser import SafeConfigParser
import logging
import logging.handlers
import syslog

from in_progress import async, dnsbl 

# ###################################################################
# CONFIGURATION

config = SafeConfigParser()
config.read(os.path.join (sys.path[0], "options.txt"))

options = optparse.Values()
options.modes = ["seq", "async"]
options.formats = os.path.join (sys.path[0], "formats", "")

options.key = config.get("HTTPBL", "key")
options.domain = config.get("HTTPBL", "domain")
options.mode = config.get("HTTPBL", "mode")
options.timeout = config.getfloat("HTTPBL", "timeout")
options.workers = config.getint("HTTPBL", "workers")
options.cache = config.getint("HTTPBL", "cache")
options.logfile = config.get("HTTPBL", "logfile")
options.format = config.get("HTTPBL", "format")

filenames = []
optimized = True

def use_options(default=options):
    "Use options from the command line"

    global options, filenames
    if sys.version_info[:3] >= (2,4,0):
        help_default = " [default = %default]"
    else:
        help_default = ""

    op = OptionParser(usage="%prog [options] [filepath]", 
                      version="%prog " + __version__)
    op.add_option("-k", "--key", dest="key", 
                  help="access KEY provided by the dnsbl host",
                  metavar="KEY", default=default.key)

    op.add_option("-d", "--domain", dest="domain", 
                  help="domain NAME of the dnsbl host" + help_default,
                  metavar="NAME", default=default.domain)

    op.add_option("-f", "--format", dest="format", 
                  help="file or directory PATHNAME for output format" +
                  help_default, metavar="PATHNAME", default=default.format)

    op.add_option("-m", "--mode", dest="mode", type="choice", 
                  choices=options.modes, help="The execution MODE" + 
                  help_default, metavar="MODE", default=default.mode)

    op.add_option("-t", "--timeout", dest="timeout", type="float", 
                  help="The TIMEOUT in seconds before a DNSBL query expires" 
                  + help_default, metavar="TIMEOUT", default=default.timeout)

    op.add_option("-l", "--log", dest="logfile", 
                  help="pathname for a log of the DNSBL queries and responses" 
                  + help_default, metavar="LOG", default=default.logfile)

    op.add_option("-w", "--workers", dest="workers", type="int",
                  help="The number of concurrent worker threads/processes" 
                  + help_default, metavar="WORKERS", default=default.workers)
    
    op.add_option("-c", "--cache", dest="cache", type="int",
                  help="The number of recent requests to keep in the cache" 
                  + help_default, metavar="CACHE", default=default.cache)

    (options, filenames) = op.parse_args(values=options)

#########################################################################
# FORMATTING

class Formatter:

    class SeparatorMissing (UserWarning): pass

    def __init__ (self, filename):

        self.replacements = []
        logging.debug("Loading format from %s" % filename)

        try:
            f = open(filename)
        except IOError:
            logging.warn("Cannot open format file - using default formatting instead")         
            self.replacements.append((re.compile("^(.*)$"), "\\1"))
            self.replacements.append((re.compile("^$"), "NONE"))
            return None            

        try:
            while 1:
                line1 = f.readline().rstrip()
                line2 = f.readline().rstrip()
                line3 = f.readline()
                self.replacements.append((re.compile(line1), line2))
                if not line3:
                    break
                elif not line3.isspace():
                    raise (self.SeparatorMissing, line3)
        finally: f.close()


    def decode (self, code):

        def extract(replacement): 
            (new, count) = re.subn(replacement[0], replacement[1], code, 1)
            if count > 0: return new
            else: return ""

        return ''.join ([extract (replacement)
                        for replacement in self.replacements])


#########################################################################
# CUSTOM DNSBL RESOLVER

class Resolver (dnsbl.Resolver):

    def resolve (self, value):
        "Performs a DNSBL lookup on an IP address (as a string with or without newline)"
        "Returns two string values: The address and the hex encoded DNSBL result"
        address = value.rstrip()
        if address[:3] == "127":
            # DNSBL hosts provide test values for addresses starting with 127,
            # which may interfer with local addresses. Per DNSBL spec.
            return (address, "")
        try:
            response = dnsbl.Resolver.resolve (self, address)
            if response:
                response = dnsbl.encode_for_regex (response)
            else:
                response = ""
        except dnsbl.Timeout:
            response = dnsbl.encode_timeout (self.timeout)
        except Exception, ex:
            logging.error ("Failed resolving %r [%s]" % (address, ex))
            response = "FF:FF:FF:FF"

        return (address, response)

#########################################################################
## LIB

def change_thread():
    "Passes control to the next thread ready to run, if any"
    time.sleep (0.001)
    

def fair (source):

    """Decorates source iteration to reduce starvation of DNS lookup 
    during heavy load. Theory: Called within the lock of async.imap,
    giving a chance to run for threads that may hold a DNS response
    from external call."""
  
    while True:
        change_thread()
        yield source.next()

log = None

def report (address, response, formatter=None):
    "Format and output the result"
    logging.debug("reporting score %s" % response)
    if formatter:
        response = formatter.decode(response)
    if filenames:
        print address,
    print response
    sys.stdout.flush()  # urgent
    if log:
        log.write ("%s\t%s\n" % (address, response) )


#########################################################################
# FILTERS

def seqfilter(source=sys.stdin, formatter=None, options=options):
    "Sequential DNSBL to standard output"

    resolver = Resolver (options.domain, options.key, timeout=options.timeout)

    for line in source:
        (address, result) = resolver.resolve (line)
        report (address, result, formatter)
        

def asyncfilter(source=sys.stdin, formatter=None, options=options):
    "Asynchronous DNSBL to standard output"

    resolver = Resolver (options.domain, options.key, timeout = options.timeout)

    def blreport (value):
        if isinstance (value, async.Promise):
            code = dnsbl.encode_timeout (value.runtime())
            report (value._args.rstrip(), code, formatter)
            change_thread()
        else:
            (address, result) = value
            report (address, result, formatter)

    if filenames:
        source = fair (source)
    else:
        # sys.stdin.next() hung in Python 2.3.5, perhaps due to buffering...
        # see http://www.nabble.com/Reading-from-stdin-td19866013.html
        source = iter (source.readline, "")


    filter = async.Mapper (resolver.resolve, 
                           source = source,
                           timeout = options.timeout,
                           workers = options.workers,
                           cache = options.cache )

    try:
        stats = None
        if not optimized:
            stats = filter (source)
            for x in stats:
                blreport (x)
        else:
            logging.info("Optimized asynchronous execution")
            stats = filter.iterate (blreport, source)
   
    finally:
        if stats:
            logging.info("Total Queries %d" % stats.total) 
            if stats.total:
                logging.info("Average Latency %f" % (stats.sumlatency / float(stats.total)))
                logging.info("Sum Latency %f" % stats.sumlatency)
                logging.info("Max Latency %f" % stats.maxlatency)
                logging.info("Min Latency %f" % stats.minlatency)
                logging.info("DNS Expired %d" % stats.loss)
                logging.info("DNS Reused %d" % stats.reused)

# ########################################################################

def main():

    if not options.key:
       logging.warning ("No DNSBL access key!")

    if filenames:
        logging.debug("Input from %s" % filenames)
        source = fileinput.input(filenames)
    else:
        source = sys.stdin

    if options.logfile:
        global log
        logfile = os.path.join (sys.path[0], options.logfile)
        log = open(logfile, 'a')

    if options.format:
        file = os.path.abspath (os.path.join 
                                 (options.formats, options.format))
    else:
        file = os.path.abspath (os.path.join 
                                (options.formats, 
                                 options.domain.replace (".", "_") 
                                 + ".txt")) 
    
    logging.info("Using DNSBL formatting in %s" % file)
    formatter = Formatter(file)

    if options.mode == "seq":
        logging.info("Sequential filter")
        seqfilter(source, formatter=formatter)
    elif options.mode == "async":
        logging.info("Asynchronous filter")
        asyncfilter(source, formatter=formatter)
    else: 
        raise (error, "Invalid mode %s" % options.mode)

# ########################################################################

if __name__ == "__main__":

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    before = time.time()

    # sys.setcheckinterval(0)

    logging.info("Starting Repel DNSBL")

    try:
        use_options()
        main()
    except Formatter.SeparatorMissing:
        logger.error("Expressions in DNSBL format file need to be separated by a blank line")
    except KeyboardInterrupt:
        logging.info("Quitting due to keyboard interrupt")
    # except Exception, ex:
    #    logging.critical("Shutting down abnormally due to exception: %s" % ex)

    logger.info("Runtime %f" % (time.time() - before))
