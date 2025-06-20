from __future__ import annotations

import base64
import collections
import hashlib
import json
import math
import netrc
import os
import re
import socket
import ssl
import sys
import time

from ..compat import compat_etree_Element
from ..compat import compat_etree_fromstring
from ..compat import compat_http_client
from ..compat import compat_integer_types
from ..compat import compat_map as map
from ..compat import compat_open as open
from ..compat import compat_os_name
from ..compat import compat_str
from ..compat import compat_urllib_error
from ..compat import compat_urllib_request
from ..compat import compat_urlparse
from ..compat import compat_xml_parse_error
from ..compat import compat_zip as zip
from ..downloader.f4m import get_base_url
from ..downloader.f4m import remove_encrypted_media
from ..utils import NO_DEFAULT
from ..utils import ExtractorError
from ..utils import GeoRestrictedError
from ..utils import RegexNotFoundError
from ..utils import T
from ..utils import age_restricted
from ..utils import base_url
from ..utils import bug_reports_message
from ..utils import clean_html
from ..utils import compiled_regex_type
from ..utils import determine_ext
from ..utils import determine_protocol
from ..utils import error_to_compat_str
from ..utils import fix_xml_ampersands
from ..utils import float_or_none
from ..utils import int_or_none
from ..utils import join_nonempty
from ..utils import mimetype2ext
from ..utils import parse_codecs
from ..utils import parse_duration
from ..utils import parse_m3u8_attributes
from ..utils import sanitize_filename
from ..utils import sanitized_Request
from ..utils import traverse_obj
from ..utils import update_Request
from ..utils import update_url_query
from ..utils import variadic
from ..utils import xpath_element
from ..utils import xpath_text


