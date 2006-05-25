#!/usr/bin/env python
#===============================================================================
#	flickrfs - Virtual Filesystem for Flickr
#	Copyright (c) 2005 Manish Rai Jain  <manishrjain@gmail.com>
#
#	This program can be distributed under the terms of the GNU GPL version 2, or 
#	its later versions. 
#
# DISCLAIMER: The API Key and Shared Secret are provided by the author in 
# the hope that it will prevent unnecessary trouble to the end-user. The 
# author will not be liable for any misuse of this API Key/Shared Secret 
# through this application/derived apps/any 3rd party apps using this key. 
#===============================================================================

import thread, array, string, urllib2, traceback, ConfigParser, mimetypes, codecs
import time, logging, logging.handlers, os, sys
from glob import glob
from errno import *
from stat import *
from traceback import format_exc
from fuse import Fuse
from flickrapi import FlickrAPI
import random
import commands
import threading

#Some global definitions and functions
DEFAULTBLOCKSIZE = 4*1024  #4KB
# flickr auth information
flickrAPIKey = "f8aa9917a9ae5e44a87cae657924f42d"  # API key
flickrSecret = "3fbf7144be7eca28"				  # shared "secret"
browserName = "/usr/bin/firefox"				   # for out-of-band auth inside a web browser

#Set up the .flickfs directory.
homedir = os.getenv('HOME')
flickrfsHome = os.path.join(homedir, '.flickrfs')
if not os.path.exists(flickrfsHome):
	os.mkdir(os.path.join(flickrfsHome))
else:
	# Remove previous metadata files from ~/.flickrfs
	for a in glob(os.path.join(flickrfsHome, '.*')):
		os.remove(os.path.join(flickrfsHome, a))

# Set up logging
log = logging.getLogger('flickrfs')
loghdlr = logging.handlers.RotatingFileHandler(os.path.join(flickrfsHome,'log'), "a", 5242880, 3)
logfmt = logging.Formatter("%(asctime)s %(levelname)-10s %(message)s", "%x %X")
loghdlr.setFormatter(logfmt)
log.addHandler(loghdlr)
log.setLevel(logging.DEBUG)

cp = ConfigParser.ConfigParser()
cp.read(flickrfsHome + '/config.txt')
iSizestr = ""
sets_sync_int = 600.0
stream_sync_int = 600.0
try:
	iSizestr = cp.get('configuration', 'image.size')
except:
	print 'No default size of image found. Will upload original size of images.'
try:
	sets_sync_int = float(cp.get('configuration', 'sets.sync.int'))
except:
	pass
try:
	stream_sync_int = float(cp.get('configuration', 'stream.sync.int'))
except:
	pass
try:
	browserName = cp.get('configuration', 'browser')
except:
	pass

#Utility functions.
def _log_exception_wrapper(func, *args, **kw):
		"""Call 'func' with args and kws and log any exception it throws.
		"""
		try: func(*args, **kw)
		except:
			log.error("Exception in function %s" % func)
			log.error(format_exc())

def background(func, *args, **kw):
		"""Run 'func' as a thread, logging any exceptions it throws.

		To run

			somefunc(arg1, arg2='value')

		as a thread, do:

			background(somefunc, arg1, arg2='value')

		Any exceptions thrown are logged as errors, and the traceback is logged.
		"""
		thread.start_new_thread(_log_exception_wrapper, (func,)+args, kw)

def kwdict(**kw): return kw

def timerThread(func, func1, interval):
	'''Execute func now, followed by func1 every interval seconds
	'''
	t = threading.Timer(0.0, func)
	try:
		t.run()
	except: pass
	while(interval):
		t = threading.Timer(interval, func1)
		try:
			t.run()
		except: pass
		
