from .nbc import NBCUniversalBaseIE


class BravoTVIE(NBCUniversalBaseIE):
    _VALID_URL = r'https?://(?:www\.)?(?:bravotv|oxygen)\.com/(?:[^/?#]+/)+(?P<id>[^/?#]+)'
    _TESTS = [{
        'url': 'https://www.bravotv.com/top-chef/season-16/episode-15/videos/the-top-chef-season-16-winner-is',
        'info_dict': {
            'id': '3923059',
            'ext': 'mp4',
            'title': 'The Top Chef Season 16 Winner Is...',
            'display_id': 'the-top-chef-season-16-winner-is',
            'description': 'Find out who takes the title of Top Chef!',
            'upload_date': '20190315',
            'timestamp': 1552618860,
            'season_number': 16,
            'episode_number': 15,
            'series': 'Top Chef',
            'episode': 'Finale',
            'duration': 190,
            'season': 'Season 16',
            'thumbnail': r're:^https://.+\.jpg',
        },
        'params': {'skip_download': 'm3u8'},
    }, {
        'url': 'https://www.bravotv.com/top-chef/season-20/episode-1/london-calling',
        'info_dict': {
            'id': '9000234570',
            'ext': 'mp4',
            'title': 'London Calling',
            'display_id': 'london-calling',
            'description': 'md5:5af95a8cbac1856bd10e7562f86bb759',
            'upload_date': '20230310',
            'timestamp': 1678418100,
            'season_number': 20,
            'episode_number': 1,
            'series': 'Top Chef',
            'episode': 'London Calling',
            'duration': 3266,
            'season': 'Season 20',
            'chapters': 'count:7',
            'thumbnail': r're:^https://.+\.jpg',
            'age_limit': 14,
        },
        'params': {'skip_download': 'm3u8'},
        'skip': 'This video requires AdobePass MSO credentials',
    }, {
        'url': 'https://www.oxygen.com/in-ice-cold-blood/season-1/closing-night',
        'info_dict': {
            'id': '3692045',
            'ext': 'mp4',
            'title': 'Closing Night',
            'display_id': 'closing-night',
            'description': 'md5:c8a5bb523c8ef381f3328c6d9f1e4632',
            'upload_date': '20230126',
            'timestamp': 1674709200,
            'season_number': 1,
            'episode_number': 1,
            'series': 'In Ice Cold Blood',
            'episode': 'Closing Night',
            'duration': 2629,
            'season': 'Season 1',
            'chapters': 'count:6',
            'thumbnail': r're:^https://.+\.jpg',
            'age_limit': 14,
        },
        'params': {'skip_download': 'm3u8'},
        'skip': 'This video requires AdobePass MSO credentials',
    }, {
        'url': 'https://www.oxygen.com/in-ice-cold-blood/season-2/episode-16/videos/handling-the-horwitz-house-after-the-murder-season-2',
        'info_dict': {
            'id': '3974019',
            'ext': 'mp4',
            'title': '\'Handling The Horwitz House After The Murder (Season 2, Episode 16)',
            'display_id': 'handling-the-horwitz-house-after-the-murder-season-2',
            'description': 'md5:f9d638dd6946a1c1c0533a9c6100eae5',
            'upload_date': '20190618',
            'timestamp': 1560819600,
            'season_number': 2,
            'episode_number': 16,
            'series': 'In Ice Cold Blood',
            'episode': 'Mother Vs Son',
            'duration': 68,
            'season': 'Season 2',
            'thumbnail': r're:^https://.+\.jpg',
            'age_limit': 14,
        },
        'params': {'skip_download': 'm3u8'},
    }, {
        'url': 'https://www.bravotv.com/below-deck/season-3/ep-14-reunion-part-1',
        'only_matching': True,
    }]

    def _real_extract(self, url):
        display_id = self._match_id(url)
        return self._extract_nbcu_video(url, display_id)
