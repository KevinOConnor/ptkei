"""Routines used to parse information from the server."""

#    Copyright (C) 1998-1999 Kevin O'Connor
#
#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program; if not, write to the Free Software
#    Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

import string
import re
import operator

import empQueue
import empDb

# Key Ideas:

# What is contained within this file:

# This file contains all the standard low-level parsers.  For each client
# understood command there is a line in empQueue.standardParsers that
# points to a parser in this file.  In actuality, empQueue.standardParsers
# is really established in this file - in the initialize().  For more
# information on the classes, please see their individual documentation.


# How to setup a parser class:

# A parser class is a class that interprets data received from a command.
# The first thing that needs to be done is to setup a class that descends
# from empQueue.baseDisp.  The new class should define methods for some,
# none, or all of Begin(), data(), flush(), and End().  See the base class
# empQueue.baseDisp for more info on how this works.  Basically, if one of
# the above methods is not defined, empQueue.baseDisp will create a dummy
# reference that just passes the information to the next parser.  If a
# method is defined for any of the above, it is the responsibility of the
# class to pass the data onto the next parser.  This is usually done by
# invoking the appropriate method of self.out.  For example, to send a data
# line on, use self.out.data(msg).

# Begin() is invoked just before the command starts receiving data.  It is
# passed the name of the command as its only argument.

# flush() is invoked when the command receives a subprompt.  It is passed
# two arguments: The first is the string prompt, the second is either None
# or a function that should be called with the desired response.  If the
# second argument (the callback function) is the value None then no
# response is possible.  (This occurs when a bursted command answers a
# subprompt line.  In such cases, the Answer() method is called
# immediately after flush() with the text that answered the line.)

# Answer() is invoked when one of the command's subprompts is answered.  It
# is passed one argument - the string response.

# End() is called after the last line of data is received.  It is passed
# the same argument as Begin().


# Binding a command to a parse class:

# There are two ways to bind a command.  The first is to add the parser to
# list found in standardParsers (which is defined below in initialize()).
# This defines a low-level parser that will be called every time the
# command is sent to the server.  The second method is to assign the parser
# on a per-command basis.  This is done by specifying the parse class when
# invoking viewer.ioq.Send().  (See empCmd.EmpParse for more info on this
# command.)  To assign a parser to a specific command use
# viewer.ioq.Send("cmd_text_here", ParseClassHere()).  When "cmd_text_here"
# is sent to the server, ParseClassHere will receive the output from it.
# Note: binding a class on a per-command basis does not override a
# low-level parser.  If the command is also associated with a low-level
# parser, then the binded class will receive the data after the low-level
# parser.


CN_OWNED = empDb.CN_OWNED
CN_UNOWNED = empDb.CN_UNOWNED
CN_ENEMY = empDb.CN_ENEMY

###########################################################################
#############################  Map Functions  #############################
def updateDesignations(lst, mapType):
    """Update map designations from a list of (x,y,designation) triples.

    This function is complex, because it must determine when a designation
    change should be honored, and when it should be ignored.  Depending on
    mapType, it may be necessary to distrust the information.
    """
##     print lst
    DB = empDb.megaDB['SECTOR']
    changes = []
    for col, row, t in lst:
        if t not in ' ?' and not empDb.megaDB['sectortype'].has_key(t):
            # Exclusion of all sector designations that aren't actual
            # designations.  Still buggy as it doesn't handle bmaps. 
            continue
        ldict = DB.get((col, row), {})
        oldown = ldict.get('owner')
        olddes = ldict.get('des')
        ndict = {}
        if mapType in ('bmap', 'land'):
            # bmap
            if t == ' ':
                continue
            if t == '?':
                if not olddes or (mapType == 'bmap' and olddes == '-'):
                    ndict['des'] = t
            elif not olddes or oldown != CN_OWNED:
                ndict['des'] = t
        else:
            if t == ' ':
                if mapType == 'radar':
                    continue
                if oldown == CN_OWNED:
                    ndict['owner'] = CN_UNOWNED
                else:
                    continue
            elif t == '?':
                if oldown is None or oldown == CN_OWNED:
                    ndict['owner'] = CN_UNOWNED
                # Hack for bridges
                if olddes == '.':
                    ndict['des'] = '='
                if not olddes:
                    ndict['des'] = t
            elif t == '.' or t == '\\':
                if oldown != 0:
                    ndict['owner'] = 0
                ndict['des'] = t
            elif t == '^' or t == '~':
                ndict['des'] = t
            elif mapType == 'newdes':
                # future designations
                if t != '-':
                    ndict['owner'] = CN_OWNED
                if olddes == t:
                    ndict['sdes'] = '_'
                else:
                    ndict['sdes'] = t
            elif mapType == 'radar':
                # radar maps
                ndict['des'] = t
            else:
                # normal maps
                if t != '-':
                    ndict['owner'] = CN_OWNED
                ndict['des'] = t
        ndict['x'] = col
        ndict['y'] = row
        changes.append(ndict)
    DB.updates(changes)

def parseStarMap(sects, coord, mapType):
    """Handle a map that is returned from a radar or prompt."""
    worldx, worldy = empDb.megaDB['version']['worldsize']
    l = len(sects)
    hl = l/2
    tl = l*2
    lst = []
    for i in range(l):
        y = (coord[1]-hl+i + worldy/2) % worldy - worldy/2
        for j in range(abs(hl-i), tl-abs(hl-i), 2):
            x = (coord[0]-l+j+1 + worldx/2) % worldx - worldx/2
            if len(sects[i]) > j:
                lst.append((x, y, sects[i][j]))
            else:
                lst.append((x, y, ' '))
    updateDesignations(lst, mapType)

###########################################################################
###########################  Header functions   ###########################
def sectToCoords(s, field):
    """Convert a string of the form 'x,y' to its x and y values."""
    try:
        idx = string.index(s, ',')
        return {'x':string.atoi(s[:idx]),
                'y':string.atoi(s[idx+1:])}
    except ValueError:
        return {}

def newdesToDes(s, field):
    """Convert a 'xy' string to designation x, and newdesignation y."""
    if len(s) == 2:
        return {'des':s[0], 'sdes':s[1]}
    return {'des':s[0], 'sdes':'_'}

def zeroIsOne(s, field):
    """Convert a 0 to 1."""
    if s == 0:
        return {field:1}
    return {field:s}

def convertOwner(s, field):
    return {'owner':empDb.megaDB['countries'].resolveId(s)}

def convertOldOwner(s, field):
    return {'oldown':empDb.megaDB['countries'].resolveId(s)}

def composeHeader(translations, *args):
    """Convert a series of string headers into a list of named qualifiers."""
    num = len(args)
    lastColumns = string.split(args[-1], ' ')
    startcut = 0
    new = []

    # Convert a set of header lines ('num' lines in 'args') to a list of
    # table column names.  This assumes the last line of the header will
    # always have the largest length.  (It breaks up the header rows by
    # column using the last row's field spacing as a guide.)
    for segment in lastColumns:
        endcut = startcut + len(segment)
        new.append(string.lstrip(string.join(
            map(string.strip,
                map(operator.getslice, args, (startcut,)*num, (endcut,)*num)),
            "\n")))
        startcut = endcut + 1
    new = filter(None, new)
##     print new

    # Now create a list of database keys for each of the header lines from
    # the translations mapping.  This also supports special translation
    # functions that handle header lines that don't have a one-to-one
    # mapping to a database field.
    final = []
    for i in new:
        try:
            idx = translations[i]
        except KeyError:
            final.append(None)
        else:
            if callable(idx):
                final.append((lambda s, field=i, f=idx:
                              f(s, field)))
            else:
                final.append(idx)
##     print final
    return final

def composeBody(hdr, msg):
    """Convert the body of a message that has a header HDR."""
    strs = string.split(msg)
    convertList(strs)
    if len(strs) == len(hdr):
        # Standard table format
        new = {}
        for field, value in map(None, hdr, strs):
            if field is None:
                continue
            if callable(field):
                new.update(field(value))
            else:
                new[field] = value
##      print new
        return new

def composePreamble(lst, mtch, str, translations=None):
    """Convert info of the form 'type val, type val, ...' to a list."""
    while str:
        mt = mtch.match(str)

        var, val = mt.group('comd', 'val')
        temp = [val]; convertList(temp); val = temp[0]
        if translations is None:
            lst[var] = val
        else:
            try:
                tran = translations[var]
            except KeyError:
                pass
            else:
                if callable(tran):
                    lst.update(tran(val, var))
                else:
                    lst[tran] = val
        str = mt.group('next')
    return lst

###########################################################################
#############################   Look Function   ###########################

# When looking from a ship or a land unit, moving land units around or
# when performing recon flight with a non spy plane, the result is the
# same as the one of the 'look' command.

