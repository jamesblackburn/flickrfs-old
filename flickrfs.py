#!/usr/bin/env python
#@+leo-ver=4
#@+node:@file flickrfs.py
#===============================================================================
#	flickrfs - Virtual Filesystem for Flickr
#    Copyright (c) 2005 Manish Rai Jain  <manishrjain@gmail.com>
#
#    This program can be distributed under the terms of the GNU GPL version 2, or 
#    its later versions. 
#
# DISCLAIMER: The API Key and Shared Secret are provided by the author in 
# the hope that it will prevent unnecessary trouble to the end-user. The 
# author will not be liable for any misuse of this API Key/Shared Secret 
# through this application/derived apps/any 3rd party apps using this key. 
#===============================================================================
#
#@+others
#@+node:imports

from fuse import Fuse
import os
from errno import *
from stat import *
from traceback import format_exc

import thread, array, string, urllib2, traceback, ConfigParser, mimetypes, codecs
#@-node:imports
#@+node:class Xmp

#Some global definitions and functions

# Setup logging
import time, logging, logging.handlers
log = logging.getLogger('flickrfs')
try:
	homedir = os.getenv('HOME')
	flickrfsHome = os.path.join(homedir, '.flickrfs')
	os.mkdir(os.path.join(flickrfsHome))
except:
	pass	#Directory already exists

# Remove previous metadata files from ~/.flickrfs
import glob
files = glob.glob1(flickrfsHome, '.*')
for a in files:
	try:
		os.remove(os.path.join(flickrfsHome, a))
	except:
		pass

loghdlr = logging.handlers.RotatingFileHandler(os.path.join(flickrfsHome,'log'), "a", 5242880, 3)
#loghdlr = logging.handlers.RotatingFileHandler("/var/log/flickrfs", "a", 5242880, 3)
	
logfmt = logging.Formatter("%(asctime)s %(levelname)-10s %(message)s", "%x %X")
loghdlr.setFormatter(logfmt)
log.addHandler(loghdlr)
log.setLevel(logging.DEBUG)

#Import flickr python api
from flickrapi import FlickrAPI

# flickr auth information
flickrAPIKey = "f8aa9917a9ae5e44a87cae657924f42d"  # API key
flickrSecret = "3fbf7144be7eca28"                  # shared "secret"
browserName = "/usr/bin/firefox"                   # for out-of-band auth inside a web browser


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



