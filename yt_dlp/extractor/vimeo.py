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
    IE_NAME = 'vimeo'
    _VALID_URL = r'https?://(?:www\.)?vimeo\.com/(?P<id>\d+)(?:/(?P<unlisted_hash>[\da-f]{10}))?'
    # XXX: Use below if player.vimeo.com URLs should be extracted by this IE instead
    # _VALID_URL = r'https?://(?:www\.|player\.)?vimeo\.com/(?:video/)?(?P<id>\d+)(?:/(?P<unlisted_hash>[\da-f]{10}))?'
    _EMBED_REGEX = [r'<video[^>]+src=(["\'])(?P<url>(?:https?:)?//(?:www\.)?vimeo\.com/[0-9]+)\1']
    TESTS = [
        {
            'url': 'http://vimeo.com/56015672#at=0',
            'md5': '8879b6cc097e987f02484baf890129e5',
            'info_dict': {
                'id': '56015672',
                'ext': 'mp4',
                'title': "youtube-dl test video '' ä↭𝕐-BaW jenozKc",
                'description': 'md5:2d3305bad981a06ff79f027f19865021',
                'timestamp': 1355990239,
                'upload_date': '20121220',
                'uploader_url': r're:https?://(?:www\.)?vimeo\.com/user7108434',
                'uploader_id': 'user7108434',
                'uploader': 'Filippo Valsorda',
                'duration': 10,
                'license': 'by-sa',
            },
            'params': {
                'format': 'best[protocol=https]',
            },
            'skip': 'No longer available'
        },
        {
            'url': 'http://vimeo.com/68375962',
            'md5': 'aaf896bdb7ddd6476df50007a0ac0ae7',
            'note': 'Video protected with password',
            'info_dict': {
                'id': '68375962',
                'ext': 'mp4',
                'title': 'youtube-dl password protected test video',
                'timestamp': 1371200155,
                'upload_date': '20130614',
                'uploader_url': r're:https?://(?:www\.)?vimeo\.com/user18948128',
                'uploader_id': 'user18948128',
                'uploader': 'Jaime Marquínez Ferrándiz',
                'duration': 10,
                'description': 'md5:6173f270cd0c0119f22817204b3eb86c',
                'thumbnail': 'https://i.vimeocdn.com/video/440665496-b2c5aee2b61089442c794f64113a8e8f7d5763c3e6b3ebfaf696ae6413f8b1f4-d_1280',
                'view_count': int,
                'comment_count': int,
                'like_count': int,
            },
            'params': {
                'format': 'best[protocol=https]',
                'videopassword': 'youtube-dl',
            },
        },
        {
            'url': 'http://vimeo.com/76979871',
            'note': 'Video with subtitles',
            'info_dict': {
                'id': '76979871',
                'ext': 'mov',
                'title': 'The New Vimeo Player (You Know, For Videos)',
                'description': 'md5:2ec900bf97c3f389378a96aee11260ea',
                'timestamp': 1381846109,
                'upload_date': '20131015',
                'uploader_url': r're:https?://(?:www\.)?vimeo\.com/staff',
                'uploader_id': 'staff',
                'uploader': 'Vimeo Staff',
                'duration': 62,
                'thumbnail': 'https://i.vimeocdn.com/video/452001751-8216e0571c251a09d7a8387550942d89f7f86f6398f8ed886e639b0dd50d3c90-d_1280',
                'subtitles': {
                    'de': 'count:5',
                    'en': 'count:5',
                    'es': 'count:5',
                    'fr': 'count:5',
                },
            },
            'expected_warnings': ['Ignoring subtitle tracks found in the HLS manifest'],
        },
        {
            # contains original format
            'url': 'https://vimeo.com/33951933',
            'md5': '53c688fa95a55bf4b7293d37a89c5c53',
            'info_dict': {
                'id': '33951933',
                'ext': 'mp4',
                'title': 'FOX CLASSICS - Forever Classic ID - A Full Minute',
                'uploader': 'The DMCI',
                'uploader_url': r're:https?://(?:www\.)?vimeo\.com/dmci',
                'uploader_id': 'dmci',
                'timestamp': 1324343742,
                'upload_date': '20111220',
                'description': 'md5:ae23671e82d05415868f7ad1aec21147',
                'duration': 60,
                'comment_count': int,
                'view_count': int,
                'thumbnail': 'https://i.vimeocdn.com/video/231174622-dd07f015e9221ff529d451e1cc31c982b5d87bfafa48c4189b1da72824ee289a-d_1280',
                'like_count': int,
                'tags': 'count:11',
            },
        },
        {
            'note': 'Contains original format not accessible in webpage',
            'url': 'https://vimeo.com/393756517',
            'md5': 'c464af248b592190a5ffbb5d33f382b0',
            'info_dict': {
                'id': '393756517',
                'ext': 'mov',
                'timestamp': 1582642091,
                'uploader_id': 'frameworkla',
                'title': 'Straight To Hell - Sabrina: Netflix',
                'uploader': 'Framework Studio',
                'description': 'md5:b41bf1564570c94f7b20e248d282b5ba',
                'upload_date': '20200225',
                'duration': 176,
                'thumbnail': 'https://i.vimeocdn.com/video/859377297-836494a4ef775e9d4edbace83937d9ad34dc846c688c0c419c0e87f7ab06c4b3-d_1280',
                'uploader_url': 'https://vimeo.com/frameworkla',
            },
        },
        {
            # redirects to ondemand extractor and should be passed through it
            # for successful extraction
            'url': 'https://vimeo.com/73445910',
            'info_dict': {
                'id': '73445910',
                'ext': 'mp4',
                'title': 'The Reluctant Revolutionary',
                'uploader': '10Ft Films',
                'uploader_url': r're:https?://(?:www\.)?vimeo\.com/tenfootfilms',
                'uploader_id': 'tenfootfilms',
                'description': 'md5:0fa704e05b04f91f40b7f3ca2e801384',
                'upload_date': '20130830',
                'timestamp': 1377853339,
            },
            'params': {
                'skip_download': True,
            },
            'skip': 'this page is no longer available.',
        },
        {
            'url': 'https://vimeo.com/109815029',
            'note': 'Video not completely processed, "failed" seed status',
            'only_matching': True,
        },
        {
            'url': 'https://vimeo.com/showcase/3253534/video/119195465',
            'note': 'A video in a password protected album (showcase)',
            'info_dict': {
                'id': '119195465',
                'ext': 'mp4',
                'title': "youtube-dl test video '' ä↭𝕐-BaW jenozKc",
                'uploader': 'Philipp Hagemeister',
                'uploader_id': 'user20132939',
                'description': 'md5:b41bf1564570c94f7b20e248d282b5ba',
                'upload_date': '20150209',
                'timestamp': 1423518307,
                'thumbnail': 'https://i.vimeocdn.com/video/default_1280',
                'duration': 10,
                'like_count': int,
                'uploader_url': 'https://vimeo.com/user20132939',
                'view_count': int,
                'comment_count': int,
            },
            'params': {
                'format': 'best[protocol=https]',
                'videopassword': 'youtube-dl',
            },
        },
        {
            # source file returns 403: Forbidden
            'url': 'https://vimeo.com/7809605',
            'only_matching': True,
        },
        {
            'note': 'Direct URL with hash',
            'url': 'https://vimeo.com/160743502/abd0e13fb4',
            'info_dict': {
                'id': '160743502',
                'ext': 'mp4',
                'uploader': 'Julian Tryba',
                'uploader_id': 'aliniamedia',
                'title': 'Harrisville New Hampshire',
                'timestamp': 1459259666,
                'upload_date': '20160329',
                'release_timestamp': 1459259666,
                'license': 'by-nc',
                'duration': 159,
                'comment_count': int,
                'thumbnail': 'https://i.vimeocdn.com/video/562802436-585eeb13b5020c6ac0f171a2234067938098f84737787df05ff0d767f6d54ee9-d_1280',
                'like_count': int,
                'uploader_url': 'https://vimeo.com/aliniamedia',
                'release_date': '20160329',
            },
            'params': {'skip_download': True},
        },
        {
            'url': 'https://vimeo.com/138909882',
            'info_dict': {
                'id': '138909882',
                'ext': 'x-m4v',
                'title': 'Eastnor Castle 2015 Firework Champions - The Promo!',
                'description': 'md5:5967e090768a831488f6e74b7821b3c1',
                'uploader_id': 'fireworkchampions',
                'uploader': 'Firework Champions',
                'upload_date': '20150910',
                'timestamp': 1441901895,
                'thumbnail': 'https://i.vimeocdn.com/video/534715882-6ff8e4660cbf2fea68282876d8d44f318825dfe572cc4016e73b3266eac8ae3a-d_1280',
                'comment_count': int,
                'duration': 229,
                'like_count': int,
                'uploader_url': 'https://vimeo.com/fireworkchampions',
                'view_count': int,
                'tags': 'count:6',
            },
            'params': {
                'skip_download': True,
            },
        },
        {
            # requires passing unlisted_hash(a52724358e) to load_download_config request
            'url': 'https://vimeo.com/392479337/a52724358e',
            'only_matching': True,
        },
        {
            # similar, but all numeric: ID must be 581039021, not 9603038895
            # issue #29690
            'url': 'https://vimeo.com/581039021/9603038895',
            'info_dict': {
                'id': '581039021',
                'ext': 'mp4',
                'timestamp': 1627621014,
                'release_timestamp': 1627621014,
                'duration': 976,
                'comment_count': int,
                'thumbnail': 'https://i.vimeocdn.com/video/1202249320-4ddb2c30398c0dc0ee059172d1bd5ea481ad12f0e0e3ad01d2266f56c744b015-d_1280',
                'like_count': int,
                'uploader_url': 'https://vimeo.com/txwestcapital',
                'release_date': '20210730',
                'uploader': 'Christopher Inks',
                'title': 'Thursday, July 29, 2021 BMA Evening Video Update',
                'uploader_id': 'txwestcapital',
                'upload_date': '20210730',
            },
            'params': {
                'skip_download': True,
            },
        },
    ]

    def _real_extract(self, url):
        url, data, headers = self._unsmuggle_headers(url)
        if 'Referer' not in headers:
            headers['Referer'] = url
        # TODO