def getLookInfo(line, unitType = 'UNKNOWN'):
    """Check whether we've got a line like 'Your city 50% efficient
    with 999 civ @ -20,54'.  If so, parses it, extracts information
    out of it, updates the database and returns 1 otherwise returns
    0."""
    
    look_info = re.compile(r"^(?:Your|"+s_counIdent+") "+ParseUnits.s_shipOrSector
                           +" @ "+s_sector+"$")
    look_stats = re.compile(
        r"^ with (?:approx )?(?P<val>\d+) (?P<comd>\S+)(?P<next>.*)$")

    if 'SHIPNAMES' in empDb.megaDB['version']['enabledOptions']:
        look_ship_info = re.compile(r"^(?P<counName>\S+)\s+"
                                    +r"\(\#(?P<counId>\d+)\)\s+"
                                    +r"(?P<shipType>\S+).*"
                                    +r"\(\#(?P<shipId>\d+)\)\s+"
                                    +r"@ (?P<sectorX>-?\d+),(?P<sectorY>-?\d+)\s*$"
                                    )
    else:
        look_ship_info = re.compile(r"^(?P<counName>\S+)\s+"
                                    +r"\(\#(?P<counId>\d+)\)\s+"
                                    +r"(?P<shipType>\S+).*"
                                    +r"\#(?P<shipId>\d+)\s+"
                                    +r"@ (?P<sectorX>-?\d+),(?P<sectorY>-?\d+)\s*$"
                                    )

    look_land_info = re.compile(r"^(?P<counName>\S+)\s+"
                                +r"\(\#(?P<counId>\d+)\)\s+"
                                +r"(?P<landType>\S+).*"
                                +r"\#(?P<landId>\d+)\s+"
                                +r"\(approx (?P<landMil>\d+) mil\)\s+"
                                +r"@ (?P<sectorX>-?\d+),(?P<sectorY>-?\d+)\s*$"
                                )
    
    look_plane_info = re.compile(r"^(?P<counName>\S+)\s+"
                                 +r"\(\#(?P<counId>\d+)\)\s+"
                                 +r"(?P<planeType>\S+).*"
                                 +r"\#(?P<planeId>\d+)\s+"
                                 +r"@ (?P<sectorX>-?\d+),(?P<sectorY>-?\d+)\s*$"
                                 )

    found = 0
    if unitType == 'SHIP':
        mm = look_ship_info.match(line)
        if mm:
            found = 1
    if unitType == 'LAND UNIT' and found == 0:
        mm = look_land_info.match(line)
        if mm:
            found = 2
        if found == 0:
            mm = look_plane_info.match(line)
            if mm:
                found = 3
    if found == 0:
        mm = look_info.match(line) 
        if mm:
            found = 4
    if found == 0:
        return 0
    
    own = mm.group('counId')
    if own is None:
        own = CN_OWNED
    else:
        own = empDb.megaDB['countries'].resolveNameId(
            mm.group('counName'), string.atoi(own))
        
    if found == 1:
        # A ship
        x, y, id = map(string.atoi,
                       mm.group('sectorX', 'sectorY', 'shipId'))
        empDb.megaDB['SHIPS'].updates([
            {'id': id, 'type':mm.group('shipType'),
             'x': x, 'y': y, 'owner':own}])
    elif found == 2:
        x, y, id = map(string.atoi, mm.group('sectorX', 'sectorY', 'landId'))
        empDb.megaDB['LAND UNITS'].updates([
            {'id': id, 'type':mm.group('landType'),
             'x': x, 'y': y, 'owner':own}])
    elif found == 3:
        x, y, id = map(string.atoi, mm.group('sectorX', 'sectorY', 'planeId'))
        empDb.megaDB['PLANES'].updates([
            {'id': id, 'type':mm.group('planeType'),
             'x': x, 'y': y, 'owner':own}])
    else:
        lst = {'civ':0, 'mil':0}
        composePreamble(lst, look_stats, mm.group('sectorStats'),
                        {'civ':zeroIsOne, 'mil':zeroIsOne})
        x, y, eff = map(string.atoi,
                        mm.group('sectorX', 'sectorY', 'eff'))
        lst.update({'des': sectorNameConvert[mm.group('sectorName')],
                    'eff': eff, 'owner': own,
                    'x': x, 'y': y})
        empDb.megaDB['SECTOR'].updates([lst])
    return 1


###########################################################################
#############################  Empire Constants ###########################

# Translate abbreviations to their full sector names.
# This is from the html info pages.
sectorDesignationConvert = {
    # BASICS
    '.': 'sea', '^': 'mountain', 's': 'sanctuary', '\\': 'wasteland',
    '-': 'wilderness', 'g': 'gold mine', 'c': 'capital', 'p': 'park',
    # COMMUNICATIONS
    '+': 'highway', ')': 'radar installation',
    '#': 'bridge head', '=': 'bridge span', '@': 'bridge tower',
    # INDUSTRIES
    'd': 'defense plant', 'i': 'shell industry', 'm': 'mine',
    'g': 'gold mine', 'h': 'harbor', 'w': 'warehouse',
    'u': 'uranium mine', '*': 'airfield', 'a': 'agribusiness',
    'o': 'oil field', 'j': 'light manufacturing', 'k': 'heavy manufacturing',
    '%': 'refinery',
    # MILITARY / SCIENTIFIC
    't': 'technical center', 'f': 'fortress', 'r': 'research lab',
    'n': 'nuclear plant', 'l': 'library/school',
    'e': 'enlistment center', '!': 'headquarters',
    # FINANCIAL
    'b': 'bank',
##      'v': 'trading post',
    }

# Translate full sector names to their abbreviations.
sectorNameConvert = {}
map(operator.setitem,
    (sectorNameConvert,) * len(sectorDesignationConvert),
    sectorDesignationConvert.values(),
    sectorDesignationConvert.keys())
# Create a regular expression that accepts full sector names.
s_sectorName = (r"(?P<sectorName>"+
                string.join(sectorDesignationConvert.values(), '|')+")")

try:
    # Ughh.  There is a bug in python 1.5.1 and earlier...
    string.atoi('-')
except ValueError:
    # Correct version
    def convertList(dlist):
        """Convert a list of strings to native types."""
        string__atof = string.atof
        string__atoi = string.atoi
        string__atol = string.atol
        for i in range(len(dlist)):
            val = dlist[i]
            if '.' in val:
                try:
                    val = string__atof(val)
                except ValueError:
                    continue
            else:
                try:
                    val = string__atoi(val)
                except OverflowError:
                    val = string__atol(val)
                except ValueError:
                    continue
            dlist[i] = val
else:
    # Bug fix version
    def convertList(dlist):
        """Convert a list of strings to native types."""
        string__atof = string.atof
        string__atoi = string.atoi
        string__atol = string.atol
        bugtest = ('+', '-')
        for i in range(len(dlist)):
            val = dlist[i]
            if val in bugtest:
                # Python 1.5.1 bug - converts '+'/'-' to 0..
                continue
            if '.' in val:
                try:
                    val = string__atof(val)
                except ValueError:
                    continue
            else:
                try:
                    val = string__atoi(val)
                except OverflowError:
                    val = string__atol(val)
                except ValueError:
                    continue
            dlist[i] = val

###########################################################################
#############################  Parse classes  #############################
s_time = empDb.s_time
atoi = string.atoi
curtimeFormat = re.compile("^"+s_time+"$")


class ParseDump(empQueue.baseDisp):
    """Parse output from dump command."""
    dumpcommand = re.compile(r"^\s*\S+\s+(\S+)(?:\s+(\S+)\s*)?$")
##     timestamp = re.compile(r"^(?:\?timestamp>(\d+))?$")
    def Begin(self, cmd):
        self.out.Begin(cmd)

        self.getheader = 0
        self.Hlist = None
        self.updateList = []
        self.sett = self.full = 0
        self.DB = None

        # Determine if the timestamp should be set for this dump
        mm = self.dumpcommand.match(cmd)
        if (mm and mm.group(1) == '*'):
            if not mm.group(2):
                # This is a total dump
                self.full = 1
                self.sett = 1
            elif mm.group(2)[:3] == '?ti':
                # This is a timestamp dump
                self.sett = 1

    dumpheader = re.compile(
        r"^DUMP (?P<dumpName>.*) (?P<timeStamp>\d+)$")
    dumpend = re.compile(
        r"^\d+ (sector|ship|unit|plane)s?$")
    dumpnone = re.compile(
        r"^.*No (sector|ship|unit|plane)\(s\)$")
    def data(self, msg):
        self.out.data(msg)
        if self.Hlist is None:
            # check time
            mtch = curtimeFormat.match(msg)
            if mtch:
##                 self.ctime = mtch
                empDb.megaDB['time'].noteTime(mtch)
                return
            # parse header
            mtch = self.dumpheader.match(msg)
            if mtch:
                tp = mtch.group('dumpName')
                self.lost = (tp == 'LOST ITEMS')
                self.DB = empDb.megaDB[tp]
                ts = string.atoi(mtch.group('timeStamp'))
##                 empDb.megaDB['time'].noteTimestamp(self.ctime, float(ts))
                if self.sett:
                    # It is possible for the server to process a command
                    # during the same second it calculates the current
                    # timestamp.  This results in a timestamp that wont
                    # cover the last command.  Therefore, it is safest to
                    # assume the timestamp is always one second less than
                    # the value received from the server.
                    self.timestamp = ts-1

                # Set the "unoficial timestamp".  This is the timestamp
                # used for any dump commands requested.  It differs from
                # the official timestamp in that the offical one is only
                # updated after a complete dump has been fully processed -
                # it is the timestamp that is stored to disk.
                if self.sett:
                    self.DB.unofficial_timestamp = self.timestamp

                self.getheader = 1
            elif self.getheader == 1:
                self.Hlist = string.split(msg)
                self.getheader = 0
                # HACK! Check for the existence of "difficult" fields
                self.oldownerHack = []
                self.nameHack = []
                for fieldname, pos in map(None, self.Hlist,
                                          range(len(self.Hlist))):
                    if fieldname == "*":
                        self.Hlist[pos] = "oldown"
                        self.oldownerHack.append(pos)
                    elif fieldname == "name":
                        self.nameHack.append(pos)
            return

        # parse each line
        mm = self.dumpend.match(msg)
        if mm :
            self.Hlist = None
            return
        mm = self.dumpnone.match(msg)
        if mm :
            self.Hlist = None
            return

        Dlist = string.split(msg)
        l = len(Dlist)
        # HACK! Fix problem with 'name' field
        if l >= len(self.Hlist):
            for i in self.nameHack:
                start = end = i
                if len(Dlist[start]) == 1:
                    end = end + 1
                while Dlist[end][-1] != '"':
                    end = end + 1
##              print start, end, string.join(Dlist[start:end+1])
                Dlist[start:end+1] = [string.join(Dlist[start:end+1])[1:-1]]
                l = l - (end-start)
        if l == len(self.Hlist):
            # Normal line

            # Convert string listing to native format
            convertList(Dlist)

            DDict = {'owner':CN_OWNED}
            map(operator.setitem, [DDict]*l, self.Hlist, Dlist)
            # HACK! Fix annoying '*' field
            if self.oldownerHack:
                if DDict['oldown'] == '.':
                    DDict['oldown'] = CN_OWNED
                else:
                    DDict['oldown'] = CN_ENEMY

