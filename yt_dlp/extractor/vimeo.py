import functools
import time
from urllib.error import HTTPError

from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.utils import (
    ExtractorError,
    OnDemandPagedList,
    extract_attributes,
    int_or_none,
    jwt_decode_hs256,
    parse_qs,
    smuggle_url,
    traverse_obj,
    unescapeHTML,
    unsmuggle_url,
    urlencode_postdata,
)


class VimeoBaseIE(InfoExtractor):
    _NETRC_MACHINE = 'vimeo'
    _LOGIN_REQUIRED = False
    _LOGIN_URL = 'https://vimeo.com/log_in'
    _TOKEN_EXPIRY = 0

    @staticmethod
    def _smuggle_referrer(url, referrer_url):
        return smuggle_url(url, {'http_headers': {'Referer': referrer_url}})

    def _unsmuggle_headers(self, url):
        """@returns (url, smuggled_data, headers)"""
        url, data = unsmuggle_url(url, {})
        headers = self.get_param('http_headers').copy()
        if 'http_headers' in data:
            headers.update(data['http_headers'])
        return url, data, headers

    def _perform_login(self, username, password):
        self._refresh_tokens(None)
        data = {
            'action': 'login',
            'email': username,
            'password': password,
            'service': 'vimeo',
            'token': self._XSRF_TOKEN,
        }
        try:
            self._download_webpage(
                self._LOGIN_URL, None, 'Logging in',
                data=urlencode_postdata(data), headers={
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'Referer': self._LOGIN_URL,
                })
        except ExtractorError as e:
            if isinstance(e.cause, HTTPError) and e.cause.code == 418:
                raise ExtractorError(
                    'Unable to log in: bad username or password',
                    expected=True)
            raise ExtractorError('Unable to log in')

    def _has_session(self):
        return bool(self._get_cookies('vimeo.com').get('vuid'))

    def _real_initialize(self):
        if self._LOGIN_REQUIRED and not self._has_session():
            self.raise_login_required()

    def _get_video_password(self):
        password = self.get_param('videopassword')
        if password is None:
            raise ExtractorError(
                'This video is protected by a password, use the --video-password option',
                expected=True)

        return password

    def _verify_video_password(self, url, video_id, password):
        # XXX: This is almost the same as password section in `_get_album_info`
        if url.startswith('http://'):
            # XXX: This should be handled through matching url
            # vimeo only supports https now, but the user can give an http url
            url = url.replace('http://', 'https://')

        return self._download_webpage(
            url + '/password', video_id, 'Verifying the password',
            'Wrong password', data=urlencode_postdata({
                'password': password,
                'token': self._XSRF_TOKEN,
            }), headers={
                'Content-Type': 'application/x-www-form-urlencoded',
                'Referer': url,
            })

    def _refresh_tokens(self, video_id):
        if self._has_session() and self._TOKEN_EXPIRY > int(time.time()):
            return

        # XXX: Redirects to `https://vimeo.com/_next/viewer` now
        # This endpoint also gives a lot of data
        # We might need to send 511 code to unlock certain vids
        viewer = self._download_json(
            'https://vimeo.com/_rv/viewer', video_id, note='Acquiring vimeo session and tokens')

        self._JSON_WEB_TOKEN = viewer['jwt']
        self._TOKEN_EXPIRY = traverse_obj(jwt_decode_hs256(self._JSON_WEB_TOKEN), ('exp', {int_or_none}))
        if not self._TOKEN_EXPIRY:
            raise ExtractorError('There was a problem with the token cookie')

        self._XSRF_TOKEN = viewer['xsrft']
        # XXX: Might need to redo login??
        self._set_cookie('vimeo.com', 'vuid', viewer['vuid'])

    def _get_unlisted_hash(self, video_id):
        unlisted_hash = traverse_obj(self._download_json(
            f'https://vimeo.com/api/oembed.json?url=http://vimeo.com/{video_id}',
            video_id, 'Downloading unlisted hash', fatal=False, errnote=False),
            ('html', {unescapeHTML}, {extract_attributes}, 'src', {parse_qs}, 'h', 0))
        self.write_debug(f'Extracted unlisted hash for {video_id}: {unlisted_hash}')
        return unlisted_hash

    def _call_api(self, path, video_id, query={}, fatal=True, note="API JSON"):
        # XXX: This could have a class prefix/path suffix (`self._API_PREFIX`/`suffix=''`)
        self._refresh_tokens(video_id)

        return self._download_json(
            f'https://api.vimeo.com/{path}', video_id, note=f'Downloading {note}', fatal=fatal, query=query, headers={
                'Authorization': f'jwt {self._JSON_WEB_TOKEN}',
            })


class VimeoIE(VimeoBaseIE):
    _VALID_URL = r'https?://(?:www\.)?vimeo\.com/(?P<id>\d+)(?:/(?P<unlisted_hash>[\da-f]{10}))?'

    def _real_extract(self, url):
        url, data, headers = self._unsmuggle_headers(url)
        if 'Referer' not in headers:
            headers['Referer'] = url
        # TODO


