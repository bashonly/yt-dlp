import hashlib
import json
import random
import re
import time

from .common import InfoExtractor
from ..utils import (
    ExtractorError,
    get_element_by_class,
    js_to_json,
    str_or_none,
    strip_jsonp,
    traverse_obj,
)


class YoukuIE(InfoExtractor):
    IE_NAME = 'youku'
    IE_DESC = '优酷'
    _VALID_URL = r'''(?x)
        (?:
            https?://(
                (?:v|player)\.youku\.com/(?:v_show/id_|player\.php/sid/)|
                video\.tudou\.com/v/)|
            youku:)
        (?P<id>[A-Za-z0-9]+)(?:\.html|/v\.swf|)
    '''

    _TESTS = [{
        # MD5 is unstable
        'url': 'http://v.youku.com/v_show/id_XMTc1ODE5Njcy.html',
        'info_dict': {
            'id': 'XMTc1ODE5Njcy',
            'title': '★Smile﹗♡ Git Fresh -Booty Music舞蹈.',
            'ext': 'mp4',
            'duration': 74.73,
            'thumbnail': r're:^https?://.*',
            'uploader': '。躲猫猫、',
            'uploader_id': '36017967',
            'uploader_url': 'http://i.youku.com/u/UMTQ0MDcxODY4',
            'tags': list,
        },
        'skip': '404 Not Found',
    }, {
        'url': 'http://player.youku.com/player.php/sid/XNDgyMDQ2NTQw/v.swf',
        'only_matching': True,
    }, {
        'url': 'http://v.youku.com/v_show/id_XODgxNjg1Mzk2_ev_1.html',
        'info_dict': {
            'id': 'XODgxNjg1Mzk2',
            'ext': 'mp4',
            'title': '武媚娘传奇 85',
            'duration': 1999.61,
            'thumbnail': r're:^https?://.*',
            'uploader': '疯狂豆花',
            'uploader_id': '62583473',
            'uploader_url': 'http://i.youku.com/u/UMjUwMzMzODky',
            'tags': list,
        },
        'skip': '404 Not Found',
    }, {
        'url': 'http://v.youku.com/v_show/id_XMTI1OTczNDM5Mg==.html',
        'info_dict': {
            'id': 'XMTI1OTczNDM5Mg',
            'ext': 'mp4',
            'title': '花千骨 04',
            'duration': 2363,
            'thumbnail': r're:^https?://.*',
            'uploader': '放剧场-花千骨',
            'uploader_id': '772849359',
            'uploader_url': 'http://i.youku.com/u/UMzA5MTM5NzQzNg==',
            'tags': list,
        },
        'skip': '404 Not Found',
    }, {
        'url': 'http://v.youku.com/v_show/id_XNjA1NzA2Njgw.html',
        'note': 'Video protected with password',
        'info_dict': {
            'id': 'XNjA1NzA2Njgw',
            'ext': 'mp4',
            'title': '邢義田复旦讲座之想象中的胡人—从“左衽孔子”说起',
            'duration': 7264.5,
            'thumbnail': r're:^https?://.*',
            'uploader': 'FoxJin1006',
            'uploader_id': '322014285',
            'uploader_url': 'http://i.youku.com/u/UMTI4ODA1NzE0MA==',
            'tags': list,
        },
        'params': {
            'videopassword': '100600',
        },
    }, {
        # /play/get.json contains streams with "channel_type":"tail"
        'url': 'http://v.youku.com/v_show/id_XOTUxMzg4NDMy.html',
        'info_dict': {
            'id': 'XOTUxMzg4NDMy',
            'ext': 'mp4',
            'title': '我的世界☆明月庄主☆车震猎杀☆杀人艺术Minecraft',
            'duration': 702.08,
            'thumbnail': r're:^https?://.*',
            'uploader': '明月庄主moon',
            'uploader_id': '38465621',
            'uploader_url': 'http://i.youku.com/u/UMTUzODYyNDg0',
            'tags': list,
        },
    }, {
        'url': 'http://video.tudou.com/v/XMjIyNzAzMTQ4NA==.html?f=46177805',
        'info_dict': {
            'id': 'XMjIyNzAzMTQ4NA',
            'ext': 'mp4',
            'title': '卡马乔国足开大脚长传冲吊集锦',
            'duration': 289,
            'thumbnail': r're:^https?://.*',
            'uploader': '阿卜杜拉之星',
            'uploader_id': '2382249',
            'uploader_url': 'http://i.youku.com/u/UOTUyODk5Ng==',
            'tags': list,
        },
        'skip': 'Tudou domain no longer exists',
    }, {
        'url': 'http://video.tudou.com/v/XMjE4ODI3OTg2MA==.html',
        'only_matching': True,
    }]

    _CKEY = 'DIl58SLFxFNndSV1GFNnMQVYkx1PP5tKe1siZu/86PR1u/Wh1Ptd+WOZsHHWxysSfAOhNJpdVWsdVJNsfJ8Sxd8WKVvNfAS8aS8fAOzYARzPyPc3JvtnPHjTdKfESTdnuTW6ZPvk2pNDh4uFzotgdMEFkzQ5wZVXl2Pf1/Y6hLK0OnCNxBj3+nb0v72gZ6b0td+WOZsHHWxysSo/0y9D2K42SaB8Y/+aD2K42SaB8Y/+ahU+WOZsHcrxysooUeND'

    def _get_cna(self, url, video_id):
        cna_cookie = self._get_cookies('https://log.mmstat.com').get('cna')
        if cna_cookie:
            return cna_cookie.value

        self.report_warning('Please consider using cookies to avoid waiting for CNA registration')
        _, urlh = self._download_webpage_handle('https://log.mmstat.com/eg.js', video_id, 'Retrieving CNA')
        # The etag header is '"foobar"'; let's remove the double quotes
        cna = urlh.headers['etag'][1:-1]
        time.sleep(12)

        self._download_webpage(
            'https://fourier.taobao.com/rp', video_id, note='Registering CNA', query={
                'ext': '51',
                'data': f'jm_{cna}',
                'random': str(random.random()).replace('0.', ''),
                'href': url,
                'protocol': 'https:'
            })

        time.sleep(5)
        return cna

    def _get_web_api_response(self, url, video_id, cna, client_ts):
        app_version = '4.1.4'
        app_key = '24679788'

        data_string = json.dumps({
            'steal_params': json.dumps({
                'ccode': '0502',
                'version': app_version,
                'client_ts': int(client_ts / 1000),
                'client_ip': '192.168.1.1',
                'utid': cna,
                'ckey': self._CKEY,
            }),
            'biz_params': json.dumps({
                'vid': video_id,
                'app_ver': app_version,
            }),
            'ad_params': json.dumps({
                'vs': '1.0',
                'pver': app_version,
            }),
        })

        token_cookie = self._get_cookies('https://acs.youku.com/').get('_m_h5_tk')
        token = token_cookie.value.split('_')[0] if token_cookie else ''

        query = {
            'api': 'mtop.youku.play.ups.appinfo.get',
            'v': '1.1',
            'jsv': '2.6.1',
            'appKey': app_key,
            't': client_ts,
            'sign': hashlib.md5(f'{token}&{client_ts}&{app_key}&{data_string}'.encode('utf-8')).hexdigest(),
            'type': 'jsonp',
            'dataType': 'jsonp',
            'callback': 'mtopjsonp1',
            'data': data_string,
        }

        api_response = self._search_json(r'mtopjsonp1\(', self._download_webpage(
            'https://acs.youku.com/h5/mtop.youku.play.ups.appinfo.get/1.1/',
            video_id, query=query), 'api_response', video_id)

        for message in api_response.get('ret'):
            if 'SUCCESS' in message:
                break

            if 'FAIL_SYS_TOKEN_EMPTY' in message or 'FAIL_SYS_TOKEN_EXOIRED' in message:
                if not self._get_cookies('https://acs.youku.com/').get('_m_h5_tk'):
                    raise ExtractorError('Could not get token')

                return self._get_web_api_response(url, video_id, cna, client_ts)

        api_error = traverse_obj(api_response, ('data', 'data', 'error'))
        if api_error:
            self.report_warning(f'Youku server reported error {api_error.get("code")}: {api_error.get("note")}')

        return traverse_obj(api_response, ('data', 'data'))

    def _get_mobile_api_response(self, video_id, cna, client_ts):
        query = {
            'vid': video_id,
            'ccode': '0501',
            'client_ip': '0.0.0.0',
            'app_ver': '1.0.75',
            'client_ts': client_ts,
            'utid': cna,
            'ckey': self._CKEY,
        }

        video_password = self.get_param('videopassword')
        if video_password:
            query['password'] = video_password

        headers = {
            'Referer': 'https://m.youku.com',
        }
        headers.update(self.geo_verification_headers())
        api_response = self._download_json(
            'https://ups.youku.com/ups/get.json', video_id, 'Downloading JSON metadata', query=query, headers=headers)

        api_error = api_response.get('e')
        if api_error.get('code') != 0:
            raise ExtractorError(
                f'Youku server reported error {api_error.get("code")}: {api_error.get("note")}')

        return api_response.get('data')

    def _extract_video_formats_and_subtitles(self, video_id, api_response):
        formats, subtitles = [], {}
        for format in api_response.get('stream') or ():
            fmts, subs = self._extract_m3u8_formats_and_subtitles(
                format.get('m3u8_url'), video_id, ext='mp4', fatal=False)
            for f in fmts:
                f['height'] = format.get('height')
                f['width'] = format.get('width')

            formats.extend(fmts)
            self._merge_subtitles(subs, target=subtitles)

        return formats, subtitles

    def _extract_thumbnails(self, api_response):
        thumbnails = []
        for thumbnail_id in ('show_thumburl', 'show_thumburl_huge', 'show_thumburl_big_jpg',
                             'show_vthumburl_huge', 'show_vthumburl_big_jpg', 'show_vthumburl'):
            thumbnail_url = traverse_obj(api_response, ('show', thumbnail_id))
            if thumbnail_url:
                thumbnails.append({
                    'id': thumbnail_id,
                    'url': thumbnail_url,
                })

        if traverse_obj(api_response, ('video', 'logo')):
            thumbnails.append({
                'id': 'logo',
                'url': traverse_obj(api_response, ('video', 'logo'))
            })

        return thumbnails

    def _real_extract(self, url):
        video_id = self._match_id(url)
        cna = self._get_cna(url, video_id)
        client_ts = int(time.time() * 1000)

        web_api_response = self._get_web_api_response(url, video_id, cna, client_ts)
        mobile_api_response = self._get_mobile_api_response(video_id, cna, client_ts)

        formats, subtitles = [], {}
        web_formats, web_subtitles = self._extract_video_formats_and_subtitles(video_id, web_api_response)
        mobile_formats, mobile_subtitles = self._extract_video_formats_and_subtitles(video_id, mobile_api_response)

        formats.extend(web_formats)
        formats.extend(mobile_formats)
        self._merge_subtitles(web_subtitles, mobile_subtitles, target=subtitles)

        thumbnails = []
        thumbnails.extend(self._extract_thumbnails(web_api_response))
        thumbnails.extend(self._extract_thumbnails(mobile_api_response))

        return {
            'id': video_id,
            'title': (traverse_obj(web_api_response, ('video', 'title'))
                      or traverse_obj(mobile_api_response, ('video', 'title'))),
            'formats': formats,
            'subtitles': subtitles,
            'thumbnails': thumbnails,
            'duration': (traverse_obj(web_api_response, ('video', 'seconds'))
                         or traverse_obj(mobile_api_response, ('video', 'seconds'))),
            'uploader': (traverse_obj(web_api_response, ('uploader', 'username'))
                         or traverse_obj(mobile_api_response, ('uploader', 'username'))),
            'uploader_id': str_or_none(traverse_obj(
                web_api_response, ('video', 'userid')) or traverse_obj(mobile_api_response, ('video', 'userid'))),
            'uploader_url': (traverse_obj(web_api_response, ('uploader', 'homepage'))
                             or traverse_obj(mobile_api_response, ('uploader', 'homepage'))),
            'tags': (traverse_obj(web_api_response, ('video', 'tags'))
                     or traverse_obj(mobile_api_response, ('video', 'tags'))),
        }