##          self.updateList.append(Dlist)
            self.updateList.append(DDict)
        else:
            # End of dump
            self.Hlist = None

    def End(self, cmd):
        self.out.End(cmd)
        if self.DB is None:
            # Something odd happened - no dump lines at all.
            return

        # Update the database
        if not self.full:
            # simple update
            self.DB.updates(self.updateList)
##          self.DB.updates(listDict)
        else:
            # A full dump
            others = self.DB.updates(self.updateList, 1)
##          others = self.DB.updates(listDict, 1)
            list = []
            for i in others.values():
                if i.get('owner') == CN_OWNED:
                    dict = i.copy()
                    dict.update({'owner':CN_UNOWNED})
                    list.append(dict)
            self.DB.updates(list)
        # Merge lost database with normal databases.
        if self.lost:
            for i in empDb.updateDB['LOST ITEMS'].values():
                subDB = (('SECTOR', 'x', 'y'), ('SHIPS', 'id'),
                         ('PLANES', 'id'), ('LAND UNITS', 'id'),
                         ('NUKES', 'x', 'y'))[i['type']]
                key = []
                d = {}
                for j in subDB[1:]:
                    key.append(i[j])
                    d[j] = i[j]
                if empDb.megaDB[subDB[0]].get(tuple(key),
                                        {}).get('owner') == CN_OWNED:
                    d['owner'] = CN_UNOWNED
                    empDb.megaDB[subDB[0]].updates([d])
            empDb.updateDB['LOST ITEMS'].clear()

        # Update the official timestamp.  (The timestamp stored on disk.)
        if self.sett:
            self.DB.timestamp = self.timestamp

class ParseMap(empQueue.baseDisp):
    """Parse output from various map commands."""
    mapcommand = re.compile(r"^\s*(\S?)map")
    def Begin(self, cmd):
        self.out.Begin(cmd)
        self.Mpos = 0
        self.Mheader = []

        # Determine the type of map
        mm = self.mapcommand.match(cmd)
        if mm:
            try:
                self.mapType = {'n':'newdes', 'b':'bmap'}[mm.group(1)]
            except KeyError:
                self.mapType = ''
        else:
            self.mapType = ''

    def data(self, msg):
        self.out.data(msg)
        # parse header
        msg_a = msg[:5]
        msg_b = msg[5:]
        if msg_a == "     ":
            # Header or trailer
            if self.Mpos == 2:
                # End of map
                self.Mpos = -1
                updateDesignations(self.lst, self.mapType)
                return
            elif self.Mpos == 0:
                # First line of header
                self.Mhead = msg_b
                self.Mpos = 1
            elif self.Mpos == 1:
                # Additional lines of header
                msg_b = string.replace(msg_b, "-", "0")
                self.Mhead = map(operator.add, self.Mhead, msg_b)
        else:
            if self.Mpos == 1:
                # First line of data - convert alphanumeric columns to numeric
                self.Mpos = 2
                cols = map(string.atoi, self.Mhead)
                if len(cols) == 1:
                    # Can't accurately parse maps with 1 column
                    self.Mpos = -1
                    return
                # Fix negative values
                if cols[-1] < cols[-2]:
                    cols[-1] = - cols[-1]
                for i in range(len(cols)-1):
                    if cols[i] > cols[i+1]:
                        cols[i] = - cols[i]
                self.oddcol = (cols[0] & 1)
                self.lst = []
                self.Mhead = cols
##              print self.Mhead
            elif self.Mpos != 2:
                # Ignore line
                return
            # Must be a data line
            row = string.atoi(msg_a)
            # Parse map
            oddstart = (row & 1) ^ self.oddcol
            for i in range(oddstart, len(self.Mhead), 2):
                self.lst.append((self.Mhead[i], row, msg_b[i]))

ss_sect = r"-?\d+"
s_sector = r"(?P<sectorX>"+ss_sect+"),(?P<sectorY>"+ss_sect+")"
s_sector2 = r"(?P<sector2X>"+ss_sect+"),(?P<sector2Y>"+ss_sect+")"
s_comm = r"(?P<comm>\S+)"
class ParseMove(empQueue.baseDisp):
    """Parse an explore prompt."""
    def __init__(self, disp):
        empQueue.baseDisp.__init__(self, disp)
        self.map = []

    ownSector = re.compile("^Sector "+s_sector+" is now yours\.$")
    def data(self, msg):
        mm = self.ownSector.match(msg)
        if mm:
            x, y = map(string.atoi, mm.group('sectorX', 'sectorY'))
            empDb.megaDB['SECTOR'].updates(
                [{'x': x, 'y': y, 'owner':CN_OWNED}])
        self.map.append(msg)
        self.out.data(msg)

    s_mob = r"(?P<mob>\d+\.\d+)"
    s_des = r"(?P<des>.)"
    promptFormat = re.compile("^<"+s_mob+": "+s_des+" "+s_sector+"> $")
    def flush(self, msg, hdl):
        self.out.flush(msg, hdl)
        mm = self.promptFormat.match(msg)
        if mm:
            # Extract map from last three lines of data
            sects = []
            for i in self.map[-3:]:
                sects.append(i[3:8])
            coord = map(string.atoi, mm.group('sectorX', 'sectorY'))
            parseStarMap(sects, coord, '')

s_landIdent = r"(?P<landType>\S+)(?:.+)? #(?P<landId>\d+)"
s_shipIdent = r"(?P<shipType>\S+)(?:.+)? \(#(?P<shipId>\d+)\)"
s_shipOrLand = r"(?:"+s_shipIdent+"|"+s_landIdent+")"
s_counName = r"(?P<counName>.*?)"
s_counId = r"\(#(?P<counId>\d+)\)"
s_counIdent = s_counName + " " + s_counId
s_eff = r"(?P<eff>\d+)%"
class ParseUnits(empQueue.baseDisp):
    """Parse info from a variety of unit type commands."""
    def Begin(self, cmd):
        self.out.Begin(cmd)
        self.num = None
        self.Map = []
        if cmd[:3] == 'nav' or cmd[:3] == 'loo':
            self.unitType = 'SHIP'
        elif cmd[:4] == 'lloo' or cmd[:4] == 'marc':
            self.unitType = 'LAND UNIT'
        else:
            self.unitType = 'UNKNOWN'
            
    s_dist = r"(?P<dist>\d+)"
    start_radar = re.compile(r"^(?:"+s_shipOrLand+" at )?"
                             +s_sector+" efficiency "+s_eff
                             +", max range "+s_dist+"$")
    sonar_info = re.compile(r"^Sonar detects (?P<shipMisc>\S.*\S) (?P<shipName>\S+)?\(#(?P<shipId>\d+)\)"+" @ "+s_sector+"$")
    sonar_unknown_sub_info = re.compile(r"^Sonar detects sub #(?P<shipId>\d+)"
                                        +" @ "+s_sector+"$")
    s_sectorStats = r"(?P<sectorStats>(?: with (?:approx )?\d+ \S+)*)"
    s_shipOrSector = ("(?:"+s_shipIdent+"|"
                      +s_sectorName+" "+s_eff+" efficient"+s_sectorStats+")")
    view_info = re.compile(r"^(?:\[(?P<viewStats>.*?)\] )?"+s_shipIdent+" @ "
                           +s_sector+" "+s_eff+" "+s_sectorName+"$")
    view_stats = re.compile(
        r"^(?P<comd>\S+):(?P<val>\d+)(?P<next>)$")
    unit_stop = re.compile(
        "^"+s_shipOrLand+" (?:stopped at|is out of mobility & stays in) "
        +s_sector+"$")
    def data(self, msg):
        self.out.data(msg)
        mm = self.sonar_info.match(msg)
        if mm:
            shipMisc = mm.group('shipMisc')
            item = string.split(shipMisc)
            if len(item) > 3:
                own = item[0]
                type = item[1]
            elif len(item) == 2:
                own = CN_ENEMY
                type = item[0]
            else:
                if empDb.megaDB['countries'].nameList.has_key(item[0]):
                    own = item[0]
                    type = item[1]
                else:
                    own = CN_ENEMY
                    type = item[0]
            x,y,id = map(string.atoi,mm.group('sectorX', 'sectorY',
                                              'shipId'))
            owner = empDb.megaDB['countries'].resolveName(
                own, 'SHIPS', (id,))
            empDb.megaDB['SHIPS'].updates([
                {'id': id, 'type': type,
                 'x': x, 'y': y, 'owner':owner}])
            self.Map = []
            return
        mm = self.sonar_unknown_sub_info.match(msg)
        if mm:
            own = CN_ENEMY
            if mm.group('shipId'):
                x,y,id = map(string.atoi,mm.group('sectorX', 'sectorY',
                                                  'shipId'))
                empDb.megaDB['SHIPS'].updates([
                    {'id': id, 'type': 'sb',
                     'x': x, 'y': y, 'owner':own}])
            self.Map = []
            return
        if self.num is not None:
            # In a pre-established radar
            self.Map.append(msg)
            if len(self.Map) == self.num:
                parseStarMap(self.Map, self.coord, 'radar')
                del self.coord
                self.Map = []
                self.num = None
            if string.find(msg, '0') > -1 :
                s = ""
                while len(s) < len(msg) :
                    s = s + " "
                while len(self.Map) < (self.num - 1) / 2 + 1:
                    self.Map.insert(0, s)
            return
        # Check for start of radar
        mm = self.start_radar.match(msg)
        if mm:
            self.coord = map(string.atoi, mm.group('sectorX', 'sectorY'))
            self.num = string.atoi(mm.group('dist'))*2+1
            self.Map = []
            return
        # Check for view
        mm = self.view_info.match(msg)
        if mm:
            lst = {}
            composePreamble(lst, self.view_stats, mm.group('viewStats'),
                            {'oil':'ocontent','fert':'fert'})
            x, y, eff = map(string.atoi,
                            mm.group('sectorX', 'sectorY', 'eff'))
            lst.update({'des': sectorNameConvert[mm.group('sectorName')],
                        'eff': eff, 'owner': CN_OWNED, 'x': x, 'y': y})
            empDb.megaDB['SECTOR'].updates([lst])
            self.Map = []
            return
        # Check for lookout
        if getLookInfo(msg, self.unitType):
            self.Map = []
            return
        # Check for unit stop
        mm = self.unit_stop.match(msg)
        if mm:
            if mm.group('shipId'):
                # A ship
                x, y, id = map(string.atoi,
                               mm.group('sectorX', 'sectorY', 'shipId'))
                empDb.megaDB['SHIPS'].updates(
                    [{'id': id, 'type':mm.group('shipType'),
                      'owner':CN_OWNED, 'x': x, 'y': y}])
            else:
                # A land unit
                x, y, id = map(string.atoi,
                               mm.group('sectorX', 'sectorY', 'landId'))
                empDb.megaDB['LAND UNITS'].updates(
                    [{'id': id, 'type':mm.group('landType'),
                      'owner':CN_OWNED, 'x': x, 'y': y}])
            self.Map = []
            return
        # Add to generic map prompt queue
        self.Map.append(msg)
    ss_mob = r"-?\d+\.\d"
    s_minMob = r"(?P<minMob>"+ss_mob+")"
    s_maxMob = r"(?P<maxMob>"+ss_mob+")"
    nav_prompt = re.compile(r"^<"+s_minMob+":"+s_maxMob+": "+s_sector+"> $")
    def flush(self, msg, hdl):
        self.out.flush(msg, hdl)
        mm = self.nav_prompt.match(msg)
        if mm:
            self.coord = map(string.atoi, mm.group('sectorX', 'sectorY'))
            if len(self.Map) == 3:
                parseStarMap(self.Map, self.coord, 'radar')

        if self.num is not None :
            s = ""
            while len(s) < len(msg) :
                s = s + " "
            while len(self.Map) < self.num :
                self.Map.append(s)
            parseStarMap(self.Map, self.coord, 'radar')
        self.Map = []
        self.num = None

    def End(self, cmd):
        self.out.End(cmd)
        if self.num is not None :
            i = -1
            for msg in self.Map[:]:
                i = i + 1
                if string.find(msg, "0") > -1 :
                    while i < (self.num - 1) / 2 :
                        self.Map.insert(0, "")
                        i = i + 1
            while len(self.Map) < self.num :
                self.Map.append("")
            parseStarMap(self.Map, self.coord, 'radar')
        try :
            del self.coord
        except AttributeError:
            """we do nothing here"""
        self.Map = []
        self.num = None

