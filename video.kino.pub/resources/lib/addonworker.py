#!/usr/bin/python
# -*- coding: utf-8 -*-

import urllib, urllib2, urlparse
import sys
import xbmcplugin
import xbmcgui
import xbmc
import xbmcaddon
import xbmcvfs
import json
import addonutils
import time
import re

__id__ = 'video.kino.pub'
__addon__ = xbmcaddon.Addon(id=__id__)
__settings__ = xbmcaddon.Addon(id=__id__)
__skinsdir__ = "DefaultSkin"
__language__ = __addon__.getLocalizedString
__plugin__ = "plugin://%s" % __id__

DEFAULT_QUALITY = __settings__.getSetting("video_quality")
DEFAULT_STREAM_TYPE = __settings__.getSetting("stream_type")

_ADDON_PATH =   xbmc.translatePath(__addon__.getAddonInfo('path'))
if (sys.platform == 'win32') or (sys.platform == 'win64'):
    _ADDON_PATH = _ADDON_PATH.decode('utf-8')
handle = int(sys.argv[1])


import authwindow as auth
Auth = auth.Auth(__settings__)
def api(action, params={}, url="http://api.service-kp.com/v1", timeout=600, method="get"):
    method = "post" if method == "post" else "get"
    access_token = __settings__.getSetting('access_token')
    xbmc.log("api) Access token %s" % access_token)
    params['access_token'] = access_token
    params = urllib.urlencode(params)
    xbmc.log("api) url = %s/%s?%s" % (url, action, params))
    try:
        access_token_expire = __settings__.getSetting('access_token_expire')
        if int(access_token_expire) < int(time.time()):
            # try to refresh token
            status, resp = Auth.get_token(refresh=True)
            if status != Auth.SUCCESS:
                xbmc.log("Refresh access token because it expired")
                xbmc.log("%s" % resp)
                if resp['status'] == 400:
                    xbmc.log("Status is 400, we need to reauth")
                    Auth.reauth()
                    actionLogin({})
                    #nav_internal_link()
                else:
                    notice("Повторите попытку позже.", "Ошибка", time=10000);

        if method == "get":
            #xbmc.log("GET REQUEST")
            request = urllib2.Request("%s/%s?%s" % (url, action, params))
            #response = urllib2.urlopen("%s/%s?%s" % (url, action, params), timeout=timeout)
        else:
            #xbmc.log("POST REQUEST")
            request = urllib2.Request("%s/%s" % (url, action), data=params)

        request.add_header('Authorization', 'Bearer %s' % __settings__.getSetting('access_token'))
        response = urllib2.urlopen(request, timeout=timeout)
        data = json.loads(response.read())
        return data
    except urllib2.HTTPError as e:
        try:
            data = json.loads(e.read())
        except:
            data = {'status': e.code, 'error': 'unknown server error'}

        return data
    except Exception as e:
        xbmc.log("%s" % e)
        return {
            'status': 105,
            'name': 'Name Not Resolved',
            'message': 'Name not resolved',
            'code': 0
        }

# Show pagination
def show_pagination(pagination, action, qp):
    # Add "next page" button
    if (pagination and int(pagination['current'])) + 1 <= int(pagination['total']):
        qp['page'] = int(pagination['current'])+1
        li = xbmcgui.ListItem("[COLOR FFFFF000]Вперёд[/COLOR]")
        link = get_internal_link(action, qp)
        xbmcplugin.addDirectoryItem(handle, link, li, True)
    xbmcplugin.endOfDirectory(handle)