class VimeoPlayerIE(VimeoBaseIE):
    IE_NAME = 'vimeo:player'
    _VALID_URL = r'https?://player\.vimeo\.com/video/(?P<id>[0-9]+)'
    _EMBED_REGEX = [r'<iframe[^>]+?src=(["\'])(?P<url>(?:https?:)?//player\.vimeo\.com/video/\d+.*?)\1']
    TESTS = [
        {
            'url': 'http://player.vimeo.com/video/54469442',
            'md5': '619b811a4417aa4abe78dc653becf511',
            'note': 'Videos that embed the url in the player page',
            'info_dict': {
                'id': '54469442',
                'ext': 'mp4',
                'title': 'Kathy Sierra: Building the minimum Badass User, Business of Software 2012',
                'uploader': 'Business of Software',
                'uploader_url': r're:https?://(?:www\.)?vimeo\.com/businessofsoftware',
                'uploader_id': 'businessofsoftware',
                'duration': 3610,
                'description': None,
                'thumbnail': 'https://i.vimeocdn.com/video/376682406-f34043e7b766af6bef2af81366eacd6724f3fc3173179a11a97a1e26587c9529-d_1280',
            },
            'params': {
                'format': 'best[protocol=https]',
            },
        },
        {
            # from https://www.ouya.tv/game/Pier-Solar-and-the-Great-Architects/
            'url': 'https://player.vimeo.com/video/98044508',
            'note': 'The js code contains assignments to the same variable as the config',
            'info_dict': {
                'id': '98044508',
                'ext': 'mp4',
                'title': 'Pier Solar OUYA Official Trailer',
                'uploader': 'Tulio Gonçalves',
                'uploader_url': r're:https?://(?:www\.)?vimeo\.com/user28849593',
                'uploader_id': 'user28849593',
                'duration': 118,
                'thumbnail': 'https://i.vimeocdn.com/video/478636036-c18440305ef3df9decfb6bf207a61fe39d2d17fa462a96f6f2d93d30492b037d-d_1280',
            },
        },
        {
            'url': 'http://player.vimeo.com/video/68375962',
            'md5': 'aaf896bdb7ddd6476df50007a0ac0ae7',
            'info_dict': {
                'id': '68375962',
                'ext': 'mp4',
                'title': 'youtube-dl password protected test video',
                'uploader_url': r're:https?://(?:www\.)?vimeo\.com/user18948128',
                'uploader_id': 'user18948128',
                'uploader': 'Jaime Marquínez Ferrándiz',
                'duration': 10,
                'description': 'md5:6173f270cd0c0119f22817204b3eb86c',
                'thumbnail': 'https://i.vimeocdn.com/video/440665496-b2c5aee2b61089442c794f64113a8e8f7d5763c3e6b3ebfaf696ae6413f8b1f4-d_1280',
                'view_count': int,
                'comment_count': int,
                'like_count': int,
            },
            'params': {
                'format': 'best[protocol=https]',
                'videopassword': 'youtube-dl',
            },
        },
        # XXX: add _WEBPAGE_TESTS
        # https://gettingthingsdone.com/workflowmap/
        # vimeo embed with check-password page protected by Referer header
    ]


