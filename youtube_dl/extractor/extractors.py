# flake8: noqa
from __future__ import unicode_literals

from .appleconnect import AppleConnectIE
from .applepodcasts import ApplePodcastsIE
from .bandcamp import BandcampIE, BandcampAlbumIE, BandcampWeeklyIE
from .beatport import BeatportIE
from .cloudflarestream import CloudflareStreamIE
from .deezer import DeezerPlaylistIE
from .dropbox import DropboxIE
from .eighttracks import EightTracksIE
from .googledrive import GoogleDriveIE
from .googlepodcasts import (
    GooglePodcastsIE,
    GooglePodcastsFeedIE,
)
from .googlesearch import GoogleSearchIE
from .iheart import (
    IHeartRadioIE,
    IHeartRadioPodcastIE,
)
from .mixcloud import (
    MixcloudIE,
    MixcloudUserIE,
    MixcloudPlaylistIE,
)
from .safari import (
    SafariIE,
    SafariApiIE,
    SafariCourseIE,
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
from .soundgasm import SoundgasmIE, SoundgasmProfileIE
from .spotify import (
    SpotifyIE,
    SpotifyShowIE,
)
from .streamcloud import StreamcloudIE
from .tunein import (
    TuneInClipIE,
    TuneInStationIE,
    TuneInProgramIE,
    TuneInTopicIE,
    TuneInShortenerIE,
)
from .twitch import (
    TwitchVodIE,
    TwitchCollectionIE,
    TwitchVideosIE,
    TwitchVideosClipsIE,
    TwitchVideosCollectionsIE,
    TwitchStreamIE,
    TwitchClipsIE,
)
from .vevo import (
    VevoIE,
    VevoPlaylistIE,
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