# Write nfo file about item
def generate_nfo(path, title, item):
    import xml.etree.ElementTree as ET
    xbmcvfs.mkdirs(path)
    f = xbmcvfs.File('%s/%s.nfo' % (path, title), 'w')
    root = None
    if item['type'] in ['serial', 'docuserial', 'tvshow']:
        root = ET.Element('tvshow')
    else:
        root = ET.Element('movie')
    ET.SubElement(root, 'title').text = item['title']
    ET.SubElement(root, 'originaltitle').text = item['title'].split(' / ')[-1]
    ET.SubElement(root, 'sorttitle').text = item['title'].split(' / ')[-1]
    ET.SubElement(root, 'year').text = str(item['year'])
    ET.SubElement(root, 'thumb').text = item['posters']['big']
    if item['imdb_rating']:
        ET.SubElement(root, 'rating').text = str(item['imdb_rating'])
    elif item['kinopoisk_rating']:
        ET.SubElement(root, 'rating').text = str(item['kinopoisk_rating'])
    else:
        ET.SubElement(root, 'rating').text = str(float(item['rating_percentage'])/10)
    ET.SubElement(root, 'plot').text = item['plot']
    for genre in item['genres']:
        ET.SubElement(root, 'genre').text = genre['title']
    for cast in item['cast'].split(','):
        actor = ET.SubElement(root, 'actor')
        ET.SubElement(actor, 'name').text = cast.strip(' ')
    for director in item['director'].split(','):
        ET.SubElement(root, 'director').text = director.strip(' ')
    trailer = trailer_link(item)
    if trailer:
        ET.SubElement(root, 'trailer').text = trailer
    if item['imdb']:
        ET.SubElement(root, 'id').text = 'tt%s' % item['imdb']
    if 'videos' in item and len(item['videos']) > 0:
        ET.SubElement(root, 'set').text = item['title']
    if item['duration']: # in minutes
        ET.SubElement(root, 'runtime').text = str(int(item['duration']['average']) / 60)
    f.write(ET.tostring(root, encoding='utf8', method='xml'))

def generate_episode_nfo(path, title, episode, season_num, episode_num):
    import xml.etree.ElementTree as ET
    xbmcvfs.mkdirs(path)
    f = xbmcvfs.File('%s/%s.nfo' % (path, title), 'w')
    root = ET.Element('episodedetails')
    episode_title = "s%02de%02d" % (season_num, episode_num)
    ET.SubElement(root, 'title').text = episode['title'] if episode['title'] else episode_title
    ET.SubElement(root, 'season').text = str(season_num)
    ET.SubElement(root, 'episode').text = str(episode_num)
    ET.SubElement(root, 'thumb').text = episode['thumbnail']
    f.write(ET.tostring(root, encoding='utf8', method='xml'))


# Get trailer link
def trailer_link(item):
    if 'trailer' in item and item['trailer']:
        trailer = item['trailer']
        return get_internal_link('trailer', {'id': item['id'], 'sid': trailer['id']})
    return None

# Fill directory for items
def show_items(items, options={}):
    xbmc.log("%s : show_items. Total items: %s" % (__plugin__, str(len(items))))
    xbmcplugin.setContent(handle, 'movies')
    # Fill list with items
    for index, item in enumerate(items):
        isdir = True if item['type'] in ['serial', 'docuserial', 'tvshow'] else False
        link = get_internal_link('view', {'id': item['id']})
        li = xbmcgui.ListItem(item['title'].encode('utf-8'))
        if 'enumerate' in options:
            li.setLabel("%s. %s" % (index+1, li.getLabel()))
        li.setInfo('Video', addonutils.video_info(item, {'trailer': trailer_link(item)}))
        li.setArt({'poster': item['posters']['big']})
        import_url = get_internal_link('import', {'id': item['id']})
        li.addContextMenuItems([('Добавить в библиотеку', 'XBMC.RunPlugin(%s)' % import_url,),])
        # If not serials or multiseries movie, create playable item
        if item['type'] not in ['serial', 'docuserial', 'tvshow']:
            if item['subtype'] == '':
                link = get_internal_link('play', {'id': item['id'], 'video': 1})
                #li.setInfo('Video', {'playcount': int(full_item['videos'][0]['watched'])})
                li.setProperty('IsPlayable', 'true')
                isdir = False
            else:
                link = get_internal_link('view', {'id': item['id']})
                isdir = True
        xbmcplugin.addDirectoryItem(handle, link, li, isdir)