class VimeoReviewIE(InfoExtractor):
    IE_NAME = 'vimeo:review'
    IE_DESC = 'Review pages on vimeo'
    _VALID_URL = r'https?://(?:www\.)?vimeo\.com/[^/?#]+/review/(?P<id>[0-9]+)/[0-9a-f]{10}'
    _TESTS = [{
        'url': 'https://vimeo.com/user21297594/review/75524534/3c257a1b5d',
        'md5': 'c507a72f780cacc12b2248bb4006d253',
        'info_dict': {
            'id': '75524534',
            'ext': 'mp4',
            'title': "DICK HARDWICK 'Comedian'",
            'uploader': 'Richard Hardwick',
            'uploader_id': 'user21297594',
            'description': "Comedian Dick Hardwick's five minute demo filmed in front of a live theater audience.\nEdit by Doug Mattocks",
            'duration': 304,
            'thumbnail': 'https://i.vimeocdn.com/video/450115033-43303819d9ebe24c2630352e18b7056d25197d09b3ae901abdac4c4f1d68de71-d_1280',
            'uploader_url': 'https://vimeo.com/user21297594',
        },
    }, {
        'note': 'video player needs Referer',
        'url': 'https://vimeo.com/user22258446/review/91613211/13f927e053',
        'md5': '6295fdab8f4bf6a002d058b2c6dce276',
        'info_dict': {
            'id': '91613211',
            'ext': 'mp4',
            'title': 're:(?i)^Death by dogma versus assembling agile . Sander Hoogendoorn',
            'uploader': 'DevWeek Events',
            'duration': 2773,
            'thumbnail': r're:^https?://.*\.jpg$',
            'uploader_id': 'user22258446',
        },
        'skip': 'video gone',
    }, {
        'note': 'Password protected',
        'url': 'https://vimeo.com/user37284429/review/138823582/c4d865efde',
        'info_dict': {
            'id': '138823582',
            'ext': 'mp4',
            'title': 'EFFICIENT PICKUP MASTERCLASS MODULE 1',
            'uploader': 'TMB',
            'uploader_id': 'user37284429',
        },
        'params': {
            'videopassword': 'holygrail',
        },
        'skip': 'video gone',
    }, {
        'note': 'turn into full test',
        'url': 'https://vimeo.com/user190726417/review/798200073/d0dbcc8dea',
        'only_matching': True,
    }]

    def _real_extract(self, url):
        video_id = self._match_valid_url(url).group('id')
        return self.url_result(f'https://vimeo.com/{video_id}', VimeoIE.ie_key(), video_id)