class TransFlickr:  #Transactions with flickr
	def uploadfile(self, filepath, taglist, bufData, mode):
		public = mode&1 #Set public 4(always), 1(public). Public overwrites f&f
		friends = mode>>3 & 1 #Set friends and family 4(always), 2(family), 1(friends)
		family = mode>>4 & 1
		log.info("Uploading file: " + filepath + ":with data of len:" + str(len(bufData)))
		log.info("Permissions:Family:%s Friends:%s Public:%s"%(family,friends,public))
		rsp = fapi.upload(filename=filepath, jpegData=bufData, api_key=flickrAPIKey, auth_token=token, \
        	        title=os.path.splitext(os.path.basename(filepath))[0], \
                	tags=taglist, \
                	is_public=public and "1" or "0", \
                	is_friend=friends and "1" or "0", \
                	is_family=family and "1" or "0")

		if rsp==None:
			log.error("Can't write file: " + filepath)
		else:
			retinfo = fapi.returntestFailure(rsp)
			if retinfo=="OK":
				id = rsp.photoid[0].elementText
				log.info("File uploaded:" + filepath + ":with photoid:" + id + ":")
				return id
			else:
				log.error(retinfo)
	def put2Set(self, set_id, photo_id):
		log.info("Uploading photo:"+photo_id+":to set_id:"+set_id)
		rsp = fapi.photosets_addPhoto(api_key=flickrAPIKey, auth_token=token,\
				photoset_id=set_id, photo_id=photo_id)

		retinfo = fapi.returntestFailure(rsp)
		if retinfo=="OK":
			log.info("Uploaded photo to set")
		else:
			log.error(retinfo)
	
	def createSet(self, path, photo_id):
		log.info("Creating set:%s:with primary photo:%s:"%(path,photo_id))
		ind = path.rindex('/')
		title = path[ind+1:]
		rsp = fapi.photosets_create(api_key=flickrAPIKey, auth_token=token,\
			title=title, primary_photo_id=photo_id)
		retinfo = fapi.returntestFailure(rsp)
		if retinfo=="OK":
			log.info("Created set:%s:"%(title))
			return rsp.photoset[0]['id']
		else:
			log.error(retinfo)
	
	def deleteSet(self, set_id):
		log.info("Deleting set:%s:"%(set_id))
		if str(set_id)=="0":
			log.info("The set is not existant online.")
			return
			
		rsp = fapi.photosets_delete(api_key=flickrAPIKey, auth_token=token,\
			photoset_id=set_id)
		retinfo = fapi.returntestFailure(rsp)
		if retinfo=="OK":
			log.info("Deleted set")
		else:
			log.error(retinfo)
	
	def getPhotoInfo(self, photoId):
		try:
			rsp = fapi.photos_getInfo(photo_id=photoId, api_key=flickrAPIKey, auth_token=token)
		except:
			return None
		retinfo = fapi.returntestFailure(rsp)
		if retinfo!="OK":
			log.error("Can't retrieve information about photo: " + photoId)
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

		permcomment = rsp.photo[0].permissions[0]['permcomment']
		permaddmeta = rsp.photo[0].permissions[0]['permaddmeta']
		commMeta = permcomment + permaddmeta #Just add both. Required for chmod
		desc = rsp.photo[0].description[0].elementText
		title = rsp.photo[0].title[0].elementText
		taglist = []
		if hasattr(rsp.photo[0].tags[0], "tag"):
			for a in rsp.photo[0].tags[0].tag:
				taglist.append(a.elementText)
		license = rsp.photo[0]['license']
		# (format, mode, commMeta, desc, title, taglist, license)
		return (format, mode, commMeta, desc, title, taglist, license)

	def setPerm(self, photoId, mode, comm_meta):
		public = mode&1 #Set public 4(always), 1(public). Public overwrites f&f
		friends = mode>>3 & 1 #Set friends and family 4(always), 2(family), 1(friends)
		family = mode>>4 & 1
		rsp = fapi.photos_setPerms(api_key=flickrAPIKey, auth_token=token, is_public=str(public),\
			is_friend=str(friends), is_family=str(family), perm_comment=comm_meta[0],\
			perm_addmeta=comm_meta[1], photo_id=photoId)
		retinfo = fapi.returntestFailure(rsp)
		if retinfo != "OK":
			log.error("Couldn't set permission:%s:"%(photoId,))
			return False
		else:
			return True

	def setTags(self, photoId, tags):
		templist = [ '"%s"'%(a,) for a in string.split(tags, ',')]
		templist.append('flickrfs')
		tagstring = ' '.join(templist)
		rsp = fapi.photos_setTags(api_key=flickrAPIKey, auth_token=token, \
			photo_id=photoId, tags=tagstring)
		retinfo = fapi.returntestFailure(rsp)
		if retinfo != "OK":
			log.error("Couldn't set tags:%s:"%(photoId,))
			log.error("setTags: retinfo:%s"%(retinfo,))
			return False
		return True
	
	def setMeta(self, photoId, title, desc):
		rsp = fapi.photos_setMeta(api_key=flickrAPIKey, auth_token=token, \
			photo_id=photoId, title=title, description=desc)
		retinfo = fapi.returntestFailure(rsp)
		if retinfo != "OK":
			log.error("Couldn't set meta info:%s:"%(photoId,))
			log.error("retinfo:%s"%(retinfo,))
			return False
		return True

	def getLicenses(self):
		try:
			rsp = fapi.photos_licenses_getInfo(api_key=flickrAPIKey, auth_token=token)
		except:
			return None
		retinfo = fapi.returntestFailure(rsp)
		if retinfo != "OK":
			log.error("retinfo:%s"%(retinfo,))
			return None
		licenseDict = {}
		for l in rsp.licenses[0].license:
			licenseDict[l['id']] = l['name']

		return licenseDict
		
	def setLicense(self, photoId, license):
		rsp = fapi.photos_licenses_setLicense(api_key=flickrAPIKey, auth_token=token,\
			photo_id=photoId, license_id=license)
		retinfo = fapi.returntestFailure(rsp)
		if retinfo != "OK":
			log.error("Couldn't set license info:%s:"%(photoId,))
			log.error("retinfo:%s"%(retinfo,))
			return False
		return True

	def getPhoto(self, photoId):
		try:
			rsp = fapi.photos_getSizes(photo_id=photoId, api_key=flickrAPIKey, auth_token=token)
		except:
			log.error("Error while trying to retrieve size information:%s:"%(photoId,))
			return ""

		retinfo = fapi.returntestFailure(rsp)
		if retinfo!="OK":
			log.error("Can't get information about photo: " + photoId)
			return None
		buf = ""
		for a in rsp.sizes[0].size:
			if a['label']=='Large':
				try:
					f = urllib2.urlopen(a['source'])
					buf = f.read()
				except:
					return ""
		return buf

	def removePhotofromSet(self, photoId, photosetId):
		rsp = fapi.photosets_removePhoto(api_key=flickrAPIKey, auth_token=token,\
			photo_id=photoId, photoset_id=photosetId)
		retinfo = fapi.returntestFailure(rsp)
		if retinfo=="OK":
			log.info("Photo removed from set")
		else:
			log.error(retinfo)
			
		
	def getBandwidthInfo(self):
		log.debug("Retrieving bandwidth information")
		try:
			rsp = fapi.people_getUploadStatus(api_key=flickrAPIKey, auth_token=token)
		except:
			log.error("Error while trying to retrieve upload information")
			return (None,None)

		retinfo = fapi.returntestFailure(rsp)
		bw = rsp.user[0].bandwidth[0]
		log.debug("Bandwidth: max:" + bw['max'])
		log.debug("Bandwidth: used:" + bw['used'])
		if retinfo=="OK":
			return (bw['max'], bw['used'])
		else:
			log.error("Can't retrieve bandwidth information")
			return (None,None)

	def getUserId(self):
		try:
			rsp = fapi.auth_checkToken(api_key=flickrAPIKey, auth_token=token)
		except:
			log.error("Not able to retrieve user Id")
			return None

		retinfo = fapi.returntestFailure(rsp)
		if retinfo=="OK":
			usr = rsp.auth[0].user[0]
			log.info("Got NSID:"+ usr['nsid'] + ":")
			return usr['nsid']
		else:
			return None


