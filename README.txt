REPEL http:BL

Release 1.0 January 24 2009

Author: Terje Norderhaug <terje@in-progress.com>  
Home:   http://repel.in-progress.com/

INTRODUCTION

Repel is an HTTP:BL filter for Apache/Python that identifies friendly search engines and detects malicious or suspicious web bots. It can be used as a rewrite map for the Apache web server to prevent unwelcome bots from accessing websites, or to direct harvester and comment spammers to a honeypot.

REQUIREMENTS

Python 2.3.5 to 2.6.1 or later; Access to DNS.

GETTING STARTED

Get an http:BL access code from Project Honeypot: 

<http://www.projecthoneypot.org?rf=51041>

Start Repel from a shell, with the access code in place of "honeypotcode":

./repel.py --key=honeypotcode 

Enter an IP address. Repel will respond with a code and keywords providing information about the owner. It will return the word NONE if the address does not belong to a known or suspected web bot. Try some of the IP addresses of the malicious bots listed at Project Honeypot.

You can also run Repel in batch mode by providing a pathname to a file with IP addresses, like the files in the enclosed 'tests' directory.

APACHE CONFIGURATION

Here is an example of how to configure Apache with Repel to reject all identified suspicious and malicious bots:

RewriteEngine on
RewriteLock /path/to/Apache/rewritelock.lock
RewriteMap repel "prg:/path/to/scripts/Repel/repel.py --key=honeypotkey"

RewriteCond ${repel:%{REMOTE_ADDR}|OK} Suspicious|Malicious
RewriteRule ^.* - [F]

The regex formatting rules mapping the response code into keywords are in the Formats directory.

The "options.txt" file can be modified as an alternative to or in combination with command line options.

HONEYPOT FUNNEL

You are encouraged to install your own honeypot <http://projecthoneypot.org/manage_honey_pots.php?rf=5104> and direct harvesters and comment spammers to it:

RewriteCond ${repel:%{REMOTE_ADDR}|OK} Harvester|CommentSpammer
RewriteRule ^.* /cgi-bin/honeypot.py [L]
 