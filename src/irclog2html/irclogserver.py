#!/usr/bin/env python
"""
Serve IRC logs (WSGI app)

Expects to find logs matching the IRCLOG_GLOB pattern (default: *.log)
in the directory specified by the IRCLOG_LOCATION environment variable.
Expects the filenames to contain a ISO 8601 date (YYYY-MM-DD).

Apache configuration example:

  WSGIScriptAlias /irclogs /path/to/irclogserver.py
  <Location /irclogs>
    # If you're serving the logs for one channel, specify this:
    SetEnv IRCLOG_LOCATION /path/to/irclog/files/
    # If you're serving the logs for many channels, specify this:
    SetEnv IRCLOG_CHAN_DIR /path/to/irclog/channels/
    # Uncomment the following if your log files use a different format
    #SetEnv IRCLOG_GLOB "*.log.????-??-??"
  </Location>

"""

# Copyright (c) 2015, Marius Gedminas and contributors
#
# Released under the terms of the GNU GPL
# http://www.gnu.org/copyleft/gpl.html

from __future__ import print_function

import argparse
import cgi
import io
import os
from wsgiref.simple_server import make_server

try:
    from urllib import quote_plus # Py2
except ImportError:
    from urllib.parse import quote_plus # Py3

from .irclog2html import CSS_FILE, LogParser, XHTMLTableStyle, convert_irc_log
from .logs2html import LogFile, Error, find_log_files, write_index
from .irclogsearch import (
    DEFAULT_LOGFILE_PATH, DEFAULT_LOGFILE_PATTERN, search_page,
    HEADER, FOOTER
)


def dir_listing(stream, path):
    """Primitive listing of subdirectories."""
    print(HEADER, file=stream)
    print(u"<h1>IRC logs</h1>", file=stream)
    print(u"<ul>", file=stream)
    for name in sorted(os.listdir(path)):
        if os.path.isdir(os.path.join(path, name)):
            print(u'<li><a href="%s/">%s</a></li>'
                  % (quote_plus(name), cgi.escape(name)),
                  file=stream)
    print(u"</ul>", file=stream)
    print(FOOTER, file=stream)


def log_listing(stream, path, pattern, channel=None):
    """Primitive listing of log files."""
    logfiles = find_log_files(path, pattern)
    logfiles.reverse()
    if channel:
        title = u"IRC logs of {channel}".format(channel=channel)
    else:
        title = u"IRC logs"
    write_index(stream, title, logfiles, searchbox=True)


def dynamic_log(stream, path, channel=None):
    """Render HTML dynamically"""
    lf = LogFile(path)
    with open(path, 'rb') as f:
        parser = LogParser(f)
        formatter = XHTMLTableStyle(stream.buffer)
        if channel:
            title = u"IRC log of {channel}".format(channel=channel)
        else:
            title = u"IRC log"
        title += u" for {date:%A, %Y-%m-%d}".format(date=lf.date)
        prev = next = ('', '')
        index = ('Index', 'index.html')
        convert_irc_log(parser, formatter, title, prev, index, next,
                        searchbox=True)


def parse_path(environ):
    """Return tuples (channel, filename).

    The channel of None means default, the filename of None means 404.
    """
    path = environ.get('PATH_INFO', '/')
    path = path[1:]  # Remove the leading slash
    channel = None
    if environ.get('IRCLOG_CHAN_DIR', os.environ.get('IRCLOG_CHAN_DIR')):
        if '/' in path:
            channel, path = path.split('/', 1)
            if channel == '..':
                return None, None
    if '/' in path or '\\' in path:
        return channel, None
    return channel, path if path != '' else 'index.html'


