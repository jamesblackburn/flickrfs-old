#!/usr/bin/python

import sys
from flickrapi import FlickrAPI

# flickr auth information:
flickrSecret = "3fbf7144be7eca28"                  # shared "secret"

flickrAPIKey = "f8aa9917a9ae5e44a87cae657924f42d"  # API key
# make a new FlickrAPI instance
fapi = FlickrAPI(flickrAPIKey, flickrSecret)

# do the whole whatever-it-takes to get a valid token:
token = fapi.getToken(browser="/usr/bin/firefox")

# get my favorites
rsp = fapi.favorites_getList(api_key=flickrAPIKey,auth_token=token)
fapi.testFailure(rsp)

#print 'Photosets: '
print fapi.photosets_getList(api_key=flickrAPIKey, auth_token=token)
rsp = fapi.photosets_getList(api_key=flickrAPIKey, auth_token=token)
fapi.testFailure(rsp)
#print photoSets
#print ', '.join([str(set.title) for set in photoSets])

#person = fapi.flickr_people_getInfo(user_id="tuxmann")
#print person.username

# and print them
if hasattr(rsp.photosets[0], "photoset"):
	print 'yeup!'
else:
	print 'nope'

for a in rsp.photosets[0].photoset:
#	print "%10s: %s" % (a['id'], a['title'].encode("ascii", "replace"))
	print "%10s" % (str(a.title[0].elementText),)

#getPhoto Sizes and urls
rsp = fapi.photos_getSizes(photo_id="43050580", api_key=flickrAPIKey, auth_token=token)
fapi.testFailure(rsp)
for a in rsp.sizes[0].size:
	if a['label']=="Large":
		print "%s: %20s: %s" % (a['label'], a['source'], a['url'])
		import urllib2
		f = urllib2.urlopen(a['source'])
		newfile = open('newfile', "w")
		tempbuf = str(f.read())
		print 'converted to string of size: ' + str(long(tempbuf.__len__()))
		newfile.write(tempbuf)
		print 'wrote to newfile'
		newfile.close()
	
# upload the file foo.jpg
rsp = fapi.upload("/tmp/bsd_vs_tux.jpg", api_key=flickrAPIKey, auth_token=token, \
	title="This is the title", description="This is the description", \
	tags='"tag1 tag2" tag3',\
	is_friend="1", is_public="0", is_family="1")
if rsp == None:
	sys.stderr.write("can't find file\n")
else:
	fapi.testFailure(rsp)