# qp - dict, query paramters
# fmt - show format
#  s - show search
#  l - show last
#  p - show popular
#  s - show alphabet sorting
#  g - show genres folder
def add_default_headings(qp, fmt="slp"):
    if 's' in fmt:
        li = xbmcgui.ListItem('[COLOR FFFFF000]Поиск[/COLOR]')
        xbmcplugin.addDirectoryItem(handle, get_internal_link('search', qp), li, False)
    if 'l' in fmt:
        li = xbmcgui.ListItem('[COLOR FFFFF000]Последние[/COLOR]')
        xbmcplugin.addDirectoryItem(handle, get_internal_link('items', qp), li, True)
    if 'p' in fmt:
        li = xbmcgui.ListItem('[COLOR FFFFF000]Популярные[/COLOR]')
        xbmcplugin.addDirectoryItem(handle, get_internal_link('items', addonutils.dict_merge(qp, {'sort': '-rating'})), li, True)
    if 'a' in fmt:
        li = xbmcgui.ListItem('[COLOR FFFFF000]По алфавиту[/COLOR]')
        xbmcplugin.addDirectoryItem(handle, get_internal_link('alphabet', qp), li, True)
    if 'g' in fmt:
        li = xbmcgui.ListItem('[COLOR FFFFF000]Жанры[/COLOR]')
        xbmcplugin.addDirectoryItem(handle, get_internal_link('genres', qp), li, True)


# Form internal link for plugin navigation
def get_internal_link(action, params={}):
    global __plugin__
    params = urllib.urlencode(params)
    return "%s/%s?%s" % (__plugin__, action, params)

def nav_internal_link(action, params={}):
    ret = xbmc.executebuiltin('Container.Update(%s)' % get_internal_link(action, params))

def notice(message, heading="", time=4000):
    xbmc.executebuiltin('XBMC.Notification("%s", "%s", "%s")' % (heading, message, time))

def route(fakeSys=None):
    global __plugin__

    if  fakeSys:
        current = fakeSys.split('?')[0]
        qs = fakeSys.split('?')['?' in fakeSys]
    else:
        current = sys.argv[0]
        qs = sys.argv[2]
    action = current.replace(__plugin__, '').lstrip('/')
    action = action if action else 'login'
    actionFn = 'action' + action.title()
    qp = get_params(qs)

    xbmc.log("%s : route. %s" % (__plugin__, str(qp)))
    globals()[actionFn](qp)


# Parse query string params into dict
def get_params(qs):
    params = {}
    if qs:
        qs = qs.replace('?', '').split('/')[-1]
        for i in qs.split('&'):
            if '=' in i:
                k,v = i.split('=')
                params[k] = urllib.unquote_plus(v)
    return params



# Entry point
def init():
    route()

"""
 Actions
"""