class ParseSimpleTime(empQueue.baseDisp):
    """Simple class that will extract the time from the first line."""
    def Begin(self, cmd):
        self.out.Begin(cmd)
        self.done = 0
    def data(self, msg):
        if not self.done:
            mm = curtimeFormat.match(msg)
            if mm:
                empDb.megaDB['time'].noteTime(mm)
            self.done = 1
        self.out.data(msg)

class ParseSpy(empQueue.baseDisp):
    """Handle spy reports."""

    # Translations from header names to dump names:
    headerConvert = {
        'sect': sectToCoords, 'de': newdesToDes,
        'own': convertOwner, 'old\nown': convertOldOwner,
        'sct\neff': 'eff', 'rd\neff': 'road',
        'rl\neff': 'rail', 'def\neff': 'defense',
        'civ': 'civ', 'mil': 'mil', 'shl': 'shell', 'gun': 'gun',
        'pet': 'pet', 'food': 'food', 'bars': 'bar',
        #    'lnd': xxx, 'pln': xxx,
        }

    def __init__(self, disp):
        empQueue.baseDisp.__init__(self, disp)
        self.pos = 0
        self.changes = []

    s_unitStats = r"(?P<unitStats>\S+ \d+(?:, \S+ \d+)*)"
    unitInfo = re.compile("^(?:Allied|Enemy|Neutral) \("+s_counName
                          +"\) unit in "+s_sector+":  "+s_landIdent
                          +"(?: \("+s_unitStats+"\))?$")
    unitStats = re.compile(
        r"(?P<comd>\S+) (?P<val>\d+)(?:, (?P<next>.*))?")
    def data(self, msg):
        self.out.data(msg)
        if self.pos == 0:
            if msg == 'SPY report':
                self.pos = 1
        elif self.pos == 1:
            # Note date
            mm = curtimeFormat.match(msg)
            if mm:
                empDb.megaDB['time'].noteTime(mm)
                self.pos = 2
        elif self.pos == 2:
            # first header
            self.hdr = msg
            self.pos = 3
        elif self.pos == 3:
            # second line of header
            self.hdr = composeHeader(self.headerConvert, self.hdr, msg)
            self.pos = 4
        elif self.pos == 4:
            # Meat of message
            mt = self.unitInfo.match(msg)
            if mt:
                lst = {}
                composePreamble(lst, self.unitStats, mt.group('unitStats'))
                lst['x'], lst['y'], id = map(
                    string.atoi,
                    mt.group('sectorX', 'sectorY', 'landId'))
                lst['id'] = id
                lst['type'] = mt.group('landType')
                lst['owner'] = empDb.megaDB['countries'].resolveName(
                    mt.group('counName'), 'LAND UNITS', (id,))
                empDb.megaDB['LAND UNITS'].updates([lst])
            else:
                info = composeBody(self.hdr, msg)
                if info:
                    self.changes.append(info)
    def End(self, cmd):
        self.out.End(cmd)
        empDb.megaDB['SECTOR'].updates(self.changes)

class ParseAttack(empQueue.baseDisp):
    # 8,0 is a 100% AUJ highway with approximately 150 military.
    # 21 of your troops now occupy -10,12
    s_mil = "(?P<mil>\d+)"
    attackInfo = re.compile("^"+s_sector
                            +" is a "+s_eff+" "+s_counName+" "+s_sectorName
                            +r" with approximately "+s_mil+" military\.$")
    sectorTake = re.compile(r"^We have (?:captured|secured a beachhead at) "
                            +s_sector+", sir!$")
    unitMove = re.compile("^"+s_landIdent
                          +" (?:moves in to occupy|now occupies) "
                          +s_sector+"$")
    milMove = re.compile(
        "^"+s_mil+" (?:mil from (?:"+s_shipIdent+"|"+s_sector2
        +") moves into|of your troops now occupy) "+s_sector+"$")
    def data(self, msg):
        self.out.data(msg)
        mm = self.attackInfo.match(msg)
        if mm:
            x, y, eff, mil = map(string.atoi,
                                 mm.group('sectorX', 'sectorY', 'eff', 'mil'))
            empDb.megaDB['SECTOR'].updates([{
                'x': x, 'y': y,
                'owner':empDb.megaDB['countries'].resolveName(
                    mm.group('counName'), 'SECTOR', (x, y)),
                'des':sectorNameConvert[mm.group('sectorName')],
                'eff': eff, 'mil': mil}])
            return
        mm = self.sectorTake.match(msg)
        if mm:
            x, y = map(string.atoi, mm.group('sectorX', 'sectorY'))
            empDb.megaDB['SECTOR'].updates([{
                'x': x, 'y': y, 'owner': CN_OWNED}])
            return
        mm = self.unitMove.match(msg)
        if mm:
            x, y, id = map(string.atoi,
                           mm.group('sectorX', 'sectorY', 'landId'))
            empDb.megaDB['LAND UNITS'].updates([{
                'id': id, 'type':mm.group('landType'),
                'owner':CN_OWNED, 'x': x, 'y': y}])
            return
        mm = self.milMove.match(msg)
        if mm:
            x, y, mil = map(string.atoi,
                            mm.group('sectorX', 'sectorY', 'mil'))
            empDb.megaDB['SECTOR'].updates([{
                'x': x, 'y': y, 'owner':CN_OWNED, 'mil': mil}])

class ParseCoastWatch(empQueue.baseDisp):
    """Handle the coastwatch command."""
##   ptkei-0.21 (#  1) bb   battleship (#12) @ 0,-4
    s_counIdent = s_counName + r" \(#\s*(?P<counId>\d+)\)"
    line = re.compile("^\s*"+s_counIdent+" "+s_shipIdent+" @ "+s_sector)
    def data(self, msg):
        self.out.data(msg)
        mm = self.line.match(msg)
        if mm:
            x, y, id, coun = map(
                string.atoi,
                mm.group('sectorX', 'sectorY', 'shipId', 'counId'))
            empDb.megaDB['SHIPS'].updates([
                {'id': id, 'type':mm.group('shipType'),
                 'x': x, 'y': y,
                 'owner':empDb.megaDB['countries'].resolveNameId(
                     mm.group('counName'), coun)}])