#Transactions with flickr, wraps FlickrAPI calls in Flickfs-specialized functions.
class TransFlickr: 

	extras = "original_format,date_upload,last_update"

	def __init__(self):
		self.fapi = FlickrAPI(flickrAPIKey, flickrSecret)
		self.user_id = ""
		# proceed with auth
		# TODO use auth.checkToken function if available, and wait after opening browser
		print "Authorizing with flickr..."
		log.info("Authorizing with flickr...")
		try:
			self.authtoken = self.fapi.getToken(browser=browserName)
		except:
			print ("Can't retrieve token from browser:%s:"%(browserName,))
			print "\tIf you're behind a proxy server, first set http_proxy environment variable."
			print "\tPlease close all your browser windows, and try again"
			log.error(format_exc())
			log.error("Can't retrieve token from browser:%s:"%(browserName,))
			sys.exit(-1)
		if self.authtoken == None:
			log.error('Not able to authorize. Exiting...')
			sys.exit(-1)
				#Add some authorization checks here(?)
		print "Authorization complete. Retrieving photos..."
		log.info('Authorization complete')

	def imageResize(self, bufData):
		im = '/tmp/flickrfs-' + str(int(random.random()*1000000000))
		f = open(im, 'w')
		f.write(bufData)
		f.close()
		cmd = 'identify -format "%w" %s'%(im,)
		status,ret = commands.getstatusoutput(cmd)
		if status!=0:
			print "identify command not found. Install Imagemagick"
			log.error("identify command not found. Install Imagemagick")
			return bufData
		try:
			if int(ret)<int(iSizestr.split('x')[0]):
				log.info('Image size is smaller than specified in config.txt. Taking original size')
				return bufData
		except:
			log.error('Invalid format of image.size in config.txt')
			return bufData
	
		cmd = 'convert %s -resize %s %s-conv'%(im, iSizestr, im)
		#try:
		ret = os.system(cmd)
		if ret!=0:
			print "convert Command not found. Install Imagemagick"
			log.error("convert Command not found. Install Imagemagick")	
			return bufData
		else:
		#except: 
		#	log.error("Command not found. Install Imagemagick")
		#	return bufData
			f = open(im + '-conv')
			return f.read()
		
	def uploadfile(self, filepath, taglist, bufData, mode):
		public = mode&1 #Set public 4(always), 1(public). Public overwrites f&f
		friends = mode>>3 & 1 #Set friends and family 4(always), 2(family), 1(friends)
		family = mode>>4 & 1
			#E.g. 745 - 4:No f&f, but 5:public
			#E.g. 754 - 5:friends, but not public
			#E.g. 774 - 7:f&f, but not public
		if iSizestr is not "":
			log.info("Resizing image to %s:%s"%(iSizestr,filepath))
			bufData = self.imageResize(bufData)
		else:
			log.info("Uploading original size of image: " + filepath)

		log.info("Uploading file: " + filepath + ":with data of len:" + str(len(bufData)))
		log.info("and tags:%s"%(str(taglist),))
		log.info("Permissions:Family:%s Friends:%s Public:%s"%(family,friends,public))
		rsp = self.fapi.upload(filename=filepath, jpegData=bufData,
					title=os.path.splitext(os.path.basename(filepath))[0],
					tags=taglist,
					is_public=public and "1" or "0",
					is_friend=friends and "1" or "0",
					is_family=family and "1" or "0")
		if rsp==None:
			log.error("Can't write file: " + filepath)
		elif rsp:
			id = rsp.photoid[0].elementText
			log.info("File uploaded:" + filepath + ":with photoid:" + id + ":")
			return id
		else:
			log.error(rsp.errormsg)

	def put2Set(self, set_id, photo_id):
		log.info("Uploading photo:"+photo_id+":to set_id:"+set_id)
		rsp = self.fapi.photosets_addPhoto(auth_token=self.authtoken, photoset_id=set_id, photo_id=photo_id)
		if rsp:
			log.info("Uploaded photo to set")
		else:
			log.error(rsp.errormsg)
	
	def createSet(self, path, photo_id):
		log.info("Creating set:%s:with primary photo:%s:"%(path,photo_id))
		path, title = os.path.split(path)
		rsp = self.fapi.photosets_create(auth_token=self.authtoken, title=title, primary_photo_id=photo_id)
		if rsp:
			log.info("Created set:%s:"%(title))
			return rsp.photoset[0]['id']
		else:
			log.error(rsp.errormsg)
	
	def deleteSet(self, set_id):
		log.info("Deleting set:%s:"%(set_id))
		if str(set_id)=="0":
			log.info("The set is non-existant online.")
			return
		rsp = self.fapi.photosets_delete(auth_token=self.authtoken, photoset_id=set_id)
		if rsp:
			log.info("Deleted set")
		else:
			log.error(rsp.errormsg)
	
	def getPhotoInfo(self, photoId):
		rsp = self.fapi.photos_getInfo(auth_token=self.authtoken, photo_id=photoId)
		if not rsp:
			log.error("Can't retrieve information about photo: " + rsp.errormsg)
			log.error("retinfo:%s"%(rsp.errormsg,))
			return None
		format = rsp.photo[0]['originalformat']
		perm_public = rsp.photo[0].visibility[0]['ispublic']
		perm_family = rsp.photo[0].visibility[0]['isfamily']
		perm_friend = rsp.photo[0].visibility[0]['isfriend']
		if perm_public == '1':
			mode = 0755
		else:
			b_cnt = 4
			if perm_family == '1':
				b_cnt += 2
			if perm_friend == '1':
				b_cnt += 1
			mode = "07" + str(b_cnt) + "4"
			mode = int(mode)
		if hasattr(rsp.photo[0],'permissions'):
			permcomment = rsp.photo[0].permissions[0]['permcomment']
			permaddmeta = rsp.photo[0].permissions[0]['permaddmeta']
		else: permcomment = permaddmeta = [None]
		commMeta = '%s%s'%(permcomment,permaddmeta) #Just add both. Required for chmod
		desc = rsp.photo[0].description[0].elementText
		title = rsp.photo[0].title[0].elementText
		if hasattr(rsp.photo[0].tags[0], "tag"):
			taglist = [ a.elementText for a in rsp.photo[0].tags[0].tag ]
		else:
			taglist = []
		license = rsp.photo[0]['license']
		owner = rsp.photo[0].owner[0]['username']
		ownerNSID = rsp.photo[0].owner[0]['nsid']
		url = rsp.photo[0].urls[0].url[0].elementText
		posted = rsp.photo[0].dates[0]['posted']
		lastupdate = rsp.photo[0].dates[0]['lastupdate']
		return (format, mode, commMeta, desc, title, taglist, license, owner, ownerNSID, url, int(posted), int(lastupdate))

	def setPerm(self, photoId, mode, comm_meta="33"):
		public = mode&1 #Set public 4(always), 1(public). Public overwrites f&f
		friends = mode>>3 & 1 #Set friends and family 4(always), 2(family), 1(friends)
		family = mode>>4 & 1
		if len(comm_meta)<2: #This wd patch string index out of range bug, caused 
							 #because some photos may not have comm_meta value set.
			comm_meta="33"
		rsp = self.fapi.photos_setPerms(auth_token=self.authtoken, is_public=str(public),
			is_friend=str(friends), is_family=str(family), perm_comment=comm_meta[0],
			perm_addmeta=comm_meta[1], photo_id=photoId)
		if not rsp:
			log.error("Couldn't set permission:%s:%s"%(photoId,rsp.errormsg))
			return False
		log.info("Set permission:" + photoId)
		return True

	def setTags(self, photoId, tags):
		templist = [ '"%s"'%(a,) for a in string.split(tags, ',')] + ['flickrfs']
		tagstring = ' '.join(templist)
		rsp = self.fapi.photos_setTags(auth_token=self.authtoken, photo_id=photoId, tags=tagstring)
		if not rsp:
			log.error("Couldn't set tags:%s:"%(photoId,))
			log.error("setTags: retinfo:%s"%(rsp.errormsg,))
			return False
		return True
	
	def setMeta(self, photoId, title, desc):
		rsp = self.fapi.photos_setMeta(auth_token=self.authtoken, photo_id=photoId, title=title, description=desc)
		if not rsp:
			log.error("Couldn't set meta info:%s:"%(photoId,))
			log.error("retinfo:%s"%(rsp.errormsg,))
			return False
		return True

	def getLicenses(self):
		rsp = self.fapi.photos_licenses_getInfo()
		if not rsp:
			log.error("retinfo:%s"%(rsp.errormsg,))
			return None
		licenseDict = {}
		for l in rsp.licenses[0].license:
			licenseDict[l['id']] = l['name']
		return licenseDict
		
	def setLicense(self, photoId, license):
		rsp = self.fapi.photos_licenses_setLicense(auth_token=self.authtoken, photo_id=photoId, license_id=license)
		if not rsp:
			log.error("Couldn't set license info:%s:"%(photoId,))
			log.error("retinfo:%s"%(rsp.errormsg,))
			return False
		return True

	def getPhoto(self, photoId):
		rsp = self.fapi.photos_getSizes(auth_token=self.authtoken, photo_id=photoId)
		if not rsp:
			log.error("Error while trying to retrieve size information:%s:"%(photoId,))
			return None
		buf = ""
		for a in rsp.sizes[0].size:
			if a['label']=='Original':
				try:
					f = urllib2.urlopen(a['source'])
					buf = f.read()
				except:
					log.error("Exception in getPhoto")
					log.error(format_exc())
					return ""
		if not buf:
			f = urllib2.urlopen(rsp.sizes[0].size[-1]['source'])
			buf = f.read()
		return buf

	def removePhotofromSet(self, photoId, photosetId):
		rsp = self.fapi.photosets_removePhoto(auth_token=self.authtoken, photo_id=photoId, photoset_id=photosetId)
		if rsp:
			log.info("Photo %s removed from set %s" % (photoId, photosetId))
		else:
			log.error(rsp.errormsg)
			
		
	def getBandwidthInfo(self):
		log.debug("Retrieving bandwidth information")
		rsp = self.fapi.people_getUploadStatus(auth_token=self.authtoken)
		if not rsp:
			log.error("Can't retrieve bandwidth information: %s" % rsp.errormsg)
			return (None,None)
		bw = rsp.user[0].bandwidth[0]
		log.debug("Bandwidth: max:" + bw['max'])
		log.debug("Bandwidth: used:" + bw['used'])
		return (bw['max'], bw['used'])

	def getUserId(self):
		rsp = self.fapi.auth_checkToken(api_key=flickrAPIKey, auth_token=self.authtoken)
		if not rsp:
			log.error("Unable to get userid:" + rsp.errormsg)
			return None
		usr = rsp.auth[0].user[0]
		log.info("Got NSID:"+ usr['nsid'] + ":")
		#Set self.user_id to this value
		self.user_id = usr['nsid']
		return usr['nsid']

	def getPhotosetList(self):
		if self.user_id is "":
			self.getUserId() #This will set the value of self.user_id
		rsp = self.fapi.photosets_getList(auth_token=self.authtoken, user_id=self.user_id)
		if not rsp:
			log.error("Error getting photoset list: %s" % (rsp.errormsg))
			return []
		if not hasattr(rsp.photosets[0], "photoset"):
			return []
		return rsp.photosets[0].photoset

	def getPhotosFromPhotoset(self, photoset_id):
		rsp = self.fapi.photosets_getPhotos(auth_token=self.authtoken, photoset_id=photoset_id, extras=self.extras)
		if not rsp:
			log.error("Error getting photos from photoset %s: %s" % (photoset_id, rsp.errormsg))
			return []
		return rsp.photoset[0].photo
						
	def getPhotoStream(self, user_id):
		retList = []
		pageNo = 1
		maxPage = 1
		while pageNo<=maxPage:
			log.info("maxPage:%s pageNo:%s"%(maxPage, pageNo))
			rsp = self.fapi.photos_search(auth_token=self.authtoken, user_id=user_id, per_page="500", page=str(pageNo), extras=self.extras)
			if not rsp:
				log.error("Can't retrive photos from your stream:" + rsp.errormsg)
				return retList
			if not hasattr(rsp.photos[0], 'photo'):
				log.error("Doesn't have attribute photos. Page requested: %s"%(pageNo,))
				return retList
			for a in rsp.photos[0].photo:
				retList.append(a)
			maxPage = int(rsp.photos[0]['pages'])
			pageNo = pageNo + 1
		return retList
 
	def getTaggedPhotos(self, tags, user_id=None):
		kw = kwdict(auth_token=self.authtoken, tags=tags, tag_mode="all", extras=self.extras, per_page="500")
		if user_id is not None: kw = kwdict(user_id=user_id, **kw)
		rsp = self.fapi.photos_search(**kw)
		log.debug("Search for photos with tags:" + tags + ":done")
		if not rsp:
			log.error("Couldn't search for the photos:" + rsp.errormsg)
			return
		if not hasattr(rsp.photos[0], 'photo'):
			return []
		return rsp.photos[0].photo
				


