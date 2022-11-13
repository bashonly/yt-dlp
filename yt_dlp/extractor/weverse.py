import base64
import hashlib
import hmac
import json
import time
import urllib.parse

from .common import InfoExtractor
from ..utils import (
    ExtractorError,
    float_or_none,
    int_or_none,
    random_uuidv4,
    traverse_obj,
)


class WeverseIE(InfoExtractor):
    _NETRC_MACHINE = 'weverse'
    _VALID_URL = r'https?://(?:www\.|m\.)?weverse.io/(?P<artist>[^/?#]+)/live/(?P<id>[0-9-]+)'
    _TESTS = [{
        'url': 'https://weverse.io/billlie/live/0-107323480',
        'md5': 'TODO',
        'info_dict': {
            'id': '0-107323480',
            'ext': 'mp4',
            'title': '행복한 평이루💜',
            'description': None,
            'uploader': 'Billlie',
            'uploader_id': 'billlie',
            'timestamp': 1666262058,
            'release_timestamp': 1666262062,
            'duration': 3102,
            'thumbnail': r're:^https?://.*\.jpg$',
        }
    }]

    _AUTH_TOKEN = None
    _WEV_DEVICE_ID = None

    _ACCOUNT_API_BASE = 'https://accountapi.weverse.io/web/api/v2'
    _NAVER_API_BASE = 'https://global.apis.naver.com'

    def _call_api(self, url, video_id, data=None, note='Downloading API JSON'):
        # https://ssl.pstatic.net/static/wevweb/2_3_2_11101725/public/static/js/2488.a09b41ff.chunk.js
        # from https://ssl.pstatic.net/static/wevweb/2_3_2_11101725/public/static/js/main.e206f7c1.js:
        key = b'1b9cb6378d959b45714bec49971ade22e6e24e42'
        ts = int(time.time() * 1000)
        wmd = base64.b64encode(
            hmac.HMAC(key, f'{url[:255]}{ts}'.encode(), digestmod=hashlib.sha1).digest()).decode()
        headers = {
            'Authorization': f'Bearer {self._AUTH_TOKEN}',
            'WEV-device-Id': self._WEV_DEVICE_ID,
        }
        if data:
            headers['Content-Type'] = 'application/json'
        return self._download_json(
            url, video_id, note=note, data=data, headers=headers, query={
                'appId': 'be4d79eb8fc7bd008ee82c8ec4ff6fd4',
                'language': 'en',
                'platform': 'WEB',
                'wpf': 'pc',
                'wmsgpad': ts,
                'wmd': wmd,
            })

    def _check_auth(self):
        if self._AUTH_TOKEN:
            return True

        auth_cookie = self._get_cookies('https://weverse.io/').get('we2_access_token')
        if auth_cookie:
            self._AUTH_TOKEN = auth_cookie.value
            return True

        return False

    def _perform_login(self, username, password):
        if self._check_auth():
            return

        headers = {
            'x-acc-app-secret': '5419526f1c624b38b10787e5c10b2a7a',
            'x-acc-app-version': '2.1.14',
            'x-acc-language': 'en',
            'x-acc-service-id': 'weverse',
            'x-acc-trace-id': random_uuidv4(),
            'x-clog-user-device-id': random_uuidv4(),
        }
        check_username = self._download_json(
            f'{self._ACCOUNT_API_BASE}/signup/email/status', None,
            note='Checking username', query={'email': username}, headers=headers)
        if not check_username.get('hasPassword'):
            self.raise_login_required('Invalid username provided')

        headers['content-type'] = 'application/json'
        auth = self._download_json(
            f'{self._ACCOUNT_API_BASE}/auth/token/by-credentials', None,
            expected_status=(400, 401, 403), data=json.dumps({
                'email': username,
                'password': password,
            }, separators=(',', ':')).encode('utf-8'), headers=headers, note='Logging in')
        if not auth.get('accessToken'):
            raise ExtractorError('Access denied. Wrong password?', expected=True)

        self._AUTH_TOKEN = auth['accessToken']

    def _real_initialize(self):
        if not self._check_auth():
            self.raise_login_required()
        if not self._WEV_DEVICE_ID:
            if self._configuration_arg('device', ie_key=WeverseIE):
                self._WEV_DEVICE_ID = self._configuration_arg('device', ie_key=WeverseIE)[0]
            else:
                self._WEV_DEVICE_ID = random_uuidv4()  # TODO: this is probably wrong

    def _real_extract(self, url):
        uploader_id, video_id = self._match_valid_url(url).group('artist', 'id')
        post = self._call_api(
            f'{self._NAVER_API_BASE}/weverse/wevweb/post/v1.0/post-{video_id}?fieldSet=postV1', video_id)

        if traverse_obj(post, ('extension', 'video', 'type')) != 'VOD':
            raise ExtractorError('Only VOD content is currently supported', expected=True)
        infra_video_id = traverse_obj(post, ('extension', 'video', 'infraVideoId'))
        api_video_id = traverse_obj(post, ('extension', 'video', 'videoId'))
        service_id = traverse_obj(post, ('extension', 'video', 'serviceId'))
        if not infra_video_id or not api_video_id or not service_id:
            raise ExtractorError('Required ID value(s) not found in API response')

        in_key = self._call_api(
            f'{self._NAVER_API_BASE}/weverse/wevweb/video/v1.0/vod/{api_video_id}/inKey?preview=false',
            video_id, data=b'{}', note='Downloading VOD API key')['inKey']

        vod_json = self._download_json(
            f'{self._NAVER_API_BASE}/rmcnmv/rmcnmv/vod/play/v2.0/{infra_video_id}', video_id,
            note='Downloading VOD JSON', query={
                'key': in_key,
                'sid': service_id,
                'pid': random_uuidv4(),
                'nonce': int(time.time() * 1000),
                'devt': 'html5_pc',
                'prv': 'Y' if post.get('membershipOnly') else 'N',
                'aup': 'N',
                'stpb': 'N',
                'cpl': 'en',
                'env': 'prod',
                'lc': 'en',
                'adi': '[{"adSystem":"null"}]',
                'adu': '/',
            })

        formats = []
        for video in traverse_obj(vod_json, ('videos', 'list', ...)):
            if not traverse_obj(video, ('encodingOption', 'isEncodingComplete')) or not video.get('source'):
                continue
            formats.append({
                'url': video['source'],
                'width': int_or_none(traverse_obj(video, ('encodingOption', 'width'))),
                'height': int_or_none(traverse_obj(video, ('encodingOption', 'height'))),
                'vcodec': video.get('type'),
                'vbr': traverse_obj(video, ('bitrate', 'video')),
                'abr': traverse_obj(video, ('bitrate', 'audio')),
                'filesize': video.get('size'),
                'format_id': traverse_obj(video, ('encodingOption', 'id')),
            })
        for stream in traverse_obj(vod_json, ('streams', ...)):
            if stream.get('type') != 'HLS' or not stream.get('source'):
                continue
            query = {}
            for param in traverse_obj(stream, ('keys', ...)):
                if param.get('type') != 'param' or not param.get('name') or not param.get('value'):
                    continue
                query.update({
                    param['name']: param['value'],
                })
            fmts = self._extract_m3u8_formats(
                stream['source'], video_id, 'mp4', m3u8_id='hls', fatal=False, query=query) or []
            if query:
                for fmt in fmts:
                    fmt['extra_param_to_segment_url'] = urllib.parse.urlencode(query)
            formats.extend(fmts)
        if not formats:
            self.raise_no_formats('No completed VOD formats found', expected=True)
        self._sort_formats(formats)

        return {
            'id': video_id,
            'title': traverse_obj(post, ('extension', 'mediaInfo', 'title'), 'title', default=''),
            'description': traverse_obj(post, ('extension', 'mediaInfo', 'body'), 'body', expected_type=str),
            'uploader': traverse_obj(post, ('author', 'profileName'), expected_type=str),
            'uploader_id': uploader_id,
            'timestamp': int_or_none(
                traverse_obj(post, ('extension', 'video', 'onAirStartAt'), expected_type=int), scale=1000),
            'release_timestamp': int_or_none(post.get('publishedAt'), scale=1000),
            'duration': float_or_none(
                traverse_obj(post, ('extension', 'video', 'playTime'), expected_type=int)),
            'thumbnail': traverse_obj(
                post, ('extension', 'mediaInfo', 'thumbnail', 'url'), ('extension', 'video', 'thumb')),
            'formats': formats,
        }


class WeverseHLSIE(InfoExtractor):
    _VALID_URL = r'https?://weverse(?:-[^.]+)?\.akamaized.net/(?:[^/]+/){5}hls/(?P<id>[a-f0-9-]+)\.m3u8\?(?P<query>__gda__=[a-f0-9_]+)'

    def _real_extract(self, url):
        video_id, query = self._match_valid_url(url).group('id', 'query')
        formats = self._extract_m3u8_formats(url, video_id, 'mp4', m3u8_id='hls')
        return {
            'id': video_id,
            'title': video_id,
            'formats': formats,
            'extra_param_to_segment_url': query,
        }
