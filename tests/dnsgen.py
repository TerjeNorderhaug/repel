#!/usr/bin/python

"""
Generate IP addresses to output (simulating Apache prg) 
Author: Terje Norderhaug <terje@in-progress.com>
No copyright nor warranty, use at your own risk.
"""

import time
import random
import sys

def randadr ():
     a = random.randint(0, 255)
     b = random.randint(0, 255)
     c = random.randint(0, 255)
     d = random.randint(0, 255)
     return ("%d.%d.%d.%d" % (a,b,c,d) )

while True:
   print randadr()
   sys.stdout.flush()
   time.sleep(0.1)  