class VimeoOndemandIE(VimeoBaseIE):
    IE_NAME = 'vimeo:ondemand'
    _VALID_URL = r'https?://(?:www\.)?vimeo\.com/ondemand/(?P<id>[^/?#]+)'
    _TESTS = [{
        # ondemand video not available via https://vimeo.com/id
        'url': 'https://vimeo.com/ondemand/20704',
        'md5': 'c424deda8c7f73c1dfb3edd7630e2f35',
        'info_dict': {
            'id': '105442900',
            'ext': 'mp4',
            'title': 'המעבדה - במאי יותם פלדמן',
            'uploader': 'גם סרטים',
            'uploader_url': r're:https?://(?:www\.)?vimeo\.com/gumfilms',
            'uploader_id': 'gumfilms',
            'description': 'md5:aeeba3dbd4d04b0fa98a4fdc9c639998',
            'upload_date': '20140906',
            'timestamp': 1410032453,
            'thumbnail': 'https://i.vimeocdn.com/video/488238335-d7bf151c364cff8d467f1b73784668fe60aae28a54573a35d53a1210ae283bd8-d_1280',
            'comment_count': int,
            'license': 'https://creativecommons.org/licenses/by-nc-nd/3.0/',
            'duration': 53,
            'view_count': int,
            'like_count': int,
        },
        'params': {
            'format': 'best[protocol=https]',
        },
        'expected_warnings': ['Unable to download JSON metadata'],
    }, {
        # requires Referer to be passed along with og:video:url
        'url': 'https://vimeo.com/ondemand/36938/126682985',
        'info_dict': {
            'id': '126584684',
            'ext': 'mp4',
            'title': 'Rävlock, rätt läte på rätt plats',
            'uploader': 'Lindroth & Norin',
            'uploader_url': r're:https?://(?:www\.)?vimeo\.com/lindrothnorin',
            'uploader_id': 'lindrothnorin',
            'description': 'md5:c3c46a90529612c8279fb6af803fc0df',
            'upload_date': '20150502',
            'timestamp': 1430586422,
            'duration': 121,
            'comment_count': int,
            'view_count': int,
            'thumbnail': 'https://i.vimeocdn.com/video/517077723-7066ae1d9a79d3eb361334fb5d58ec13c8f04b52f8dd5eadfbd6fb0bcf11f613-d_1280',
            'like_count': int,
        },
        'params': {
            'skip_download': True,
        },
        'expected_warnings': ['Unable to download JSON metadata'],
    }, {
        'url': 'https://vimeo.com/ondemand/nazmaalik',
        'only_matching': True,
    }, {
        'url': 'https://vimeo.com/ondemand/141692381',
        'only_matching': True,
    }, {
        'url': 'https://vimeo.com/ondemand/thelastcolony/150274832',
        'only_matching': True,
    }]


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
        {
            'url': 'https://vimeo.com/album/2632481/video/79010983',
            'only_matching': True,
        },
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