class ParseSate(empQueue.baseDisp):
    def Begin(self, cmd):
        self.out.Begin(cmd)
        self.pos = 0
    # Translations from header names to dump names:
    conversion = (
        ("Satellite sector report", 'SECTOR', 2, {
        'sect': sectToCoords, 'type': 'des',
        'own': convertOwner,
        'sct\neff': 'eff', 'rd\neff': 'road',
        'rl\neff': 'rail', 'def\neff': 'defense',
        'civ': 'civ', 'mil': 'mil', 'shl': 'shell', 'gun': 'gun',
        'iron': 'iron', 'pet': 'pet', 'food': 'food'}),
        ##  ("Satellite ship report", 'SHIPS', 1, {
        ##      'own', convertOwner, 'shp#':'id', 'ship type':
        ##      }),
        ##  ("Satellite unit report", 'LAND UNITS', 1, {
        ##      })
        )

    typeLine = re.compile(r"^Satellite (?P<type>Map|Spy) Report:$")
    rangeLine = re.compile("^"+s_landIdent+" at "+s_sector
                           +" efficiency "+s_eff
                           +", max range (?P<range>\d+)$")
    def data(self, msg):
        self.out.data(msg)
        if self.pos == 0:
            mm = self.typeLine.match(msg)
            if mm:
                type = mm.group('type')
                if type == 'Map':
                    self.type = 'land'
                else:
                    self.type = 'radar'
                self.pos = 1
        elif self.pos == 1:
            mm = self.rangeLine.match(msg)
            if mm:
                self.coord = map(string.atoi, mm.group('sectorX', 'sectorY'))
                self.range = string.atoi(mm.group('range'))*2+1
                self.pos = 2
        elif self.pos == 2:
            if msg == "Satellite radar report":
                self.buf = []
                self.pos = 3
            elif msg[0:14] == "   sect   type":
                self.pos = 4
            elif msg[0:10] == " own  shp#":
                self.pos = 5
            elif msg[0:10] == " own  lnd#":
                self.pos = 6
        elif self.pos == 3:
            self.buf.append(msg)
            if len(self.buf) == self.range:
                parseStarMap(self.buf, self.coord, self.type)
                self.pos = -1
        elif self.pos == 4: # sectors
            item = string.split(string.strip(msg))
            if len(item) == 2:
                self.pos = 2
            else:
                val = sectToCoords(item[0], '')
                val['des'] = item[1]
                val['owner'] = empDb.megaDB['countries'].resolveId(string.atoi(item[2]))
                val['eff'] = string.atoi(item[3])
                val['road'] = string.atoi(item[4])
                val['rail'] = string.atoi(item[5])
                val['defense'] = string.atoi(item[6])
                val['civ'] = string.atoi(item[7])
                val['mil'] = string.atoi(item[8])
                val['shell'] = string.atoi(item[9])
                val['gun'] = string.atoi(item[10])
                val['iron'] = string.atoi(item[11])
                val['pet'] = string.atoi(item[12])
                val['food'] = string.atoi(item[13])
                empDb.megaDB['SECTOR'].updates([val])
        elif self.pos == 5: # ships
            item = string.split(string.strip(msg))
            if len(item) == 2:
                self.pos = 2
            else:
                val = sectToCoords(item[-2], '')
                val['owner'] = empDb.megaDB['countries'].resolveId(string.atoi(item[0]))
                val['id'] = string.atoi(item[1])
                val['type'] = item[2]
                val['eff'] = string.atoi(item[-1][:-1])
                empDb.megaDB['SHIPS'].updates([val])
        elif self.pos == 6: # land units
            item = string.split(string.strip(msg))
            if len(item) == 2:
                self.pos = 2
            else:
                val = sectToCoords(item[-2], '')
                val['owner'] = empDb.megaDB['countries'].resolveId(string.atoi(item[0]))
                val['id'] = string.atoi(item[1])
                val['type'] = item[2]
                val['eff'] = string.atoi(item[-1][:-1])
                empDb.megaDB['LAND UNITS'].updates([val])

class ParseBuild(empQueue.baseDisp):
    """Parse build command."""
    buildItems = re.compile(r"^(?:Bridge span built over|"
                            "(?P<tower>Bridge tower built in)|"
                            +s_shipOrLand+" built in sector) "
                            +s_sector+"$")
    def data(self, msg):
        self.out.data(msg)
        mm = self.buildItems.match(msg)
        if mm:
            if mm.group('shipId'):
                # A ship
                x, y, id = map(
                    string.atoi,
                    mm.group('sectorX', 'sectorY', 'shipId'))
                empDb.megaDB['SHIPS'].updates(
                    [{'id': id, 'type':mm.group('shipType'),
                      'owner':CN_OWNED, 'x': x, 'y': y}])
            elif mm.group('landId'):
                # Argh, can't distinguish between land units and planes..
                pass
##              empDb.megaDB['LAND UNITS'].updates([{'id':mm.group('landId'),
##                                             'type':mm.group('landType'),
##                                             'owner':CN_OWNED,
##                                             'x':mm.group('sectorX'),
##                                             'y':mm.group('sectorY')}])
            else:
                # A bridge
                if mm.group('tower'):
                    des = '@'
                else:
                    des = '='
                x, y = map(string.atoi, mm.group('sectorX', 'sectorY'))
                empDb.megaDB['SECTOR'].updates(
                    [{'owner':0, 'x': x, 'y': y, 'des':des}])

class ParseCapital(empQueue.baseDisp):
    """Parse output from capital command."""
    moveCapital = re.compile(r"^Capital now at "+s_sector+"\.$|"
                             +"^"+s_sector2+" is already your capital\.$")
    def data(self, msg):
        self.out.data(msg)
        mm = self.moveCapital.match(msg)
        if mm:
            if mm.group('sectorX') is not None:
                loc = tuple(map(string.atoi, mm.group('sectorX', 'sectorY')))
            else:
                loc = tuple(map(string.atoi, mm.group('sector2X', 'sector2Y')))
            checkUpdated('nation', 'capital', loc)

class ParseReport(empQueue.baseDisp):
    """Parse output from report command."""
    def data(self, msg):
        mm = curtimeFormat.match(msg)
        if mm:
            empDb.megaDB['time'].noteTime(mm)
            return
        self.out.data(msg)
        line = string.split(msg)
        try:
            id = string.atoi(line[0])
        except ValueError:
            pass
        else:
            empDb.megaDB['countries'].resolveNameId(line[1], id)

class ParseRelations(empQueue.baseDisp):
    """Parse output from relations."""
    s_yourRelation = r"(?P<your>\S+)"
    s_theirRelation = r"(?P<their>\S+)"
    header = re.compile("^\s*"+s_counName
                        +" Diplomatic Relations Report\t"+s_time+"$")
    line = re.compile("^\s*"+s_counId+"\) "+s_counName+"\s+"
                      +s_yourRelation+"\s+"+s_theirRelation+"$")
    def data(self, msg):
        self.out.data(msg)
        mm = self.line.match(msg)
        if mm:
            empDb.megaDB['countries'].resolveNameId(mm.group('counName'),
                string.atoi(mm.group('counId')))

class ParseRealm(empQueue.baseDisp):
    """Parse output from realm command."""
    s_range = (r"(?P<minX>"+ss_sect+"):(?P<maxX>"+ss_sect
               +"),(?P<minY>"+ss_sect+"):(?P<maxY>"+ss_sect+")")
    s_realm = r"#(?P<realm>\d+)"
    rm = re.compile(r"^Realm " + s_realm + " is " + s_range + "$")
    def data(self, msg):
        self.out.data(msg)
        mtch = self.rm.match(msg)
        if mtch:
            vals = tuple(map(string.atoi, mtch.groups()))
            realm = vals[0]
            vals = vals[1:]
            checkUpdated('realm', realm, vals)

class ParseTele(empQueue.baseDisp):
    """Parse outgoing telegrams for future reference."""
    def Begin(self, cmd):
        self.out.Begin(cmd)
        self.to = None
        self.buf = ""
        self.pos = None
        self.max = None
    init = re.compile("^Enter telegram for "+s_counName+"$")
    def data(self, msg):
        self.out.data(msg)
        if self.to is None:
            mm = self.init.match(msg)
            if mm:
                self.to = mm.group('counName')
                return
        if msg == "Telegram aborted":
            self.pos = None
            return
    prompt = re.compile(r"^\s*(?P<left>\d+) left: $")
    def flush(self, msg, hdl):
        try:
            mm = self.prompt.match(msg)
            if mm:
                left = string.atoi(mm.group('left'))
                if self.max is None:
                    self.max = left
                self.pos = self.max - left
            else:
                self.pos = None
        finally:
            self.out.flush(msg, hdl)
    def Answer(self, msg):
        self.out.Answer(msg)
        if msg is not None and self.pos is not None:
            self.buf = self.buf[:self.pos] + msg + '\n'
    def End(self, cmd):
        self.out.End(cmd)
        if self.to is not None and self.pos is not None:
            msg = string.split(self.buf, '\n')
            del msg[-1]
            msg[:0] = ["> Telegram to "+self.to]
            if msg[-1] == '.':
                del msg[-1]
            empDb.megaDB['telegrams']['list'].append(msg)
            try:
                empDb.updateDB['telegrams']['list'].append(msg)
            except KeyError:
                empDb.updateDB['telegrams']['list'] = [msg]

class ParseRead(empQueue.baseDisp):
    """Parse and store telegrams and announcements.

    This parser is responsible for making a copy of all correspondence that
    is received.  It then stores these telegrams and annoucements in the
    database.
    """
    def Begin(self, cmd):
        self.out.Begin(cmd)

        # Storage for the current telegram
        self.stor = None
        # List of all telegrams received that have not been processed.
        self.tlist = []

        c = string.lstrip(cmd)
        if c[:3] == 'wir':
            self.dbname = 'announcements'
        else:
            self.dbname = 'telegrams'

        # The latest telegram header.
        self.last = empDb.megaDB[self.dbname]['last']

    headerInfo = re.compile(
        r"^> (?P<type>.*?)(?: from "
        +s_counName+", "+s_counId+")?  dated "+s_time+"$")
    def data(self, msg):
        self.out.data(msg)
        if msg[:1] == '>':
            # A message header
            mm = self.headerInfo.match(msg)
            if mm:
                counId = mm.group('counId')
                if counId is not None:
                    counId = empDb.megaDB['countries'].resolveNameId(
                        mm.group('counName'), string.atoi(counId))
                msg = (mm.group('type'), counId,
                       empDb.megaDB['time'].translateTime(mm))
            # Check if this message is a duplicate.
            if msg == self.last:
                self.stor = None
                self.tlist = []
                return
            # Remove the annoying empty line at the end of each message.
            if self.stor is not None and self.stor[-1] == '':
                del self.stor[-1]
            self.stor = [msg]
            self.tlist.append(self.stor)
        elif self.stor is not None:
            # message body
            self.stor.append(msg)
    def process(self):
        """Merge the internal list of telegrams with the main database."""
        if not self.tlist:
            return
        db = empDb.megaDB[self.dbname]
        udb = empDb.updateDB[self.dbname]
        db['last'] = udb['last'] = self.tlist[-1][0]
        lst = db['list']
        lst[len(lst):] = self.tlist
        try:
            lst = udb['list']
            lst[len(lst):] = self.tlist
        except KeyError:
            udb['list'] = self.tlist
    def End(self, cmd):
        self.out.End(cmd)
        # Remove the annoying empty line at the end of each message.
        if self.stor is not None and self.stor[-1] == "":
            del self.stor[-1]
        self.process()
    def flush(self, msg, hdl):
        self.out.flush(msg, hdl)
        self.process()
        self.stor = None
        self.tlist = []

ss_flt = r"\d+(?:\.\d+)?"

