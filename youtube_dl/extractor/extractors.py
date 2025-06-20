# flake8: noqa
from __future__ import unicode_literals

from .mixcloud import (
    MixcloudIE,
    MixcloudUserIE,
    MixcloudPlaylistIE,
)
from .soundcloud import (
    SoundcloudEmbedIE,
    SoundcloudIE,
    SoundcloudSetIE,
    SoundcloudUserIE,
    SoundcloudTrackStationIE,
    SoundcloudPlaylistIE,
    SoundcloudSearchIE,
)
from .spotify import (
    SpotifyIE,
    SpotifyShowIE,
)
from .youtube import (
    YoutubeIE,
    YoutubeFavouritesIE,
    YoutubeHistoryIE,
    YoutubeTabIE,
    YoutubePlaylistIE,
    YoutubeRecommendedIE,
    YoutubeSearchDateIE,
    YoutubeSearchIE,
    YoutubeSearchURLIE,
    YoutubeSubscriptionsIE,
    YoutubeTruncatedIDIE,
    YoutubeTruncatedURLIE,
    YoutubeYtBeIE,
    YoutubeYtUserIE,
    YoutubeWatchLaterIE,
)