class InfoExtractor:
    """Information Extractor class.

    Information extractors are the classes that, given a URL, extract
    information about the video (or videos) the URL refers to. This
    information includes the real video URL, the video title, author and
    others. The information is stored in a dictionary which is then
    passed to the YoutubeDL. The YoutubeDL processes this
    information possibly downloading the video to the file system, among
    other possible outcomes.

    The type field determines the type of the result.
    By far the most common value (and the default if _type is missing) is
    "video", which indicates a single video.

    For a video, the dictionaries must include the following fields:

    id:             Video identifier.
    title:          Video title, unescaped.

    Additionally, it must contain either a formats entry or a url one:

    formats:        A list of dictionaries for each format available, ordered
                    from worst to best quality.

                    Potential fields:
                    * url        The mandatory URL representing the media:
                                   for plain file media - HTTP URL of this file,
                                   for RTMP - RTMP URL,
                                   for HLS - URL of the M3U8 media playlist,
                                   for HDS - URL of the F4M manifest,
                                   for DASH
                                     - HTTP URL to plain file media (in case of
                                       unfragmented media)
                                     - URL of the MPD manifest or base URL
                                       representing the media if MPD manifest
                                       is parsed from a string (in case of
                                       fragmented media)
                                   for MSS - URL of the ISM manifest.
                    * manifest_url
                                 The URL of the manifest file in case of
                                 fragmented media:
                                   for HLS - URL of the M3U8 master playlist,
                                   for HDS - URL of the F4M manifest,
                                   for DASH - URL of the MPD manifest,
                                   for MSS - URL of the ISM manifest.
                    * ext        Will be calculated from URL if missing
                    * format     A human-readable description of the format
                                 ("mp4 container with h264/opus").
                                 Calculated from the format_id, width, height.
                                 and format_note fields if missing.
                    * format_id  A short description of the format
                                 ("mp4_h264_opus" or "19").
                                Technically optional, but strongly recommended.
                    * format_note Additional info about the format
                                 ("3D" or "DASH video")
                    * width      Width of the video, if known
                    * height     Height of the video, if known
                    * resolution Textual description of width and height
                    * tbr        Average bitrate of audio and video in KBit/s
                    * abr        Average audio bitrate in KBit/s
                    * acodec     Name of the audio codec in use
                    * asr        Audio sampling rate in Hertz
                    * vbr        Average video bitrate in KBit/s
                    * fps        Frame rate
                    * vcodec     Name of the video codec in use
                    * container  Name of the container format
                    * filesize   The number of bytes, if known in advance
                    * filesize_approx  An estimate for the number of bytes
                    * player_url SWF Player URL (used for rtmpdump).
                    * protocol   The protocol that will be used for the actual
                                 download, lower-case.
                                 "http", "https", "rtsp", "rtmp", "rtmpe",
                                 "m3u8", "m3u8_native" or "http_dash_segments".
                    * fragment_base_url
                                 Base URL for fragments. Each fragment's path
                                 value (if present) will be relative to
                                 this URL.
                    * fragments  A list of fragments of a fragmented media.
                                 Each fragment entry must contain either an url
                                 or a path. If an url is present it should be
                                 considered by a client. Otherwise both path and
                                 fragment_base_url must be present. Here is
                                 the list of all potential fields:
                                 * "url" - fragment's URL
                                 * "path" - fragment's path relative to
                                            fragment_base_url
                                 * "duration" (optional, int or float)
                                 * "filesize" (optional, int)
                                 * "range" (optional, str of the form "start-end"
                                            to use in HTTP Range header)
                    * preference Order number of this format. If this field is
                                 present and not None, the formats get sorted
                                 by this field, regardless of all other values.
                                 -1 for default (order by other properties),
                                 -2 or smaller for less than default.
                                 < -1000 to hide the format (if there is
                                    another one which is strictly better)
                    * language   Language code, e.g. "de" or "en-US".
                    * language_preference  Is this in the language mentioned in
                                 the URL?
                                 10 if it's what the URL is about,
                                 -1 for default (don't know),
                                 -10 otherwise, other values reserved for now.
                    * quality    Order number of the video quality of this
                                 format, irrespective of the file format.
                                 -1 for default (order by other properties),
                                 -2 or smaller for less than default.
                    * source_preference  Order number for this video source
                                  (quality takes higher priority)
                                 -1 for default (order by other properties),
                                 -2 or smaller for less than default.
                    * http_headers  A dictionary of additional HTTP headers
                                 to add to the request.
                    * stretched_ratio  If given and not 1, indicates that the
                                 video's pixels are not square.
                                 width : height ratio as float.
                    * no_resume  The server does not support resuming the
                                 (HTTP or RTMP) download. Boolean.
                    * downloader_options  A dictionary of downloader options as
                                 described in FileDownloader

    url:            Final video URL.
    ext:            Video filename extension.
    format:         The video format, defaults to ext (used for --get-format)
    player_url:     SWF Player URL (used for rtmpdump).

    The following fields are optional:

    alt_title:      A secondary title of the video.
    display_id      An alternative identifier for the video, not necessarily
                    unique, but available before title. Typically, id is
                    something like "4234987", title "Dancing naked mole rats",
                    and display_id "dancing-naked-mole-rats"
    thumbnails:     A list of dictionaries, with the following entries:
                        * "id" (optional, string) - Thumbnail format ID
                        * "url"
                        * "preference" (optional, int) - quality of the image
                        * "width" (optional, int)
                        * "height" (optional, int)
                        * "resolution" (optional, string "{width}x{height}",
                                        deprecated)
                        * "filesize" (optional, int)
    thumbnail:      Full URL to a video thumbnail image.
    description:    Full video description.
    uploader:       Full name of the video uploader.
    license:        License name the video is licensed under.
    creator:        The creator of the video.
    release_timestamp: UNIX timestamp of the moment the video was released.
    release_date:   The date (YYYYMMDD) when the video was released.
    timestamp:      UNIX timestamp of the moment the video became available
                    (uploaded).
    upload_date:    Video upload date (YYYYMMDD).
                    If not explicitly set, calculated from timestamp.
    uploader_id:    Nickname or id of the video uploader.
    uploader_url:   Full URL to a personal webpage of the video uploader.
    channel:        Full name of the channel the video is uploaded on.
                    Note that channel fields may or may not repeat uploader
                    fields. This depends on a particular extractor.
    channel_id:     Id of the channel.
    channel_url:    Full URL to a channel webpage.
    location:       Physical location where the video was filmed.
    subtitles:      The available subtitles as a dictionary in the format
                    {tag: subformats}. "tag" is usually a language code, and
                    "subformats" is a list sorted from lower to higher
                    preference, each element is a dictionary with the "ext"
                    entry and one of:
                        * "data": The subtitles file contents
                        * "url": A URL pointing to the subtitles file
                    "ext" will be calculated from URL if missing
    automatic_captions: Like 'subtitles', used by the YoutubeIE for
                    automatically generated captions
    duration:       Length of the video in seconds, as an integer or float.
    view_count:     How many users have watched the video on the platform.
    like_count:     Number of positive ratings of the video
    dislike_count:  Number of negative ratings of the video
    repost_count:   Number of reposts of the video
    average_rating: Average rating give by users, the scale used depends on the webpage
    comment_count:  Number of comments on the video
    comments:       A list of comments, each with one or more of the following
                    properties (all but one of text or html optional):
                        * "author" - human-readable name of the comment author
                        * "author_id" - user ID of the comment author
                        * "id" - Comment ID
                        * "html" - Comment as HTML
                        * "text" - Plain text of the comment
                        * "timestamp" - UNIX timestamp of comment
                        * "parent" - ID of the comment this one is replying to.
                                     Set to "root" to indicate that this is a
                                     comment to the original video.
    age_limit:      Age restriction for the video, as an integer (years)
    webpage_url:    The URL to the video webpage, if given to youtube-dl it
                    should allow to get the same result again. (It will be set
                    by YoutubeDL if it's missing)
    categories:     A list of categories that the video falls in, for example
                    ["Sports", "Berlin"]
    tags:           A list of tags assigned to the video, e.g. ["sweden", "pop music"]
    is_live:        True, False, or None (=unknown). Whether this video is a
                    live stream that goes on instead of a fixed-length video.
    start_time:     Time in seconds where the reproduction should start, as
                    specified in the URL.
    end_time:       Time in seconds where the reproduction should end, as
                    specified in the URL.
    chapters:       A list of dictionaries, with the following entries:
                        * "start_time" - The start time of the chapter in seconds
                        * "end_time" - The end time of the chapter in seconds
                        * "title" (optional, string)

    The following fields should only be used when the video belongs to some logical
    chapter or section:

    chapter:        Name or title of the chapter the video belongs to.
    chapter_number: Number of the chapter the video belongs to, as an integer.
    chapter_id:     Id of the chapter the video belongs to, as a unicode string.

    The following fields should only be used when the video is an episode of some
    series, programme or podcast:

    series:         Title of the series or programme the video episode belongs to.
    season:         Title of the season the video episode belongs to.
    season_number:  Number of the season the video episode belongs to, as an integer.
    season_id:      Id of the season the video episode belongs to, as a unicode string.
    episode:        Title of the video episode. Unlike mandatory video title field,
                    this field should denote the exact title of the video episode
                    without any kind of decoration.
    episode_number: Number of the video episode within a season, as an integer.
    episode_id:     Id of the video episode, as a unicode string.

    The following fields should only be used when the media is a track or a part of
    a music album:

    track:          Title of the track.
    track_number:   Number of the track within an album or a disc, as an integer.
    track_id:       Id of the track (useful in case of custom indexing, e.g. 6.iii),
                    as a unicode string.
    artist:         Artist(s) of the track.
    genre:          Genre(s) of the track.
    album:          Title of the album the track belongs to.
    album_type:     Type of the album (e.g. "Demo", "Full-length", "Split", "Compilation", etc).
    album_artist:   List of all artists appeared on the album (e.g.
                    "Ash Borer / Fell Voices" or "Various Artists", useful for splits
                    and compilations).
    disc_number:    Number of the disc or other physical medium the track belongs to,
                    as an integer.
    release_year:   Year (YYYY) when the album was released.

    Unless mentioned otherwise, the fields should be Unicode strings.

    Unless mentioned otherwise, None is equivalent to absence of information.


    _type "playlist" indicates multiple videos.
    There must be a key "entries", which is a list, an iterable, or a PagedList
    object, each element of which is a valid dictionary by this specification.

    Additionally, playlists can have "id", "title", "description", "uploader",
    "uploader_id", "uploader_url", "duration" attributes with the same semantics
    as videos (see above).


    _type "multi_video" indicates that there are multiple videos that
    form a single show, for examples multiple acts of an opera or TV episode.
    It must have an entries key like a playlist and contain all the keys
    required for a video at the same time.


    _type "url" indicates that the video must be extracted from another
    location, possibly by a different extractor. Its only required key is:
    "url" - the next URL to extract.
    The key "ie_key" can be set to the class name (minus the trailing "IE",
    e.g. "Youtube") if the extractor class is known in advance.
    Additionally, the dictionary may have any properties of the resolved entity
    known in advance, for example "title" if the title of the referred video is
    known ahead of time.


    _type "url_transparent" entities have the same specification as "url", but
    indicate that the given additional information is more precise than the one
    associated with the resolved URL.
    This is useful when a site employs a video service that hosts the video and
    its technical metadata, but that video service does not embed a useful
    title, description etc.


    A subclass of InfoExtractor must be defined to handle each specific site (or
    several sites). Such a concrete subclass should be added to the list of
    extractors. It should also:
    * define its _VALID_URL attribute as a regexp, or a Sequence of alternative
      regexps (but see below)
    * re-define the _real_extract() method
    * optionally re-define the _real_initialize() method.

    An extractor subclass may also override suitable() if necessary, but the
    function signature must be preserved and the function must import everything
    it needs (except other extractors), so that lazy_extractors works correctly.
    If the subclass's suitable() and _real_extract() functions avoid using
    _VALID_URL, the subclass need not set that class attribute.

    An abstract subclass of InfoExtractor may be used to simplify implementation
    within an extractor module; it should not be added to the list of extractors.

    Finally, the _WORKING attribute should be set to False for broken IEs
    in order to warn the users and skip the tests.
    """

    _ready = False
    _downloader = None
    _x_forwarded_for_ip = None

    # supply this in public subclasses: used in supported sites list, etc
    # IE_DESC = 'short description of IE'

    def __init__(self, downloader=None):
        """Constructor. Receives an optional downloader."""
        self._ready = False
        self._x_forwarded_for_ip = None
        self.set_downloader(downloader)

    @classmethod
    def __match_valid_url(cls, url):
        # This does not use has/getattr intentionally - we want to know whether
        # we have cached the regexp for cls, whereas getattr would also
        # match its superclass
        if '_VALID_URL_RE' not in cls.__dict__:
            # _VALID_URL can now be a list/tuple of patterns
            cls._VALID_URL_RE = tuple(map(re.compile, variadic(cls._VALID_URL)))

        # 20% faster than next(filter(None, (p.match(url) for p in cls._VALID_URL_RE)), None) in 2.7
        for p in cls._VALID_URL_RE:
            p = p.match(url)
            if p:
                return p

    # The public alias can safely be overridden, as in some back-ports
    _match_valid_url = __match_valid_url

    @classmethod
    def suitable(cls, url):
        """Receives a URL and returns True if suitable for this IE."""
        # This function must import everything it needs (except other extractors),
        # so that lazy_extractors works correctly
        return cls.__match_valid_url(url) is not None

    @classmethod
    def _match_id(cls, url):
        m = cls.__match_valid_url(url)
        assert m
        return compat_str(m.group('id'))

    def initialize(self):
        """Initializes an instance (authentication, etc)."""
        if not self._ready:
            self._real_initialize()
            self._ready = True

    def extract(self, url):
        """Extracts URL information and returns it in list of dicts."""
        try:
            for _ in range(2):
                try:
                    self.initialize()
                    return self._real_extract(url)
                except GeoRestrictedError:
                    raise
        except ExtractorError:
            raise
        except compat_http_client.IncompleteRead as e:
            raise ExtractorError('A network error has occurred.', cause=e, expected=True)
        except (KeyError, StopIteration) as e:
            raise ExtractorError('An extractor error has occurred.', cause=e)

    def set_downloader(self, downloader):
        """Sets the downloader for this IE."""
        self._downloader = downloader

    @property
    def cache(self):
        return self._downloader.cache

    @property
    def cookiejar(self):
        return self._downloader.cookiejar

    def _real_initialize(self):
        """Real initialization process. Redefine in subclasses."""
        pass

    def _real_extract(self, url):
        """Real extraction process. Redefine in subclasses."""
        pass

    @classmethod
    def ie_key(cls):
        """A string for getting the InfoExtractor with get_info_extractor"""
        return compat_str(cls.__name__[:-2])

    @property
    def IE_NAME(self):
        return compat_str(type(self).__name__[:-2])

    @staticmethod
    def __can_accept_status_code(err, expected_status):
        assert isinstance(err, compat_urllib_error.HTTPError)
        if expected_status is None:
            return False
        if isinstance(expected_status, compat_integer_types):
            return err.code == expected_status
        elif isinstance(expected_status, (list, tuple)):
            return err.code in expected_status
        elif callable(expected_status):
            return expected_status(err.code) is True
        else:
            assert False

    def _request_webpage(
        self,
        url_or_request,
        video_id,
        note=None,
        errnote=None,
        fatal=True,
        data=None,
        headers={},
        query={},
        expected_status=None,
    ):
        """
        Return the response handle.

        See _download_webpage docstring for arguments specification.
        """
        if note is None:
            self.report_download_webpage(video_id)
        elif note is not False:
            if video_id is None:
                self.to_screen(f'{note}')
            else:
                self.to_screen(f'{video_id}: {note}')

        if isinstance(url_or_request, compat_urllib_request.Request):
            url_or_request = update_Request(url_or_request, data=data, headers=headers, query=query)
        else:
            if query:
                url_or_request = update_url_query(url_or_request, query)
            if data is not None or headers:
                url_or_request = sanitized_Request(url_or_request, data, headers)
        exceptions = [compat_urllib_error.URLError, compat_http_client.HTTPException, socket.error]
        if hasattr(ssl, 'CertificateError'):
            exceptions.append(ssl.CertificateError)
        try:
            return self._downloader.urlopen(url_or_request)
        except tuple(exceptions) as err:
            if isinstance(err, compat_urllib_error.HTTPError):
                if self.__can_accept_status_code(err, expected_status):
                    # Retain reference to error to prevent file object from
                    # being closed before it can be read. Works around the
                    # effects of <https://bugs.python.org/issue15002>
                    # introduced in Python 3.4.1.
                    err.fp._error = err
                    return err.fp

            if errnote is False:
                return False
            if errnote is None:
                errnote = 'Unable to download webpage'

            errmsg = f'{errnote}: {error_to_compat_str(err)}'
            if fatal:
                raise ExtractorError(errmsg, sys.exc_info()[2], cause=err)
            else:
                self.report_warning(errmsg)
                return False

    def _download_webpage_handle(
        self,
        url_or_request,
        video_id,
        note=None,
        errnote=None,
        fatal=True,
        encoding=None,
        data=None,
        headers={},
        query={},
        expected_status=None,
    ):
        """
        Return a tuple (page content as string, URL handle).

        See _download_webpage docstring for arguments specification.
        """
        # Strip hashes from the URL (#1038)
        if isinstance(url_or_request, (compat_str, str)):
            url_or_request = url_or_request.partition('#')[0]

        urlh = self._request_webpage(
            url_or_request,
            video_id,
            note,
            errnote,
            fatal,
            data=data,
            headers=headers,
            query=query,
            expected_status=expected_status,
        )
        if urlh is False:
            assert not fatal
            return False
        content = self._webpage_read_content(urlh, url_or_request, video_id, note, errnote, fatal, encoding=encoding)
        return (content, urlh)

    @staticmethod
    def _guess_encoding_from_content(content_type, webpage_bytes):
        m = re.match(r'[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+\s*;\s*charset=(.+)', content_type)
        if m:
            encoding = m.group(1)
        else:
            m = re.search(rb'<meta[^>]+charset=[\'"]?([^\'")]+)[ /\'">]', webpage_bytes[:1024])
            if m:
                encoding = m.group(1).decode('ascii')
            elif webpage_bytes.startswith(b'\xff\xfe'):
                encoding = 'utf-16'
            else:
                encoding = 'utf-8'

        return encoding

    def __check_blocked(self, content):
        first_block = content[:512]
        if '<title>Access to this site is blocked</title>' in content and 'Websense' in first_block:
            msg = 'Access to this webpage has been blocked by Websense filtering software in your network.'
            blocked_iframe = self._html_search_regex(
                r'<iframe src="([^"]+)"', content, 'Websense information URL', default=None
            )
            if blocked_iframe:
                msg += f' Visit {blocked_iframe} for more details'
            raise ExtractorError(msg, expected=True)
        if '<title>The URL you requested has been blocked</title>' in first_block:
            msg = (
                'Access to this webpage has been blocked by Indian censorship. '
                'Use a VPN or proxy server (with --proxy) to route around it.'
            )
            block_msg = self._html_search_regex(r'</h1><p>(.*?)</p>', content, 'block message', default=None)
            if block_msg:
                msg += ' (Message: "{}")'.format(block_msg.replace('\n', ' '))
            raise ExtractorError(msg, expected=True)
        if '<title>TTK :: Доступ к ресурсу ограничен</title>' in content and 'blocklist.rkn.gov.ru' in content:
            raise ExtractorError(
                'Access to this webpage has been blocked by decision of the Russian government. '
                'Visit http://blocklist.rkn.gov.ru/ for a block reason.',
                expected=True,
            )

    def _webpage_read_content(
        self, urlh, url_or_request, video_id, note=None, errnote=None, fatal=True, prefix=None, encoding=None
    ):
        content_type = urlh.headers.get('Content-Type', '')
        webpage_bytes = urlh.read()
        if prefix is not None:
            webpage_bytes = prefix + webpage_bytes
        if not encoding:
            encoding = self._guess_encoding_from_content(content_type, webpage_bytes)
        if self.get_param('dump_intermediate_pages', False):
            self.to_screen('Dumping request to ' + urlh.geturl())
            dump = base64.b64encode(webpage_bytes).decode('ascii')
            self.to_screen(dump)
        if self.get_param('write_pages', False):
            basen = f'{video_id}_{urlh.geturl()}'
            if len(basen) > 240:
                h = '___' + hashlib.md5(basen.encode('utf-8')).hexdigest()
                basen = basen[: 240 - len(h)] + h
            raw_filename = basen + '.dump'
            filename = sanitize_filename(raw_filename, restricted=True)
            self.to_screen('Saving request to ' + filename)
            # Working around MAX_PATH limitation on Windows (see
            # http://msdn.microsoft.com/en-us/library/windows/desktop/aa365247(v=vs.85).aspx)
            if compat_os_name == 'nt':
                absfilepath = os.path.abspath(filename)
                if len(absfilepath) > 259:
                    filename = '\\\\?\\' + absfilepath
            with open(filename, 'wb') as outf:
                outf.write(webpage_bytes)

        try:
            content = webpage_bytes.decode(encoding, 'replace')
        except LookupError:
            content = webpage_bytes.decode('utf-8', 'replace')

        self.__check_blocked(content)

        return content

    def _download_webpage(
        self,
        url_or_request,
        video_id,
        note=None,
        errnote=None,
        fatal=True,
        tries=1,
        timeout=5,
        encoding=None,
        data=None,
        headers={},
        query={},
        expected_status=None,
    ):
        """
        Return the data of the page as a string.

        Arguments:
        url_or_request -- plain text URL as a string or
            a compat_urllib_request.Requestobject
        video_id -- Video/playlist/item identifier (string)

        Keyword arguments:
        note -- note printed before downloading (string)
        errnote -- note printed in case of an error (string)
        fatal -- flag denoting whether error should be considered fatal,
            i.e. whether it should cause ExtractionError to be raised,
            otherwise a warning will be reported and extraction continued
        tries -- number of tries
        timeout -- sleep interval between tries
        encoding -- encoding for a page content decoding, guessed automatically
            when not explicitly specified
        data -- POST data (bytes)
        headers -- HTTP headers (dict)
        query -- URL query (dict)
        expected_status -- allows to accept failed HTTP requests (non 2xx
            status code) by explicitly specifying a set of accepted status
            codes. Can be any of the following entities:
                - an integer type specifying an exact failed status code to
                  accept
                - a list or a tuple of integer types specifying a list of
                  failed status codes to accept
                - a callable accepting an actual failed status code and
                  returning True if it should be accepted
            Note that this argument does not affect success status codes (2xx)
            which are always accepted.
        """

        success = False
        try_count = 0
        while success is False:
            try:
                res = self._download_webpage_handle(
                    url_or_request,
                    video_id,
                    note,
                    errnote,
                    fatal,
                    encoding=encoding,
                    data=data,
                    headers=headers,
                    query=query,
                    expected_status=expected_status,
                )
                success = True
            except compat_http_client.IncompleteRead as e:
                try_count += 1
                if try_count >= tries:
                    raise e
                self._sleep(timeout, video_id)
        if res is False:
            return res
        else:
            content, _ = res
            return content

    def _download_xml_handle(
        self,
        url_or_request,
        video_id,
        note='Downloading XML',
        errnote='Unable to download XML',
        transform_source=None,
        fatal=True,
        encoding=None,
        data=None,
        headers={},
        query={},
        expected_status=None,
    ):
        """
        Return a tuple (xml as an compat_etree_Element, URL handle).

        See _download_webpage docstring for arguments specification.
        """
        res = self._download_webpage_handle(
            url_or_request,
            video_id,
            note,
            errnote,
            fatal=fatal,
            encoding=encoding,
            data=data,
            headers=headers,
            query=query,
            expected_status=expected_status,
        )
        if res is False:
            return res
        xml_string, urlh = res
        return self._parse_xml(xml_string, video_id, transform_source=transform_source, fatal=fatal), urlh

    def _download_xml(
        self,
        url_or_request,
        video_id,
        note='Downloading XML',
        errnote='Unable to download XML',
        transform_source=None,
        fatal=True,
        encoding=None,
        data=None,
        headers={},
        query={},
        expected_status=None,
    ):
        """
        Return the xml as an compat_etree_Element.

        See _download_webpage docstring for arguments specification.
        """
        res = self._download_xml_handle(
            url_or_request,
            video_id,
            note=note,
            errnote=errnote,
            transform_source=transform_source,
            fatal=fatal,
            encoding=encoding,
            data=data,
            headers=headers,
            query=query,
            expected_status=expected_status,
        )
        return res if res is False else res[0]

    def _parse_xml(self, xml_string, video_id, transform_source=None, fatal=True):
        if transform_source:
            xml_string = transform_source(xml_string)
        try:
            return compat_etree_fromstring(xml_string.encode('utf-8'))
        except compat_xml_parse_error as ve:
            errmsg = f'{video_id}: Failed to parse XML '
            if fatal:
                raise ExtractorError(errmsg, cause=ve)
            else:
                self.report_warning(errmsg + str(ve))

    def _download_json_handle(
        self,
        url_or_request,
        video_id,
        note='Downloading JSON metadata',
        errnote='Unable to download JSON metadata',
        transform_source=None,
        fatal=True,
        encoding=None,
        data=None,
        headers={},
        query={},
        expected_status=None,
    ):
        """
        Return a tuple (JSON object, URL handle).

        See _download_webpage docstring for arguments specification.
        """
        res = self._download_webpage_handle(
            url_or_request,
            video_id,
            note,
            errnote,
            fatal=fatal,
            encoding=encoding,
            data=data,
            headers=headers,
            query=query,
            expected_status=expected_status,
        )
        if res is False:
            return res
        json_string, urlh = res
        return self._parse_json(json_string, video_id, transform_source=transform_source, fatal=fatal), urlh

    def _download_json(
        self,
        url_or_request,
        video_id,
        note='Downloading JSON metadata',
        errnote='Unable to download JSON metadata',
        transform_source=None,
        fatal=True,
        encoding=None,
        data=None,
        headers={},
        query={},
        expected_status=None,
    ):
        """
        Return the JSON object as a dict.

        See _download_webpage docstring for arguments specification.
        """
        res = self._download_json_handle(
            url_or_request,
            video_id,
            note=note,
            errnote=errnote,
            transform_source=transform_source,
            fatal=fatal,
            encoding=encoding,
            data=data,
            headers=headers,
            query=query,
            expected_status=expected_status,
        )
        return res if res is False else res[0]

    def _parse_json(self, json_string, video_id, transform_source=None, fatal=True):
        if transform_source:
            json_string = transform_source(json_string)
        try:
            return json.loads(json_string)
        except ValueError as ve:
            errmsg = f'{video_id}: Failed to parse JSON '
            if fatal:
                raise ExtractorError(errmsg, cause=ve)
            else:
                self.report_warning(errmsg + str(ve))

    def __ie_msg(self, *msg):
        return '[{}] {}'.format(self.IE_NAME, ''.join(msg))

    # msg, video_id=None, *args, only_once=False, **kwargs
    def report_warning(self, msg, *args, **kwargs):
        if len(args) > 0:
            video_id = args[0]
            args = args[1:]
        else:
            video_id = kwargs.pop('video_id', None)
        idstr = '' if video_id is None else f'{video_id}: '
        self._downloader.report_warning(self.__ie_msg(idstr, msg), *args, **kwargs)

    def to_screen(self, msg):
        """Print msg to screen, prefixing it with '[ie_name]'"""
        self._downloader.to_screen(self.__ie_msg(msg))

    def write_debug(self, msg, only_once=False):
        """Log debug message or Print message to stderr"""
        self._downloader.write_debug(self.__ie_msg(msg), only_once=only_once)

    # name, default=None, *args, **kwargs
    def get_param(self, name, *args, **kwargs):
        default, args = (args[0], args[1:]) if len(args) > 0 else (kwargs.pop('default', None), args)
        if self._downloader:
            return self._downloader.params.get(name, default, *args, **kwargs)
        return default

    def report_drm(self, video_id):
        self.raise_no_formats('This video is DRM protected', expected=True, video_id=video_id)

    def report_extraction(self, id_or_name):
        """Report information extraction."""
        self.to_screen(f'{id_or_name}: Extracting information')

    def report_download_webpage(self, video_id):
        """Report webpage download."""
        self.to_screen(f'{video_id}: Downloading webpage')

    def report_age_confirmation(self):
        """Report attempt to confirm age."""
        self.to_screen('Confirming age')

    def report_login(self):
        """Report attempt to log in."""
        self.to_screen('Logging in')

    @staticmethod
    def raise_login_required(msg='This video is only available for registered users'):
        raise ExtractorError(
            f'{msg}. Use --username and --password or --netrc to provide account credentials.', expected=True
        )

    @staticmethod
    def raise_geo_restricted(
        msg='This video is not available from your location due to geo restriction', countries=None
    ):
        raise GeoRestrictedError(msg, countries=countries)

    def raise_no_formats(self, msg, expected=False, video_id=None):
        if expected and (self.get_param('ignore_no_formats_error') or self.get_param('wait_for_video')):
            self.report_warning(msg, video_id)
        elif isinstance(msg, ExtractorError):
            raise msg
        else:
            raise ExtractorError(msg, expected=expected, video_id=video_id)

    # Methods for following #608
    @staticmethod
    def url_result(url, ie=None, video_id=None, video_title=None):
        """Returns a URL that points to a page that should be processed"""
        # TODO: ie should be the class used for getting the info
        video_info = {'_type': 'url', 'url': url, 'ie_key': ie}
        if video_id is not None:
            video_info['id'] = video_id
        if video_title is not None:
            video_info['title'] = video_title
        return video_info

    @staticmethod
    def playlist_result(entries, playlist_id=None, playlist_title=None, playlist_description=None):
        """Returns a playlist"""
        video_info = {'_type': 'playlist', 'entries': entries}
        if playlist_id:
            video_info['id'] = playlist_id
        if playlist_title:
            video_info['title'] = playlist_title
        if playlist_description:
            video_info['description'] = playlist_description
        return video_info

    def _search_regex(self, pattern, string, name, default=NO_DEFAULT, fatal=True, flags=0, group=None):
        """
        Perform a regex search on the given string, using a single or a list of
        patterns returning the first matching group.
        In case of failure return a default value or raise a WARNING or a
        RegexNotFoundError, depending on fatal, specifying the field name.
        """
        if isinstance(pattern, (str, compat_str, compiled_regex_type)):
            mobj = re.search(pattern, string, flags)
        else:
            for p in pattern:
                mobj = re.search(p, string, flags)
                if mobj:
                    break

        if not self.get_param('no_color') and compat_os_name != 'nt' and sys.stderr.isatty():
            _name = f'\033[0;34m{name}\033[0m'
        else:
            _name = name

        if mobj:
            if group is None:
                # return the first matching group
                return next(g for g in mobj.groups() if g is not None)
            elif isinstance(group, (list, tuple)):
                return tuple(mobj.group(g) for g in group)
            else:
                return mobj.group(group)
        elif default is not NO_DEFAULT:
            return default
        elif fatal:
            raise RegexNotFoundError(f'Unable to extract {_name}')
        else:
            self.report_warning(f'unable to extract {_name}' + bug_reports_message())
            return None

    def _html_search_regex(self, pattern, string, name, default=NO_DEFAULT, fatal=True, flags=0, group=None):
        """
        Like _search_regex, but strips HTML tags and unescapes entities.
        """
        res = self._search_regex(pattern, string, name, default, fatal, flags, group)
        if isinstance(res, tuple):
            return tuple(map(clean_html, res))
        return clean_html(res)

    def _get_netrc_login_info(self, netrc_machine=None):
        username = None
        password = None

        if self.get_param('usenetrc', False):
            try:
                netrc_machine = netrc_machine or self._NETRC_MACHINE
                info = netrc.netrc().authenticators(netrc_machine)
                if info is not None:
                    username = info[0]
                    password = info[2]
                else:
                    raise netrc.NetrcParseError(f'No authenticators for {netrc_machine}')
            except (OSError, AttributeError, netrc.NetrcParseError) as err:
                self.report_warning(f'parsing .netrc: {error_to_compat_str(err)}')

        return username, password

    def _get_login_info(self, username_option='username', password_option='password', netrc_machine=None):
        """
        Get the login info as (username, password)
        First look for the manually specified credentials using username_option
        and password_option as keys in params dictionary. If no such credentials
        available look in the netrc file using the netrc_machine or _NETRC_MACHINE
        value.
        If there's no info available, return (None, None)
        """
        if self._downloader is None:
            return (None, None)

        downloader_params = self._downloader.params

        # Attempt to use provided username and password or .netrc data
        if downloader_params.get(username_option) is not None:
            username = downloader_params[username_option]
            password = downloader_params[password_option]
        else:
            username, password = self._get_netrc_login_info(netrc_machine)

        return username, password

    def _html_search_meta(self, name, html, display_name=None, fatal=False, **kwargs):
        if not isinstance(name, (list, tuple)):
            name = [name]
        if display_name is None:
            display_name = name[0]
        return self._html_search_regex(
            [self._meta_regex(n) for n in name], html, display_name, fatal=fatal, group='content', **kwargs
        )

    def _sort_formats(self, formats, field_preference=None):
        if not formats:
            raise ExtractorError('No video formats found')

        for f in formats:
            # Automatically determine tbr when missing based on abr and vbr (improves
            # formats sorting in some cases)
            if 'tbr' not in f and f.get('abr') is not None and f.get('vbr') is not None:
                f['tbr'] = f['abr'] + f['vbr']

        def _formats_key(f):
            # TODO remove the following workaround
            from ..utils import determine_ext

            if not f.get('ext') and 'url' in f:
                f['ext'] = determine_ext(f['url'])

            if isinstance(field_preference, (list, tuple)):
                return tuple(
                    f.get(field) if f.get(field) is not None else ('' if field == 'format_id' else -1)
                    for field in field_preference
                )

            preference = f.get('preference')
            if preference is None:
                preference = 0
                if f.get('ext') in ['f4f', 'f4m']:  # Not yet supported
                    preference -= 0.5

            protocol = f.get('protocol') or determine_protocol(f)
            proto_preference = 0 if protocol in ['http', 'https'] else (-0.5 if protocol == 'rtsp' else -0.1)

            if f.get('vcodec') == 'none':  # audio only
                preference -= 50
                if self.get_param('prefer_free_formats'):
                    ORDER = ['aac', 'mp3', 'm4a', 'webm', 'ogg', 'opus']
                else:
                    ORDER = ['webm', 'opus', 'ogg', 'mp3', 'aac', 'm4a']
                ext_preference = 0
                try:
                    audio_ext_preference = ORDER.index(f['ext'])
                except ValueError:
                    audio_ext_preference = -1
            else:
                if f.get('acodec') == 'none':  # video only
                    preference -= 40
                if self.get_param('prefer_free_formats'):
                    ORDER = ['flv', 'mp4', 'webm']
                else:
                    ORDER = ['webm', 'flv', 'mp4']
                try:
                    ext_preference = ORDER.index(f['ext'])
                except ValueError:
                    ext_preference = -1
                audio_ext_preference = 0

            return (
                preference,
                f.get('language_preference') if f.get('language_preference') is not None else -1,
                f.get('quality') if f.get('quality') is not None else -1,
                f.get('tbr') if f.get('tbr') is not None else -1,
                f.get('filesize') if f.get('filesize') is not None else -1,
                f.get('vbr') if f.get('vbr') is not None else -1,
                f.get('height') if f.get('height') is not None else -1,
                f.get('width') if f.get('width') is not None else -1,
                proto_preference,
                ext_preference,
                f.get('abr') if f.get('abr') is not None else -1,
                audio_ext_preference,
                f.get('fps') if f.get('fps') is not None else -1,
                f.get('filesize_approx') if f.get('filesize_approx') is not None else -1,
                f.get('source_preference') if f.get('source_preference') is not None else -1,
                f.get('format_id') if f.get('format_id') is not None else '',
            )

        formats.sort(key=_formats_key)

    def _is_valid_url(self, url, video_id, item='video', headers={}):
        url = self._proto_relative_url(url, scheme='http:')
        # For now assume non HTTP(S) URLs always valid
        if not (url.startswith('http://') or url.startswith('https://')):
            return True
        try:
            self._request_webpage(url, video_id, f'Checking {item} URL', headers=headers)
            return True
        except ExtractorError as e:
            self.to_screen(f'{video_id}: {item} URL is invalid, skipping: {error_to_compat_str(e.cause)}')
            return False

    def http_scheme(self):
        """Either "http:" or "https:", depending on the user's preferences"""
        return 'http:' if self.get_param('prefer_insecure', False) else 'https:'

    def _proto_relative_url(self, url, scheme=None):
        if url is None:
            return url
        if url.startswith('//'):
            if scheme is None:
                scheme = self.http_scheme()
            return scheme + url
        else:
            return url

    def _sleep(self, timeout, video_id, msg_template=None):
        if msg_template is None:
            msg_template = '%(video_id)s: Waiting for %(timeout)s seconds'
        msg = msg_template % {'video_id': video_id, 'timeout': timeout}
        self.to_screen(msg)
        time.sleep(timeout)

    def _extract_f4m_formats(
        self,
        manifest_url,
        video_id,
        preference=None,
        f4m_id=None,
        transform_source=lambda s: fix_xml_ampersands(s).strip(),
        fatal=True,
        m3u8_id=None,
        data=None,
        headers={},
        query={},
    ):
        manifest = self._download_xml(
            manifest_url,
            video_id,
            'Downloading f4m manifest',
            'Unable to download f4m manifest',
            # Some manifests may be malformed, e.g. prosiebensat1 generated manifests
            # (see https://github.com/ytdl-org/youtube-dl/issues/6215#issuecomment-121704244)
            transform_source=transform_source,
            fatal=fatal,
            data=data,
            headers=headers,
            query=query,
        )

        if manifest is False:
            return []

        return self._parse_f4m_formats(
            manifest,
            manifest_url,
            video_id,
            preference=preference,
            f4m_id=f4m_id,
            transform_source=transform_source,
            fatal=fatal,
            m3u8_id=m3u8_id,
        )

    def _parse_f4m_formats(
        self,
        manifest,
        manifest_url,
        video_id,
        preference=None,
        f4m_id=None,
        transform_source=lambda s: fix_xml_ampersands(s).strip(),
        fatal=True,
        m3u8_id=None,
    ):
        if not isinstance(manifest, compat_etree_Element) and not fatal:
            return []

        # currently youtube-dl cannot decode the playerVerificationChallenge as Akamai uses Adobe Alchemy
        akamai_pv = manifest.find('{http://ns.adobe.com/f4m/1.0}pv-2.0')
        if akamai_pv is not None and ';' in akamai_pv.text:
            playerVerificationChallenge = akamai_pv.text.split(';')[0]
            if playerVerificationChallenge.strip() != '':
                return []

        formats = []
        manifest_version = '1.0'
        media_nodes = manifest.findall('{http://ns.adobe.com/f4m/1.0}media')
        if not media_nodes:
            manifest_version = '2.0'
            media_nodes = manifest.findall('{http://ns.adobe.com/f4m/2.0}media')
        # Remove unsupported DRM protected media from final formats
        # rendition (see https://github.com/ytdl-org/youtube-dl/issues/8573).
        media_nodes = remove_encrypted_media(media_nodes)
        if not media_nodes:
            return formats

        manifest_base_url = get_base_url(manifest)

        bootstrap_info = xpath_element(
            manifest,
            ['{http://ns.adobe.com/f4m/1.0}bootstrapInfo', '{http://ns.adobe.com/f4m/2.0}bootstrapInfo'],
            'bootstrap info',
            default=None,
        )

        vcodec = None
        mime_type = xpath_text(
            manifest,
            ['{http://ns.adobe.com/f4m/1.0}mimeType', '{http://ns.adobe.com/f4m/2.0}mimeType'],
            'base URL',
            default=None,
        )
        if mime_type and mime_type.startswith('audio/'):
            vcodec = 'none'

        for i, media_el in enumerate(media_nodes):
            tbr = int_or_none(media_el.attrib.get('bitrate'))
            width = int_or_none(media_el.attrib.get('width'))
            height = int_or_none(media_el.attrib.get('height'))
            format_id = '-'.join(filter(None, [f4m_id, compat_str(i if tbr is None else tbr)]))
            # If <bootstrapInfo> is present, the specified f4m is a
            # stream-level manifest, and only set-level manifests may refer to
            # external resources.  See section 11.4 and section 4 of F4M spec
            if bootstrap_info is None:
                media_url = None
                # @href is introduced in 2.0, see section 11.6 of F4M spec
                if manifest_version == '2.0':
                    media_url = media_el.attrib.get('href')
                if media_url is None:
                    media_url = media_el.attrib.get('url')
                if not media_url:
                    continue
                manifest_url = (
                    media_url
                    if media_url.startswith('http://') or media_url.startswith('https://')
                    else ((manifest_base_url or '/'.join(manifest_url.split('/')[:-1])) + '/' + media_url)
                )
                # If media_url is itself a f4m manifest do the recursive extraction
                # since bitrates in parent manifest (this one) and media_url manifest
                # may differ leading to inability to resolve the format by requested
                # bitrate in f4m downloader
                ext = determine_ext(manifest_url)
                if ext == 'f4m':
                    f4m_formats = self._extract_f4m_formats(
                        manifest_url,
                        video_id,
                        preference=preference,
                        f4m_id=f4m_id,
                        transform_source=transform_source,
                        fatal=fatal,
                    )
                    # Sometimes stream-level manifest contains single media entry that
                    # does not contain any quality metadata (e.g. http://matchtv.ru/#live-player).
                    # At the same time parent's media entry in set-level manifest may
                    # contain it. We will copy it from parent in such cases.
                    if len(f4m_formats) == 1:
                        f = f4m_formats[0]
                        f.update(
                            {
                                'tbr': f.get('tbr') or tbr,
                                'width': f.get('width') or width,
                                'height': f.get('height') or height,
                                'format_id': f.get('format_id') if not tbr else format_id,
                                'vcodec': vcodec,
                            }
                        )
                    formats.extend(f4m_formats)
                    continue
                elif ext == 'm3u8':
                    formats.extend(
                        self._extract_m3u8_formats(
                            manifest_url, video_id, 'mp4', preference=preference, m3u8_id=m3u8_id, fatal=fatal
                        )
                    )
                    continue
            formats.append(
                {
                    'format_id': format_id,
                    'url': manifest_url,
                    'manifest_url': manifest_url,
                    'ext': 'flv' if bootstrap_info is not None else None,
                    'protocol': 'f4m',
                    'tbr': tbr,
                    'width': width,
                    'height': height,
                    'vcodec': vcodec,
                    'preference': preference,
                }
            )
        return formats

    def _report_ignoring_subs(self, name):
        self.report_warning(
            bug_reports_message(
                f'Ignoring subtitle tracks found in the {name} manifest; if any subtitle tracks are missing,'
            ),
            only_once=True,
        )

    def _extract_m3u8_formats(
        self,
        m3u8_url,
        video_id,
        ext=None,
        entry_protocol='m3u8',
        preference=None,
        m3u8_id=None,
        note=None,
        errnote=None,
        fatal=True,
        live=False,
        data=None,
        headers={},
        query={},
    ):
        res = self._download_webpage_handle(
            m3u8_url,
            video_id,
            note=note or 'Downloading m3u8 information',
            errnote=errnote or 'Failed to download m3u8 information',
            fatal=fatal,
            data=data,
            headers=headers,
            query=query,
        )

        if res is False:
            return []

        m3u8_doc, urlh = res
        m3u8_url = urlh.geturl()

        return self._parse_m3u8_formats(
            m3u8_doc,
            m3u8_url,
            ext=ext,
            entry_protocol=entry_protocol,
            preference=preference,
            m3u8_id=m3u8_id,
            live=live,
        )

    def _parse_m3u8_formats(
        self, m3u8_doc, m3u8_url, ext=None, entry_protocol='m3u8', preference=None, m3u8_id=None, live=False
    ):
        if '#EXT-X-FAXS-CM:' in m3u8_doc:  # Adobe Flash Access
            return []

        if re.search(r'#EXT-X-SESSION-KEY:.*?URI="skd://', m3u8_doc):  # Apple FairPlay
            return []

        formats = []

        def format_url(u):
            return u if re.match(r'^https?://', u) else compat_urlparse.urljoin(m3u8_url, u)

        # References:
        # 1. https://tools.ietf.org/html/draft-pantos-http-live-streaming-21
        # 2. https://github.com/ytdl-org/youtube-dl/issues/12211
        # 3. https://github.com/ytdl-org/youtube-dl/issues/18923

        # We should try extracting formats only from master playlists [1, 4.3.4],
        # i.e. playlists that describe available qualities. On the other hand
        # media playlists [1, 4.3.3] should be returned as is since they contain
        # just the media without qualities renditions.
        # Fortunately, master playlist can be easily distinguished from media
        # playlist based on particular tags availability. As of [1, 4.3.3, 4.3.4]
        # master playlist tags MUST NOT appear in a media playlist and vice versa.
        # As of [1, 4.3.3.1] #EXT-X-TARGETDURATION tag is REQUIRED for every
        # media playlist and MUST NOT appear in master playlist thus we can
        # clearly detect media playlist with this criterion.

        if '#EXT-X-TARGETDURATION' in m3u8_doc:  # media playlist, return as is
            return [
                {
                    'url': m3u8_url,
                    'format_id': m3u8_id,
                    'ext': ext,
                    'protocol': entry_protocol,
                    'preference': preference,
                }
            ]

        groups = {}
        last_stream_inf = {}

        def extract_media(x_media_line):
            media = parse_m3u8_attributes(x_media_line)
            # As per [1, 4.3.4.1] TYPE, GROUP-ID and NAME are REQUIRED
            media_type, group_id, name = media.get('TYPE'), media.get('GROUP-ID'), media.get('NAME')
            if not (media_type and group_id and name):
                return
            groups.setdefault(group_id, []).append(media)
            if media_type not in ('VIDEO', 'AUDIO'):
                return
            media_url = media.get('URI')
            if media_url:
                format_id = []
                for v in (m3u8_id, group_id, name):
                    if v:
                        format_id.append(v)
                f = {
                    'format_id': '-'.join(format_id),
                    'url': format_url(media_url),
                    'manifest_url': m3u8_url,
                    'language': media.get('LANGUAGE'),
                    'ext': ext,
                    'protocol': entry_protocol,
                    'preference': preference,
                }
                if media_type == 'AUDIO':
                    f['vcodec'] = 'none'
                formats.append(f)

        def build_stream_name():
            # Despite specification does not mention NAME attribute for
            # EXT-X-STREAM-INF tag it still sometimes may be present (see [1]
            # or vidio test in TestInfoExtractor.test_parse_m3u8_formats)
            # 1. http://www.vidio.com/watch/165683-dj_ambred-booyah-live-2015
            stream_name = last_stream_inf.get('NAME')
            if stream_name:
                return stream_name
            # If there is no NAME in EXT-X-STREAM-INF it will be obtained
            # from corresponding rendition group
            stream_group_id = last_stream_inf.get('VIDEO')
            if not stream_group_id:
                return
            stream_group = groups.get(stream_group_id)
            if not stream_group:
                return stream_group_id
            rendition = stream_group[0]
            return rendition.get('NAME') or stream_group_id

        # parse EXT-X-MEDIA tags before EXT-X-STREAM-INF in order to have the
        # chance to detect video only formats when EXT-X-STREAM-INF tags
        # precede EXT-X-MEDIA tags in HLS manifest such as [3].
        for line in m3u8_doc.splitlines():
            if line.startswith('#EXT-X-MEDIA:'):
                extract_media(line)

        for line in m3u8_doc.splitlines():
            if line.startswith('#EXT-X-STREAM-INF:'):
                last_stream_inf = parse_m3u8_attributes(line)
            elif line.startswith('#') or not line.strip():
                continue
            else:
                tbr = float_or_none(
                    last_stream_inf.get('AVERAGE-BANDWIDTH') or last_stream_inf.get('BANDWIDTH'), scale=1000
                )
                format_id = []
                if m3u8_id:
                    format_id.append(m3u8_id)
                stream_name = build_stream_name()
                # Bandwidth of live streams may differ over time thus making
                # format_id unpredictable. So it's better to keep provided
                # format_id intact.
                if not live:
                    format_id.append(stream_name if stream_name else '%d' % (tbr if tbr else len(formats)))
                manifest_url = format_url(line.strip())
                f = {
                    'format_id': '-'.join(format_id),
                    'url': manifest_url,
                    'manifest_url': m3u8_url,
                    'tbr': tbr,
                    'ext': ext,
                    'fps': float_or_none(last_stream_inf.get('FRAME-RATE')),
                    'protocol': entry_protocol,
                    'preference': preference,
                }
                resolution = last_stream_inf.get('RESOLUTION')
                if resolution:
                    mobj = re.search(r'(?P<width>\d+)[xX](?P<height>\d+)', resolution)
                    if mobj:
                        f['width'] = int(mobj.group('width'))
                        f['height'] = int(mobj.group('height'))
                # Unified Streaming Platform
                mobj = re.search(r'audio.*?(?:%3D|=)(\d+)(?:-video.*?(?:%3D|=)(\d+))?', f['url'])
                if mobj:
                    abr, vbr = mobj.groups()
                    abr, vbr = float_or_none(abr, 1000), float_or_none(vbr, 1000)
                    f.update(
                        {
                            'vbr': vbr,
                            'abr': abr,
                        }
                    )
                codecs = parse_codecs(last_stream_inf.get('CODECS'))
                f.update(codecs)
                audio_group_id = last_stream_inf.get('AUDIO')
                # As per [1, 4.3.4.1.1] any EXT-X-STREAM-INF tag which
                # references a rendition group MUST have a CODECS attribute.
                # However, this is not always respected, for example, [2]
                # contains EXT-X-STREAM-INF tag which references AUDIO
                # rendition group but does not have CODECS and despite
                # referencing an audio group it represents a complete
                # (with audio and video) format. So, for such cases we will
                # ignore references to rendition groups and treat them
                # as complete formats.
                if audio_group_id and codecs and f.get('vcodec') != 'none':
                    audio_group = groups.get(audio_group_id)
                    if audio_group and audio_group[0].get('URI'):
                        # TODO: update acodec for audio only formats with
                        # the same GROUP-ID
                        f['acodec'] = 'none'
                formats.append(f)

                # for DailyMotion
                progressive_uri = last_stream_inf.get('PROGRESSIVE-URI')
                if progressive_uri:
                    http_f = f.copy()
                    del http_f['manifest_url']
                    http_f.update(
                        {
                            'format_id': f['format_id'].replace('hls-', 'http-'),
                            'protocol': 'http',
                            'url': progressive_uri,
                        }
                    )
                    formats.append(http_f)

                last_stream_inf = {}
        return formats

    @staticmethod
    def _xpath_ns(path, namespace=None):
        if not namespace:
            return path
        out = []
        for c in path.split('/'):
            if not c or c == '.':
                out.append(c)
            else:
                out.append(f'{{{namespace}}}{c}')
        return '/'.join(out)

    def _extract_mpd_formats(self, *args, **kwargs):
        fmts, subs = self._extract_mpd_formats_and_subtitles(*args, **kwargs)
        if subs:
            self._report_ignoring_subs('DASH')
        return fmts

    def _extract_mpd_formats_and_subtitles(
        self, mpd_url, video_id, mpd_id=None, note=None, errnote=None, fatal=True, data=None, headers=None, query=None
    ):
        # TODO: or not? param not yet implemented
        if self.get_param('ignore_no_formats_error'):
            fatal = False

        res = self._download_xml_handle(
            mpd_url,
            video_id,
            note='Downloading MPD manifest' if note is None else note,
            errnote='Failed to download MPD manifest' if errnote is None else errnote,
            fatal=fatal,
            data=data,
            headers=headers or {},
            query=query or {},
        )
        if res is False:
            return [], {}
        mpd_doc, urlh = res
        if mpd_doc is None:
            return [], {}

        # We could have been redirected to a new url when we retrieved our mpd file.
        mpd_url = urlh.geturl()
        mpd_base_url = base_url(mpd_url)

        return self._parse_mpd_formats_and_subtitles(mpd_doc, mpd_id, mpd_base_url, mpd_url)

    def _parse_mpd_formats_and_subtitles(self, mpd_doc, mpd_id=None, mpd_base_url='', mpd_url=None):
        """
        Parse formats from MPD manifest.
        References:
         1. MPEG-DASH Standard, ISO/IEC 23009-1:2014(E),
            http://standards.iso.org/ittf/PubliclyAvailableStandards/c065274_ISO_IEC_23009-1_2014.zip
         2. https://en.wikipedia.org/wiki/Dynamic_Adaptive_Streaming_over_HTTP
        """
        # TODO: param not yet implemented: default like previous yt-dl logic
        if not self.get_param('dynamic_mpd', False):
            if mpd_doc.get('type') == 'dynamic':
                return [], {}

        namespace = self._search_regex(r'(?i)^{([^}]+)?}MPD$', mpd_doc.tag, 'namespace', default=None)

        def _add_ns(path):
            return self._xpath_ns(path, namespace)

        def is_drm_protected(element):
            return element.find(_add_ns('ContentProtection')) is not None

        from ..utils import YoutubeDLHandler

        fix_path = YoutubeDLHandler._fix_path

        def resolve_base_url(element, parent_base_url=None):
            # TODO: use native XML traversal when ready
            b_url = traverse_obj(element, (T(lambda e: e.find(_add_ns('BaseURL')).text)))
            if parent_base_url and b_url:
                if parent_base_url[-1] not in ('/', ':'):
                    parent_base_url += '/'
                b_url = compat_urlparse.urljoin(parent_base_url, b_url)
            if b_url:
                b_url = fix_path(b_url)
            return b_url or parent_base_url

        def extract_multisegment_info(element, ms_parent_info):
            ms_info = ms_parent_info.copy()
            base_url = ms_info['base_url'] = resolve_base_url(element, ms_info.get('base_url'))

            # As per [1, 5.3.9.2.2] SegmentList and SegmentTemplate share some
            # common attributes and elements.  We will only extract relevant
            # for us.
            def extract_common(source):
                segment_timeline = source.find(_add_ns('SegmentTimeline'))
                if segment_timeline is not None:
                    s_e = segment_timeline.findall(_add_ns('S'))
                    if s_e:
                        ms_info['total_number'] = 0
                        ms_info['s'] = []
                        for s in s_e:
                            r = int(s.get('r', 0))
                            ms_info['total_number'] += 1 + r
                            ms_info['s'].append(
                                {
                                    't': int(s.get('t', 0)),
                                    # @d is mandatory (see [1, 5.3.9.6.2, Table 17, page 60])
                                    'd': int(s.attrib['d']),
                                    'r': r,
                                }
                            )
                start_number = source.get('startNumber')
                if start_number:
                    ms_info['start_number'] = int(start_number)
                timescale = source.get('timescale')
                if timescale:
                    ms_info['timescale'] = int(timescale)
                segment_duration = source.get('duration')
                if segment_duration:
                    ms_info['segment_duration'] = float(segment_duration)

            def extract_Initialization(source):
                initialization = source.find(_add_ns('Initialization'))
                if initialization is not None:
                    ms_info['initialization_url'] = initialization.get('sourceURL') or base_url
                    initialization_url_range = initialization.get('range')
                    if initialization_url_range:
                        ms_info['initialization_url_range'] = initialization_url_range

            segment_list = element.find(_add_ns('SegmentList'))
            if segment_list is not None:
                extract_common(segment_list)
                extract_Initialization(segment_list)
                segment_urls_e = segment_list.findall(_add_ns('SegmentURL'))
                segment_urls = traverse_obj(segment_urls_e, (Ellipsis, T(lambda e: e.attrib), 'media'))
                if segment_urls:
                    ms_info['segment_urls'] = segment_urls
                segment_urls_range = traverse_obj(
                    segment_urls_e,
                    (Ellipsis, T(lambda e: e.attrib), 'mediaRange', T(lambda r: re.findall(r'^\d+-\d+$', r)), 0),
                )
                if segment_urls_range:
                    ms_info['segment_urls_range'] = segment_urls_range
                    if not segment_urls:
                        ms_info['segment_urls'] = [base_url for _ in segment_urls_range]
            else:
                segment_template = element.find(_add_ns('SegmentTemplate'))
                if segment_template is not None:
                    extract_common(segment_template)
                    media = segment_template.get('media')
                    if media:
                        ms_info['media'] = media
                    initialization = segment_template.get('initialization')
                    if initialization:
                        ms_info['initialization'] = initialization
                    else:
                        extract_Initialization(segment_template)
            return ms_info

        mpd_duration = parse_duration(mpd_doc.get('mediaPresentationDuration'))
        formats, subtitles = [], {}
        stream_numbers = collections.defaultdict(int)
        mpd_base_url = resolve_base_url(mpd_doc, mpd_base_url or mpd_url)
        for period in mpd_doc.findall(_add_ns('Period')):
            period_duration = parse_duration(period.get('duration')) or mpd_duration
            period_ms_info = extract_multisegment_info(
                period,
                {
                    'start_number': 1,
                    'timescale': 1,
                    'base_url': mpd_base_url,
                },
            )
            for adaptation_set in period.findall(_add_ns('AdaptationSet')):
                if is_drm_protected(adaptation_set):
                    continue
                adaptation_set_ms_info = extract_multisegment_info(adaptation_set, period_ms_info)
                for representation in adaptation_set.findall(_add_ns('Representation')):
                    if is_drm_protected(representation):
                        continue
                    representation_attrib = adaptation_set.attrib.copy()
                    representation_attrib.update(representation.attrib)
                    # According to [1, 5.3.7.2, Table 9, page 41], @mimeType is mandatory
                    mime_type = representation_attrib['mimeType']
                    content_type = representation_attrib.get('contentType') or mime_type.split('/')[0]
                    codec_str = representation_attrib.get('codecs', '')
                    # Some kind of binary subtitle found in some youtube livestreams
                    if mime_type == 'application/x-rawcc':
                        codecs = {'scodec': codec_str}
                    else:
                        codecs = parse_codecs(codec_str)
                    if content_type not in ('video', 'audio', 'text'):
                        if mime_type == 'image/jpeg':
                            content_type = mime_type
                        elif codecs.get('vcodec', 'none') != 'none':
                            content_type = 'video'
                        elif codecs.get('acodec', 'none') != 'none':
                            content_type = 'audio'
                        elif codecs.get('scodec', 'none') != 'none':
                            content_type = 'text'
                        elif mimetype2ext(mime_type) in ('tt', 'dfxp', 'ttml', 'xml', 'json'):
                            content_type = 'text'
                        else:
                            self.report_warning(f'Unknown MIME type {mime_type} in DASH manifest')
                            continue

                    representation_id = representation_attrib.get('id')
                    lang = representation_attrib.get('lang')
                    url_el = representation.find(_add_ns('BaseURL'))
                    filesize = int_or_none(
                        url_el.get('{http://youtube.com/yt/2012/10/10}contentLength') if url_el is not None else None
                    )
                    bandwidth = int_or_none(representation_attrib.get('bandwidth'))
                    format_id = join_nonempty(representation_id or content_type, mpd_id)
                    if content_type in ('video', 'audio'):
                        f = {
                            'format_id': f'{mpd_id}-{representation_id}' if mpd_id else representation_id,
                            'manifest_url': mpd_url,
                            'ext': mimetype2ext(mime_type),
                            'width': int_or_none(representation_attrib.get('width')),
                            'height': int_or_none(representation_attrib.get('height')),
                            'tbr': float_or_none(bandwidth, 1000),
                            'asr': int_or_none(representation_attrib.get('audioSamplingRate')),
                            'fps': int_or_none(representation_attrib.get('frameRate')),
                            'language': lang if lang not in ('mul', 'und', 'zxx', 'mis') else None,
                            'format_note': f'DASH {content_type}',
                            'filesize': filesize,
                            'container': mimetype2ext(mime_type) + '_dash',
                        }
                        f.update(codecs)
                    elif content_type == 'text':
                        f = {
                            'ext': mimetype2ext(mime_type),
                            'manifest_url': mpd_url,
                            'filesize': filesize,
                        }
                    elif content_type == 'image/jpeg':
                        # See test case in VikiIE
                        # https://www.viki.com/videos/1175236v-choosing-spouse-by-lottery-episode-1
                        f = {
                            'format_id': format_id,
                            'ext': 'mhtml',
                            'manifest_url': mpd_url,
                            'format_note': 'DASH storyboards (jpeg)',
                            'acodec': 'none',
                            'vcodec': 'none',
                        }
                    if is_drm_protected(adaptation_set) or is_drm_protected(representation):
                        f['has_drm'] = True
                    representation_ms_info = extract_multisegment_info(representation, adaptation_set_ms_info)

                    def prepare_template(template_name, identifiers):
                        tmpl = representation_ms_info[template_name]
                        # First of, % characters outside $...$ templates
                        # must be escaped by doubling for proper processing
                        # by % operator string formatting used further (see
                        # https://github.com/ytdl-org/youtube-dl/issues/16867).
                        t = ''
                        in_template = False
                        for c in tmpl:
                            t += c
                            if c == '$':
                                in_template = not in_template
                            elif c == '%' and not in_template:
                                t += c
                        # Next, $...$ templates are translated to their
                        # %(...) counterparts to be used with % operator
                        t = t.replace('$RepresentationID$', representation_id)
                        t = re.sub(r'\$({})\$'.format('|'.join(identifiers)), r'%(\1)d', t)
                        t = re.sub(r'\$({})%([^$]+)\$'.format('|'.join(identifiers)), r'%(\1)\2', t)
                        t.replace('$$', '$')
                        return t

                    # @initialization is a regular template like @media one
                    # so it should be handled just the same way (see
                    # https://github.com/ytdl-org/youtube-dl/issues/11605)
                    if 'initialization' in representation_ms_info:
                        initialization_template = prepare_template(
                            'initialization',
                            # As per [1, 5.3.9.4.2, Table 15, page 54] $Number$ and
                            # $Time$ shall not be included for @initialization thus
                            # only $Bandwidth$ remains
                            ('Bandwidth',),
                        )
                        representation_ms_info['initialization_url'] = initialization_template % {
                            'Bandwidth': bandwidth,
                        }

                    def location_key(location):
                        return 'url' if re.match(r'^https?://', location) else 'path'

                    def calc_segment_duration():
                        return (
                            float_or_none(
                                representation_ms_info['segment_duration'], representation_ms_info['timescale']
                            )
                            if 'segment_duration' in representation_ms_info
                            else None
                        )

                    if 'segment_urls' not in representation_ms_info and 'media' in representation_ms_info:
                        media_template = prepare_template('media', ('Number', 'Bandwidth', 'Time'))
                        media_location_key = location_key(media_template)

                        # As per [1, 5.3.9.4.4, Table 16, page 55] $Number$ and $Time$
                        # can't be used at the same time
                        if '%(Number' in media_template and 's' not in representation_ms_info:
                            segment_duration = None
                            if (
                                'total_number' not in representation_ms_info
                                and 'segment_duration' in representation_ms_info
                            ):
                                segment_duration = float_or_none(
                                    representation_ms_info['segment_duration'], representation_ms_info['timescale']
                                )
                                representation_ms_info['total_number'] = math.ceil(
                                    float_or_none(period_duration, segment_duration, default=0)
                                )
                            representation_ms_info['fragments'] = [
                                {
                                    media_location_key: media_template
                                    % {
                                        'Number': segment_number,
                                        'Bandwidth': bandwidth,
                                    },
                                    'duration': segment_duration,
                                }
                                for segment_number in range(
                                    representation_ms_info['start_number'],
                                    representation_ms_info['total_number'] + representation_ms_info['start_number'],
                                )
                            ]
                        else:
                            # $Number*$ or $Time$ in media template with S list available
                            # Example $Number*$: http://www.svtplay.se/klipp/9023742/stopptid-om-bjorn-borg
                            # Example $Time$: https://play.arkena.com/embed/avp/v2/player/media/b41dda37-d8e7-4d3f-b1b5-9a9db578bdfe/1/129411
                            representation_ms_info['fragments'] = []
                            segment_time = 0
                            segment_d = None
                            segment_number = representation_ms_info['start_number']

                            def add_segment_url():
                                segment_url = media_template % {
                                    'Time': segment_time,
                                    'Bandwidth': bandwidth,
                                    'Number': segment_number,
                                }
                                representation_ms_info['fragments'].append(
                                    {
                                        media_location_key: segment_url,
                                        'duration': float_or_none(segment_d, representation_ms_info['timescale']),
                                    }
                                )

                            for num, s in enumerate(representation_ms_info['s']):
                                segment_time = s.get('t') or segment_time
                                segment_d = s['d']
                                add_segment_url()
                                segment_number += 1
                                for r in range(s.get('r', 0)):
                                    segment_time += segment_d
                                    add_segment_url()
                                    segment_number += 1
                                segment_time += segment_d
                    elif 'segment_urls' in representation_ms_info:
                        fragments = []
                        if 's' in representation_ms_info:
                            # No media template
                            # Example: https://www.youtube.com/watch?v=iXZV5uAYMJI
                            # or any YouTube dashsegments video
                            segment_index = 0
                            timescale = representation_ms_info['timescale']
                            for s in representation_ms_info['s']:
                                duration = float_or_none(s['d'], timescale)
                                for r in range(s.get('r', 0) + 1):
                                    segment_uri = representation_ms_info['segment_urls'][segment_index]
                                    fragments.append(
                                        {
                                            location_key(segment_uri): segment_uri,
                                            'duration': duration,
                                        }
                                    )
                                    segment_index += 1
                        elif 'segment_urls_range' in representation_ms_info:
                            # Segment URLs with mediaRange
                            # Example: https://kinescope.io/200615537/master.mpd
                            # https://github.com/ytdl-org/youtube-dl/issues/30235
                            # or any mpd generated with Bento4 `mp4dash --no-split --use-segment-list`
                            segment_duration = calc_segment_duration()
                            for segment_url, segment_url_range in zip(
                                representation_ms_info['segment_urls'], representation_ms_info['segment_urls_range']
                            ):
                                fragments.append(
                                    {
                                        location_key(segment_url): segment_url,
                                        'range': segment_url_range,
                                        'duration': segment_duration,
                                    }
                                )
                        else:
                            # Segment URLs with no SegmentTimeline
                            # Example: https://www.seznam.cz/zpravy/clanek/cesko-zasahne-vitr-o-sile-vichrice-muze-byt-i-zivotu-nebezpecny-39091
                            # https://github.com/ytdl-org/youtube-dl/pull/14844
                            segment_duration = calc_segment_duration()
                            for segment_url in representation_ms_info['segment_urls']:
                                fragments.append(
                                    {
                                        location_key(segment_url): segment_url,
                                        'duration': segment_duration,
                                    }
                                )
                        representation_ms_info['fragments'] = fragments

                    # If there is a fragments key available then we correctly recognized fragmented media.
                    # Otherwise we will assume unfragmented media with direct access. Technically, such
                    # assumption is not necessarily correct since we may simply have no support for
                    # some forms of fragmented media renditions yet, but for now we'll use this fallback.
                    if 'fragments' in representation_ms_info:
                        base_url = representation_ms_info['base_url']
                        f.update(
                            {
                                # NB: mpd_url may be empty when MPD manifest is parsed from a string
                                'url': mpd_url or base_url,
                                'fragment_base_url': base_url,
                                'fragments': [],
                                'protocol': 'http_dash_segments',
                            }
                        )
                        if (
                            'initialization_url' in representation_ms_info
                            and 'initialization_url_range' in representation_ms_info
                        ):
                            # Initialization URL with range (accompanied by Segment URLs with mediaRange above)
                            # https://github.com/ytdl-org/youtube-dl/issues/30235
                            initialization_url = representation_ms_info['initialization_url']
                            f['fragments'].append(
                                {
                                    location_key(initialization_url): initialization_url,
                                    'range': representation_ms_info['initialization_url_range'],
                                }
                            )
                        elif 'initialization_url' in representation_ms_info:
                            initialization_url = representation_ms_info['initialization_url']
                            if not f.get('url'):
                                f['url'] = initialization_url
                            f['fragments'].append({location_key(initialization_url): initialization_url})
                        elif 'initialization_url_range' in representation_ms_info:
                            # no Initialization URL but range (accompanied by no Segment URLs but mediaRange above)
                            # https://github.com/ytdl-org/youtube-dl/issues/27575
                            f['fragments'].append(
                                {
                                    location_key(base_url): base_url,
                                    'range': representation_ms_info['initialization_url_range'],
                                }
                            )
                        f['fragments'].extend(representation_ms_info['fragments'])
                        if not period_duration:
                            period_duration = sum(
                                traverse_obj(
                                    representation_ms_info, ('fragments', Ellipsis, 'duration', T(float_or_none))
                                )
                            )
                    else:
                        # Assuming direct URL to unfragmented media.
                        f['url'] = representation_ms_info['base_url']
                    if content_type in ('video', 'audio', 'image/jpeg'):
                        f['manifest_stream_number'] = stream_numbers[f['url']]
                        stream_numbers[f['url']] += 1
                        formats.append(f)
                    elif content_type == 'text':
                        subtitles.setdefault(lang or 'und', []).append(f)
        return formats, subtitles

    def _parse_ism_formats(self, ism_doc, ism_url, ism_id=None):
        """
        Parse formats from ISM manifest.
        References:
         1. [MS-SSTR]: Smooth Streaming Protocol,
            https://msdn.microsoft.com/en-us/library/ff469518.aspx
        """
        if ism_doc.get('IsLive') == 'TRUE' or ism_doc.find('Protection') is not None:
            return []

        duration = int(ism_doc.attrib['Duration'])
        timescale = int_or_none(ism_doc.get('TimeScale')) or 10000000

        formats = []
        for stream in ism_doc.findall('StreamIndex'):
            stream_type = stream.get('Type')
            if stream_type not in ('video', 'audio'):
                continue
            url_pattern = stream.attrib['Url']
            stream_timescale = int_or_none(stream.get('TimeScale')) or timescale
            stream_name = stream.get('Name')
            for track in stream.findall('QualityLevel'):
                fourcc = track.get('FourCC', 'AACL' if track.get('AudioTag') == '255' else None)
                # TODO: add support for WVC1 and WMAP
                if fourcc not in ('H264', 'AVC1', 'AACL'):
                    self.report_warning(f'{fourcc} is not a supported codec')
                    continue
                tbr = int(track.attrib['Bitrate']) // 1000
                # [1] does not mention Width and Height attributes. However,
                # they're often present while MaxWidth and MaxHeight are
                # missing, so should be used as fallbacks
                width = int_or_none(track.get('MaxWidth') or track.get('Width'))
                height = int_or_none(track.get('MaxHeight') or track.get('Height'))
                sampling_rate = int_or_none(track.get('SamplingRate'))

                track_url_pattern = re.sub(r'{[Bb]itrate}', track.attrib['Bitrate'], url_pattern)
                track_url_pattern = compat_urlparse.urljoin(ism_url, track_url_pattern)

                fragments = []
                fragment_ctx = {
                    'time': 0,
                }
                stream_fragments = stream.findall('c')
                for stream_fragment_index, stream_fragment in enumerate(stream_fragments):
                    fragment_ctx['time'] = int_or_none(stream_fragment.get('t')) or fragment_ctx['time']
                    fragment_repeat = int_or_none(stream_fragment.get('r')) or 1
                    fragment_ctx['duration'] = int_or_none(stream_fragment.get('d'))
                    if not fragment_ctx['duration']:
                        try:
                            next_fragment_time = int(stream_fragment[stream_fragment_index + 1].attrib['t'])
                        except IndexError:
                            next_fragment_time = duration
                        fragment_ctx['duration'] = (next_fragment_time - fragment_ctx['time']) / fragment_repeat
                    for _ in range(fragment_repeat):
                        fragments.append(
                            {
                                'url': re.sub(r'{start[ _]time}', compat_str(fragment_ctx['time']), track_url_pattern),
                                'duration': fragment_ctx['duration'] / stream_timescale,
                            }
                        )
                        fragment_ctx['time'] += fragment_ctx['duration']

                format_id = []
                if ism_id:
                    format_id.append(ism_id)
                if stream_name:
                    format_id.append(stream_name)
                format_id.append(compat_str(tbr))

                formats.append(
                    {
                        'format_id': '-'.join(format_id),
                        'url': ism_url,
                        'manifest_url': ism_url,
                        'ext': 'ismv' if stream_type == 'video' else 'isma',
                        'width': width,
                        'height': height,
                        'tbr': tbr,
                        'asr': sampling_rate,
                        'vcodec': 'none' if stream_type == 'audio' else fourcc,
                        'acodec': 'none' if stream_type == 'video' else fourcc,
                        'protocol': 'ism',
                        'fragments': fragments,
                        '_download_params': {
                            'duration': duration,
                            'timescale': stream_timescale,
                            'width': width or 0,
                            'height': height or 0,
                            'fourcc': fourcc,
                            'codec_private_data': track.get('CodecPrivateData'),
                            'sampling_rate': sampling_rate,
                            'channels': int_or_none(track.get('Channels', 2)),
                            'bits_per_sample': int_or_none(track.get('BitsPerSample', 16)),
                            'nal_unit_length_field': int_or_none(track.get('NALUnitLengthField', 4)),
                        },
                    }
                )
        return formats

    def get_testcases(self, include_onlymatching=False):
        t = getattr(self, '_TEST', None)
        if t:
            assert not hasattr(self, '_TESTS'), f'{type(self).__name__} has _TEST and _TESTS'
            tests = [t]
        else:
            tests = getattr(self, '_TESTS', [])
        for t in tests:
            if not include_onlymatching and t.get('only_matching', False):
                continue
            t['name'] = type(self).__name__[: -len('IE')]
            yield t

    def is_suitable(self, age_limit):
        """Test whether the extractor is generally suitable for the given
        age limit (i.e. pornographic sites are not, all others usually are)"""

        any_restricted = False
        for tc in self.get_testcases(include_onlymatching=False):
            if tc.get('playlist', []):
                tc = tc['playlist'][0]
            is_restricted = age_restricted(tc.get('info_dict', {}).get('age_limit'), age_limit)
            if not is_restricted:
                return True
            any_restricted = any_restricted or is_restricted
        return not any_restricted

    def mark_watched(self, *args, **kwargs):
        if self.get_param('mark_watched', False) and (
            self._get_login_info()[0] is not None or self.get_param('cookiefile') is not None
        ):
            self._mark_watched(*args, **kwargs)

    def _mark_watched(self, *args, **kwargs):
        raise NotImplementedError('This method must be implemented by subclasses')