def actionLogin(qp):
    xbmc.log("%s : actionLogin. %s" % (__plugin__, str(qp)))

    access_token = __settings__.getSetting('access_token')
    device_code = __settings__.getSetting('device_code')
    access_token_expire = __settings__.getSetting('access_token_expire')

    def update_device_info(force=False):
        try:
            # Update device info
            deviceInfoUpdate = __settings__.getSetting('device_info_update')
            if force or (not deviceInfoUpdate or int(deviceInfoUpdate)+1800 < int(float(time.time()))):
                infoLabels = [
                    '"System.BuildVersion"',
                    '"System.FriendlyName"',
                    '"System.KernelVersion"',
                ]
                result = "Busy"
                while "Busy" in result:
                    result = xbmc.executeJSONRPC('{"jsonrpc": "2.0", "method": "XBMC.GetInfoLabels", "id": 1, "params": {"labels": [%s]}}' % ",".join(infoLabels))
                try:
                    result = json.loads(result)['result']
                    title = result['System.FriendlyName']
                    hardware = result['System.KernelVersion']
                    software = "Kodi/%s" % result['System.BuildVersion']
                    result = api("device/notify", params={'title': title, 'hardware': hardware, 'software': software}, method="post")
                    __settings__.setSetting('device_info_update', str(int(float(time.time()))))
                except:
                    pass
        except:
            pass

    def showActivationWindow():
        xbmc.log("%s : actionLogin - No acess_token. Show modal auth" % __plugin__)
        wn = auth.AuthWindow("auth.xml", _ADDON_PATH, __skinsdir__, settings=__settings__, afterAuth=update_device_info)
        wn.doModal()
        del wn
        xbmc.log("%s : actionLogin - Close modal auth" % __plugin__)


    # if no access_token exists
    if not access_token:
        showActivationWindow()
        actionLogin(qp)
        return
    else:
        if int(access_token_expire) - int(time.time()) <= 15 * 60:
            # try to refresh token
            status, resp = Auth.get_token(refresh=True)

        # test API call
        response = api('types')
        if int(response['status']) == 401:
            status, resp = Auth.get_token(refresh=True)
            if status != Auth.SUCCESS:
                # reset access_token
                Auth.settings.setSetting('access_token', '')
                showActivationWindow()
                actionLogin(qp)
        elif int(response['status']) == 200:
            update_device_info()
            actionIndex(qp)
        else:
            notice("Повторите попытку позже (%s)." % response['status'], "Ошибка", time=10000);

# Main screen - show type list
def actionIndex(qp):
    xbmc.log("%s : actionIndex. %s" % (__plugin__, str(qp)))
    xbmc.executebuiltin('Container.SetViewMode(0)')
    if 'type' in qp:
        add_default_headings(qp, "slpga")
    else:
        response = api('types')
        if response['status'] == 200:
            add_default_headings(qp)
            # Temporary Rio 2016
            li = xbmcgui.ListItem('[COLOR FFFFF000]ТВ[/COLOR] [COLOR FFFF0000]!! NEW !![/COLOR]')
            xbmcplugin.addDirectoryItem(handle, get_internal_link('tv'), li, True)
            # Add bookmarks
            li = xbmcgui.ListItem('[COLOR FFFFF000]Закладки[/COLOR]')
            xbmcplugin.addDirectoryItem(handle, get_internal_link('bookmarks'), li, True)
            li = xbmcgui.ListItem('[COLOR FFFFF000]Я смотрю[/COLOR]')
            xbmcplugin.addDirectoryItem(handle, get_internal_link('watching'), li, True)
            li = xbmcgui.ListItem('[COLOR FFFFF000]Подборки[/COLOR]')
            xbmcplugin.addDirectoryItem(handle, get_internal_link('collections'), li, True)

            for i in response['items']:
                li = xbmcgui.ListItem(i['title'].encode('utf-8'))
                #link = get_internal_link('items', {'type': i['id']})
                link = get_internal_link('index', {'type': i['id']})
                xbmcplugin.addDirectoryItem(handle, link, li, True)
    xbmcplugin.endOfDirectory(handle)

def actionTv(qp):
    response = api('tv/index')
    if response['status'] == 200:
        for ch in response['channels']:
            li = xbmcgui.ListItem(ch['title'].encode('utf-8'), iconImage=ch['logos']['s'])
            xbmcplugin.addDirectoryItem(handle, ch['stream'], li, False)
    xbmcplugin.endOfDirectory(handle)

def actionGenres(qp):
    response = api('genres', {'type': qp.get('type', '')})
    if response['status'] == 200:
        add_default_headings(qp, "")
        for genre in response['items']:
            li = xbmcgui.ListItem(genre['title'].encode('utf-8'))
            link = get_internal_link('items', {'type': qp.get('type'), 'genre': genre['id']})
            xbmcplugin.addDirectoryItem(handle, link, li, True)
        xbmcplugin.endOfDirectory(handle)
    else:
        notice(response['message'], response['name'], )