class Inode(object):
	"""Common base class for all file system objects
	"""

	def __init__(self, path=None, id='', mode=0, size=0L, mtime=None, ctime=None):
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
		else: self.mtime = mtime
		if ctime is None: self.ctime = now
		else: self.ctime = ctime
		self.blocksize = DefaultBlockSize


class DirInode(Inode):

	def __init__(self, path=None, id="", mode=0, mtime=None, ctime=None):
		super(DirInode, self).__init__(path, id, mode, 0L, mtime, ctime)
		if self.mode==0: self.mode = S_IFDIR | 0755
		else: self.mode = S_IFDIR | self.mode
		self.nlink += 1
		self.dirfile = ""
                self.setId = self.id


class FileInode(Inode):

	def __init__(self, path=None, id="", mode=0, comm_meta="", size=1L, mtime=None, ctime=None):
		super(FileInode, self).__init__(path, id, mode, size, mtime, ctime)
		if self.mode==0: self.mode = S_IFREG | 0644
		else: self.mode = S_IFREG | self.mode
		self.buf = ""
		self.photoId = self.id
		self.comm_meta = comm_meta

		

class Flickrfs(Fuse):

	#@@+others

	extras = "original_format,date_upload,last_update"
    
	#@+node:__init__
    	def __init__(self, *args, **kw):
    
        	Fuse.__init__(self, *args, **kw)
    
        	if 1:
            		log.info("flickrfs.py:Flickrfs:mountpoint: %s" % repr(self.mountpoint))
            		log.info("flickrfs.py:Flickrfs:unnamed mount options: %s" % self.optlist)
	       		log.info("flickrfs.py:Flickrfs:named mount options: %s" % self.optdict)
	    		log.info("Authorizing with flickr...")
	    		# initialise FlickrAPI object
		
		self.inodeCache = {}  #Cached inodes for faster access
