#!/usr/bin/env python
"""
Convert a directory with IRC logs to HTML.

Usage: logs2html.py pathname

Needs irclog2html.py.  Produces an index page and a number of HTML-formatted
log files with navigational links.

Looks for *.log in a given directory.  Needs an ISO 8601 date (YYYY-MM-DD or
YYYYMMDD) in the filename.
"""

from __future__ import print_function, unicode_literals

from operator import attrgetter


# Copyright (c) 2005--2013  Marius Gedminas
# latest.log.html symlink suggested by Chris Foster
#
# Released under the terms of the GNU GPL
# http://www.gnu.org/copyleft/gpl.html

import os
import re
import sys
import glob
import datetime
import optparse
import shutil

try:
    from urllib import quote
except ImportError:
    from urllib.parse import quote

from . import irclog2html


VERSION = irclog2html.VERSION
RELEASE = irclog2html.RELEASE

escape = irclog2html.escape

# If someone packages this for a Linux distro, they'll want to patch this to
# something like /usr/share/irclog2html/irclog.css, I imagine
CSS_FILE = os.path.join(os.path.dirname(__file__), 'irclog.css')


DATE_REGEXP = re.compile('^.*(\d\d\d\d)-?(\d\d)-?(\d\d)')


class Error(Exception):
    """Application error."""


class LogFile:
    """IRC log file."""

    def __init__(self, filename):
        self.filename = filename
        basename = os.path.basename(filename)
        m = DATE_REGEXP.match(basename)
        if not m:
            raise Error("File name does not contain a YYYY-MM-DD date: %s"
                        % filename)
        self.date = datetime.date(*map(int, m.groups()))
        self.link = irclog2html.pick_output_filename(basename)
        self.title = self.date.strftime('%Y-%m-%d (%A)')

    def __eq__(self, other):
        return isinstance(other, LogFile) and other.filename == self.filename

    def __ne__(self, other):
        return not self.__eq__(other)

    def newfile(self):
        """Check whether the log file is new.

        The log file is new iff the corresponding html file does not exist
        or was just generated by self.generate.  This implies that navigation
        links for the previous/next file need to be updated.
        """
        if not hasattr(self, '_newfile'):
            # Only do this once, so that self.generate() does not change
            # newness
            self._newfile = not os.path.exists(self.filename + ".html")
        return self._newfile

    def uptodate(self):
        """Check whether the HTML version of the log is up to date."""
        log_mtime = os.stat(self.filename).st_mtime
        try:
            html_mtime = os.stat(self.filename + ".html").st_mtime
        except OSError:
            return False
        return html_mtime > log_mtime

    def generate(self, style, title_prefix='', prev=None, next=None,
                 extra_args=()):
        """Generate HTML for this log file."""
        self.newfile() # update newness flag and remember it
        argv = ['irclog2html.py', '-s', style]
        argv.extend(extra_args)
        argv += ['-t', title_prefix + self.date.strftime('%A, %Y-%m-%d')]
        if prev:
            argv += ['--prev-url', prev.link,
                     '--prev-title',
                     '&#171; ' + prev.date.strftime('%A, %Y-%m-%d')]
        argv += ['--index-url=index.html', '--index-title=Index']
        if next:
            argv += ['--next-url', next.link,
                     '--next-title',
                     next.date.strftime('%A, %Y-%m-%d') + ' &#187;']
        argv += [self.filename]
        irclog2html.main(argv)


def find_log_files(directory, pattern='*.log'):
    """Find all IRC log files in a given directory.

    Returns a sorted list of LogFile objects (oldest first).
    """
    pattern = os.path.join(directory, pattern)
    # ISO 8601 dates sort the way we need them
    return sorted([LogFile(filename)
                   for filename in glob.glob(pattern)
                                   + glob.glob(pattern + '.gz')],
                  key=attrgetter('filename'))


