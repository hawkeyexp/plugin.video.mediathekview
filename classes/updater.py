# -*- coding: utf-8 -*-
# Copyright 2017 Leo Moll
#

# -- Imports ------------------------------------------------
import os, stat, urllib, urllib2, subprocess, ijson
import xml.etree.ElementTree as etree
import xbmc, xbmcgui

from operator import itemgetter
from classes.storesqlite import StoreSQLite

# -- Constants ----------------------------------------------
FILMLISTE_URL = 'https://res.mediathekview.de/akt.xml'

# -- Classes ------------------------------------------------
class MediathekViewUpdater( object ):
	def __init__( self, id, logger, notifier, settings ):
		self.id			= id
		self.logger		= logger
		self.notifier	= notifier
		self.settings	= settings
		self.addonpath	= os.path.join( xbmc.translatePath( "special://masterprofile" ), 'addon_data', id )

	def Update( self ):
		self.sql = StoreSQLite( self.id, self.logger, self.notifier, self.settings )
		self.sql.Init( reset = False )
		self.Import()
		self.sql.Exit()
		del self.sql

	def Import( self ):
		destfile = os.path.join( self.addonpath, 'Filmliste-akt' )
		if not self._file_exists( destfile ):
			self.logger.error( 'File {} does not exists')
			return False
		try:
			file = open( destfile, 'r' )
			parser = ijson.parse( file )
			self._update_start()
			for prefix, event, value in parser:
				if ( prefix, event ) == ( "X", "start_array" ):
					self._init_record()
				elif ( prefix, event ) == ( "X", "end_array" ):
					self._end_record()
					if self.count >= 50000:
						self._update_end()
						file.close()
						return True
				elif ( prefix, event ) == ( "X.item", "string" ):
					if value is not None:
#						self._add_value( value.strip().encode('utf-8') )
						self._add_value( value.strip() )
					else:
						self._add_value( "" )
			self._update_end()
			file.close()
		except IOError as err:
			self.logger.error( 'Error {} wile processing {}', err, destfile )
			try:
				file.close()
			except Exception as err:
				pass
			return False
		self.logger.info( 'Import of {} finished', destfile )
		return True

	def GetNewestList( self ):
		# get xz binary
		xzbin = self._find_xz()
		if xzbin is None:
			self.notifier.ShowMissingXZError()
			return False

		# get mirrorlist
		self.logger.info( 'Opening {}', FILMLISTE_URL )
		try:
			data = urllib2.urlopen( FILMLISTE_URL ).read()
		except URLError as err:
			self.logger.error( 'Failure opening {}', FILMLISTE_URL )
			self.notifier.ShowDowloadError( FILMLISTE_URL, err )
			return False

		root = etree.fromstring ( data )
		urls = []
		for server in root.findall( 'Server' ):
			try:
				URL = server.find( 'URL' ).text
				Prio = server.find( 'Prio' ).text
				urls.append( ( URL, Prio ) )
				self.logger.info( 'Found mirror {} (Priority {})', URL, Prio )
			except AttributeError as error:
				pass
		urls = sorted( urls, key = itemgetter( 1 ) )
		urls = [ url[0] for url in urls ]
		result = None

		# cleanup downloads
		self._cleanup_downloads()

		# download filmliste
		compfile = os.path.join( self.addonpath, 'Filmliste-akt.xz' )
		self.logger.info( 'Tryinig to download file...' )
		self.notifier.ShowDownloadProgress()
		lasturl = ''
		for url in urls:
			try:
				lasturl = url
				self.notifier.UpdateDownloadProgress( 0, url )
				result = urllib.urlretrieve( url, filename = compfile, reporthook = self._reporthook )
				break
			except IOError as err:
				self.logger.error( 'Failure opening {}', url )
		if result is None:
			self.logger.info( 'No file downloaded' )
			self.notifier.CloseDownloadProgress()
			self.notifier.ShowDowloadError( lasturl, err )
			return False

		# decompress filmliste
		self.logger.info( 'Trying to decompress file...' )
		destfile = os.path.join( self.addonpath, 'Filmliste-akt' )
		retval = subprocess.call( [ xzbin, '-d', compfile ] )
		self.logger.info( 'Return {}', retval )
		self.notifier.CloseDownloadProgress()
		return retval == 0 and self._file_exists( destfile )

	def _cleanup_downloads( self ):
		self.logger.info( 'Cleaning up old downloads...' )
		self._file_remove( os.path.join( self.addonpath, 'Filmliste-akt.xz' ) )
		self._file_remove( os.path.join( self.addonpath, 'Filmliste-akt' ) )

	def _find_xz( self ):
		for xzbin in [ '/bin/xz', '/usr/bin/xz', '/usr/local/bin/xz' ]:
			if self._file_exists( xzbin ):
				return xzbin
		return None

	def _file_exists( self, name ):
		try:
			s = os.stat( name )
			return stat.S_ISREG( s.st_mode )
		except OSError as err:
			return False

	def _file_remove( self, name ):
		if self._file_exists( name ):
			try:
				os.remove( name )
				return True
			except OSError as err:
				self.logger.error( 'Failed to remove {}: error {}', name, err )
		return False

	def _reporthook( self, blockcount, blocksize, totalsize ):
		downloaded = blockcount * blocksize
		if totalsize > 0:
			percent = int( (downloaded * 100) / totalsize )
			self.notifier.UpdateDownloadProgress( percent )
		self.logger.info( 'Downloading blockcount={}, blocksize={}, totalsize={}', blockcount, blocksize, totalsize )

	def _update_start( self ):
		self.logger.info( 'Initialting update...' )
		self.channels = 0
		self.shows = 0
		self.movies = 0
		self.index = 0
		self.count = 0
		self.film = {
			"channel": "",
			"show": "",
			"title": "",
			"aired": "1980-01-01 00:00:00",
			"duration": "00:00:00",
			"size": 0,
			"description": "",
			"website": "",
			"url_sub": "",
			"url_video": "",
			"url_video_sd": "",
			"url_video_hd": "",
			"airedepoch": 0,
			"geo": ""
		}
		self.sql.ftInit()
		self.sql.ftUpdateStart()

	def _update_end( self ):
		self.logger.info( 'Added: channels:%d, shows:%d, movies:%d ...' % ( self.channels, self.shows, self.movies ) )
		( cnt_chn, cnt_shw, cnt_mov ) = self.sql.ftUpdateEnd()
		self.logger.info( 'Deleted: channels:%d, shows:%d, movies:%d' % ( cnt_chn, cnt_shw, cnt_mov ) )

	def _init_record( self ):
		self.index = 0
		self.film["title"] = ""
		self.film["aired"] = "1980-01-01 00:00:00"
		self.film["duration"] = "00:00:00"
		self.film["size"] = 0
		self.film["description"] = ""
		self.film["website"] = ""
		self.film["url_sub"] = ""
		self.film["url_video"] = ""
		self.film["url_video_sd"] = ""
		self.film["url_video_hd"] = ""
		self.film["airedepoch"] = 0
		self.film["geo"] = ""

	def _end_record( self ):
		if self.count % 1000 == 0:
			self.logger.info( 'In progress (%d): channels:%d, shows:%d, movies:%d ...' % ( self.count, self.channels, self.shows, self.movies ) )
		self.count = self.count + 1
		( filmid, cnt_chn, cnt_shw, cnt_mov ) = self.sql.ftInsertFilm( self.film )
		self.channels += cnt_chn
		self.shows += cnt_shw
		self.movies += cnt_mov

	def _add_value( self, val ):
		if self.index == 0:
			if val != "":
				self.film["channel"] = val
		elif self.index == 1:
			if val != "":
				self.film["show"] = val[:255]
		elif self.index == 2:
			self.film["title"] = val[:255]
		elif self.index == 3:
			if len(val) == 10:
				self.film["aired"] = val[6:] + '-' + val[3:5] + '-' + val[:2]
		elif self.index == 4:
			if ( self.film["aired"] != "1980-01-01 00:00:00" ) and ( len(val) == 8 ):
				self.film["aired"] = self.film["aired"] + " " + val
		elif self.index == 5:
			if len(val) == 8:
				self.film["duration"] = val
		elif self.index == 6:
			if val != "":
				self.film["size"] = int(val)
		elif self.index == 7:
			self.film["description"] = val
		elif self.index == 8:
			self.film["url_video"] = val
		elif self.index == 9:
			self.film["website"] = val
		elif self.index == 10:
			self.film["suburl_subtitles"] = val
		elif self.index == 12:
			self.film["url_video_sd"] = self._make_url(val)
		elif self.index == 14:
			self.film["url_video_hd"] = self._make_url(val)
		elif self.index == 16:
			if val != "":
				self.film["airedepoch"] = int(val)
		elif self.index == 18:
			self.film["geo"] = val
		self.index = self.index + 1

	def _make_search( self, val ):
		cset = string.letters + string.digits + ' _-#'
		search = ''.join( [ c for c in val if c in cset ] )
		return search.upper().strip()

	def _make_url( self, val ):
		x = val.split( '|' )
		if len( x ) == 2:
			cnt = int( x[0] )
			return self.film["url_video"][:cnt] + x[1]
		else:
			return val