class VimeoPlaylistBaseIE(VimeoBaseIE):
    ...


class VimeoChannelIE(VimeoPlaylistBaseIE):
    IE_NAME = 'vimeo:channel'
    _VALID_URL = r'https?://(?:www\.)?vimeo\.com/channels/(?P<id>[^/?#]+)'
    _TESTS = [
        {
            'url': 'https://vimeo.com/channels/tributes',
            'info_dict': {
                'id': 'tributes',
                'title': 'Vimeo Tributes',
            },
            'playlist_mincount': 22,
        },
        {
            'url': 'http://vimeo.com/channels/keypeele/75629013',
            'md5': '2f86a05afe9d7abc0b9126d229bbe15d',
            'info_dict': {
                'id': '75629013',
                'ext': 'mp4',
                'title': 'Key & Peele: Terrorist Interrogation',
                'description': 'md5:6173f270cd0c0119f22817204b3eb86c',
                'uploader_url': r're:https?://(?:www\.)?vimeo\.com/atencio',
                'uploader_id': 'atencio',
                'uploader': 'Peter Atencio',
                'channel_id': 'keypeele',
                'channel_url': r're:https?://(?:www\.)?vimeo\.com/channels/keypeele',
                'timestamp': 1380339469,
                'upload_date': '20130928',
                'duration': 187,
                'thumbnail': 'https://i.vimeocdn.com/video/450239872-a05512d9b1e55d707a7c04365c10980f327b06d966351bc403a5d5d65c95e572-d_1280',
                'view_count': int,
                'comment_count': int,
                'like_count': int,
            },
            'params': {'format': 'http-1080p'},
        },
        {
            # only available via https://vimeo.com/channels/tributes/6213729 and
            # not via https://vimeo.com/6213729
            'url': 'https://vimeo.com/channels/tributes/6213729',
            'info_dict': {
                'id': '6213729',
                'ext': 'mp4',
                'title': 'Vimeo Tribute: The Shining',
                'uploader': 'Casey Donahue',
                'uploader_url': r're:https?://(?:www\.)?vimeo\.com/caseydonahue',
                'uploader_id': 'caseydonahue',
                'channel_url': r're:https?://(?:www\.)?vimeo\.com/channels/tributes',
                'channel_id': 'tributes',
                'timestamp': 1250886430,
                'upload_date': '20090821',
                'description': 'md5:b41bf1564570c94f7b20e248d282b5ba',
                'duration': 321,
                'comment_count': int,
                'view_count': int,
                'thumbnail': 'https://i.vimeocdn.com/video/22728298-bfc22146f930de7cf497821c7b0b9f168099201ecca39b00b6bd31fcedfca7a6-d_1280',
                'like_count': int,
            },
            'params': {
                'skip_download': True,
            },
        },
        {
            'url': 'https://vimeo.com/channels/staffpicks/143603739',
            'info_dict': {
                'id': '143603739',
                'ext': 'mp4',
                'uploader': 'Karim Huu Do',
                'timestamp': 1445846953,
                'upload_date': '20151026',
                'title': 'The Shoes - Submarine Feat. Blaine Harrison',
                'uploader_id': 'karimhd',
                'description': 'md5:8e2eea76de4504c2e8020a9bcfa1e843',
                'channel_id': 'staffpicks',
                'duration': 336,
                'comment_count': int,
                'view_count': int,
                'thumbnail': 'https://i.vimeocdn.com/video/541243181-b593db36a16db2f0096f655da3f5a4dc46b8766d77b0f440df937ecb0c418347-d_1280',
                'like_count': int,
                'uploader_url': 'https://vimeo.com/karimhd',
                'channel_url': 'https://vimeo.com/channels/staffpicks',
                'tags': 'count:6',
            },
            'params': {'skip_download': 'm3u8'},
        },
    ]