def write_index(outfile, title, logfiles, searchbox=False, latest_log_link=None):
    """Write an index with links to all log files."""
    print("""\
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN"
          "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">
<html>
<head>
  <meta http-equiv="Content-Type" content="text/html; charset=%(charset)s" />
  <title>%(title)s</title>
  <link rel="stylesheet" href="irclog.css" />
  <meta name="generator" content="logs2html.py %(VERSION)s by Marius Gedminas" />
  <meta name="version" content="%(VERSION)s - %(RELEASE)s" />
</head>
<body>""" % {'VERSION': VERSION, 'RELEASE': RELEASE,
             'title': escape(title), 'charset': 'UTF-8'}, file=outfile)
    print('<h1>%s</h1>' % escape(title), file=outfile)
    if searchbox:
        print("""
<div class="searchbox">
<form action="search" method="get">
<input type="text" name="q" id="searchtext" />
<input type="submit" value="Search" id="searchbutton" />
</form>
</div>
""", file=outfile)
    if latest_log_link:
        link = escape(quote(latest_log_link))
        print('<ul>', file=outfile)
        print(('<li><a href="%s">Latest (bookmarkable)</a></li>' %
                           link), file=outfile)
        print('</ul>', file=outfile)
    print('<ul>', file=outfile)
    for logfile in logfiles:
        # TODO: split by year/month.  Perhaps split off old logs into separate
        # pages
        link = escape(quote(logfile.link))
        title = escape(logfile.title)
        print('<li><a href="%s">%s</a></li>' % (link, title), file=outfile)
    print('</ul>', file=outfile)
    print("""
<div class="generatedby">
<p>Generated by logs2html.py %(VERSION)s by <a href="mailto:marius@pov.lt">Marius Gedminas</a>
 - find it at <a href="http://mg.pov.lt/irclog2html/">mg.pov.lt</a>!</p>
</div>
</body>
</html>""" % {'VERSION': VERSION, 'RELEASE': RELEASE}, file=outfile)


def main(argv=sys.argv):
    progname = os.path.basename(argv[0])
    parser = optparse.OptionParser("usage: %prog [options] directory",
                                   version=VERSION,
                                   prog=progname,
                                   description="Colourises and converts all IRC"
                                               " logs to HTML format for easy"
                                               " web reading.")
    parser.add_option('-c', '--config', action='callback', type='str',
                      metavar='FILE', callback=irclog2html.do_config_file,
                      help="read options from a config file")
    parser.add_option('-s', '--style', dest="style", default="xhtmltable",
                      help="format log according to specific style"
                           " (default: xhtmltable); passes the style name"
                           " to irclog2html.py")
    parser.add_option('-t', '--title', dest="title", default="IRC logs",
                      help="title of the index page (default: IRC logs)")
    parser.add_option('-p', '--prefix', dest="prefix", default="",
                      help="prefix for page title (e.g.:"
                           " 'IRC logs of #channel for ')")
    parser.add_option('-f', '--force', action="store_true", dest="force",
                      default=False,
                      help="ignore mtime and regenerate all files")
    parser.add_option('-S', '--searchbox', action="store_true", dest="searchbox",
                      default=False,
                      help="include a search box")
    parser.add_option('--dircproxy', action='store_true', default=False,
                      help="dircproxy log file support (strips leading + or - from messages; off by default)")
    parser.add_option('-g', '--glob-pattern', dest="pattern", default="*.log",
                      help="glob pattern that finds log files to be processed"
                      " (default: *.log)")
    options, args = parser.parse_args(argv[1:])
    if len(args) < 1:
        parser.error("missing directory name")
    if len(args) > 1:
        parser.error("too many arguments")
    dir = args[0]

    try:
        process(dir, options)
    except Error as e:
        sys.exit("%s: %s" % (progname, e))


def process(dir, options):
    """Process log files in a given directory."""
    extra_args = []
    if options.searchbox:
        extra_args += ['-S']
    if options.dircproxy:
        extra_args += ['--dircproxy']
    logfiles = find_log_files(dir, options.pattern)
    logfiles.reverse() # newest first
    for n, logfile in enumerate(logfiles):
        if n > 0:
            next = logfiles[n - 1]
        else:
            next = None
        if n + 1 < len(logfiles):
            prev = logfiles[n + 1]
        else:
            prev = None
        if (options.force or not logfile.uptodate()
            or prev and prev.newfile() or next and next.newfile()):
            logfile.generate(options.style, options.prefix, prev, next,
                             extra_args)
    latest_log_link = None
    if logfiles and hasattr(os, "symlink"):
        latest_log_link = 'latest.log.html'
        move_symlink(logfiles[0].link, os.path.join(dir, latest_log_link))
    outfilename = os.path.join(dir, 'index.html')
    try:
        outfile = open(outfilename, 'w')
    except IOError as e:
        raise Error("cannot open %s for writing: %s" % (outfilename, e))
    try:
        write_index(outfile, options.title, logfiles, options.searchbox,
                    latest_log_link)
    finally:
        outfile.close()
    css_file = os.path.join(dir, 'irclog.css')
    if not os.path.exists(css_file) and os.path.exists(CSS_FILE):
        shutil.copy(CSS_FILE, css_file)


def move_symlink(src, dst):
    """Create or overwrite a symlink.

    ``src`` is the link target.

    ``dst`` is the name of the symlink.
    """
    try:
        os.unlink(dst)
    except OSError:
        pass
    os.symlink(src, dst)


if __name__ == '__main__':
    main()
