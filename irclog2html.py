#!/usr/bin/env python
"""
Convert IRC logs to HTML.

Usage: irclog2html.py filename

irclog2html will write out a colourised irc log, appending a .html
extension to the output file.

This is a Python port of irclog2html.py Version 2.1, which
was written by Jeff Waugh and is available at www.perkypants.org
"""

# Copyright (c) 2005, Marius Gedminas 
# Copyright (c) 2000, Jeffrey W. Waugh

# Python port:
#   Marius Gedminas <marius@pov.lt>
# Original Author:
#   Jeff Waugh <jdub@perkypants.org>
# Contributors:
#   Rick Welykochy <rick@praxis.com.au>
#   Alexander Else <aelse@uu.net>
#
# Released under the terms of the GNU GPL
# http://www.gnu.org/copyleft/gpl.html

# Differences from the Perl version:
#   There are no hardcoded nick colour preferences for jdub, cantanker and
#   chuckd
#
#   irclog2html.pl interprets --colour-server #rrggbb as -s #rrggbb,
#   irclog2html.py does not have this bug
#
#   irclog2html.py understands ISO8601 timestamps such as used by supybot's
#   ChannelLogger (http://supybot.sourceforge.net/)
#

import os
import re
import sys
import optparse

VERSION = "2.1mg"
RELEASE = "2005-01-09"

# $Id$


#
# Log parsing
#

class Enum(object):
    """Enumerated value."""

    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return self.value


class LogParser(object):
    """Parse an IRC log file.

    When iterated, yields the following events:

        time, COMMENT, (nick, text)
        time, ACTION, text
        time, JOIN, text
        time, PART, text,
        time, NICKCHANGE, (text, oldnick, newnick)
        time, SERVER, text

    """

    COMMENT = Enum('COMMENT')
    ACTION = Enum('ACTION')
    JOIN = Enum('JOIN')
    PART = Enum('PART')
    NICKCHANGE = Enum('NICKCHANGE')
    SERVER = Enum('SERVER')
    OTHER = Enum('OTHER')

    TIME_REGEXP = re.compile(
            r'^\[?((?:\d\d\d\d-\d\d-\d\dT)?\d\d:\d\d(:\d\d)?)\]? +')
    NICK_REGEXP = re.compile(r'^<(.*?)>\s')
    NICK_CHANGE_REGEXP = re.compile(
            r'^(?:\*\*\*|---) (.*?) (?:are|is) now known as (.*)')

    def __init__(self, infile):
        self.infile = infile

    def __iter__(self):
        for line in self.infile:
            line = line.rstrip('\r\n')
            if not line:
                continue

            m = self.TIME_REGEXP.match(line)
            if m:
                time = m.group(1)
                line = line[len(m.group(0)):]
            else:
                time = None

            m = self.NICK_REGEXP.match(line)
            if m:
                nick = m.group(1)
                text = line[len(m.group(0)):]
                yield time, self.COMMENT, (nick, text)
            elif line.startswith('* '):
                yield time, self.ACTION, line
            elif (line.startswith('*** ') or line.startswith('--> ')
                  and 'joined' in line):
                yield time, self.JOIN, line
            elif (line.startswith('*** ') or line.startswith('--> ')
                  and ('left' in line or 'quit' in line)):
                yield time, self.PART, line
            else:
                m = self.NICK_CHANGE_REGEXP.match(line)
                if m:
                    nick_old = m.group(1)
                    nick_new = m.group(2)
                    yield time, self.NICKCHANGE, (line, oldnick, newnick)
                elif line.startswith('*** ') or line.startswith('--- '):
                    yield time, self.SERVER, line
                else:
                    yield time, self.OTHER, line


#
# Colouring stuff
#

class ColourChooser:
    """Choose distinguishable colours."""

    def __init__(self, rgbmin=240, rgbmax=125, rgb=None, a=0.95, b=0.5):
        """Define a range of colours available for choosing.

        `rgbmin` and `rgbmax` define the outmost range of colour depth (note
        that it is allowed to have rgbmin > rgbmax).

        `rgb`, if specified, is a list of (r,g,b) values where each component
        is between 0 and 1.0.

        If `rgb` is not specified, then it is constructed as
           [(a,b,b), (b,a,b), (b,b,a), (a,a,b), (a,b,a), (b,a,a)]

        You can tune `a` and `b` for the starting and ending concentrations of
        RGB.
        """
        assert 0 <= rgbmin < 256
        assert 0 <= rgbmax < 256
        self.rgbmin = rgbmin
        self.rgbmax = rgbmax
        if not rgb:
            assert 0 <= a <= 1.0
            assert 0 <= b <= 1.0
            rgb = [(a,b,b), (b,a,b), (b,b,a), (a,a,b), (a,b,a), (b,a,a)]
        else:
            for r, g, b in rgb:
                assert 0 <= r <= 1.0
                assert 0 <= g <= 1.0
                assert 0 <= b <= 1.0
        self.rgb = rgb

    def choose(self, i, n):
        """Choose a colour.

        `n` specifies how many different colours you want in total.
        `i` identifies a particular colour in a set of `n` distinguishable
        colours.

        Returns a string '#rrggbb'.
        """
        if n == 0:
            n = 1
        r, g, b = self.rgb[i % len(self.rgb)]
        m = self.rgbmin + (self.rgbmax - self.rgbmin) * float(n - i) / n
        r, g, b = map(int, (r * m, g * m, b * m))
        assert 0 <= r < 256
        assert 0 <= g < 256
        assert 0 <= b < 256
        return '#%02x%02x%02x' % (r, g, b)