class ParseVersion(empQueue.baseDisp):
    """Parse the version info."""
    def Begin(self, cmd):
        self.out.Begin(cmd)
        self.pos = 0
    versionVars = re.compile(
        r"^World size is (?P<maxX>\d+) by (?P<maxY>\d+)\.$|"
        r"^There can be up to (?P<coun>\d+) countries\.$|"

        # An Empire time unit is 75 seconds long.
        r"^An Empire time unit is (?P<etu>\d+) seconds long\.$|"
        # The current time is Sun Sep 6 18:15:49.
        r"^The current time is "+s_time+r"\.$|"
        # An update consists of 48 empire time units.
        r"^An update consists of (?P<updt>\d+) empire time units\.$|"
        # Each country is allowed to be logged in 1440 minutes a day.
        r"^Each country is allowed to be logged in "
        r"(?P<minutes>\d+) minutes a day\.$|"
        # It takes 8.33 civilians to produce a BTU in one time unit.
        r"^It takes (?P<btu>"+ss_flt
        +r") civilians to produce a BTU in one time unit\.$|"

        # A non-aggi, 100 fertility sector can grow 0.12 food per etu.
        r"^A non-aggi, 100 fertility sector can grow (?P<grow>"
        +ss_flt+r") food per etu\.$|"
        #  1000 civilians will harvest 1.3 food per etu.
        r"^1000 civilians will harvest (?P<harv>"+ss_flt
        +r") food per etu\.$|"
        #  1000 civilians will give birth to 5.0 babies per etu.
        r"^1000 civilians will give birth to (?P<birth>"+ss_flt
        +r") babies per etu\.$|"
        #  1000 uncompensated workers will give birth to 2.5 babies.
        r"^1000 uncompensated workers will give birth to (?P<ubirth>"+ss_flt
        +r") babies\.$|"
        #  In one time unit, 1000 people eat 0.5 units of food.
        r"^In one time unit, 1000 people eat (?P<eat>"+ss_flt
        +r") units of food\.$|"
        #  1000 babies eat 6.0 units of food becoming adults.
        r"^1000 babies eat (?P<baby>"+ss_flt
        +r") units of food becoming adults\.$|"

        # Banks pay $250.00 in interest per 1000 gold bars per etu.
        r"^Banks pay \$(?P<interest>"+ss_flt
        +r") in interest per 1000 gold bars per etu\.$|"
        # 1000 civilians generate $8.33, uncompensated workers $1.78 each time unit.
        r"^1000 civilians generate \$(?P<tax>"+ss_flt
        +r"), uncompensated workers \$(?P<utax>"+ss_flt
        +r") each time unit\.$|"
        # 1000 active military cost $83.33, reserves cost $8.33.
        r"^1000 active military cost \$(?P<milcost>"+ss_flt
        +r"), reserves cost \$(?P<rescost>"+ss_flt+r")\.$|"
        # Happiness p.e. requires 1 happy stroller per 5000 civ.
        r"^Happiness p\.e\. requires 1 happy stroller per "
        r"(?P<stroll>\d+) civ\.$|"
        # Education p.e. requires 1 class of graduates per 4000 civ.
        r"^Education p\.e\. requires 1 class of graduates per "
        r"(?P<grad>\d+) civ\.$|"
        # Happiness is averaged over 48 time units.
        r"^Happiness is averaged over (?P<havg>\d+) time units\.$|"
        # Education is averaged over 192 time units.
        r"^Education is averaged over (?P<eavg>\d+) time units\.$|"
        # The technology/research boost you get from the world is 50.00%.
        r"^The technology/research boost you get from the world is "
        r"(?P<boost>"+ss_flt+")%\.$|"
        # Nation levels (tech etc.) decline 1% every 96 time units.
        r"^Nation levels \(tech etc\.\) decline 1% every "
        r"(?P<decline>\d+) time units\.$|"
        # Tech Buildup is limited to logarithmic growth (base 2.00) after 1.00.
        r"^Tech Buildup is limited to logarithmic growth \(base (?P<tbase>"
        +ss_flt+r")\) after (?P<tafter>"+ss_flt+r")\.$|"

        # Maximum mobility              127     127     127     127
        r"^Maximum mobility\s+(?P<Omax>.*)$|"
        # Max mob gain per update               48      72      48      48
        r"^Max mob gain per update\s+(?P<Omob>.*)$|"
        # Max eff gain per update               --      100     96      96
        r"^Max eff gain per update\s+(?P<Oeff>.*)$|"

        # Fire ranges are scaled by 1.00
        r"^Fire ranges are scaled by (?P<fire>"+ss_flt+r")$|"

        r"^(?P<goOptions>)Options enabled in this game:$|"
        r"^(?P<goNoOptions>)Options disabled in this game:$"
        )
    def data(self, msg):
        self.out.data(msg)
        if self.pos > 0:
            if msg == "":
                name = {1:'enabledOptions', 2:'disabledOptions'}[self.pos]
                self.opts.sort()
                checkUpdated('version', name, self.opts)
                self.pos = 0
            self.opts[:0] = filter(
                None, map(string.strip, string.split(msg, ',')))
            return
        mm = self.versionVars.match(msg)
        if mm is None:
            return
        (maxX, maxY, coun,
         etu, date, updt, minutes, btu,
         grow, harv, birth, ubirth, eat, baby,
         interest, tax, utax, milcost, rescost, stroll,
         grad, havg, eavg, boost, decline, tbase, tafter,
         Omax, Omob, Oeff, fire, goOptions, goNoOptions) = mm.group(
             'maxX', 'maxY', 'coun',
             'etu', 'date', 'updt', 'minutes', 'btu',
             'grow', 'harv', 'birth', 'ubirth', 'eat', 'baby',
             'interest', 'tax', 'utax', 'milcost', 'rescost', 'stroll',
             'grad', 'havg', 'eavg', 'boost', 'decline', 'tbase', 'tafter',
             'Omax', 'Omob', 'Oeff', 'fire', 'goOptions', 'goNoOptions')
        if maxX is not None:
            checkUpdated('version', 'worldsize',
                         (string.atoi(maxX), string.atoi(maxY)))
        elif coun is not None:
            checkUpdated('version', 'maxCountries', string.atoi(coun))
        elif etu is not None:
            checkUpdated('version', 'ETUSeconds', string.atoi(etu))
        elif date is not None:
            empDb.megaDB['time'].noteTime(mm)
        elif updt is not None:
            checkUpdated('version', 'updateETUs', string.atoi(updt))
        elif minutes is not None:
            checkUpdated('version', 'minutesOnline', string.atoi(minutes))
        elif btu is not None:
            checkUpdated('version', 'BTURate', string.atof(btu))
        elif grow is not None:
            checkUpdated('version', 'growRate', string.atof(grow))
        elif harv is not None:
            checkUpdated('version', 'harvestRate', string.atof(harv)/1000.0)
        elif birth is not None:
            checkUpdated('version', 'birthRate', string.atof(birth)/1000.0)
        elif ubirth is not None:
            checkUpdated('version', 'UBirthRate', string.atof(ubirth)/1000.0)
        elif eat is not None:
            checkUpdated('version', 'eatRate', string.atof(eat)/1000.0)
        elif baby is not None:
            checkUpdated('version', 'BEatRate', string.atof(baby)/1000.0)
        elif interest is not None:
            checkUpdated('version', 'barInterest',
                         string.atof(interest)/1000.0)
        elif tax is not None:
            checkUpdated('version', 'civTax', string.atof(tax)/1000.0)
        elif utax is not None:
            checkUpdated('version', 'UWTax', string.atof(utax)/1000.0)
        elif milcost is not None:
            checkUpdated('version', 'milCost', string.atof(milcost)/1000.0)
        elif rescost is not None:
            checkUpdated('version', 'reserveCost', string.atof(rescost)/1000.0)
        elif stroll is not None:
            checkUpdated('version', 'happyRatio', string.atoi(stroll))
        elif grad is not None:
            checkUpdated('version', 'educationRatio', string.atoi(grad))
        elif havg is not None:
            checkUpdated('version', 'happyAverage', string.atoi(havg))
        elif eavg is not None:
            checkUpdated('version', 'educationAverage', string.atoi(eavg))
        elif boost is not None:
            checkUpdated('version', 'techBoost', string.atof(boost))
        elif decline is not None:
            checkUpdated('version', 'levelDecline', string.atoi(decline))
        elif tbase is not None:
            checkUpdated('version', 'techLog', string.atof(tbase))
        elif tafter is not None:
            checkUpdated('version', 'techBase', string.atof(tafter))
        elif Omax is not None:
            val = []
            for i in string.split(Omax):
                if i == '--': val.append(99999)
                else: val.append(string.atoi(i))
            checkUpdated('version', 'objectMax', val)
        elif Omob is not None:
            val = []
            for i in string.split(Omob):
                if i == '--': val.append(99999)
                else: val.append(string.atoi(i))
            checkUpdated('version', 'objectMob', val)
        elif Oeff is not None:
            val = []
            for i in string.split(Oeff):
                if i == '--': val.append(99999)
                else: val.append(string.atoi(i))
            checkUpdated('version', 'objectEff', val)
        elif fire is not None:
            checkUpdated('version', 'fireRange', string.atof(fire))
        elif goOptions is not None:
            self.opts = []
            self.pos = 1
        elif goNoOptions is not None:
            self.opts = []
            self.pos = 2