class Inode(object):
	"""Common base class for all file system objects
	"""

	def __init__(self, path=None, id='', mode=None, size=0L, mtime=None, ctime=None):
		self.nlink = 1
		self.size = size
		self.id = id
		self.mode = mode
		self.ino = long(time.time())
		self.dev = 409089L
		self.uid = int(os.getuid())
		self.gid = int(os.getgid())
		now = int(time.time())
		self.atime = now
		if mtime is None: self.mtime = now
		else: self.mtime = int(mtime)
		if ctime is None: self.ctime = now
		else: self.ctime = int(ctime)
		self.blocksize = DEFAULTBLOCKSIZE


class DirInode(Inode):

	def __init__(self, path=None, id="", mode=None, mtime=None, ctime=None):
		if mode is None: mode = 0755
		super(DirInode, self).__init__(path, id, mode, 0L, mtime, ctime)
		self.mode = S_IFDIR | self.mode
		self.nlink += 1
		self.dirfile = ""
		self.setId = self.id


class FileInode(Inode):

	def __init__(self, path=None, id="", mode=None, comm_meta="", size=1L, mtime=None, ctime=None):
		if mode is None: mode = 0644
		super(FileInode, self).__init__(path, id, mode, size, mtime, ctime)
		self.mode = S_IFREG | self.mode
		self.buf = ""
		self.photoId = self.id
		self.comm_meta = comm_meta


