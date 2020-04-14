#!/usr/bin/python

"""DNSBL - retrieve DNSBL info for IP addresses"""

"""Distributed with Repel: <http://repel.in-progress.com/>. Executable
demo provides a basic DNSBL resolver filter that maps IP addresses
from input to regex friendly DNSBL codes."""

__author__ = "Terje Norderhaug"
__copyright__ = "Copyright (C) 2008 Terje Norderhaug <terje@in-progress.com>"
__version__  = "1.0a"

"""
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
####################################################################
# IMPLEMENTATION NOTES

"""Supposed to be compatible with Python back to 2.3.5, so there are
some old school syntax.

For a draft DNSBL spec, see:
http://tools.ietf.org/html/draft-irtf-asrg-dnsbl-08
"""

####################################################################

import time
import sys
import socket
from socket import gethostbyname, gethostbyname_ex
import re
import os
import logging

#########################################################################
# DNS LOOKUP

"""
Note: According to the implementation of gethostbyname() and the like
in <socketmodule.c>, on some platforms Python may use a lock to only
allow one thread to be in gethostbyname or getaddrinfo at the same
time. See USE_GETHOSTBYNAME_LOCK and setipaddr() in that module.
"""

class Timeout (Exception):
    "Raised when a DNSBL query could not be resolved within a given time"

def dnslookup (query, timeout=None):
    "Performs a simple DNS hostname lookup using a complete query;"
    "Returns None if hostname had no DNS record."
    "Uses timeout if available, potentially raising Timeout exception."
    logging.debug("DNS lookup of %s" % query)
    # if timeout: # did not make a difference
    #    socket.setdefaulttimeout(3.0)  
    try:
        # (_hostname, _aliaslist, _ipaddrlist) = gethostbyname_ex (query)
        # result = _ipaddrlist[0]
        return gethostbyname (query)
    except (socket.herror, socket.gaierror, ValueError), ex: 
        return None
    except socket.timeout:
        raise Timeout 

""" 
# Alternative implementation using 'dnspython' contribution:

import dns.resolver

def dnslookup (query, timeout=None):
    try:
      resolver = dns.resolver.get_default_resolver()
      resolver.lifetime = timeout
      response = dns.resolver.query(query)
      for rrset in response:
        return rrset.address
    except dns.exception.Timeout:
        raise Timeout
    except dns.resolver.NXDOMAIN:
        return None
    except dns.exception.DNSException, ex:
        logging.warning ("DNS problem [%s]" % ex)
        return None
    except Exception, ex:  # should not happen
        logging.error ("DNS failed [%s]" % ex)
        return "255.0.0.0"
"""

# -------------------------------------------------------------------
# DNSBL RESOLVE

def resolve (address, domain, key, timeout=None):
    """Queries a DNSBL host, returning the result formatted like an IP address,
       or None if address is not in registry. May raise a Timeout exception."""
    alist = address.split(".")
    alist.reverse()  # destructive, does not return list
    iprev = ".".join (alist)
    query = ".".join ((key, iprev, domain))
    return dnslookup(query, timeout)

# -------------------------------------------------------------------
# ENCODING

def encode_for_regex (response):
    """Encode the ip-address response from dnsbl in a format suited for
        regex matching"""
    (a,b,c,d) = response.split('.')
    return "%.2X:%.2X:%.2X:%.2X" % (int(a), int(b), int(c), int(d))

def encode_timeout (time):
    "decimals presented in hex as if they were in decimal format"
    minutes = min (time / 60 , 99)
    seconds = time % 60
    millisecs = 100 * (time - int(time))
    code = ("00:%.2d:%.2d:%.2d" % 
                   (int ("%d" % minutes, 16), 
                    int ("%d" % seconds, 16), 
                    int ("%d" % millisecs, 16)))
    return code

# -------------------------------------------------------------------
# RESOLVER

class Resolver:

    domain = None
    key = None
    timeout = None

    def __init__ (self, domain, key = None, timeout = None):
        self.domain = domain
        self.key = key
        self.timeout = timeout

    def resolve (self, address):
        return resolve (address, self.domain, self.key, self.timeout)

############################################################################

if __name__ == "__main__":

    import optparse
    from optparse import OptionParser

    logger = logging.getLogger()
    logger.setLevel (logging.INFO)
    logging.info("Starting DNSBL %s on Python %s"
                     % (__version__, sys.version_info) )

    if sys.version_info[:3] >= (2,4,0):
        help_default = " [default = %default]"
    else:
        help_default = ""

    op = OptionParser(usage="%prog [options] [filepath]", 
                      version="%prog " + __version__)
    op.add_option("-k", "--key", dest="key", 
                  help="access KEY provided by the dnsbl host",
                  metavar="KEY", default="")
    op.add_option("-d", "--domain", dest="domain", 
                  help="domain NAME of the dnsbl host" + help_default,
                  metavar="NAME", default="dnsbl.httpbl.org")
    op.add_option("-t", "--timeout", dest="timeout", type="float", 
                  help="The TIMEOUT in seconds before a query expires" 
                  + help_default, metavar="TIMEOUT", default=3.0)
    (options, filenames) = op.parse_args()

    if not options.key:
        logging.warning ("Requires a DNSBL access key, see e.g. <projecthoneypot.org>")
    
    resolver = Resolver (options.domain, options.key, options.timeout)

    for line in iter(sys.stdin.readline, ""):  # work around Python Issue1633941
        address = line.rstrip()
        try:
            result = resolver.resolve (address)
            if result:
                print encode_for_regex (result)
            else:
                print "NONE"
        except Timeout:
            print encode_timeout (resolver.timeout)