# List items with pagination
#  qp - dict, query parameters for item filtering
#   title - filter by title
#   type - filter by type
#   category - filter by categroies
#   page - filter by page
def actionItems(qp):
    response = api('items', qp)
    if response['status'] == 200:
        pagination = response['pagination']
        add_default_headings(qp, "s")

        show_items(response['items'])
        show_pagination(pagination, "items", qp)
    else:
        notice(response['message'], response['name'])

def actionImport(qp):
    response = api('items/%s' % qp['id'])
    folder_path = None
    if response['status'] == 200:
        # show settings if folders are not set
        if not xbmcvfs.exists(__settings__.getSetting('movies_folder')) or not xbmcvfs.exists(__settings__.getSetting('tvshows_folder')):
            __addon__.openSettings()

        item = response['item']
        title = item['title']
        # cleanup title
        title = re.sub(ur'[^\w\s-]', '', title.split(' / ')[-1], flags=re.UNICODE).strip().lower()
        title = re.sub(ur'[-\s]+', '-', title, flags=re.UNICODE)
        title = '%s-(%s)' % (title.encode('utf-8'), str(item['year']))

        # import a movie
        if item['type'] not in ['serial', 'docuserial', 'tvshow']:
            folder_path = __settings__.getSetting('movies_folder')
            if not xbmcvfs.exists(folder_path):
                notice('Путь к библиотеке фильмов не существует', 'Ошибка')
                return
            if item['subtype'] == 'multi' and 'videos' in item and len(item['videos']) > 1:
                folder_path = '%s/%s' % (folder_path, title)
                xbmcvfs.mkdirs(folder_path)
                generate_nfo(folder_path, title, item)
                for video_number, video in enumerate(item['videos']):
                    video_number += 1
                    episode_title = "%s.%02d" % (title, video_number)
                    f = xbmcvfs.File('%s/%s.strm' % (folder_path, episode_title), 'w')
                    f.write(get_internal_link('play', {'id': qp['id'], 'video': video_number}))
            else:
                generate_nfo(folder_path, title, item)
                f = xbmcvfs.File('%s/%s.strm' % (folder_path, title), 'w')
                f.write(get_internal_link('play', {'id': qp['id'], 'video': 1}))
        # import a show
        else:
            season_to_import = int(qp['season']) if 'season' in qp else None
            episode_to_import = int(qp['episode']) if 'episode' in qp else None
            folder_path = __settings__.getSetting('tvshows_folder')
            if not xbmcvfs.exists(folder_path):
                notice('Путь к библиотеке сериалов не существует', 'Ошибка')
                return
            folder_path = '%s/%s' % (folder_path, title)
            generate_nfo(folder_path, title, item)
            for season in item['seasons']:
                if season_to_import is None or int(season['number']) == int(qp['season']):
                    for episode_number, episode in enumerate(season['episodes']):
                        episode_number += 1
                        if episode_to_import is None or episode_number == episode_to_import:
                            episode_path = '%s/s%02d' % (folder_path, season['number'])
                            episode_title = "%s_s%02de%02d" % (title, season['number'], episode_number)
                            xbmcvfs.mkdirs(episode_path)
                            generate_episode_nfo(episode_path, episode_title, episode, season['number'], episode_number)
                            f = xbmcvfs.File('%s/%s.strm' % (episode_path, episode_title), 'w')
                            f.write(get_internal_link('play', {'id': qp['id'], 'season': season['number'], 'episode': episode_number}))

        xbmc.executebuiltin('XBMC.UpdateLibrary(video)')
        notice('Добавлено успешно', 'KinoPub', 1000)