class ParseNation(empQueue.baseDisp):
    """Parse nation command."""
    nationVars = re.compile(
        # (#6) TestPtkei Nation Report  Thu Nov 12 13:27:43 1998
        "^"+s_counId+" "+s_counName+" Nation Report\t"+s_time+"$|"
        # Nation status is ACTIVE     Bureaucratic Time Units: 640
        r"^Nation status is (?P<status>.*?)\s+|"
        # 100% eff capital at 0,-2 has 805 civilians & 5 military
        +s_eff+r" eff (?:mountain )?capital at "+s_sector
        +r" has (?P<cciv>\d+) civilians? & (?P<cmil>\d+) military$|"
        "^No capital\. \(was at "+s_sector2+"\)$|"
        #  The treasury has $35703.00     Military reserves: 2769
        r"^ The treasury has \$(?P<bud>"+ss_flt
        +r")\s+Military reserves: (?P<resv>\d+)$|"
        # Education.......... 78.35       Happiness.......  0.00
        r"^Education\.*\s*(?P<edu>"+ss_flt
        +r")\s+Happiness\.*\s*(?P<hap>"+ss_flt+")$|"
        # Technology.........251.80       Research........  0.00
        r"^Technology\.*\s*(?P<tech>"+ss_flt
        +r")\s*Research\.*\s*(?P<res>"+ss_flt+")$|"
        # Technology factor : 66.80%     Plague factor :   0.00%
        r"^Technology factor :\s*(?P<tfact>"+ss_flt
        +r")%\s+Plague factor :\s*(?P<pfact>"+ss_flt+")%$|"
        # Max population : 999
        r"^Max population :\s*(?P<pop>\d+)$|"
        # Max safe population for civs/uws: 805/891
        r"^Max safe population for civs/uws: (?P<civs>\d+)/(?P<uws>\d+)$|"
        # Happiness needed is 31.410360
        r"^Happiness needed is (?P<nhap>"+ss_flt+")$")

    def data(self, msg):
        self.out.data(msg)
        mm = self.nationVars.match(msg)
        if mm is None:
            return
        (counId, counName, date, status, eff, sectorX,
         sectorY, sector2X, sector2Y, cciv, cmil, bud,
         resv, edu, hap, tech, res, tfact, pfact,
         pop, civs, uws, nhap) = mm.group(
             'counId', 'counName', 'date', 'status', 'eff', 'sectorX',
             'sectorY', 'sector2X', 'sector2Y', 'cciv', 'cmil', 'bud',
             'resv', 'edu', 'hap', 'tech', 'res', 'tfact', 'pfact',
             'pop', 'civs', 'uws', 'nhap')
        if counId is not None:
            empDb.megaDB['time'].noteTime(mm)
            empDb.megaDB['countries'].resolvePlayer(
                counName, string.atoi(counId))
        elif status is not None:
            checkUpdated('nation', 'status', status)
        elif eff is not None:
            checkUpdated('nation', 'capital',
                         (string.atoi(sectorX), string.atoi(sectorY)))
            empDb.megaDB['SECTOR'].updates([{
                'x':string.atoi(sectorX), 'y':string.atoi(sectorY),
                'eff': string.atoi(eff), 'mil':string.atoi(cmil),
                'civ': string.atoi(cciv)}])
        elif sector2X is not None:
            checkUpdated('nation', 'capital', ())
        elif bud is not None:
            checkUpdated('nation', 'budget', string.atof(bud))
            checkUpdated('nation', 'reserves', string.atoi(resv))
        elif edu is not None:
            checkUpdated('nation', 'education', string.atof(edu))
            checkUpdated('nation', 'happiness', string.atof(hap))
        elif tech is not None:
            checkUpdated('nation', 'technology', string.atof(tech))
            checkUpdated('nation', 'research', string.atof(res))
        elif tfact is not None:
            checkUpdated('nation', 'techFactor', string.atof(tfact))
            checkUpdated('nation', 'plagueFactor', string.atof(pfact))
        elif pop is not None:
            checkUpdated('nation', 'maxPopulation', string.atoi(pop))
        elif civs is not None:
            checkUpdated('nation', 'maxCiv', string.atoi(civs))
            checkUpdated('nation', 'maxUW', string.atoi(uws))
        elif nhap is not None:
            checkUpdated('nation', 'happyNeeded', string.atof(nhap))

class ParseUpdate(empQueue.baseDisp):
    """Parser for the update command.

    Grab info that will allow the client to calculate when the next update
    will occur.
    """
## The next update is at Sun Sep  6 20:00:00.
## The current time is   Sun Sep  6 19:07:38.
    getTimes = re.compile(
        r"^(?:(?P<next>)The next update is at|The current time is  ) "
        +s_time+r"\.$")
    def data(self, msg):
        self.out.data(msg)
        mm = self.getTimes.match(msg)
        if mm is None:
            return
        if mm.group('next') is not None:
            empDb.megaDB['time'].noteNextUpdate(mm)
        else:
            empDb.megaDB['time'].noteTime(mm)

class ParseSpyPlane(empQueue.baseDisp):
    """Handle spy plane reports."""

    # Translations from header names to dump names:
    headerConvert = {
        'sect': sectToCoords, 'type': newdesToDes,
        'own': convertOwner, 'sct\neff': 'eff', 'rd\neff': 'road',
        'rl\neff': 'rail', 'def\neff': 'defense',
        'civ': 'civ', 'mil': 'mil', 'shl': 'shell', 'gun': 'gun',
        'iron': 'iron', 'pet': 'pet', 'food': 'food',
        }

    def __init__(self, disp):
        empQueue.baseDisp.__init__(self, disp)
        self.mode = 0
        self.sect_changes = []
        self.ship_changes = []
        self.land_changes = []

    seaSect = re.compile(r"^flying over sea at "+s_sector)
    shipHeader = re.compile(r"^\s*own\s+shp\#")
    landHeader = re.compile(r"^\s*own\s+lnd\#")
    uStats = re.compile(r"^\s*(?P<own>\d+)\s+(?P<id>\d+)\s+(?P<type>\S+)\s+"+
                        r"\S+\s+"+s_sector+"\s+"+s_eff)
    def data(self, msg):
        self.out.data(msg)
        if self.mode == 0:
            if msg == 'SPY Plane report' or msg == 'Reconnaissance report':
                self.mode = 1
        elif self.mode == 1:
            # Note date
            mm = curtimeFormat.match(msg)
            if mm:
                empDb.megaDB['time'].noteTime(mm)
                self.mode = 2
        elif self.mode == 2:
            # first header
            self.hdr = msg
            self.mode = 3
        elif self.mode == 3:
            # second line of header
            self.hdr = composeHeader(self.headerConvert, self.hdr, msg)
            self.mode = 4
        elif self.mode == 4:
            if self.shipHeader.match(msg):
                self.mode = 5
            elif self.landHeader.match(msg):
                self.mode = 6
            else:
                info = self.seaSect.match(msg)
                if info:
                    x, y = map(string.atoi, info.group('sectorX', 'sectorY'))
                    info = {'owner': 0, 'des': '.', 'x': x, 'y': y}
                    self.sect_changes.append(info)
# for some reason spy planes can't see ships at sea. is this a server bug?
                else:
                   info = composeBody(self.hdr, msg)
                   if info:
                       self.sect_changes.append(info)
                   else:
                       # When performing a recon with a non spy capable plane
                       #lfm
                       getLookInfo(msg)
                                                      
# the other case that could come up is flak a message of the form:
# "firing 9 flak guns in 26,2..."
# I'm not sure what if any useful info we can derive from this other than the
# recon report that said there weren't any guns in that sector was wrong.
        elif self.mode == 5:
            info = self.uStats.match(msg)
            if info:
                id, x, y, owner, eff = map(string.atoi,
                                           info.group('id', 'sectorX',
                                                      'sectorY', 'own', 'eff'))
                if owner == empDb.megaDB['countries'].player:
                    owner = CN_OWNED
                ship_info = {'id': id, 'type':info.group('type'), 'x': x,
                             'y': y, 'owner':owner}
                self.ship_changes.append(ship_info)
            else:
# assume this is the blank line that marks the end of the sub section.
                self.mode = 4
        elif self.mode == 6:
            info = self.uStats.match(msg)
            if info:
                id, x, y, owner, eff = map(string.atoi,
                                           info.group('id', 'sectorX',
                                                      'sectorY', 'own', 'eff'))
                if owner == empDb.megaDB['countries'].player:
                    owner = CN_OWNED
                land_info = {'id': id, 'type':info.group('type'), 'x': x,
                             'y': y, 'owner':owner}
                self.land_changes.append(land_info)
            else:
# assume this is the blank line that marks the end of the sub section.
                self.mode = 4

    def End(self, cmd):
        self.out.End(cmd)
        empDb.megaDB['SHIPS'].updates(self.ship_changes)
        empDb.megaDB['LAND UNITS'].updates(self.land_changes)
        empDb.megaDB['SECTOR'].updates(self.sect_changes)

class ParseBomb(empQueue.baseDisp):
    """Handle the bomb command to find sunk ships."""
    ##   ms   minesweeper (#223) sunk!
    line = re.compile("^\s*"+s_shipIdent+" sunk!")
    def data(self, msg):
        self.out.data(msg)
        mm = self.line.match(msg)
        if mm:
            id = string.atoi(mm.group('shipId'))
            empDb.megaDB['SHIPS'].updates([
                {'id': id, 'owner': CN_UNOWNED}])

class ParseFire(empQueue.baseDisp):
    """Handle the fire command to find sunk ships."""
    ##   ms   minesweeper (#223) sunk!
    line = re.compile("^\s*"+s_shipIdent+" sunk!")
    def data(self, msg):
        self.out.data(msg)
        mm = self.line.match(msg)
        if mm:
            id = string.atoi(mm.group('shipId'))
            empDb.megaDB['SHIPS'].updates([
                {'id': id, 'owner': CN_UNOWNED}])

class ParseTorpedo(empQueue.baseDisp):
    """Handle the torpedo command to find sunk ships."""
    ## ms   minesweeper (#223) sunk!
    line = re.compile("^\s*"+s_shipIdent+" sunk!")
    def data(self, msg):
        self.out.data(msg)
        mm = self.line.match(msg)
        if mm:
            id = string.atoi(mm.group('shipId'))
            empDb.megaDB['SHIPS'].updates([
                {'id': id, 'owner': CN_UNOWNED}])