#		self.listDir = {} #Store the file names inside the directory
		self.NSID = ""
		global fapi
    		global token
		global DefaultBlockSize
		DefaultBlockSize = 4*1024  #4KB
		fapi = FlickrAPI(flickrAPIKey, flickrSecret)

		# proceed with auth
		# TODO use auth.checkToken function if available, and wait after opening browser
		try:
			token = fapi.getToken(browser = browserName)
		except:
			print ("Can't retrieve token from browser:%s:"%(browserName,))
			log.error("Can't retrieve token from browser:%s:"%(browserName,))
			sys.exit(-1)

		if token == None:
			log.error('Not able to authorize. Exiting...')
			sys.exit(-1)
	    		#Add some authorization checks here(?)
		log.info('Authorization complete')
		
		self.NSID = TransFlickr().getUserId()
		if self.NSID==None:
			print "Can't retrieve user information"
			log.error("Initialization:Can't retrieve user information")
			sys.exit(-1)

		log.info('Getting list of licenses available')
		self.licenseDict = TransFlickr().getLicenses()
		if self.licenseDict==None:
			print "Can't retreive license information"
			log.error("Initialization:Can't retrieve license information")
			sys.exit(-1)

		# do stuff to set up your filesystem here, if you want
		self._mkdir("/")
		self._mkdir("/tags")
		self._mkdir("/tags/personal")
		self._mkdir("/tags/public")
        	background(self.sets_thread)

	def writeMetaInfo(self, id, INFO):
		#The metadata may be unicode strings, so we need to encode them on write
		f = codecs.open(os.path.join(flickrfsHome, '.'+id), 'w', 'utf8')
		f.write('#Metadata file : flickrfs - Virtual filesystem for flickr\n')
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


	#@+node:sets_thread
	def sets_thread(self):
		"""
        	The beauty of the FUSE python implementation is that with the python interp
        	running in foreground, you can have threads
        	"""    
		log.info("sets_thread: started")
		self._mkdir("/sets")
		try:
			rsp = fapi.photosets_getList(api_key=flickrAPIKey, auth_token=token)
		except:
			log.error("Can't retrieve information about sets.")
			log.error("You may wish to remount the filesystem")
			return 

		retinfo = fapi.returntestFailure(rsp)
		if retinfo!="OK":
			return
		if hasattr(rsp.photosets[0], "photoset"):
			for a in rsp.photosets[0].photoset:
				title = a.title[0].elementText.replace('/', ' ')
				curdir = "/sets/" + title
				if title.strip()=='':
					curdir = "/sets/" + a['id']
				set_id = a['id']
				self._mkdir(curdir, id=set_id)
				try:
					photos = fapi.photosets_getPhotos(api_key=flickrAPIKey, photoset_id=set_id, auth_token=token,
						extras=self.extras)
				except:
					log.error("sets_thread:Error while trying to retrieve photos from photoset:%s:"%(a.title[0].elementText,))
					log.error(format_exc())
					return
					
				retinfo = fapi.returntestFailure(photos)
				if retinfo=="OK":
					for b in photos.photoset[0].photo:
				# (format, mode, commMeta, desc, title, tags)
						INFO = TransFlickr().getPhotoInfo(b['id'])
						if INFO==None:
							log.error("Can't retrieve info:%s:"%(b['id'],))
							continue
						title = b['title'].replace('/', ' ')
						if title.strip()=='':
							title = str(b['id'])
						title = title[:32]   #Only allow 32 characters
						title = title + "." + INFO[0]
						self.writeMetaInfo(b['id'], INFO) #Write to a localfile
						self._mkfile(curdir+'/'+title, id=str(b['id']),\
							MODE=INFO[1], comm_meta=INFO[2], mtime=int(b['lastupdate']),
							ctime=int(b['dateupload']))
						
						
	#@-node:sets_thread
	
	def stream_thread(self, path):
		try:
			rsp = fapi.photos_search(api_key=flickrAPIKey, user_id=self.NSID, per_page="500", extras=self.extras,
				auth_token=token)
		except:
			log.error("stream_thread:Error while trying to get stream")
			return

		retinfo = fapi.returntestFailure(rsp)
		if retinfo!="OK":
			log.error("Can't retrive photos from your stream")
			log.error("retinfo:%s"%(retinfo,))
			return
		if hasattr(rsp.photos[0], 'photo'):
			for b in rsp.photos[0].photo:
				# (format, mode, commMeta, desc, title, tags)
				INFO = TransFlickr().getPhotoInfo(b['id'])
				if INFO==None:
					log.error("Can't retrieve info:%s:"%(b['id'],))
					continue
				title = b['title'].replace('/', ' ')
				if title.strip()=='':
					title = str(b['id'])
				title = title[:32]   #Only allow 32 characters
				title = title + "." + INFO[0]
				self.writeMetaInfo(b['id'], INFO) #Write to a localfile
				self._mkfile(path+'/'+title, id=b['id'],\
					MODE=INFO[1], comm_meta=INFO[2], mtime=int(b['lastupdate']), ctime=int(b['dateupload']))
				
			
	
	def tags_thread(self, path):
		ind = string.rindex(path, '/')
		tagName = path[ind+1:]
		if tagName.strip()=='':
			log.error("The tagName:%s: doesn't contain any tags"%(tagName))
			return 

		log.info("tags_thread:" + tagName + ":started")
		sendtagList = ','.join(tagName.split(':'))

		if(path.startswith('/tags/personal')):
			try:
				tags_rsp = fapi.photos_search(api_key=flickrAPIKey,user_id=self.NSID,\
					tags=sendtagList, extras=self.extras, tag_mode="all", per_page="500", auth_token=token)
			except:
				log.error("tags_thread:Error while trying to search personal photos")
				log.error(format_exc())
				return
			personal = True
		elif(path.startswith('/tags/public')):
			try:
				tags_rsp = fapi.photos_search(api_key=flickrAPIKey, tags=sendtagList,\
					tag_mode="all", extras=self.extras, per_page="500")
			except:
				log.error("tags_thread:Error while trying to search public photos")
				log.error(format_exc())
				return
			personal = False
		else:
			return

		log.debug("Search for photos with tag:" + sendtagList + ":done")
		retinfo = fapi.returntestFailure(tags_rsp)
		if retinfo!="OK":
			log.error("Couldn't search for the photos")
			log.error("retinfo:%s"%(retinfo,))
			return
		
		if hasattr(tags_rsp.photos[0], 'photo'):
			for b in tags_rsp.photos[0].photo:
				if personal:
					INFO = TransFlickr().getPhotoInfo(b['id'])
					if INFO==None:
						log.error("Can't retrieve info:%s:"%(b['id'],))
						continue
					title = b['title'].replace('/', ' ')
					if title.strip()=='':
						title = str(b['id'])
					title = title[:32]   #Only allow 32 characters
					title = title + "." + INFO[0]
					self.writeMetaInfo(b['id'], INFO) #Write to a localfile
					self._mkfile(path +"/" + title, id=b['id'],\
						MODE=INFO[1], comm_meta=INFO[2], mtime=int(b['lastupdate']), ctime=int(b['dateupload']))
				else:
					title = b['title'].replace('/', ' ')
					if title.strip()=='':
						title = str(b['id'])
					title = title[:32]   #Only allow 32 characters
					title = title + "." + b['originalformat']
					self._mkfile(path+'/'+title, id=b['id'],\
						mtime=int(b['lastupdate']), ctime=int(b['dateupload']))
	
	#@+node:attribs
    	flags = 1
	#@-node:attribs

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

	def _mkdir(self, path, id="", MODE=0, comm_meta="", mtime=None, ctime=None):
		path, id, parentDir, name = self._parsepathid(path, id)
		log.debug("Creating directory:" + path)
		self.inodeCache[path] = DirInode(path, id, mtime=mtime, ctime=ctime)
		if path=='/':
			log.debug("This is root already. Can't find parent of GOD!!!")
		else:
			pinode = self.getInode(parentDir)
			pinode.nlink += 1

	def _mkfile(self, path, id="", MODE=0, comm_meta="", mtime=None, ctime=None):
		path, id, parentDir, name = self._parsepathid(path, id)
		log.debug("Creating file:" + path + ":with id:" + id)
		image_name, extension = os.path.splitext(name)
		if not extension:
			log.error("Can't create such a file")
			return
		self.inodeCache[path] = FileInode(path, id, mode=MODE, comm_meta=comm_meta, mtime=mtime, ctime=ctime)
		# Now create the meta info file
		path = parentDir + '/.' + image_name + '.meta'
		try:
			size = os.path.getsize(os.path.join(flickrfsHome, '.'+id))
			self.inodeCache[path] = FileInode(path, id, mode=0644, size=size)
		except:
			pass

	#@+node:getattr
    	def getattr(self, path):
    		log.debug("getattr:" + path + ":")
		if path.startswith('/sets/'):
			templist = path.split('/')
			ind = templist.index('sets')
			setName = templist[ind+1].split(':')[0]
			templist[2] = setName
			path = '/'.join(templist)
			log.debug("getattr:After modifying:%s:" % (path))

		inode=self.getInode(path)
        	if inode:
			log.debug("inode "+str(inode))
            		statTuple = (inode.mode,inode.ino,inode.dev,inode.nlink, \
				inode.uid,inode.gid,inode.size,inode.atime,inode.mtime,inode.ctime)
                	log.debug("statsTuple "+str(statTuple))
            		return statTuple
        	else:
			e = OSError("No such file"+path)
            		e.errno = ENOENT
           		raise e

	#@-node:getattr

	#@+node:readlink
    	def readlink(self, path):
    		log.debug("readlink")
    		return os.readlink(path)
    	#@-node:readlink
	
    	#@+node:getdir
    	def getdir(self, path):
    		log.debug("getdir:" + path)