class NickColourizer:
    """Choose distinguishable colours for nicknames."""

    def __init__(self, maxnicks=30, colour_chooser=None, default_colours=None):
        """Create a colour chooser for nicknames.

        If you know how many different nicks there might be, specify that
        numer as `maxnicks`.  If you don't know, don't worry.

        If you really want to, you can specify a colour chooser.  Default is
        ColourChooser().

        If you want, you can specify default colours for certain nicknames
        (`default_colours` is a mapping of nicknames to HTML colours, that is
        '#rrggbb' strings).
        """
        if colour_chooser is None:
            colour_chooser = ColourChooser()
        self.colour_chooser = colour_chooser
        self.nickcount = 0
        self.maxnicks = maxnicks
        self.nick_colour = {}
        if default_colours:
            self.nick_colour.update(default_colours)

    def __getitem__(self, nick):
        colour = self.nick_colour.get(nick)
        if not colour:
            self.nickcount += 1
            if self.nickcount >= self.maxnicks:
                self.maxnicks *= 2
            colour = self.colour_chooser.choose(self.nickcount, self.maxnicks)
            self.nick_colour[nick] = colour
        return colour

    def nickchange(self, oldnick, newnick):
        if oldnick in self.nick_colour:
            self.nick_colour[newnick] = self.nick_colour.pop(oldnick)


#
# HTML
#

URL_REGEXP = re.compile(r'(http|https|ftp|gopher|news)://\S*')

def createlinks(text):
    """Replace possible URLs with links."""
    return URL_REGEXP.sub(r'<a href="\0">\0</a>', text)

def escape(s):
    """Replace ampersands, pointies, control characters"""
    s = s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    return ''.join([c for c in s if ord(c) > 0x1F])


#
# Output styles
#

class AbstractStyle(object):
    """A style defines the way HTML is formatted.

    This is not a real class, rather it is an description of how style
    classes should be written.
    """

    name = "stylename"
    description = "Single-line description"

    def head(self, title, charset=None):
        """Generate the header."""

    def foot(self):
        """Generate the footer."""

    def servermsg(self, line):
        """Output a generic server message.

        `line` may contain HTML markup.
        """

    def nicktext(self, nick, text, htmlcolour):
        """Output a comment uttered by someone.

        `text` may contain HTML markup.
        `htmlcolour` is a string (#rrggbb).
        """


class SimpleTextStyle(object):
    """Text style with little use of colour"""

    name = "simplett"
    description = property(lambda self: self.__doc__)

    def __init__(self, outfile, colours=None):
        """Create a text formatter for writing to outfile.

        `colours` may have the following attributes:
           part
           join
           server
           nickchange
           action
        """
        self.outfile = outfile
        self.colours = colours or {}

    def head(self, title, charset="iso-8859-1"):
        print >> self.outfile, """\
<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.0 Transitional//EN">
<html>
<head>
\t<title>%(title)s</title>
\t<meta name="generator" content="irclog2html.py %(VERSION)s by Marius Gedminas">
\t<meta name="version" content="%(VERSION)s - %(RELEASE)s">
\t<meta http-equiv="Content-Type" content="text/html; charset=%(charset)s">
</head>
<body text="#000000" bgcolor="#ffffff"><tt>""" % {
            'VERSION': VERSION,
            'RELEASE': RELEASE,
            'title': title,
            'charset': charset,
        }

    def foot(self):
        print >> self.outfile, """
<br>Generated by irclog2html.py %(VERSION)s by <a href="mailto:marius@pov.lt">Marius Gedminas</a>
 - find it at <a href="http://mg.pov.lt/irclog2html.py">mg.pov.lt</a>!
</tt></body></html>""" % {'VERSION': VERSION, 'RELEASE': RELEASE},

    def servermsg(self, what, text):
        colour = self.colours.get(what)
        if colour:
            text = '<font color="%s">%s</font>' % (colour, text)
        self._servermsg(text)

    def _servermsg(self, line):
        print >> self.outfile, '%s<br>' % line

    def nicktext(self, nick, text, htmlcolour):
        print >> self.outfile, '&lt;%s&gt; %s<br>' % (nick, text)


