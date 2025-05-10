from .nbc import NBCUniversalBaseIE


class SyfyIE(NBCUniversalBaseIE):
    _VALID_URL = r'https?://(?:www\.)?syfy\.com/[^/?#]+/(?:season-\d+/episode-\d+/(?:videos/)?|videos/)(?P<id>[^/?#]+)'
    _TESTS = [{
        'url': 'https://www.syfy.com/face-off/season-13/episode-10/videos/keyed-up',
        'info_dict': {
            'id': '3774403',
            'ext': 'mp4',
            'display_id': 'keyed-up',
            'title': 'Keyed Up',
            'description': 'md5:feafd15bee449f212dcd3065bbe9a755',
            'age_limit': 14,
            'duration': 169,
            'thumbnail': r're:https://www\.syfy\.com/.+/.+\.jpg',
            'series': 'Face Off',
            'season': 'Season 13',
            'season_number': 13,
            'episode': 'Through the Looking Glass Part 2',
            'episode_number': 10,
            'timestamp': 1533711618,
            'upload_date': '20180808',
            '_old_archive_ids': ['theplatform 3774403'],
        },
        'params': {'skip_download': 'm3u8'},
    }, {
        'url': 'https://www.syfy.com/face-off/season-13/episode-10/through-the-looking-glass-part-2',
        'info_dict': {
            'id': '3772391',
            'ext': 'mp4',
            'display_id': 'through-the-looking-glass-part-2',
            'title': 'Through the Looking Glass Pt.2',
            'description': 'md5:90bd5dcbf1059fe3296c263599af41d2',
            'age_limit': 0,
            'duration': 2599,
            'thumbnail': r're:https://www\.syfy\.com/.+/.+\.jpg',
            'chapters': [{'start_time': 0.0, 'end_time': 679.0, 'title': '<Untitled Chapter 1>'},
                         {'start_time': 679.0, 'end_time': 1040.967, 'title': '<Untitled Chapter 2>'},
                         {'start_time': 1040.967, 'end_time': 1403.0, 'title': '<Untitled Chapter 3>'},
                         {'start_time': 1403.0, 'end_time': 1870.0, 'title': '<Untitled Chapter 4>'},
                         {'start_time': 1870.0, 'end_time': 2496.967, 'title': '<Untitled Chapter 5>'},
                         {'start_time': 2496.967, 'end_time': 2599, 'title': '<Untitled Chapter 6>'}],
            'series': 'Face Off',
            'season': 'Season 13',
            'season_number': 13,
            'episode': 'Through the Looking Glass Part 2',
            'episode_number': 10,
            'timestamp': 1672570800,
            'upload_date': '20230101',
            '_old_archive_ids': ['theplatform 3772391'],
        },
        'params': {'skip_download': 'm3u8'},
        'skip': 'This video requires AdobePass MSO credentials',
    }]

    def _real_extract(self, url):
        display_id = self._match_id(url)
        return self._extract_nbcu_video(url, display_id, old_ie_key='ThePlatform')