class Flickrfs(Fuse):

	def __init__(self, *args, **kw):
	
		Fuse.__init__(self, *args, **kw)
		log.info("flickrfs.py:Flickrfs:mountpoint: %s" % repr(self.mountpoint))
		log.info("flickrfs.py:Flickrfs:unnamed mount options: %s" % self.optlist)
		log.info("flickrfs.py:Flickrfs:named mount options: %s" % self.optdict)
		
		self.inodeCache = {}  #Cached inodes for faster access
		self.NSID = ""
		self.transfl = TransFlickr()

		self.NSID = self.transfl.getUserId()
		if self.NSID==None:
			print "Can't retrieve user information"
			log.error("Initialization:Can't retrieve user information")
			sys.exit(-1)

		log.info('Getting list of licenses available')
		self.licenseDict = self.transfl.getLicenses()
		if self.licenseDict==None:
			print "Can't retreive license information"
			log.error("Initialization:Can't retrieve license information")
			sys.exit(-1)

		# do stuff to set up your filesystem here, if you want
		self._mkdir("/")
		self._mkdir("/tags")
		self._mkdir("/tags/personal")
		self._mkdir("/tags/public")
		background(timerThread, self.sets_thread, self.sync_sets_thread, sets_sync_int) #sync every 2 minutes

	def writeMetaInfo(self, id, INFO):
		#The metadata may be unicode strings, so we need to encode them on write
		f = codecs.open(os.path.join(flickrfsHome, '.'+id), 'w', 'utf8')
		f.write('#Metadata file : flickrfs - Virtual filesystem for flickr\n')
		f.write('#Photo owner: %s  NSID: %s\n'%(INFO[7], INFO[8]))
		f.write('#Handy link to photo: %s\n'%(INFO[9]))
		f.write('#Licences available: \n')
		iter = self.licenseDict.iterkeys()
		while True:
			try:
				key = iter.next()
				f.write('#%s : %s\n'%(key, self.licenseDict[key]))
			
			except:
				break
		f.write('#0 : for "All Rights Reserved"\n')
		f.write('[metainfo]\n')
		f.write("%s:%s\n"%('title', INFO[4]))
		f.write("%s:%s\n"%('description', INFO[3]))
		tags = ','.join(INFO[5])
		f.write("%s:%s\n"%('tags', tags))
		f.write("%s:%s\n"%('license',INFO[6]))
		f.close()

	def sets_thread(self):
		"""
			The beauty of the FUSE python implementation is that with the python interp
			running in foreground, you can have threads
			"""	
		log.info("sets_thread: started")
		self._mkdir("/sets")
		for a in self.transfl.getPhotosetList():
			title = a.title[0].elementText.replace('/', '_')
			curdir = "/sets/" + title
			if title.strip()=='':
				curdir = "/sets/" + a['id']
			set_id = a['id']
			self._mkdir(curdir, id=set_id)
			for b in self.transfl.getPhotosFromPhotoset(set_id):
				self._mkfileWithMeta(curdir, b['id'])
		log.info('Sets population finished')

	def _sync_code(self, psetOnline, curdir):
		psetLocal = self.getdir(curdir, False)
		for b in psetOnline:
			imageTitle = b['title'].replace('/', '_')
			imageTitle = imageTitle[:32] + '_' + str(b['id']) + '.' + str(b['originalformat'])
			path = "%s/%s"%(curdir, imageTitle)
			try:
				inode = self.inodeCache[path]
				if inode.mtime != int(b['lastupdate']):
					log.debug("Image %s changed"%(path))
					self.inodeCache.pop(path)
					self._mkfileWithMeta(curdir, b['id'])
				psetLocal.remove((imageTitle,0))
			except: #Image inode not present in the set
				log.debug("New image found: %s"%(path))
				self._mkfileWithMeta(curdir, b['id'])
		if len(psetLocal)>0:
			log.info('%s photos have been deleted online'%(len(psetLocal),))
		for c in psetLocal:
			log.info('deleting:%s'%(c[0],))
			self.unlink(curdir+'/'+c[0], False)

	def sync_sets_thread(self):
		log.info("sync_sets_thread: started")
		setListOnline = self.transfl.getPhotosetList()
		setListLocal = self.getdir('/sets', False)
		
		for a in setListOnline:
			title = a.title[0].elementText.replace('/', '_')
			if title.strip()=="":
				title = a['id']
			if (title,0) not in setListLocal: #New set added online
				log.info("%s set has been added online."%(title,))
				self._mkdir('/sets/'+title, a['id'])
			else: #Present Online
				setListLocal.remove((title,0))
		for a in setListLocal: #List of sets present locally, but not online
			log.info('Recursively deleting set %s'%(a,))
			self.rmdir('/sets/'+a[0], online=False, recr=True)
				
		for a in setListOnline:
			title = a.title[0].elementText.replace('/', '_')
			curdir = "/sets/" + title
			if title.strip()=='':
				curdir = "/sets/" + a['id']
			set_id = a['id']
			psetOnline = self.transfl.getPhotosFromPhotoset(set_id)
			self._sync_code(psetOnline, curdir)
		log.info('sync_sets_thread finished')

	def sync_stream_thread(self):
		log.info('sync_stream_thread started')
		psetOnline = self.transfl.getPhotoStream(self.NSID)
		self._sync_code(psetOnline, '/stream')
		log.info('sync_stream_thread finished')
			
	def stream_thread(self):
		log.info("stream_thread started")
		for b in self.transfl.getPhotoStream(self.NSID):
			self._mkfileWithMeta('/stream', b['id'])
		log.info("stream_thread finished")
			
	def tags_thread(self, path):
		ind = string.rindex(path, '/')
		tagName = path[ind+1:]
		if tagName.strip()=='':
			log.error("The tagName:%s: doesn't contain any tags"%(tagName))
			return 
		log.info("tags_thread:" + tagName + ":started")
		sendtagList = ','.join(tagName.split(':'))
		if(path.startswith('/tags/personal')):
			user_id = self.NSID
		else:
			user_id = None
		for b in self.transfl.getTaggedPhotos(sendtagList, user_id):
			self._mkfileWithMeta(path, b['id'])

	def _mkfileWithMeta(self, path, id):
		INFO = self.transfl.getPhotoInfo(id)
		if INFO==None:
			log.error("Can't retrieve info:%s:"%(id,))
			return
		title = INFO[4].replace('/', '_')
		#if title.strip()=='':
		title = title[:32]   #Only allow 32 characters
		title += '_' + str(id)
		ext = '.' + INFO[0]
		if os.path.splitext(title)[1]!=ext:
			title = title + ext
		self.writeMetaInfo(id, INFO) #Write to a localfile
		self._mkfile(path +"/" + title, id=id,
			mode=INFO[1], comm_meta=INFO[2], mtime=INFO[11], ctime=INFO[10])

	def _parsepathid(self, path, id=""):
		#Path and Id may be unicode strings, so encode them to utf8 now before
		#we use them, otherwise python will throw errors when we combine them
		#with regular strings.
		path = path.encode('utf8')
		if id!=0: id = id.encode('utf8')
		parentDir, name = os.path.split(path)
		if parentDir=='':
			parentDir = '/'
		log.debug("parentDir:" + parentDir + ":")
		return path, id, parentDir, name

	def _mkdir(self, path, id="", mtime=None, ctime=None):
		path, id, parentDir, name = self._parsepathid(path, id)
		log.debug("Creating directory:" + path)
		self.inodeCache[path] = DirInode(path, id, mtime=mtime, ctime=ctime)
		if path!='/':
			pinode = self.getInode(parentDir)
			pinode.nlink += 1
			log.debug("nlink of %s is now %s" % (parentDir, pinode.nlink))

	def _mkfile(self, path, id="", mode=None, comm_meta="", mtime=None, ctime=None):
		path, id, parentDir, name = self._parsepathid(path, id)
		log.debug("Creating file:" + path + ":with id:" + id)
		image_name, extension = os.path.splitext(name)
		if not extension:
			log.error("Can't create file without extension")
			return
		self.inodeCache[path] = FileInode(path, id, mode=mode, comm_meta=comm_meta, mtime=mtime, ctime=ctime)
		# Now create the meta info inode if the meta info file exists
		path = os.path.join(parentDir, '.' + image_name + '.meta')
		datapath = os.path.join(flickrfsHome, '.'+id)
		if os.path.exists(datapath):
			size = os.path.getsize(datapath)
			self.inodeCache[path] = FileInode(path, id, size=size)

	def getattr(self, path):
		#log.debug("getattr:" + path + ":")
		templist = path.split('/')
		if path.startswith('/sets/'):
			templist[2] = templist[2].split(':')[0]
		elif path.startswith('/stream'):
			templist[1] = templist[1].split(':')[0]
		path = '/'.join(templist)

		inode=self.getInode(path)
		if inode:
			#log.debug("inode "+str(inode))
			statTuple = (inode.mode,inode.ino,inode.dev,inode.nlink,
				inode.uid,inode.gid,inode.size,inode.atime,inode.mtime,inode.ctime)
			#log.debug("statsTuple "+str(statTuple))
			return statTuple
		else:
			e = OSError("No such file"+path)
			e.errno = ENOENT
			raise e

	def readlink(self, path):
		log.debug("readlink")
		return os.readlink(path)
	
	def getdir(self, path, hidden=True):
		log.debug("getdir:" + path)
		templist = []
		if hidden:
			templist = ['.', '..']
		for a in self.inodeCache.keys():
			ind = a.rindex('/')
			if path=='/':
				path=""
			if path==a[:ind]:
				name = a.split('/')[-1]
				if name=="":
					continue
				if hidden and name.startswith('.'):
					templist.append(name)
				elif not name.startswith('.'):
					templist.append(name)
		return map(lambda x: (x,0), templist)

	def unlink(self, path, online=True):
		log.debug("unlink:%s:" % (path))
		if self.inodeCache.has_key(path):
			inode = self.inodeCache.pop(path)
			
			typesinfo = mimetypes.guess_type(path)
			if typesinfo[0]==None or typesinfo[0].count('image')<=0:
				log.debug("unlinked a non-image file:%s:"%(path,))
				return

			if path.startswith('/sets/'):
				ind = path.rindex('/')
				pPath = path[:ind]
				pinode = self.getInode(pPath)
				if online:
					self.transfl.removePhotofromSet(photoId=inode.photoId, photosetId=pinode.setId)
					log.info("Photo %s removed from set"%(path,))
			del inode
		else:
			log.error("Can't find what you want to remove")
			#Dont' raise an exception. Not useful when
			#using editors like Vim. They make loads of 
			#crap buffer files
	
	def rmdir(self, path, online=True, recr=False):
		log.debug("rmdir:%s:"%(path))
		if self.inodeCache.has_key(path):
			for a in self.inodeCache.keys():
				if a.startswith(path+'/'):
					if recr:
						self.unlink(a, online)
					else:
						e = OSError("Directory not empty")
						e.errno = ENOTEMPTY
						raise e
		else:
			log.error("Can't find the directory you want to remove")
			e = OSError("No such folder"+path)
			e.errno = ENOENT
			raise e
			
		if path=='/sets' or path=='/tags' or path=='/tags/personal' or path=='/tags/public' or path=='/stream':
			log.debug("rmdir on the framework! I refuse to do anything! <Stubborn>")
			e = OSError("Removal of folder %s not allowed" % (path))
			e.errno = EPERM
			raise e

		ind = path.rindex('/')
		pPath = path[:ind]
		inode = self.inodeCache.pop(path)
		if online and path.startswith('/sets/'):
			self.transfl.deleteSet(inode.setId)
		del inode
		pInode = self.getInode(pPath)
		pInode.nlink -= 1
	
	def symlink(self, path, path1):
		log.debug("symlink")
		return os.symlink(path, path1)	
	
   	def rename(self, path, path1):
		log.debug("rename:path:%s:to path1:%s:"%(path,path1))
		#Donot allow Vim to create a file~
		#Check for .meta in both paths
		if path.count('~')>0 or path1.count('~')>0:
			log.debug("This seems Vim working")
			try:
				#Get inode, but _dont_ remove from cache
				inode = self.getInode(path)
				self.inodeCache[path1] = inode
			except:
				log.debug("Couldn't find inode for:%s:"%(path,))
			return

		#Read from path
		inode = self.getInode(path)
		if inode is None or not hasattr(inode, 'photoId'):
			return
		fname = os.path.join(flickrfsHome, '.'+inode.photoId)
		f = open(fname, 'r')
		buf = f.read()
		f.close()
		
		#Now write to path1
		inode = self.getInode(path1)
		if inode is None or not hasattr(inode, 'photoId'):
			return
		fname = os.path.join(flickrfsHome, '.'+inode.photoId)
		f = open(fname, 'w')
		f.write(buf)
		f.close()
		inode.size = os.path.getsize(fname)
		retinfo = self.parse(fname, inode.photoId)
		if retinfo.count('Error')>0:
			log.error(retinfo)
		
	def link(self, srcpath, destpath):
		log.debug("link: %s:%s"%(srcpath, destpath))
		#Add image from stream to set, w/o retrieving
		slist = srcpath.split('/')
		sname_file = slist.pop(-1)
		dlist = destpath.split('/')
		dname_file = dlist.pop(-1)
		error = 0
		if sname_file=="" or sname_file.startswith('.'):
			error = 1
		if dname_file=="" or dname_file.startswith('.'):
			error = 1
		if not destpath.startswith('/sets/'):
			error = 1
		if error is 1:
			log.error("Linking is allowed only between 2 image files")
			return
		sinode = self.getInode(srcpath)
		self._mkfile(destpath, id=sinode.id, mode=sinode.mode, comm_meta=sinode.comm_meta, mtime=sinode.mtime, ctime=sinode.ctime)
		parentPath = '/'.join(dlist)
		pinode = self.getInode(parentPath)
		if pinode.setId==0:
			try:
				pinode.setId = self.transfl.createSet(parentPath, sinode.photoId)
			except:
				e = OSError("Can't create a new set")
				e.errno = EIO
				raise e
		else:
			self.transfl.put2Set(pinode.setId, sinode.photoId)

	
	def chmod(self, path, mode):
		log.debug("chmod. Oh! So, you found use as well!")
		inode = self.getInode(path)
		typesinfo = mimetypes.guess_type(path)

		if inode.comm_meta==None:
			log.debug("chmod on directory? No use la!")
			return
				