#		return map(lambda x: (x,0),  self.listDir[path])
		templist = ['.', '..']
		for a in self.inodeCache.keys():
			ind = a.rindex('/')
			if path=='/':
				path=""
			if path==a[:ind]:
				name = a.split('/')[-1]
				if name!="":
					templist.append(name)
		return map(lambda x: (x,0), templist)

    	#@-node:getdir
	
    	#@+node:unlink
    	def unlink(self, path):
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
				TransFlickr().removePhotofromSet(photoId=inode.photoId, photosetId=pinode.setId)
	
			del inode
		else:
			log.error("Can't find what you want to remove")
			#Dont' raise an exception. Not useful when
			#using editors like Vim. They make loads of 
			#crap buffer files
    	#@-node:unlink
	
    	#@+node:rmdir
    	def rmdir(self, path):
		log.debug("rmdir:%s:"%(path))
		if self.inodeCache.has_key(path):
			for a in self.inodeCache.keys():
				if a.startswith(path+'/'):
					e = OSError("Directory not empty")
					e.errno = ENOTEMPTY
					raise e
		else:
			log.error("Can't find the directory you want to remove")
			e = OSError("No such folder"+path)
            		e.errno = ENOENT
           		raise e
			
		ind = path.rindex('/')
		pPath = path[:ind]
		if path.startswith('/tags/personal/'):	
			inode = self.inodeCache.pop(path)
			del inode
			pInode = self.getInode(pPath)
			pInode.nlink -= 1
		elif path.startswith('/tags/public/'):
			inode = self.inodeCache.pop(path)
			del inode
			pInode = self.getInode(pPath)
			pInode.nlink -= 1
		elif path.startswith('/sets/'):
			inode = self.inodeCache.pop(path)
			TransFlickr().deleteSet(inode.setId)
			del inode
			pInode = self.getInode(pPath)
			pInode.nlink -= 1
		else:
    			log.debug("rmdir!! I refuse to do anything! <Stubborn>")
			e = OSError("Removal of folder %s not allowed" % (path))
			e.errno = EPERM
			raise e
			
	#    	return os.rmdir(path)	
	#@-node:rmdir
	
    	#@+node:symlink
    	def symlink(self, path, path1):
    		log.debug("symlink")
    		return os.symlink(path, path1)	
    	#@-node:symlink
    
    	#@+node:rename
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
		fname = os.path.join(flickrfsHome, '.'+inode.photoId)
		f = open(fname, 'r')
		buf = f.read()
		f.close()
		
		#Now write to path1
		inode = self.getInode(path1)
		fname = os.path.join(flickrfsHome, '.'+inode.photoId)
		f = open(fname, 'w')
		f.write(buf)
		f.close()
		inode.size = os.path.getsize(fname)
		retinfo = self.parse(fname, inode.photoId)
		if retinfo.count('Error')>0:
			log.error(retinfo)