class ParseShow(empQueue.baseDisp):
    def Begin(self,cmd):
        self.out.Begin(cmd)
        self.what = ''
    def data(self,msg):
        self.out.data(msg)
        if string.find(msg, 'cost to des') > -1:
            self.what = 'sebu'
            return
        if string.find(msg, 'mcost') > -1 :
            self.what = 'sest'
            return
        if string.find(msg, 'use1 use2 use3') > -1:
            self.what = 'seca'
            return
        if string.find(msg, 'lcm hcm crew') > -1:
            self.what = 'plbu'
            return
        if string.find(msg, 'lcm hcm avail') > -1:
            self.what = 'shbu'
            return
        if string.find(msg, 'lcm hcm guns') > -1:
            self.what = 'labu'
            return
        if self.what == 'sebu':
            if len(msg) < 2 or msg[0] == ' ' or msg[1] != ' ':
                return
            item = string.split(msg)
            empDb.megaDB['sectortype'][item[0]]['cost_to_des'] =  string.atoi(item[1])
            empDb.megaDB['sectortype'][item[0]]['cost_eff'] =  string.atoi(item[2])
            empDb.megaDB['sectortype'][item[0]]['lcm_eff'] =  string.atoi(item[3])
            empDb.megaDB['sectortype'][item[0]]['hcm_eff'] =  string.atoi(item[4])
            return
        if self.what == 'sest':
            global sectorDesignationConvert, sectorNameConvert, s_sectorName 
            item = string.split(msg)
            type = item[0]
            item[0:1] = []
            if empDb.megaDB['sectortype'].has_key(type) and \
               sectorDesignationConvert.has_key(type) :
                return
            mcost = item[-9]
            [ mcost, maxoff, maxdef, pack_mil, pack_uw, pack_civ,
              pack_bar, pack_other, maxpop ] = item[-9:]
            item[-9:] = []
            name = item[0]
            for x in item[1:] :
                name = name + " " + x
            empDb.megaDB['sectortype'][type] = {
                'mcost': string.atof(mcost),
                'name': name,
                'pack_mil': string.atoi(pack_mil),
                'pack_uw': string.atoi(pack_uw),
                'pack_civ': string.atoi(pack_civ),
                'pack_bar': string.atoi(pack_bar),
                'pack_other': string.atoi(pack_other),
                'maxpop': string.atoi(maxpop) }
            if not sectorDesignationConvert.has_key(type) \
               or sectorDesignationConvert[type] != name :
                sectorDesignationConvert[type] = name
                sectorNameConvert = {}
                map(operator.setitem,
                    (sectorNameConvert,) * len(sectorDesignationConvert),
                    sectorDesignationConvert.values(),
                    sectorDesignationConvert.keys())
                # Create a regular expression that accepts full sector names.
                s_sectorName = (r"(?P<sectorName>"+
                                string.join(sectorDesignationConvert.values(), '|')+")")
                ParseUnits.s_shipOrSector = ("(?:"+s_shipIdent+"|"
                      +s_sectorName+" "+s_eff+" efficient"+ParseUnits.s_sectorStats+")")
                ParseUnits.view_info = re.compile(r"^(?:\[(?P<viewStats>.*?)\] )?"+s_shipIdent+" @ "
                           +s_sector+" "+s_eff+" "+s_sectorName+"$")
                ParseAttack.attackInfo = re.compile("^"+s_sector
                            +" is a "+s_eff+" "+s_counName+" "+s_sectorName
                            +r" with approximately "+ParseAttack.s_mil+" military\.$")
                getLookInfo.look_info = re.compile(r"^(?:Your|"+s_counIdent+") "+ParseUnits.s_shipOrSector
                                                   +" @ "+s_sector+"$")
            return
        if self.what == 'seca':
            if len(msg) < 2 or msg[0] == ' ' or msg[1] != ' ':
                return

            item = string.split(msg)

            if string.digits.find(item[-1]) > -1:
                comout = ''
            else:
                comout = item[-1]
                del item[-1:]

            minlevel, lag, eff, cost, dep = map(string.atoi, item[-5:])
            del item[-5:]

            des = item[0]
            del item[0]

            i = 0
            while i < len(item):
                try:
                    a = string.atoi(item[i])
                    break
                except:
                    i = i + 1
            del item[:i]

            level = None
            use = []

            if len(item) > 0:
                i = 0
                while i < len(item):
                    try:
                        amount = string.atoi(item[i])
                        use.append((amount, item[i+1]))
                        i = i + 2
                    except:
                        level = item[i]
                        break
            empDb.megaDB['sectortype'][des]['level'] = level
            empDb.megaDB['sectortype'][des]['min'] = minlevel
            empDb.megaDB['sectortype'][des]['lag'] = lag
            empDb.megaDB['sectortype'][des]['eff'] = eff
            empDb.megaDB['sectortype'][des]['prodcost'] = cost
            empDb.megaDB['sectortype'][des]['depletion'] = dep
            empDb.megaDB['sectortype'][des]['comout'] = comout
            empDb.megaDB['sectortype'][des]['comuse'] = use[:]
            return
        if self.what == 'plbu':
            item = string.split(msg)
            type = item[0]
            item[0:1] = []
            lcm, hcm, crew, avail, tech, cost = item[-6:]
            item[-6:] = []
            name = item[0]
            for x in item[1:] :
                name = name + " " + x
            if not empDb.megaDB['planetype'].has_key(type) :
                empDb.megaDB['planetype'][type] = {
                    'name': name,
                    'lcm': string.atoi(lcm),
                    'hcm': string.atoi(hcm),
                    'mil': string.atoi(crew),
                    'avail': string.atoi(avail),
                    'tech': string.atoi(tech) }
            return
        if self.what == 'shbu':
            item = string.split(msg)
            type = item[0]
            item[0:1] = []
            lcm, hcm, avail, tech, cost = item[-5:]
            item[-5:] = []
            name = item[0]
            for x in item[1:] :
                name = name + " " + x
            if not empDb.megaDB['shiptype'].has_key(type) :
                empDb.megaDB['shiptype'][type] = {
                    'name': name,
                    'lcm': string.atoi(lcm),
                    'hcm': string.atoi(hcm),
                    'avail': string.atoi(avail),
                    'tech': string.atoi(tech) }
            return
        if self.what == 'labu':
            item = string.split(msg)
            type = item[0]
            item[0:1] = []
            lcm, hcm, gun, avail, tech, cost = item[-6:]
            item[-6:] = []
            name = item[0]
            for x in item[1:] :
                name = name + " " + x
            if not empDb.megaDB['landtype'].has_key(type) :
                empDb.megaDB['landtype'][type] = {
                    'name': name,
                    'lcm': string.atoi(lcm),
                    'hcm': string.atoi(hcm),
                    'gun': string.atoi(gun),
                    'avail': string.atoi(avail),
                    'tech': string.atoi(tech) }
            return

###########################################################################
#############################  Parser list    #############################

DB_SECTOR = 1
DB_LAND = 2
DB_SHIP = 4
DB_PLANE = 8
DB_NUKE = 16
DB_LOST = 32

DB_ALL = DB_SECTOR|DB_LAND|DB_SHIP|DB_PLANE|DB_NUKE|DB_LOST

def initialize():
    commandUpdates = []
    standardParsers = []
    for i in (
        (ParseRead,
         ('read', 4, 0), ('wire', -3, 0)),
        (ParseTele,
         ('telegram', -3, 0)),
        (ParseDump,
         ('dump', -2, 0), ('pdump', -2, 0), ('ldump', -2, 0),
         ('sdump', -2, 0), ('ndump', -2, 0), ('lost', 3, 0)),
        (ParseMap,
         ('map', -3, 0), ('nmap', -2, 0), ('bmap', -2, 0)),
        (ParseRealm,
         ('realm', -4, 0)),
        (ParseMove,
         ('explore', -3, 1), ('move', -3, 1),
         ('transport', -4, 1), ('test', -3, 0)),
        (ParseVersion,
         ('version', 1, 0)),
        (ParseUpdate,
         ('update', 3, 0)),
        (ParseNation,
         ('nation', 3, 0)),
        (ParseCapital,
         ('capital', -3, 0)),
        (ParseSpy,
         ('spy', -2, 1)),
        (ParseAttack,
         ('attack', -2, 1), ('assault', -2, 1)),
        (ParseUnits,
         ('radar', -3, 0), ('lradar', -4, 0), ('lookout', -3, 0),
         ('llookout', -4, 0), ('navigate', -3, 1), ('march', -4, 1),
         ('sonar', -3, 0)),
    ##     (ParsePathSetting,
        (None,
         ('sail', -3, 1), ('bomb', -3, 1), ('fly', -3, 1),
         ('paradrop', -3, 1), ('sweep', -2, 1)),
        (ParseSpyPlane,
         ('recon', -3, 1)),
        (ParseReport,
         ('report', -4, 0)),
        (ParseRelations,
         ('relations', -3, 0)),
        (ParseCoastWatch,
         ('coastwatch', 3, 0)),
        (ParseBuild,
         ('build', -3, 1)),
        (ParseSimpleTime,
         ('census', -2, 0), ('resource', -4, 0), ('cutoff', -2, 0),
         ('sinfrastructure', -2, 0),
         ('commodity', -3, 0), ('level', -3, 0), ('neweff', -4, 0),
         ('production', -3, 0),
         ('strength', -3, 0), ('stop', -3, 1), ('start', -5, 1),
         ('anti', -3, 1)),
        (ParseSate,
         ('satellite', -3, 0)),
        (ParseBomb,
         ('bomb', 3, 0)),
        (ParseFire,
         ('fire', 3, 0)),
        (ParseTorpedo,
         ('torpedo', 3, 0)),
        (ParseShow,
         ('show', 4, 0)),
        (None,
         ('motd', 3, 0)),
        ):
        for j in i[1:]:
            if i[0] is not None:
                standardParsers.append(j[:2]+i[:1])
            commandUpdates.append(j)
    standardParsers.sort()
    commandUpdates.sort()
    empQueue.standardParsers = standardParsers
##      for k in range(abs(j[1]), len(j[0])+1):
##          if i[0] != None:
##              standardParsers[j[0][:k]] = i[0]
##          commandUpdates[j[0][:k]] = j[2]

initialize()

###########################################################################
#############################  Functions      #############################

def str2Coords(s):
    idx = string.index(s, ',')
    return (string.atoi(s[:idx]), string.atoi(s[idx+1:]))

def checkUpdated(dbname, item, val):
    """Update the value in the main/update databases iff a change is made."""
    megaDB = empDb.megaDB
    if megaDB[dbname].get(item) != val:
        megaDB[dbname][item] = empDb.updateDB[dbname][item] = val