# Show items
# If item type is movie with more than 1 episodes - show those episodes
# If item type is serial, docuserial, tvshow - show seasons
#  if parameter season is set - show episodes
# Otherwise play content
def actionView(qp):
    response = api('items/%s' % qp['id'])
    #xbmc.log("%s" % response)
    if response['status'] == 200:
        item = response['item']
        #xbmc.log("%s" % item)
        watchingInfo = api('watching', {'id': item['id']})['item']
        # If serial instance or multiseries film show navigation, else start play
        if item['type'] in ['serial', 'docuserial', 'tvshow']:
            if 'season' in qp:
                for season in item['seasons']:
                    if int(season['number']) == int(qp['season']):
                        watching_season = watchingInfo['seasons'][season['number']-1]
                        selectedEpisode = False
                        xbmcplugin.setContent(handle, 'episodes')
                        for episode_number, episode in enumerate(season['episodes']):
                            episode_number += 1
                            episode_title = "s%02de%02d" % (season['number'], episode_number)
                            episode_title = episode_title + " | " + episode['title'] if episode['title'] else episode_title
                            li = xbmcgui.ListItem(episode_title, iconImage=episode['thumbnail'], thumbnailImage=episode['thumbnail'])
                            li.setInfo('Video', addonutils.video_info(item, {
                                'season': int(season['number']),
                                'episode': episode_number,
                                'duration': int(episode['duration']),
                            }))
                            li.setInfo('Video', {'playcount': int(episode['watched'])})
                            li.setArt({'poster': item['posters']['big']})
                            li.setProperty('IsPlayable', 'true')
                            import_url = get_internal_link('import', {'id': item['id'], 'season': season['number'], 'episode': episode_number})
                            li.addContextMenuItems([('Добавить в библиотеку', 'XBMC.RunPlugin(%s)' % import_url,),])
                            if watching_season['episodes'][episode_number-1]['status'] < 1 and not selectedEpisode:
                                selectedEpisode = True
                                li.select(selectedEpisode)
                            link = get_internal_link('play', {'id': item['id'], 'season': int(season['number']), 'episode': episode_number})
                            xbmcplugin.addDirectoryItem(handle, link, li, False)
                        break
                xbmcplugin.endOfDirectory(handle)
            else:
                selectedSeason = False
                xbmcplugin.setContent(handle, 'tvshows')
                for season in item['seasons']:
                    #xbmc.log("%s" % season)
                    season_title = "Сезон %s" % int(season['number'])
                    watching_season = watchingInfo['seasons'][season['number']-1]
                    li = xbmcgui.ListItem(season_title)
                    li.setInfo('Video', addonutils.video_info(item, {
                        'season': int(season['number']),
                    }))
                    li.setArt({'poster': item['posters']['big']})
                    import_url = get_internal_link('import', {'id': item['id'], 'season': season['number']})
                    li.addContextMenuItems([('Добавить в библиотеку', 'XBMC.RunPlugin(%s)' % import_url,),])
                    if watching_season['status'] < 1 and not selectedSeason:
                        selectedSeason = True
                        li.select(selectedSeason)
                    link = get_internal_link('view', {'id': qp['id'], 'season': season['number']})
                    xbmcplugin.addDirectoryItem(handle, link, li, True)
                xbmcplugin.endOfDirectory(handle)
        elif 'videos' in item and len(item['videos']) > 1:
            xbmcplugin.setContent(handle, 'episodes')
            for video_number, video in enumerate(item['videos']):
                video_number += 1
                episode_title = "e%02d" % video_number
                episode_title = "%s | %s" % (episode_title, video['title']) if video['title'] else episode_title
                li = xbmcgui.ListItem(episode_title, iconImage=video['thumbnail'], thumbnailImage=video['thumbnail'])
                li.setInfo('Video', addonutils.video_info(item, {
                    'season' : 1,
                    'episode': video_number
                }))
                li.setInfo('Video', {'playcount': int(video['watched'])})
                li.setArt({'poster': item['posters']['big']})
                li.setProperty('IsPlayable', 'true')
                link = get_internal_link('play', {'id': item['id'], 'video': video_number})
                xbmcplugin.addDirectoryItem(handle, link, li, False)
            xbmcplugin.endOfDirectory(handle)
        else:
            return