class TextStyle(SimpleTextStyle):
    """Text style using colours for each nick"""

    name = "tt"

    def nicktext(self, nick, text, htmlcolour):
        print >> self.outfile, ('<font color="%s">&lt;%s&gt;</font>'
                                ' <font color="#000000">%s</font><br>'
                                % (htmlcolour, nick, text))


class SimpleTableStyle(SimpleTextStyle):
    """Table style, without heavy use of colour"""

    name = "simpletable"

    def head(self, title, charset="iso-8859-1"):
        SimpleTextStyle.head(self, title, charset)
        print >> self.outfile, "<table cellspacing=3 cellpadding=2 border=0>"

    def foot(self):
        print >> self.outfile, "</table>"
        SimpleTextStyle.foot(self)

    def _servermsg(self, line):
        print >> self.outfile, ('<tr><td colspan=2><tt>%s</tt></td></tr>'
                                % line)

    def nicktext(self, nick, text, htmlcolour):
        print >> self.outfile, ('<tr bgcolor="#eeeeee"><th><font color="%s">'
                                '<tt>%s</tt></font></th>'
                                '<td width="100%%"><tt>%s</tt></td></tr>'
                                % (htmlcolour, nick, text))


class TableStyle(SimpleTableStyle):
    """Default style, using a table with bold colours"""

    name = "table"

    def nicktext(self, nick, text, htmlcolour):
        print >> self.outfile, ('<tr><th bgcolor="%s"><font color="#ffffff">'
                                '<tt>%s</tt></font></th>'
                                '<td width="100%%" bgcolor="#eeeeee"><tt><font'
                                ' color="%s">%s</font></tt></td></tr>'
                                % (htmlcolour, nick, htmlcolour, text))


#
# Main
#

# All styles
STYLES = [
    SimpleTextStyle,
    TextStyle,
    SimpleTableStyle,
    TableStyle
]

# Customizable colours
COLOURS = [
    ("part",       "#000099", LogParser.PART),
    ("join",       "#009900", LogParser.JOIN),
    ("server",     "#009900", LogParser.SERVER),
    ("nickchange", "#009900", LogParser.ACTION),
    ("action",     "#CC00CC", LogParser.NICKCHANGE),
]


def main():
    progname = os.path.basename(sys.argv[0])
    parser = optparse.OptionParser("usage: %prog [options] filename",
                                   description="Colourises and converts IRC"
                                               " logs to HTML format for easy"
                                               " web reading.")
    parser.add_option('-s', '--style', dest="style", default="table",
                      help="format log according to specific style"
                           " (default: table); try -s help for a list of"
                           " available styles")
    for name, default, what in COLOURS:
        parser.add_option('--color-%s' % name, '--colour-%s' % name,
                          dest="colour_%s" % name, default=default,
                          help="select %s colour (default: %s)"
                               % (name, default))
    options, args = parser.parse_args()
    if options.style == "help":
        print "The following styles are available for use with irclog2html.py:"
        for style in STYLES:
            print
            print "  %s" % style.name
            print "    %s" % style.description
        print
        return
    for style in STYLES:
        if style.name == options.style:
            break
    else:
        parser.error("unknown style: %s" % style)
    colours = {}
    for name, default, what in COLOURS:
        colours[what] = getattr(options, 'colour_%s' % name)
    if not args:
        parser.error("required parameter missing")

    for filename in args:
        try:
            infile = open(filename)
        except EnvironmentError, e:
            sys.exit("%s: cannot open %s for reading: %s"
                     % (progname, filename, e))
        outfilename = filename + ".html"
        try:
            outfile = open(outfilename, "w")
        except EnvironmentError, e:
            infile.close()
            sys.exit("%s: cannot open %s for writing: %s"
                     % (progname, outfilename, e))
        try:
            parser = LogParser(infile)
            formatter = style(outfile, colours)
            log2html(parser, formatter, filename)
        finally:
            outfile.close()
            infile.close()


def log2html(parser, formatter, title):
    """Convert IRC log to HTML."""
    nick_colour = NickColourizer()
    formatter.head(title)
    for time, what, info in parser:
        if what == LogParser.COMMENT:
            nick, text = map(escape, info)
            text = createlinks(text)
            text = text.replace('  ', '&nbsp;&nbsp;')
            htmlcolour = nick_colour[nick]
            formatter.nicktext(nick, text, htmlcolour)
        else:
            if what == LogParser.NICKCHANGE:
                text, oldnick, newnick = map(escape, info)
                nick_colour.change(oldnick, newnick)
            else:
                text = escape(info)
            text = createlinks(text)
            formatter.servermsg(what, text)
    formatter.foot()


if __name__ == '__main__':
    main()