class VimeoUserIE(VimeoPlaylistBaseIE):
    IE_NAME = 'vimeo:user'
    _VALID_URL = r'https?://(?:www\.)?vimeo\.com/(?!(?:\d+|watchlater|moogaloop)(?:$|[?#/]))(?P<id>[^/?#]+)(?:/videos)?/?(?:$|[?#])'
    _TESTS = [{
        'url': 'https://vimeo.com/nkistudio/videos',
        'info_dict': {
            'title': 'Nki',
            'id': 'nkistudio',
        },
        'playlist_mincount': 66,
    }, {
        'url': 'https://vimeo.com/nkistudio/',
        'only_matching': True,
    }]


class VimeoGroupsIE(VimeoPlaylistBaseIE):
    IE_NAME = 'vimeo:group'
    _VALID_URL = r'https?://(?:www\.)?vimeo\.com/groups/(?P<id>[^/?#]+)'
    _TESTS = [
        {
            'url': 'https://vimeo.com/groups/meetup',
            'info_dict': {
                'id': 'meetup',
                'title': 'Vimeo Meetup!',
            },
            'playlist_mincount': 27,
        },
        {
            'url': 'https://vimeo.com/groups/travelhd/videos/22439234',
            'only_matching': True,
        },
    ]


class VimeoWatchLaterIE(VimeoPlaylistBaseIE):
    IE_NAME = 'vimeo:watchlater'
    IE_DESC = 'Vimeo watch later list, ":vimeowatchlater" keyword (requires authentication)'
    _VALID_URL = r'https?://(?:www\.)?vimeo\.com/(?:home/)?watchlater|:vimeowatchlater'
    _LOGIN_REQUIRED = True
    _TESTS = [{
        'url': 'https://vimeo.com/watchlater',
        'only_matching': True,
    }]


