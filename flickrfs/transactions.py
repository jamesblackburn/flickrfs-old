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

__author__ =  "Manish Rai Jain (manishrjain@gmail.com)"
__license__ = "GPLv2 (details at http://www.gnu.org/licenses/licenses.html#GPL)"

from flickrapi import FlickrAPI
from traceback import format_exc
import urllib2
import sys
import string
import os
import time
import logging
log = logging.getLogger('flickrfs.trans')

# flickr auth information
flickrAPIKey = "f8aa9917a9ae5e44a87cae657924f42d"  # API key
flickrSecret = "3fbf7144be7eca28"  # shared "secret"

# Utility functions
def kwdict(**kw): return kw

#Transactions with flickr, wraps FlickrAPI 
# calls in Flickfs-specialized functions.
class TransFlickr: 

  extras = "original_format,date_upload,last_update"

  def __init__(self, browserName):
    self.fapi = FlickrAPI(flickrAPIKey, flickrSecret)
    self.user_id = ""
    # proceed with auth
    # TODO use auth.checkToken function if available, 
    # and wait after opening browser.
    print "Authorizing with flickr..."
    log.info("authorizing with flickr...")
    try:
      self.authtoken = self.fapi.getToken(browser=browserName)
    except:
      print ("Can't retrieve token from browser %s" % browserName)
      print ("\tIf you're behind a proxy server,"
             " first set http_proxy environment variable.")
      print "\tPlease close all your browser windows, and try again"
      log.error(format_exc())
      log.error("can't retrieve token from browser %s", browserName)
      sys.exit(-1)
    if self.authtoken == None:
      print "Unable to authorize (reason unknown)"
      log.error('not able to authorize; exiting')
      sys.exit(-1)
        #Add some authorization checks here(?)
    print "Authorization complete."
    log.info('authorization complete')
    
  def uploadfile(self, filepath, taglist, bufData, mode):
    #Set public 4(always), 1(public). Public overwrites f&f.
    public = mode&1
    #Set friends and family 4(always), 2(family), 1(friends).
    friends = mode>>3 & 1
    family = mode>>4 & 1
      #E.g. 745 - 4:No f&f, but 5:public
      #E.g. 754 - 5:friends, but not public
      #E.g. 774 - 7:f&f, but not public

    log.info("uploading file %s", filepath)
    log.info("  data length: %s", len(bufData))
    log.info("  taglist: %s", taglist)
    log.info("  permissions: family %s, friends %s, public %s",
             family, friends, public)
    filename = os.path.splitext(os.path.basename(filepath))[0]
    rsp = self.fapi.upload(filename=filepath, jpegData=bufData,
          title=filename,
          tags=taglist,
          is_public=public and "1" or "0",
          is_friend=friends and "1" or "0",
          is_family=family and "1" or "0")

    if rsp is None:
      log.error("response None from attempt to write file %s", filepath)
      log.error("will attempt recovery...")
      recent_rsp = None
      trytimes = 2
      while(trytimes):
        log.info("sleeping for 3 seconds...")
        time.sleep(3)
        trytimes -= 1
        # Keep on trying to retrieve the recently uploaded photo, till we
        # actually get the information, or the function throws an exception.
        while(recent_rsp is None or not recent_rsp):
          recent_rsp = self.fapi.photos_recentlyUpdated(
              auth_token=self.authtoken, min_date='1', per_page='1')
        
        pic = recent_rsp.photos[0].photo[0]
        log.info('we are looking for %s', filename)
        log.info('most recently updated pic is %s', pic['title'])
        if filename == pic['title']:
          id = pic['id']
          log.info("file %s uploaded with photoid %s", filepath, id)
          return id
      log.error("giving up; upload of %s appears to have failed", filepath)
      return None
    else:
      id = rsp.photoid[0].elementText
      log.info("file %s uploaded with photoid %s", filepath, id)
      return id

  def put2Set(self, set_id, photo_id):
    log.info("uploading photo %s to set id %s", photo_id, set_id)
    rsp = self.fapi.photosets_addPhoto(auth_token=self.authtoken, 
                                       photoset_id=set_id, photo_id=photo_id)
    if rsp:
      log.info("photo uploaded to set")
    else:
      log.error(rsp.errormsg)
  
  def createSet(self, path, photo_id):
    log.info("creating set %s with primary photo %s", path, photo_id)
    path, title = os.path.split(path)
    rsp = self.fapi.photosets_create(auth_token=self.authtoken, 
                                     title=title, primary_photo_id=photo_id)
    if rsp:
      log.info("created set %s", title)
      return rsp.photoset[0]['id']
    else:
      log.error(rsp.errormsg)
  
  def deleteSet(self, set_id):
    log.info("deleting set %s", set_id)
    if str(set_id)=="0":
      log.info("ignoring attempt to delete set wtih set_id 0 (a locally "
        "created set that has not yet acquired an id via uploading")
      return
    rsp = self.fapi.photosets_delete(auth_token=self.authtoken, 
                                     photoset_id=set_id)
    if rsp:
      log.info("deleted set %s", set_id)
    else:
      log.error(rsp.errormsg)
  
  def getPhotoInfo(self, photoId):
    log.debug("id: %s", photoId)
    rsp = self.fapi.photos_getInfo(auth_token=self.authtoken, photo_id=photoId)
    if not rsp:
      log.error("can't retrieve information about photo %s; got error %s",
                photoId, rsp.errormsg)
      return None
    #XXX: should see if there's some other 'format' option we can fall back to.
    try: format = rsp.photo[0]['originalformat']
    except KeyError: format = 'jpg'
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
    else:
      permcomment = permaddmeta = [None]
      
    commMeta = '%s%s' % (permcomment,permaddmeta) # Required for chmod.
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
    return (format, mode, commMeta, desc, title, taglist, 
            license, owner, ownerNSID, url, int(posted), int(lastupdate))

  def setPerm(self, photoId, mode, comm_meta="33"):
    log.debug("id: %s, mode: %s, comm_meta=%s", photoId, mode, comm_meta)
    public = mode&1 #Set public 4(always), 1(public). Public overwrites f&f
    #Set friends and family 4(always), 2(family), 1(friends) 
    friends = mode>>3 & 1
    family = mode>>4 & 1
    if len(comm_meta)<2: 
      # This wd patch string index out of range bug, caused 
      # because some photos may not have comm_meta value set.
      comm_meta="33"
    rsp = self.fapi.photos_setPerms(auth_token=self.authtoken,
                                    is_public=str(public),
                                    is_friend=str(friends), 
                                    is_family=str(family), 
                                    perm_comment=comm_meta[0],
                                    perm_addmeta=comm_meta[1], 
                                    photo_id=photoId)
    if not rsp:
      log.error("couldn't set permission for photo %s; got error %s",
                photoId, rsp.errormsg)
      return False
    log.info("permissions have been set for photo %s", photoId)
    return True

  def setTags(self, photoId, tags):
    log.debug("id: %s, tags: %s", photoId, tags)
    templist = [ '"%s"'%(a,) for a in string.split(tags, ',')] + ['flickrfs']
    tagstring = ' '.join(templist)
    rsp = self.fapi.photos_setTags(auth_token=self.authtoken, 
                                   photo_id=photoId, tags=tagstring)
    if not rsp:
      log.error("couldn't set tags for %s; got error %s",
                photoId, rsp.errormsg)
      return False
    return True
  
  def setMeta(self, photoId, title, desc):
    log.debug("id: %s, title: %s, desc: %s", photoId, title, desc)
    rsp = self.fapi.photos_setMeta(auth_token=self.authtoken, 
                                   photo_id=photoId, title=title, 
                                   description=desc)
    if not rsp:
      log.error("couldn't set meta info for photo %s; got error",
                photoId, rsp.errormsg)
      return False
    return True

  def getLicenses(self):
    log.debug("started")
    rsp = self.fapi.photos_licenses_getInfo()
    if not rsp:
      log.error("couldn't retrieve licenses; got error %s", rsp.errormsg)
      return None
    licenseDict = {}
    for l in rsp.licenses[0].license:
      licenseDict[l['id']] = l['name']
    keys = licenseDict.keys()
    keys.sort()
    sortedLicenseList = []
    for k in keys:
      # Add tuple of license key, and license value.
      sortedLicenseList.append((k, licenseDict[k]))
    return sortedLicenseList
    
  def setLicense(self, photoId, license):
    log.debug("id: %s, license: %s", photoId, license)
    rsp = self.fapi.photos_licenses_setLicense(auth_token=self.authtoken, 
                                               photo_id=photoId, 
                                               license_id=license)
    if not rsp:
      log.error("couldn't set license info for photo %s; got error %s",
                photoId, rsp.errormsg)
      return False
    return True

  def getPhoto(self, photoId):
    log.debug("id: %s", photoId)
    rsp = self.fapi.photos_getSizes(auth_token=self.authtoken, 
                                    photo_id=photoId)
    if not rsp:
      log.error("error while trying to retrieve size information"
                " for photo %s", photoId)
      return None
    buf = ""
    for a in rsp.sizes[0].size:
      if a['label']=='Original':
        try:
          f = urllib2.urlopen(a['source'])
          buf = f.read()
        except:
          log.error("exception in getPhoto")
          log.error(format_exc())
          return ""
    if not buf:
      f = urllib2.urlopen(rsp.sizes[0].size[-1]['source'])
      buf = f.read()
    return buf

  def removePhotofromSet(self, photoId, photosetId):
    log.debug("id: %s, setid: %s", photoId, photosetId)
    rsp = self.fapi.photosets_removePhoto(auth_token=self.authtoken, 
                                          photo_id=photoId, 
                                          photoset_id=photosetId)
    if rsp:
      log.info("photo %s removed from set %s", photoId, photosetId)
    else:
      log.error(rsp.errormsg)
      
    
  def getBandwidthInfo(self):
    log.debug("retrieving bandwidth information")
    rsp = self.fapi.people_getUploadStatus(auth_token=self.authtoken)
    if not rsp:
      log.error("can't retrieve bandwidth information; got error %s",
        rsp.errormsg)
      return (None,None)
    bw = rsp.user[0].bandwidth[0]
    log.debug("max bandwidth: %s, bandwidth used: %s", bw['max'], bw['used'])
    return (bw['max'], bw['used'])

  def getUserId(self):
    log.debug("entered")
    rsp = self.fapi.auth_checkToken(api_key=flickrAPIKey, 
                                    auth_token=self.authtoken)
    if not rsp:
      log.error("unable to get userid; got error %s", rsp.errormsg)
      return None
    usr = rsp.auth[0].user[0]
    log.info("got NSID %s", usr['nsid'])
    #Set self.user_id to this value
    self.user_id = usr['nsid']
    return usr['nsid']

  def getPhotosetList(self):
    log.debug("entered")
    if self.user_id is "":
      self.getUserId() #This will set the value of self.user_id
    rsp = self.fapi.photosets_getList(auth_token=self.authtoken, 
                                      user_id=self.user_id)
    if not rsp:
      log.error("error getting photoset list; got error %s", rsp.errormsg)
      return []
    if not hasattr(rsp.photosets[0], "photoset"):
      log.info("no sets found for userid %s", self.user_id)
      return []
    else:
      log.info("%s sets found for userid %s",
          len(rsp.photosets[0].photoset), self.user_id)
    return rsp.photosets[0].photoset

  def parseInfoFromPhoto(self, photo, perms=None):
    info = {}
    info['id'] = photo['id']
    info['title'] = photo['title'].replace('/', '_')
    # Some pics don't contain originalformat attribute, so set it to jpg by default.
    try:
      info['format'] = photo['originalformat']
    except KeyError:
      info['format'] = 'jpg'

    try:
      info['dupload'] = photo['dateupload']
    except KeyError:
      info['dupload'] = '0'

    try:
      info['dupdate'] = photo['lastupdate']
    except KeyError:
      info['dupdate'] = '0'
    
    info['perms'] = perms
    return info

  def parseInfoFromFullInfo(self, id, fullInfo):
    info = {}
    info['id'] = id
    info['title'] = fullInfo[4]
    info['format'] = fullInfo[0]
    info['dupload'] = fullInfo[10]
    info['dupdate'] = fullInfo[11]
    info['mode'] = fullInfo[1]
    return info

  def getPhotosFromPhotoset(self, photoset_id):
    log.debug("set id: %s", photoset_id)
    photosPermsMap = {}
    # I'm not utilizing the value part of this dictionary. Its arbitrarily
    # set to i.
    for i in range(0,3):
      page = 1
      while True:
        rsp = self.fapi.photosets_getPhotos(auth_token=self.authtoken,
                                            photoset_id=photoset_id, 
                                            extras=self.extras, 
                                            page=str(page),
                                            privacy_filter=str(i))
        if not rsp:
          break
        if not hasattr(rsp.photoset[0], 'photo'):
          log.error("photoset %s doesn't have attribute photo", rsp.photoset[0]['id'])
          break
        for p in rsp.photoset[0].photo:
          photosPermsMap[p] = str(i)
        page += 1
        if page > int(rsp.photoset[0]['pages']): break
      if photosPermsMap: break
    return photosPermsMap
            
  def getPhotoStream(self, user_id):
    log.debug("userid: %s", user_id)
    retList = []
    pageNo = 1
    maxPage = 1
    while pageNo<=maxPage:
      log.info("retreiving page number %s of %s", pageNo, maxPage) 
      rsp = self.fapi.photos_search(auth_token=self.authtoken, 
                                    user_id=user_id, per_page="500", 
                                    page=str(pageNo), extras=self.extras)
      if not rsp:
        log.error("can't retrive photos from your stream; got error %s",
            rsp.errormsg)
        return retList
      if not hasattr(rsp.photos[0], 'photo'):
        log.error("photos.search response doesn't have attribute photos; "
            "returning list acquired so far")
        return retList
      for a in rsp.photos[0].photo:
        retList.append(a)
      maxPage = int(rsp.photos[0]['pages'])
      pageNo = pageNo + 1
    return retList
 
  def getTaggedPhotos(self, tags, user_id=None):
    log.debug("tags: %s user_id: %s", tags, user_id)
    kw = kwdict(auth_token=self.authtoken, tags=tags, tag_mode="all", 
                extras=self.extras, per_page="500")
    if user_id is not None: 
      kw = kwdict(user_id=user_id, **kw)
    rsp = self.fapi.photos_search(**kw)
    log.debug("search for photos with tags %s has been"
              " successfully finished" % tags)
    if not rsp:
      log.error("couldn't search for the photos; got error %s", rsp.errormsg)
      return
    if not hasattr(rsp.photos[0], 'photo'):
      return []
    return rsp.photos[0].photo