#		elif typesinfo[0]==None or typesinfo[0].count('image')<=0:
#		else:
#			inode.mode = mode
#			return

		if self.transfl.setPerm(inode.photoId, mode, inode.comm_meta)==True:
			inode.mode = mode
		
	def chown(self, path, user, group):
		log.debug("chown. Are you of any use in flickrfs?")
		
	def truncate(self, path, size):
		log.debug("truncate?? Okay okay! I accept your usage:%s:%s"%(path,size))
		ind = path.rindex('/')
		name_file = path[ind+1:]

		typeinfo = mimetypes.guess_type(path)
		if typeinfo[0]==None or typeinfo[0].count('image')<=0:
			inode = self.getInode(path)
			filePath = os.path.join(flickrfsHome, '.'+inode.photoId)
			f = open(filePath, 'w+')
			return f.truncate(size)
		
	def mknod(self, path, mode, dev):
		""" Python has no os.mknod, so we can only do some things """
		log.debug("mknod? OK! Had a close encounter!!:%s:"%(path,))
		templist = path.split('/')
		name_file = templist[-1]
		if name_file.startswith('.') and name_file.count('.meta')>0:
			log.debug("mknod for meta file? No use!")
			return
			#Metadata files will automatically be created. 
			#mknod can't be used for them

		if path.startswith('/sets/'):
			templist[2] = templist[2].split(':')[0]
		elif path.startswith('/stream'):
			templist[1] = templist[1].split(':')[0]
		path = '/'.join(templist)

		log.debug("mknod:After modifying:%s:" % (path))
			

		#Lets guess what kind of a file is this. 
		#Is it an image file? or, some other temporary file
		#created by the tools you're using. 
		typeinfo = mimetypes.guess_type(path)
		if typeinfo[0]==None or typeinfo[0].count('image')<=0:
			f = open(os.path.join(flickrfsHome,'.'+name_file), 'w')
			f.close()
			self.inodeCache[path] = FileInode(path, name_file, mode=mode)
		else:
			self._mkfile(path, id="NEW", mode=mode)

	def mkdir(self, path, mode):
		log.debug("mkdir:" + path + ":")
		if path.startswith("/tags"):
			if path.count('/')==3:   #/tags/personal (or private)/dirname ONLY
				self._mkdir(path)
				background(self.tags_thread, path)
			else:
				e = OSError("Not allowed to create directory:%s:"%(path))
				e.errno = EACCES
				raise e
		elif path.startswith("/sets"):
			if path.count('/')==2:  #Only allow creation of new set /sets/newset
				self._mkdir(path, id=0)
					#id=0 means that not yet created online
			else:
				e = OSError("Not allowed to create directory:%s:"%(path))
				e.errno = EACCES
				raise e
		elif path=='/stream':
			self._mkdir(path)
			background(timerThread, self.stream_thread, self.sync_stream_thread, stream_sync_int)
			
		else:
			e = OSError("Not allowed to create directory:%s:"%(path))
			e.errno = EACCES
			raise e
			
	def utime(self, path, times):
		inode = self.getInode(path)
		inode.atime = times[0]
		inode.mtime = times[1]
		return 0

	def open(self, path, flags):
		log.info("open: " + path)
		ind = path.rindex('/')
		name_file = path[ind+1:]
		if name_file.startswith('.'):
			if name_file.endswith('.meta'):
				return 0
		
		typesinfo = mimetypes.guess_type(path)
		if typesinfo[0]==None or typesinfo[0].count('image')<=0:
			log.debug('open:non-image file found')
			return 0
		
		templist = path.split('/')
		if path.startswith('/sets/'):
			templist[2] = templist[2].split(':')[0]
		elif path.startswith('/stream'):
			templist[1] = templist[1].split(':')[0]
		path = '/'.join(templist)
		log.debug("open:After modifying:%s:" % (path))
		
		inode = self.getInode(path)
		if inode.photoId=="NEW": #Just skip if new (i.e. uploading)
			return 0
		if inode.buf=="":	
			log.debug("Retrieving image from flickr: " + inode.photoId)
			inode.buf = str(self.transfl.getPhoto(inode.photoId))
			inode.size = long(inode.buf.__len__())
			log.debug("Size of image: " + str(inode.size))
		return 0
		
	def read(self, path, len, offset):
		log.debug("read:%s:offset:%s:len:%s:"%(path,offset,len))
		inode = self.getInode(path)

		ind = path.rindex('/')
		name_file = path[ind+1:]
		if name_file.startswith('.'):
			if name_file.endswith('.meta'):
				f = open(os.path.join(flickrfsHome, '.'+inode.photoId), 'r')
				f.seek(offset)
				return f.read(len)

		typesinfo = mimetypes.guess_type(path)
		if typesinfo[0]==None or typesinfo[0].count('image')<=0:
			log.debug('read:non-image file found')
			f = open(os.path.join(flickrfsHome, '.'+inode.photoId), 'r')
			f.seek(offset)
			return f.read(len)
			
		if inode.buf == "":
			log.debug("Retrieving image from flickr: " + inode.photoId)
			inode.buf = str(self.transfl.getPhoto(inode.photoId))
			inode.size = long(inode.buf.__len__())
		sIndex = int(offset)
		ilen = int(len)
		temp = inode.buf[sIndex:sIndex+ilen]
		if temp.__len__() < len:
			del inode.buf
			inode.buf=""
		return temp

	def parse(self, fname, photoId):
		cp = ConfigParser.ConfigParser()
		try:
			log.debug("Parsing file:%s:"%(fname,))
			cp.read(fname)
			options = cp.options('metainfo')
			title=''
			desc=''
			tags=''
			license=''
			if 'description' in options:
				desc = cp.get('metainfo', 'description')
			if 'tags' in options:
				tags = cp.get('metainfo', 'tags')
			if 'title' in options:
				title = cp.get('metainfo', 'title')
			if 'license' in options:
				license = cp.get('metainfo', 'license')
			
			log.debug("Setting metadata:%s:"%(fname,))
			if self.transfl.setMeta(photoId, title, desc)==False:
				return "Error:Can't set Meta information"
				
			log.debug("Setting tags:%s:"%(fname,))
			if self.transfl.setTags(photoId, tags)==False:
				return "Error:Can't set tags"

			log.debug("Setting license:%s:"%(fname,))
			if self.transfl.setLicense(photoId, license)==False:
				return "Error:Can't set license"
						
		except:
			log.error("Can't parse file:%s:"%(fname,))
			return "Error:Can't parse"
		return 'Success:Updated photo:%s:%s:'%(fname,photoId)

	def write(self, path, buf, off):
		log.debug("write:%s:%s"%(path, off))
		
		# I think its better that you wait when you upload photos. 
		# So, dun start a thread. Do it inline!