class VimeoLikesIE(VimeoPlaylistBaseIE):
    IE_NAME = 'vimeo:likes'
    IE_DESC = 'Vimeo user likes'
    _VALID_URL = r'https?://(?:www\.)?vimeo\.com/(?P<id>[^\d/?#][^/?#]*)/likes'
    _TESTS = [{
        'url': 'https://vimeo.com/user755559/likes/',
        'playlist_mincount': 293,
        'info_dict': {
            'id': 'user755559',
            'title': 'urza’s Likes',
        },
    }, {
        'url': 'https://vimeo.com/stormlapse/likes',
        'only_matching': True,
    }]


class VHXEmbedIE(VimeoBaseIE):
    IE_NAME = 'vhx:embed'
    _VALID_URL = r'https?://embed\.vhx\.tv/videos/(?P<id>\d+)'
    _EMBED_REGEX = [r'<iframe[^>]+src="(?P<url>https?://embed\.vhx\.tv/videos/\d+[^"]*)"']


class VimeoLegacyEmbedIE(VimeoBaseIE):
    IE_NAME = 'vimeo:legacy'
    _VALID_URL = r'https?://(?:www\.|player\.)?vimeo\.com/(?:moogaloop\.swf|play_redirect_hls)\?[^#]*\bclip_id=(?P<id>\d+)'
    _EMBED_REGEX = [r'<embed[^>]+?src=(["\'])(?P<url>(?:https?:)?//(?:www\.)?vimeo\.com/moogaloop\.swf.+?)\1']
    _TESTS = [{
        'url': 'http://player.vimeo.com/play_redirect_hls?clip_id=58445885&time=1359702733&sig=77ad552562d66875691aa156dba6d3dd&type=mobile_site&profiles=iphone,standard,high',
        'only_matching': True,
    }, {
        'url': 'http://vimeo.com/moogaloop.swf?clip_id=2539741',
        'only_matching': True,
    }]


class VimeoProIE(VimeoBaseIE):
    IE_NAME = 'vimeo:pro'
    _VALID_URL = r'https?://(?:www\.)?vimeopro\.com/[^/?#]+/(?P<slug>[^/?#]+)(?:(?:/videos?/(?P<id>[0-9]+)))?'
    _TESTS = [{
        # Vimeo URL derived from video_id
        'url': 'http://vimeopro.com/openstreetmapus/state-of-the-map-us-2013/video/68093876',
        'md5': '3b5ca6aa22b60dfeeadf50b72e44ed82',
        'note': 'Vimeo Pro video (#1197)',
        'info_dict': {
            'id': '68093876',
            'ext': 'mp4',
            'uploader_url': r're:https?://(?:www\.)?vimeo\.com/openstreetmapus',
            'uploader_id': 'openstreetmapus',
            'uploader': 'OpenStreetMap US',
            'title': 'Andy Allan - Putting the Carto into OpenStreetMap Cartography',
            'description': 'md5:2c362968038d4499f4d79f88458590c1',
            'duration': 1595,
            'upload_date': '20130610',
            'timestamp': 1370893156,
            'license': 'by',
            'thumbnail': 'https://i.vimeocdn.com/video/440260469-19b0d92fca3bd84066623b53f1eb8aaa3980c6c809e2d67b6b39ab7b4a77a344-d_960',
            'view_count': int,
            'comment_count': int,
            'like_count': int,
            'tags': 'count:1',
        },
        'params': {
            'format': 'best[protocol=https]',
        },
    }, {
        # password-protected VimeoPro page with Vimeo player embed
        'url': 'https://vimeopro.com/cadfem/simulation-conference-mechanische-systeme-in-perfektion',
        'info_dict': {
            'id': '764543723',
            'ext': 'mp4',
            'title': 'Mechanische Systeme in Perfektion: Realität erfassen, Innovation treiben',
            'thumbnail': 'https://i.vimeocdn.com/video/1543784598-a1a750494a485e601110136b9fe11e28c2131942452b3a5d30391cb3800ca8fd-d_1280',
            'description': 'md5:2a9d195cd1b0f6f79827107dc88c2420',
            'uploader': 'CADFEM',
            'uploader_id': 'cadfem',
            'uploader_url': 'https://vimeo.com/cadfem',
            'duration': 12505,
            'chapters': 'count:10',
        },
        'params': {
            'videopassword': 'Conference2022',
            'skip_download': True,
        },
    }]