#    		return os.rename(path, path1)
	#@-node:rename
	    
	#@+node:link
	def link(self, path, path1):
		log.debug("link")
#    		return os.link(path, path1)
	#@-node:link
	    
	#@+node:chmod
	def chmod(self, path, mode):
		log.debug("chmod. Oh! So, you found use as well!")
		inode = self.getInode(path)
		typesinfo = mimetypes.guess_type(path)

		if inode.comm_meta==None:
			log.debug("chmod on directory? No use la!")
			return
				
#		elif typesinfo[0]==None or typesinfo[0].count('image')<=0:
		else:
			inode.mode = mode
			return

		if TransFlickr().setPerm(inode.photoId, mode, inode.comm_meta)==True:
			inode.mode = mode
	#@-node:chmod
	    
	#@+node:chown
	def chown(self, path, user, group):
		log.debug("chown. Are you of any use in flickrfs?")
	#    	return os.chown(path, user, group)
	#@-node:chown
	    
	#@+node:truncate
	def truncate(self, path, size):
	#   	log.debug("truncate?? WTF for?")
		log.debug("truncate?? Okay okay! I accept your usage:%s:%s"%(path,size))
		ind = path.rindex('/')
		name_file = path[ind+1:]

		typeinfo = mimetypes.guess_type(path)
		if typeinfo[0]==None or typeinfo[0].count('image')<=0:
			inode = self.getInode(path)
			filePath = os.path.join(flickrfsHome, '.'+inode.photoId)
			f = open(filePath, 'w+')
			return f.truncate(size)
	#    	f = open(path, "w+")
	#    	return f.truncate(size)
	#@-node:truncate
	    
	#@+node:mknod
	def mknod(self, path, mode, dev):
		""" Python has no os.mknod, so we can only do some things """
		log.debug("mknod? OK! Had a close encounter!!:%s:"%(path,))
		ind = path.rindex('/')
		name_file = path[ind+1:]
		if name_file.startswith('.'):
			if name_file.count('.meta')>0:
				log.debug("mknod for meta file? No use!")
				return
					#Metadata files will automatically be created. 
					#mknod can't be used for them

		if path.startswith('/sets/'):
			templist = path.split('/')
			ind = templist.index('sets')
			setName = templist[ind+1].split(':')[0]
			templist[2] = setName
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
			self._mkfile(path, id="NEW", MODE=mode)