#			thread.start_new_thread(self.transfl.uploadfile, (path, taglist, inode.buf))
		ind = path.rindex('/')
		name_file = path[ind+1:]
		if name_file.startswith('.') and name_file.count('.meta')>0:
			inode = self.getInode(path)
#			ext = name_file[metaInd+5:]
#			print 'extension:', ext
			fname = os.path.join(flickrfsHome, '.'+inode.photoId) #ext
			log.debug("Writing to :%s:"%(fname,))
			f = open(fname, 'r+')
			f.seek(off)
			f.write(buf)
			f.close()
			if len(buf)<4096:
				inode.size = os.path.getsize(fname)
				retinfo = self.parse(fname, inode.photoId)
				if retinfo.count('Error')>0:
					e = OSError(retinfo.split(':')[1])
					e.errno = EIO
					raise e
			return len(buf)
				
		typesinfo = mimetypes.guess_type(path)
		if typesinfo[0]==None or typesinfo[0].count('image')<=0:
			log.debug('write:non-image file found')
			try:
				inode = self.getInode(path)
			except:
				log.error("inode doesn't exist:%s:"%(path,))
				e = OSError("No inode found")
				e.errno = EIO
				raise e
			fname = os.path.join(flickrfsHome, '.'+inode.photoId)
			f = open(fname, 'r+')
			f.seek(off)
			f.write(buf)
			f.close()
			inode.size = os.path.getsize(fname)
			return len(buf)

		templist = path.split('/')
		if path.startswith('/tags'):
			e = OSError("Copying not allowed")
			e.errno = EIO
			raise e
			
		if path.startswith('/stream'):
			tags = templist[1].split(':')
			templist[1] = tags.pop(0)
			path = '/'.join(templist)
			inode = self.getInode(path)
			inode.buf += buf
			if len(buf) < 4096:
				tags = [ '"%s"'%(a,) for a in tags]
				tags.append('flickrfs')
				taglist = ' '.join(tags)
				id = self.transfl.uploadfile(path, taglist, inode.buf, inode.mode)
				del inode.buf
				inode.buf = ""
				inode.photoId = id

		elif path.startswith('/sets/'):
			setnTags = templist[2].split(':')
			setName = setnTags.pop(0)
			templist[2] = setName
			path = '/'.join(templist)
			inode = self.getInode(path)
			inode.buf += buf

			if len(buf) < 4096:
				templist.pop(-1)
				parentPath = '/'.join(templist)
				pinode = self.getInode(parentPath)
				setnTags = [ '"%s"'%(a,) for a in setnTags]
				setnTags.append('flickrfs')
				taglist = ' '.join(setnTags)
				log.debug("Uploading with tags: %s" % (taglist))
				id = self.transfl.uploadfile(path, taglist, inode.buf, inode.mode)
				del inode.buf
				inode.buf = ""
				inode.photoId = id
				
				#Create set if it doesn't exist online (i.e. if id=0)
				if pinode.setId==0:
					try:
						pinode.setId = self.transfl.createSet(parentPath, id)
					except:
						e = OSError("Can't create a new set")
						e.errno = EIO
						raise e
				else:
					self.transfl.put2Set(pinode.setId, id)
		
		log.debug("After modifying write:%s:%s"%(path, off))
		if len(buf)<4096:
			templist = path.split('/')
			templist.pop(-1)
			parentPath = '/'.join(templist)
			try:
				self.inodeCache.pop(path)
			except:
				pass
			self._mkfileWithMeta(parentPath, id)
		return len(buf)

	def getInode(self, path):
		if self.inodeCache.has_key(path):
			#log.debug("Got cached inode: " + path)
			return self.inodeCache[path]
		else:
			#log.debug("No inode??? I DIE!!!")
			return None


	def release(self, path, flags):
		log.debug("flickrfs.py:Flickrfs:release: %s %s" % (path,flags))
		return 0
	
	def statfs(self):
		"""
	Should return a tuple with the following elements in respective order:
	
	F_BSIZE - Preferred file system block size. (int)
	F_FRSIZE - Fundamental file system block size. (int)
	F_BLOCKS - Total number of blocks in the filesystem. (long)
	F_BFREE - Total number of free blocks. (long)
	F_BAVAIL - Free blocks available to non-super user. (long)
	F_FILES - Total number of file nodes. (long)
	F_FFREE - Total number of free file nodes. (long)
	F_FAVAIL - Free nodes available to non-super user. (long)
	F_FLAG - Flags. System dependent: see statvfs() man page. (int)
	F_NAMEMAX - Maximum file name length. (int)
	Feel free to set any of the above values to 0, which tells
	the kernel that the info is not available.
		"""
		#Not working properly. Block for time being
		return
		log.debug("statfs called")
		block_size = 1024
		fun_block_size = 1024
		total_blocks = 0L
		blocks_free = 0L
		blocks_free_user = 0L
		files = 0L
		files_free = 0L
		files_free_user = 0L
		flag = 0
		namelen = 255
		(max, used) = self.transfl.getBandwidthInfo()
		if max!=None:
			total_blocks = long(int(max)/block_size)
			blocks_free = long( ( int(max)-int(used) )/block_size)
			blocks_free_user = blocks_free

			#files = total_blocks
			#files_free = blocks_free
			#files_free_user = blocks_free_user
			log.debug('total blocks:%s'%(total_blocks))
			log.debug('blocks_free:%s'%(blocks_free))
		return (block_size, fun_block_size, total_blocks, blocks_free, blocks_free_user, files, files_free, files_free_user, namelen)

	def fsync(self, path, isfsyncfile):
		log.debug("flickrfs.py:Flickrfs:fsync: path=%s, isfsyncfile=%s"%(path,isfsyncfile))
		return 0



if __name__ == '__main__':
	try:
		server = Flickrfs()
		server.multithreaded = 1;
		server.main()
	except KeyError:
		log.error('Got key error. Exiting...')
		sys.exit(0)