def application(environ, start_response):
    """WSGI application"""
    def getenv(name, default=None):
        return environ.get(name, os.environ.get(name, default))

    chan_path = getenv('IRCLOG_CHAN_DIR')
    logfile_path = getenv('IRCLOG_LOCATION') or DEFAULT_LOGFILE_PATH
    logfile_pattern = getenv('IRCLOG_GLOB') or DEFAULT_LOGFILE_PATTERN
    form = cgi.FieldStorage(fp=environ['wsgi.input'], environ=environ)
    stream = io.TextIOWrapper(io.BytesIO(), 'ascii',
                              errors='xmlcharrefreplace',
                              line_buffering=True)

    status = "200 Ok"
    content_type = "text/html; charset=UTF-8"
    headers = {}

    channel, path = parse_path(environ)
    if channel:
        logfile_path = os.path.join(chan_path, channel)
    if path is None:
        status = "404 Not Found"
        result = [b"Not found"]
        content_type = "text/plain"
    elif path == "index.html" and chan_path and channel is None:
        dir_listing(stream, chan_path)
        result = [stream.buffer.getvalue()]
    elif path == 'search':
        search_page(stream, form, logfile_path, logfile_pattern)
        result = [stream.buffer.getvalue()]
    elif path == 'irclog.css':
        content_type = "text/css"
        try:
            with open(CSS_FILE, "rb") as f:
                result = [f.read()]
        except IOError:  # pragma: nocover
            status = "404 Not Found"
            result = [b"Not found"]
            content_type = "text/plain"
    else:
        try:
            with open(os.path.join(logfile_path, path), "rb") as f:
                result = [f.read()]
        except IOError:
            if path == 'index.html':
                log_listing(stream, logfile_path, logfile_pattern, channel)
                result = [stream.buffer.getvalue()]
            elif path.endswith('.html'):
                try:
                    dynamic_log(stream, os.path.join(logfile_path, path[:-5]),
                                channel=channel)
                    result = [stream.buffer.getvalue()]
                except (Error, IOError):
                    # Error will be raised if the filename has no ISO-8601 date
                    status = "404 Not Found"
                    result = [b"Not found"]
                    content_type = "text/plain"
            else:
                status = "404 Not Found"
                result = [b"Not found"]
                content_type = "text/plain"
        else:
            if path.endswith('.css'):
                content_type = "text/css"
            elif path.endswith('.log') or path.endswith('.txt'):
                content_type = "text/plain; charset=UTF-8"
                result = [LogParser.decode(line).encode('UTF-8')
                          for line in b''.join(result).splitlines(True)]

    headers["Content-Type"] = content_type
    # We need str() for Python 2 because of unicode_literals
    headers = sorted((str(k), str(v)) for k, v in headers.items())
    start_response(str(status), headers)
    return result


def main():  # pragma: nocover
    """Simple web server for manual testing"""
    parser = argparse.ArgumentParser(description="Serve IRC logs")
    parser.add_argument(
        '-p', '--port', type=int, default=8080,
        help='listen on the specified port (default: 8080)')
    parser.add_argument(
        '-P', '--pattern',
        help='IRC log file pattern (default: $IRCLOG_GLOB,'
             ' falling back to %s)' % DEFAULT_LOGFILE_PATTERN)
    parser.add_argument(
        '-m', '--multi', action='store_true',
        help='serve logs for multiple channels in subdirectories'
             ' (default: when $IRCLOG_CHAN_DIR points to a path)')
    parser.add_argument(
        'path',
        help='where to find IRC logs (default: $IRCLOG_LOCATION'
             ' or $IRCLOG_CHAN_DIR, falling back to %s)'
             % DEFAULT_LOGFILE_PATH)
    args = parser.parse_args()
    srv = make_server('localhost', args.port, application)
    print("Started at http://localhost:{port}/".format(port=args.port))
    if args.multi:
        os.environ['IRCLOG_CHAN_DIR'] = args.path
        print("Serving IRC logs for multiple channels from {path}".format(
            path=args.path))
    else:
        os.environ['IRCLOG_LOCATION'] = args.path
        print("Serving IRC logs from {path}".format(path=args.path))
    if args.pattern:
        os.environ['IRCLOG_GLOB'] = args.pattern
        print("Looking for files matching {pattern}".format(
            pattern=args.pattern))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
