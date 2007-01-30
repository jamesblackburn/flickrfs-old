#===============================================================================
#  flickrfs - Virtual Filesystem for Flickr
#  Copyright (c) 2005,2006 Manish Rai Jain  <manishrjain@gmail.com>
#
#  This program can be distributed under the terms of the GNU GPL version 2, or 
#  its later versions. 
#
# DISCLAIMER: The API Key and Shared Secret are provided by the author in 
# the hope that it will prevent unnecessary trouble to the end-user. The 
# author will not be liable for any misuse of this API Key/Shared Secret 
# through this application/derived apps/any 3rd party apps using this key. 
#===============================================================================

import os, sys, time
from stat import *
import bsddb, cPickle

DEFAULTBLOCKSIZE = 4*1024 # 4 KB

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
    if mtime is None:
      self.mtime = now
    else:
      self.mtime = int(mtime)
    if ctime is None:
      self.ctime = now
    else:
      self.ctime = int(ctime)
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
  def __init__(self, path=None, id="", mode=None, comm_meta="", size=0L, mtime=None, ctime=None):
    if mode is None: mode = 0644
    super(FileInode, self).__init__(path, id, mode, size, mtime, ctime)
    self.mode = S_IFREG | self.mode
    self.photoId = self.id
    self.comm_meta = comm_meta


class ImageCache:
  def __init__(self):
    self.bufDict = {}

  def setBuffer(self, id, buf):
    self.bufDict[id] = buf

  def addBuffer(self, id, inc):
    buf = self.getBuffer(id)
    self.setBuffer(id, buf+inc)

  def getBuffer(self, id, start=0, end=0):
    if end == 0:
      return self.bufDict.get(id, "")[start:]
    else:
      return self.bufDict.get(id, "")[start:end]

  def getBufLen(self, id):
    return long(len(self.bufDict.get(id, "")))

  def popBuffer(self, id):
    if id in self.bufDict:
      return self.bufDict.pop(id)


class InodeCache(dict):
  def __init__(self, dbPath):
    dict.__init__(self)
    self.db = bsddb.btopen(dbPath, flag='c')
    # Keep the keys in memory.
    self.keysCache = set()
  
  def __getitem__(self, key):
    valObjStr = self.db.get(key)
    if valObjStr != None:
      return cPickle.loads(valObjStr)
    else:
      return None

  def __setitem__(self, key, value):
    self.keysCache.add(key)
    self.db[key] = cPickle.dumps(value)
  
  def keys(self):
    return list(self.keysCache)
  
  def pop(self, k, *args):
    valObjStr = self.db.pop(k, *args)
    self.keysCache.discard(k)
    if valObjStr != None:
      return cPickle.loads(valObjStr)

  def has_key(self, k):
    return self.keysCache.__contains__(k)