def actionPlay(qp):
    response = api('items/%s' % qp['id'])
    if response['status'] == 200:
        item = response['item']
        videoObject = None
        liObject = None
        season_number = 0
        if 'season' in qp:
            # process episode
            for season in item['seasons']:
                if int(qp['season']) != int(season['number']):
                    continue
                season_number = season['number']
                for episode_number, episode in enumerate(season['episodes']):
                    episode_number+=1
                    if episode_number == int(qp['episode']):
                        videoObject = episode
                        episode_title = "s%02de%02d" % (season['number'], episode_number)
                        episode_title = "%s | %s" % (episode_title, episode['title']) if episode['title'] else episode_title
                        liObject = xbmcgui.ListItem(episode_title)
                        liObject.setInfo("video", addonutils.video_info(item, {
                            'season': season['number'],
                            'episode': episode_number,
                            'duration': videoObject['duration'] if 'duration' in videoObject else None
                        }))
        elif 'video' in qp:
            # process video
            for video_number, video in enumerate(item['videos']):
                video_number+=1
                if video_number == int(qp['video']):
                    videoObject = video
                    if len(item['videos']) > 1:
                        episode_title = "e%02d" % (video_number)
                        episode_title = "%s | %s" % (episode_title, video['title']) if video['title'] else episode_title
                        liObject = xbmcgui.ListItem(episode_title)
                        liObject.setInfo("video", addonutils.video_info(item, {
                            'season': 1,
                            'episode': video_number
                        }))
                    else:
                        liObject = xbmcgui.ListItem(item['title'])
                        liObject.setInfo('video', addonutils.video_info(item))
        else:
            pass

        subtitles = list()

        for subtitle in videoObject['subtitles']:
            subtitles.append(subtitle['url'])

        if len(subtitles) > 0:
            liObject.setSubtitles(subtitles)

        liObject.setThumbnailImage(item['posters']['big'])
        liObject.setArt({'poster': item['posters']['small']})

        if 'files' not in videoObject:
            notice("Видео обновляется и временно не доступно!", "Видео в обработке", time=8000)
            return
        url = addonutils.get_mlink(videoObject, quality=DEFAULT_QUALITY, streamType=DEFAULT_STREAM_TYPE)
        api("watching/marktime", {'id': qp['id'], 'video': videoObject['number'], 'time': videoObject['duration'], 'season': season_number})
        liObject.setPath(url)
        xbmcplugin.setResolvedUrl(handle, True, liObject)


def actionTrailer(qp):
    response = api('items/trailer', params={'id': qp['id']})
    if response['status'] == 200:
        trailer = None
        trailer = response['trailer']
        if 'files' in trailer:
            url = addonutils.get_mlink(trailer, quality=DEFAULT_QUALITY, streamType=DEFAULT_STREAM_TYPE)
        elif 'sid' in qp:
            url = 'plugin://plugin.video.youtube/?path=/root/video&action=play_video&videoid=%s' % qp['sid']
        liObject = xbmcgui.ListItem('Трейлер')
        liObject.setPath(url)
        xbmcplugin.setResolvedUrl(handle, True, liObject)


def actionSearch(qp):
    kbd = xbmc.Keyboard()
    kbd.setDefault('')
    kbd.setHeading('Поиск')
    kbd.doModal()
    out=''
    if kbd.isConfirmed():
        out = kbd.getText()
    if len(out.decode('utf-8')) >= 3:
        if 'page' in qp:
            qp['page'] = 1
        qp['title'] = out
        nav_internal_link('items', qp)
    else:
        notice("Введите больше символов для поиска", "Поиск")
        nav_internal_link('index')