class VimeoReviewIE(InfoExtractor):
    IE_NAME = 'vimeo:review'
    IE_DESC = 'Review pages on vimeo'
    _VALID_URL = r'https?://(?:www\.)?vimeo\.com/[^/]/review/(?P<id>[0-9]+)/[0-9a-f]{10})'

    def _real_extract(self, url):
        video_id = self._match_valid_url(url).group('id')
        return self.url_result(f'https://vimeo.com/{video_id}', VimeoIE.ie_key(), video_id)


class VimeoAlbumIE(VimeoBaseIE):
    IE_NAME = "vimeo:album"
    # XXX: This looks ugly, alternatives?
    _VALID_URL = r'https?://(?:www\.)?vimeo\.com/(?:album|showcase)/(?P<id>\d+)(?:/video/(?P<video_id>\d+))?'
    _PAGE_SIZE = 100
    _TESTS = [
        {
            "url": "https://vimeo.com/album/2632481",
            "info_dict": {
                "id": "2632481",
                "title": "Staff Favorites: November 2013",
            },
            "playlist_mincount": 13,
        },
        {
            "note": "Password-protected album",
            "url": "https://vimeo.com/album/3253534",
            "info_dict": {
                "title": "test",
                "id": "3253534",
            },
            "playlist_count": 1,
            "params": {
                "videopassword": "youtube-dl",
            },
        },
        ...,
    ]
    # XXX: This is not used??
    _TITLE_RE = r'<header id="page_header">\n\s*<h1>(.*?)</h1>'

    def _get_album_info(self, album_id):
        album = self._call_api(
            f'albums/{album_id}', album_id,
            query={'fields': 'description,name,privacy'}, note="album info")
        # XXX: Maybe not have this error?
        if not isinstance(album, dict):
            raise ExtractorError('Incorrect data for album')
        if traverse_obj(album, ('privacy', 'view')) != 'password':
            return album, None

        password = self._get_video_password()
        try:
            # XXX: This is almost the same as `_verify_video_password`
            hashed_pass = self._download_json(
                f'https://vimeo.com/showcase/{album_id}/auth',
                album_id, 'Verifying the password', data=urlencode_postdata({
                    'password': password,
                    'token': self._XSRF_TOKEN,
                }), headers={
                    'X-Requested-With': 'XMLHttpRequest',
                })['hashed_pass']
            return album, hashed_pass

        except ExtractorError as e:
            if isinstance(e.cause, HTTPError) and e.cause.code == 401:
                raise ExtractorError('Wrong password', expected=True)
            raise

    def _real_extract(self, url):
        album_id, video_id = self._match_id(url).groups()

        if video_id:
            # TODO: `_real_extract` is not possible since the url
            #       doesn't match and we dont want to make matching.
            #       We have to define a different function for this.
            #       Let's wait until `VimeoIE` is done for this.
            return VimeoIE._real_extract(url)

        album, hashed_pass = self._get_album_info(album_id)
        entries = OnDemandPagedList(functools.partial(
            self._fetch_page, album_id, hashed_pass), self._PAGE_SIZE)
        return self.playlist_result(
            entries, album_id, album.get('name'), album.get('description'))

    def _fetch_page(self, album_id, hashed_pass, page):
        api_page = page + 1
        query = {
            'fields': 'link,uri',
            'page': api_page,
            'per_page': self._PAGE_SIZE,
        }
        if hashed_pass:
            query['_hashed_pass'] = hashed_pass

        try:
            videos = self._call_api(
                f'albums/{album_id}/videos', album_id, query=query,
                note=f'page {api_page}')['data']

        except ExtractorError as e:
            if isinstance(e.cause, HTTPError) and e.cause.code == 400:
                return

            raise

        for video in videos:
            link = video.get('link')
            if not link:
                continue

            video_id = self._match_id(video.get('uri') or '').group('video_id')
            yield self.url_result(link, VimeoAlbumIE.ie_key(), video_id)


class VimeoOndemandIE(VimeoBaseIE):
    _VALID_URL = r'https?://(?:www\.)?vimeo\.com/ondemand/(?P<id>[^/?#]+)'


class VimeoPlaylistBaseIE(VimeoBaseIE):
    ...


class VimeoChannelsIE(VimeoPlaylistBaseIE):
    _VALID_URL = r'https?://(?:www\.)?vimeo\.com/channels/(?P<id>[^/?#]+)'


class VimeoUserIE(VimeoPlaylistBaseIE):
    _VALID_URL = r'https?://(?:www\.)?vimeo\.com/(?!(?:\d+|watchlater)(?:$|[?#/]))(?P<id>[^/?#]+)(?:/videos)?/?(?:$|[?#])'


class VimeoGroupsIE(VimeoPlaylistBaseIE):
    _VALID_URL = r'https?://(?:www\.)?vimeo\.com/groups/(?P<id>[^/?#]+)'


class VimeoLikesIE(VimeoPlaylistBaseIE):
    _VALID_URL = r'https?://(?:www\.)?vimeo\.com/(?P<id>[^\d/?#][^/?#]*)/likes'


class VimeoWatchLaterIE(VimeoPlaylistBaseIE):
    _VALID_URL = r'https?://(?:www\.)?vimeo\.com/(?:home/)?watchlater|:vimeowatchlater'


class VHXEmbedIE(VimeoBaseIE):
    ...


class VimeoProIE(VimeoBaseIE):
    ...