#    		if S_ISREG(mode):
#    			open(path, "w")
#    		else:
#    			return -EINVAL
    	#@-node:mknod
    	#@+node:mkdir
    	def mkdir(self, path, mode):
#    		return os.mkdir(path, mode)
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
			background(self.stream_thread, path)
			
		else:
			e = OSError("Not allowed to create directory:%s:"%(path))
			e.errno = EACCES
			raise e
			

    	#@-node:mkdir
    	#@+node:utime
    	def utime(self, path, times):
		inode = self.getInode(path)
		inode.atime = times[0]
		inode.mtime = times[1]
#    		return os.utime(path, times)
		return 0
    	#@-node:utime
    	#@+node:open
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
		
		if path.startswith('/sets/'):
			templist = path.split('/')
			ind = templist.index('sets')
			setName = templist[ind+1].split(':')[0]
			templist[2] = setName
			path = '/'.join(templist)
			log.debug("open:After modifying:%s:" % (path))
		
		inode = self.getInode(path)
		if inode.photoId=="NEW": #Just skip if new (i.e. uploading)
			return 0
		if inode.buf=="":	
			log.debug("Retrieving image from flickr: " + inode.photoId)
			inode.buf = str(TransFlickr().getPhoto(inode.photoId))
			inode.size = long(inode.buf.__len__())
			log.debug("Size of image: " + str(inode.size))
		return 0
	    
	#@-node:open
	#@+node:read
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
			inode.buf = str(TransFlickr().getPhoto(inode.photoId))
			inode.size = long(inode.buf.__len__())
		sIndex = int(offset)
		ilen = int(len)
    		temp = inode.buf[sIndex:sIndex+ilen]
		if temp.__len__() < len:
			del inode.buf
			inode.buf=""
		return temp
    
	#@-node:read

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
			if TransFlickr().setMeta(photoId, title, desc)==False:
				return "Error:Can't set Meta information"
				
			log.debug("Setting tags:%s:"%(fname,))
			if TransFlickr().setTags(photoId, tags)==False:
				return "Error:Can't set tags"

			log.debug("Setting license:%s:"%(fname,))
			if TransFlickr().setLicense(photoId, license)==False:
				return "Error:Can't set license"
						
		except:
			log.error("Can't parse file:%s:"%(fname,))
			return "Error:Can't parse"
		return 'Success:Updated photo:%s:%s:'%(fname,photoId)

    	#@+node:write
    	def write(self, path, buf, off):
		log.debug("write:" + path)
		
		# I think its better that you wait when you upload photos. 
		# So, dun start a thread. Do it inline!
