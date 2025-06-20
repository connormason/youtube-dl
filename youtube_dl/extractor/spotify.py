from __future__ import annotations

import json
import re

from ..utils import clean_podcast_url
from ..utils import float_or_none
from ..utils import int_or_none
from ..utils import strip_or_none
from ..utils import try_get
from ..utils import unified_strdate
from .common import InfoExtractor


class SpotifyBaseIE(InfoExtractor):
    _ACCESS_TOKEN = None
    _OPERATION_HASHES = {
        'Episode': '8276d4423d709ae9b68ec1b74cc047ba0f7479059a37820be730f125189ac2bf',
        'MinimalShow': '13ee079672fad3f858ea45a55eb109553b4fb0969ed793185b2e34cbb6ee7cc0',
        'ShowEpisodes': 'e0e5ce27bd7748d2c59b4d44ba245a8992a05be75d6fabc3b20753fc8857444d',
    }
    _VALID_URL_TEMPL = r'https?://open\.spotify\.com/%s/(?P<id>[^/?&#]+)'

    def _real_initialize(self):
        self._ACCESS_TOKEN = self._download_json('https://open.spotify.com/get_access_token', None)['accessToken']

    def _call_api(self, operation, video_id, variables):
        return self._download_json(
            'https://api-partner.spotify.com/pathfinder/v1/query',
            video_id,
            query={
                'operationName': 'query' + operation,
                'variables': json.dumps(variables),
                'extensions': json.dumps(
                    {
                        'persistedQuery': {
                            'sha256Hash': self._OPERATION_HASHES[operation],
                        },
                    }
                ),
            },
            headers={'authorization': 'Bearer ' + self._ACCESS_TOKEN},
        )['data']

    def _extract_episode(self, episode, series):
        episode_id = episode['id']
        title = episode['name'].strip()

        formats = []
        audio_preview = episode.get('audioPreview') or {}
        audio_preview_url = audio_preview.get('url')
        if audio_preview_url:
            f = {
                'url': audio_preview_url.replace('://p.scdn.co/mp3-preview/', '://anon-podcast.scdn.co/'),
                'vcodec': 'none',
            }
            audio_preview_format = audio_preview.get('format')
            if audio_preview_format:
                f['format_id'] = audio_preview_format
                mobj = re.match(r'([0-9A-Z]{3})_(?:[A-Z]+_)?(\d+)', audio_preview_format)
                if mobj:
                    f.update(
                        {
                            'abr': int(mobj.group(2)),
                            'ext': mobj.group(1).lower(),
                        }
                    )
            formats.append(f)

        for item in try_get(episode, lambda x: x['audio']['items']) or []:
            item_url = item.get('url')
            if not (item_url and item.get('externallyHosted')):
                continue
            formats.append(
                {
                    'url': clean_podcast_url(item_url),
                    'vcodec': 'none',
                }
            )

        thumbnails = []
        for source in try_get(episode, lambda x: x['coverArt']['sources']) or []:
            source_url = source.get('url')
            if not source_url:
                continue
            thumbnails.append(
                {
                    'url': source_url,
                    'width': int_or_none(source.get('width')),
                    'height': int_or_none(source.get('height')),
                }
            )

        return {
            'id': episode_id,
            'title': title,
            'formats': formats,
            'thumbnails': thumbnails,
            'description': strip_or_none(episode.get('description')),
            'duration': float_or_none(try_get(episode, lambda x: x['duration']['totalMilliseconds']), 1000),
            'release_date': unified_strdate(try_get(episode, lambda x: x['releaseDate']['isoString'])),
            'series': series,
        }


class SpotifyIE(SpotifyBaseIE):
    IE_NAME = 'spotify'
    _VALID_URL = SpotifyBaseIE._VALID_URL_TEMPL % 'episode'
    _TEST = {
        'url': 'https://open.spotify.com/episode/4Z7GAJ50bgctf6uclHlWKo',
        'md5': '74010a1e3fa4d9e1ab3aa7ad14e42d3b',
        'info_dict': {
            'id': '4Z7GAJ50bgctf6uclHlWKo',
            'ext': 'mp3',
            'title': 'From the archive: Why time management is ruining our lives',
            'description': 'md5:b120d9c4ff4135b42aa9b6d9cde86935',
            'duration': 2083.605,
            'release_date': '20201217',
            'series': "The Guardian's Audio Long Reads",
        },
    }

    def _real_extract(self, url):
        episode_id = self._match_id(url)
        episode = self._call_api('Episode', episode_id, {'uri': 'spotify:episode:' + episode_id})['episode']
        return self._extract_episode(episode, try_get(episode, lambda x: x['podcast']['name']))


class SpotifyShowIE(SpotifyBaseIE):
    IE_NAME = 'spotify:show'
    _VALID_URL = SpotifyBaseIE._VALID_URL_TEMPL % 'show'
    _TEST = {
        'url': 'https://open.spotify.com/show/4PM9Ke6l66IRNpottHKV9M',
        'info_dict': {
            'id': '4PM9Ke6l66IRNpottHKV9M',
            'title': 'The Story from the Guardian',
            'description': 'The Story podcast is dedicated to our finest audio documentaries, investigations and long form stories',
        },
        'playlist_mincount': 36,
    }

    def _real_extract(self, url):
        show_id = self._match_id(url)
        podcast = self._call_api(
            'ShowEpisodes',
            show_id,
            {
                'limit': 1000000000,
                'offset': 0,
                'uri': 'spotify:show:' + show_id,
            },
        )['podcast']
        podcast_name = podcast.get('name')

        entries = []
        for item in try_get(podcast, lambda x: x['episodes']['items']) or []:
            episode = item.get('episode')
            if not episode:
                continue
            entries.append(self._extract_episode(episode, podcast_name))

        return self.playlist_result(entries, show_id, podcast_name, podcast.get('description'))
