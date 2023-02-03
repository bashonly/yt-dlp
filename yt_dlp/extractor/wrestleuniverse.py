import base64
import binascii
import json
import time

from .common import InfoExtractor
from ..utils import (
    ExtractorError,
    int_or_none,
    jwt_decode_hs256,
    traverse_obj,
    url_or_none,
)


class WrestleUniverseIE(InfoExtractor):
    _VALID_URL = r'https?://(?:www\.)?wrestle-universe\.com/(?:(?P<lang>[\w-]+)/)?lives/(?P<id>\w+)'
    _TESTS = [{
        'url': 'https://www.wrestle-universe.com/en/lives/buH9ibbfhdJAY4GKZcEuJX',
        'info_dict': {
            'id': 'buH9ibbfhdJAY4GKZcEuJX',
            'ext': 'mp4',
            'title': '【PPV】Beyond the origins, into the future',
            'description': 'md5:9a872db68cd09be4a1e35a3ee8b0bdfc',
            'channel': 'tjpw',
            'location': '東京・Twin Box AKIHABARA',
            'duration': 10098,
            'timestamp': 1675076400,
            'upload_date': '20230130',
            'thumbnail': 'https://image.asset.wrestle-universe.com/rJs2m7cBaLXrwCcxMdQGRM/rJs2m7cBaLXrwCcxMdQGRM',
            'thumbnails': 'count:3',
            'hls_aes_key': '5633184acd6e43f1f1ac71c6447a4186',
            'hls_aes_iv': '5bac71beb33197d5600337ce86de7862',
        },
        'params': {
            'skip_download': 'm3u8',
        },
    }]

    def _get_token_cookie(self):
        token_cookie = self._get_cookies('https://www.wrestle-universe.com/').get('token')
        if not token_cookie or not token_cookie.value:
            self.raise_login_required(method='cookies')
        return token_cookie.value

    def _call_api(self, video_id, path='', msg='API', auth=False, data=None, query={}, fatal=True):
        headers = {'CA-CID': ''}
        if data:
            headers['Content-Type'] = 'application/json;charset=utf-8'
        if auth:
            headers['Authorization'] = f'Bearer {self._get_token_cookie()}'
        return self._download_json(
            f'https://api.wrestle-universe.com/v1/events/{video_id}{path}', video_id,
            note=f'Downloading {msg} JSON', errnote=f'Failed to download {msg} JSON',
            data=json.dumps(data, separators=(',', ':')).encode('utf-8') if data else None,
            headers=headers, query=query, fatal=fatal)

    def _call_public_key_api(self, video_id):
        # TODO: Fix imports using `dependencies.cryptodome`
        from Cryptodome.Cipher import PKCS1_OAEP
        from Cryptodome.Hash import SHA1
        from Cryptodome.PublicKey import RSA

        private_key = RSA.generate(2048)
        cipher = PKCS1_OAEP.new(private_key, hashAlgo=SHA1)

        def decrypt(data):
            if not data:
                return None
            try:
                return cipher.decrypt(base64.b64decode(data)).decode()
            except (ValueError, binascii.Error) as e:
                raise ExtractorError(f'Could not decrypt data: {e}')

        token = base64.b64encode(private_key.public_key().export_key('DER')).decode()
        api_json = self._call_api(video_id, ':watchArchive', 'watch archive', auth=True, data={
            # deviceId is a random uuidv4 generated at login; not required but may be in future
            # 'deviceId': self._DEVICE_ID,
            'token': token,
            'method': 1,
        })
        return api_json, decrypt

    def _real_extract(self, url):
        lang, video_id = self._match_valid_url(url).group('lang', 'id')
        if not lang:
            lang = 'ja'

        metadata = self._call_api(video_id, msg='metadata', query={'al': lang}, fatal=False)
        if not metadata:
            webpage = self._download_webpage(url, video_id)
            nextjs_data = self._search_nextjs_data(webpage, video_id)
            metadata = traverse_obj(nextjs_data, ('props', 'pageProps', 'eventFallbackData', {dict}))

        info = traverse_obj(metadata, {
            'title': ('displayName', {str}),
            'description': ('description', {str}),
            'channel': ('labels', 'group', {str}),
            'location': ('labels', 'venue', {str}),
            'timestamp': ('startTime', {int_or_none}),
            'thumbnails': (('keyVisualUrl', 'alterKeyVisualUrl', 'heroKeyVisualUrl'), {url_or_none}, {'url': None}),
        })

        ended_time = traverse_obj(metadata, ('endedTime', {int_or_none}))
        if info.get('timestamp') and ended_time:
            info['duration'] = ended_time - info['timestamp']

        video_data, decrypt = self._call_public_key_api(video_id)
        if video_data.get('canWatch') is False:
            exp = traverse_obj(jwt_decode_hs256(self._get_token_cookie()), ('exp', {int_or_none}))
            if not exp:
                raise ExtractorError('There was a problem with the token cookie')
            elif exp <= int(time.time()):
                raise ExtractorError(
                    'Expired token. Refresh your cookies in browser and try again', expected=True)
            raise ExtractorError(
                'This account does not have access to the requested content', expected=True)

        hls_url = traverse_obj(video_data, (
            ('hls', None), ('urls', 'chromecastUrls'), ..., {url_or_none}), get_all=False)
        if not hls_url:
            self.raise_no_formats('No supported formats found')
        formats = self._extract_m3u8_formats(hls_url, video_id, 'mp4', m3u8_id='hls', live=True)
        for f in formats:
            # bitrates are exaggerated in master playlists, avoid wrong/huge filesize_approx values
            if f.get('tbr'):
                f['tbr'] = f['tbr'] // 4

        hls_aes_key = traverse_obj(video_data, ('hls', 'key', {decrypt}))
        if not hls_aes_key and traverse_obj(video_data, ('hls', 'encryptType', {int_or_none})) > 0:
            self.report_warning('HLS AES-128 key was not found in API response')

        return {
            'id': video_id,
            'formats': formats,
            'hls_aes_key': hls_aes_key,
            'hls_aes_iv': traverse_obj(video_data, ('hls', 'iv', {decrypt})),
            **info,
        }