#			thread.start_new_thread(TransFlickr().uploadfile, (path, taglist, inode.buf))
		ind = path.rindex('/')
		name_file = path[ind+1:]
		if name_file.startswith('.') and name_file.count('.meta')>0:
			inode = self.getInode(path)
#			ext = name_file[metaInd+5:]
#			print 'extension:', ext
			fname = os.path.join(flickrfsHome, '.'+inode.photoId) #+ext
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
		
		if path.startswith('/tags/'):
			inode = self.getInode(path)
			inode.buf += buf
			if len(buf) < 4096:
				eind = path.rindex('/')
				sind = path.rindex('/',0,eind)
				tags = string.split(path[sind+1:eind], ':')
				tags = [ '"%s"'%(a,) for a in tags]
				tags.append('flickrfs')
				taglist = ' '.join(tags)
				id = TransFlickr().uploadfile(path, taglist, inode.buf, inode.mode)
				del inode.buf
				inode.buf = ""
				inode.photoId = id

		elif path.startswith('/sets/'):
			templist = path.split('/')
			ind = templist.index('sets')
			setnTags = templist[ind+1].split(':')
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
				id = TransFlickr().uploadfile(path, taglist, inode.buf, inode.mode)
				del inode.buf
				inode.buf = ""
				inode.photoId = id
				
				#Create set if it doesn't exist online (i.e. if id=0)
				if pinode.setId==0:
					try:
						pinode.setId = TransFlickr().createSet(parentPath, id)
					except:
						e = OSError("Can't create a new set")
						e.errno = EIO
						raise e
				else:
					TransFlickr().put2Set(pinode.setId, id)
				
    		return len(buf)
	#@-node:write

	#@+node:getInode
	def getInode(self, path):
		if self.inodeCache.has_key(path):
			log.debug("Got cached inode: " + path)
			return self.inodeCache[path]
		else:
			log.debug("No inode??? I DIE!!!")
			return None

	#@-node:getInode

	#@+node:release
	def release(self, path, flags):
	        log.debug("flickrfs.py:Flickrfs:release: %s %s" % (path,flags))
	        return 0
	#@-node:release
	
	#@+node:statfs
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
		(max, used) = TransFlickr().getBandwidthInfo()
		if max!=None:
			total_blocks = long(int(max)/block_size)
			blocks_free = long( ( int(max)-int(used) )/block_size)
			blocks_free_user = blocks_free
			log.debug('total blocks:%s'%(total_blocks))
			log.debug('blocks_free:%s'%(blocks_free))
        	return (block_size, fun_block_size, total_blocks, blocks_free, blocks_free_user, \
			files, files_free, files_free_user, namelen)
	#@-node:statfs
	#@+node:fsync
	def fsync(self, path, isfsyncfile):
	        log.debug("flickrfs.py:Flickrfs:fsync: path=%s, isfsyncfile=%s"%(path,isfsyncfile))
	        return 0
    
	#@-node:fsync

#@+node:mainline
if __name__ == '__main__':
	try:
		server = Flickrfs()
		server.multithreaded = 1;
		server.main()
	except KeyError:
		log.error('Got key error. Exiting...')
		sys.exit(0)
#@-node:mainline
#@-leo