def actionBookmarks(qp):
    xbmc.log("%s : actionBookmarks. %s" % (__plugin__, str(qp)))
    if 'folder-id' not in qp:
        response = api('bookmarks')
        if response['status'] == 200:
            for folder in response['items']:
                li = xbmcgui.ListItem(folder['title'].encode('utf-8'))
                li.setProperty('folder-id', str(folder['id']).encode('utf-8'))
                li.setProperty('views', str(folder['views']).encode('utf-8'))
                link = get_internal_link('bookmarks', {'folder-id': folder['id']})
                xbmcplugin.addDirectoryItem(handle, link, li, True)
            xbmcplugin.endOfDirectory(handle)
    else:
        # Show content of the folder
        response = api('bookmarks/%s' % qp['folder-id'], qp)
        if response['status'] == 200:
            show_items(response['items'])
            show_pagination(response['pagination'], 'bookmarks', qp)
            xbmcplugin.endOfDirectory(handle)

def actionWatching(qp):
    response = api('watching/serials', {'subscribed': 1})
    if response['status'] == 200:
        xbmcplugin.setContent(handle, 'tvshows')
        for item in response['items']:
            li = xbmcgui.ListItem("%s : [COLOR FFFFF000]+%s[/COLOR]" % (item['title'].encode('utf-8'), str(item['new']).encode('utf-8')))
            li.setLabel2(str(item['new']).encode('utf-8'))
            li.setArt({'poster': item['posters']['big']})
            link = get_internal_link('view', {'id': item['id']})
            xbmcplugin.addDirectoryItem(handle, link, li, True)
        xbmcplugin.endOfDirectory(handle)
    else:
        notice("При загрузке сериалов произошла ошибка. Попробуйте позже.", "Я смотрю")

def actionCollections(qp):
    if 'id' not in qp:
        response = api('collections/index', qp)
        if response['status'] == 200:
            xbmcplugin.setContent(handle, 'movies')
            li = xbmcgui.ListItem('[COLOR FFFFF000]Последние[/COLOR]')
            qp['sort'] = '-created'
            xbmcplugin.addDirectoryItem(handle, get_internal_link('collections', qp), li, True)
            li = xbmcgui.ListItem('[COLOR FFFFF000]Просматриваемые[/COLOR]')
            qp['sort'] = '-watchers'
            xbmcplugin.addDirectoryItem(handle, get_internal_link('collections', qp), li, True)
            li = xbmcgui.ListItem('[COLOR FFFFF000]Популярные[/COLOR]')
            qp['sort'] = '-views'
            xbmcplugin.addDirectoryItem(handle, get_internal_link('collections', qp), li, True)
            for item in response['items']:
                li = xbmcgui.ListItem("%s" % (item['title'].encode('utf-8')))
                li.setThumbnailImage(item['posters']['medium'])
                link = get_internal_link('collections', {'id': item['id']})
                xbmcplugin.addDirectoryItem(handle, link, li, True)
            show_pagination(response['pagination'], "collections", qp)
            xbmcplugin.endOfDirectory(handle)
        else:
            notice("При загрузке подборок произошла ошибка. Попробуйте позже.", "Подборки")
    else:
        response = api('collections/view', qp)
        if response['status'] == 200:
            show_items(response['items'], options={'enumerate': True})
            #show_pagination(response['pagination'], "collections", qp)
            xbmcplugin.endOfDirectory(handle)
        else:
            notice("При загрузке произошла ошибка. Попробуйте позже.", "Подборки / Просмотр")

def actionAlphabet(qp):
    alpha = [
        "А,Б,В,Г,Д,Е,Ё,Ж,З,И,Й,К,Л,М,Н,О,П,Р,С,Т,У,Ф,Х,Ц,Ч,Ш,Щ,Ы,Э,Ю,Я",
        "A,B,C,D,E,F,G,H,I,J,K,L,M,N,O,P,Q,R,S,T,U,V,W,X,Y,Z"
    ]
    for al in alpha:
        letters = al.split(",")
        for letter in letters:
            li = xbmcgui.ListItem(letter)
            link = get_internal_link('items', addonutils.dict_merge(qp, {'letter': letter}))
            xbmcplugin.addDirectoryItem(handle, link, li, True)
    xbmcplugin.endOfDirectory(handle)