class SearchInfoExtractor(InfoExtractor):
    """
    Base class for paged search queries extractors.
    They accept URLs in the format _SEARCH_KEY(|all|[0-9]):{query}
    Instances should define _SEARCH_KEY and _MAX_RESULTS.
    """

    @classmethod
    def _make_valid_url(cls):
        return rf'{cls._SEARCH_KEY}(?P<prefix>|[1-9][0-9]*|all):(?P<query>[\s\S]+)'

    @classmethod
    def suitable(cls, url):
        return re.match(cls._make_valid_url(), url) is not None

    def _real_extract(self, query):
        mobj = re.match(self._make_valid_url(), query)
        if mobj is None:
            raise ExtractorError(f'Invalid search query "{query}"')

        prefix = mobj.group('prefix')
        query = mobj.group('query')
        if prefix == '':
            return self._get_n_results(query, 1)
        elif prefix == 'all':
            return self._get_n_results(query, self._MAX_RESULTS)
        else:
            n = int(prefix)
            if n <= 0:
                raise ExtractorError(f'invalid download number {n} for query "{query}"')
            elif n > self._MAX_RESULTS:
                self._downloader.report_warning(
                    '%s returns max %i results (you requested %i)' % (self._SEARCH_KEY, self._MAX_RESULTS, n)
                )
                n = self._MAX_RESULTS
            return self._get_n_results(query, n)

    def _get_n_results(self, query, n):
        """Get a specified number of results for a query"""
        raise NotImplementedError('This method must be implemented by subclasses')

    @property
    def SEARCH_KEY(self):
        return self._SEARCH_KEY