class YoukuShowIE(InfoExtractor):
    _VALID_URL = r'https?://list\.youku\.com/show/id_(?P<id>[0-9a-z]+)\.html'
    IE_NAME = 'youku:show'

    _TESTS = [{
        'url': 'http://list.youku.com/show/id_zc7c670be07ff11e48b3f.html',
        'info_dict': {
            'id': 'zc7c670be07ff11e48b3f',
            'title': '花千骨 DVD版',
            'description': 'md5:a1ae6f5618571bbeb5c9821f9c81b558',
        },
        'playlist_count': 50,
    }, {
        # Episode number not starting from 1
        'url': 'http://list.youku.com/show/id_zefbfbd70efbfbd780bef.html',
        'info_dict': {
            'id': 'zefbfbd70efbfbd780bef',
            'title': '超级飞侠3',
            'description': 'md5:275715156abebe5ccc2a1992e9d56b98',
        },
        'playlist_count': 24,
    }, {
        # Ongoing playlist. The initial page is the last one
        'url': 'http://list.youku.com/show/id_za7c275ecd7b411e1a19e.html',
        'only_matching': True,
    }, {
        #  No data-id value.
        'url': 'http://list.youku.com/show/id_zefbfbd61237fefbfbdef.html',
        'only_matching': True,
    }, {
        #  Wrong number of reload_id.
        'url': 'http://list.youku.com/show/id_z20eb4acaf5c211e3b2ad.html',
        'only_matching': True,
    }]

    def _extract_entries(self, playlist_data_url, show_id, note, query):
        query['callback'] = 'cb'
        playlist_data = self._download_json(
            playlist_data_url, show_id, query=query, note=note,
            transform_source=lambda s: js_to_json(strip_jsonp(s))).get('html')
        if playlist_data is None:
            return [None, None]
        drama_list = (get_element_by_class('p-drama-grid', playlist_data)
                      or get_element_by_class('p-drama-half-row', playlist_data))
        if drama_list is None:
            raise ExtractorError('No episodes found')
        video_urls = re.findall(r'<a[^>]+href="([^"]+)"', drama_list)
        return playlist_data, [
            self.url_result(self._proto_relative_url(video_url, 'http:'), YoukuIE.ie_key())
            for video_url in video_urls]

    def _real_extract(self, url):
        show_id = self._match_id(url)
        webpage = self._download_webpage(url, show_id)

        entries = []
        page_config = self._parse_json(self._search_regex(
            r'var\s+PageConfig\s*=\s*({.+});', webpage, 'page config'),
            show_id, transform_source=js_to_json)
        first_page, initial_entries = self._extract_entries(
            'http://list.youku.com/show/module', show_id,
            note='Downloading initial playlist data page',
            query={
                'id': page_config['showid'],
                'tab': 'showInfo',
            })
        first_page_reload_id = self._html_search_regex(
            r'<div[^>]+id="(reload_\d+)', first_page, 'first page reload id')
        # The first reload_id has the same items as first_page
        reload_ids = re.findall('<li[^>]+data-id="([^"]+)">', first_page)
        entries.extend(initial_entries)
        for idx, reload_id in enumerate(reload_ids):
            if reload_id == first_page_reload_id:
                continue
            _, new_entries = self._extract_entries(
                'http://list.youku.com/show/episode', show_id,
                note='Downloading playlist data page %d' % (idx + 1),
                query={
                    'id': page_config['showid'],
                    'stage': reload_id,
                })
            if new_entries is not None:
                entries.extend(new_entries)
        desc = self._html_search_meta('description', webpage, fatal=False)
        playlist_title = desc.split(',')[0] if desc else None
        detail_li = get_element_by_class('p-intro', webpage)
        playlist_description = get_element_by_class(
            'intro-more', detail_li) if detail_li else None

        return self.playlist_result(
            entries, show_id, playlist_title, playlist_description)
