#!/usr/bin/env python
from __future__ import annotations

import collections
import copy
import datetime
import errno
import functools
import io
import itertools
import json
import locale
import logging
import operator
import os
import platform
import random
import re
import shutil
import subprocess
import sys
import time
import tokenize
import traceback
from typing import Any
from typing import ClassVar

try:
    from ssl import OPENSSL_VERSION
except ImportError:
    # Must be Python 2.6, should be built against 1.0.2
    OPENSSL_VERSION = 'OpenSSL 1.0.2(?)'
from string import ascii_letters

from .cache import Cache
from .compat import compat_basestring
from .compat import compat_collections_chain_map as ChainMap
from .compat import compat_filter as filter
from .compat import compat_http_client
from .compat import compat_http_cookiejar_Cookie
from .compat import compat_http_cookies_SimpleCookie
from .compat import compat_integer_types
from .compat import compat_kwargs
from .compat import compat_map as map
from .compat import compat_numeric_types
from .compat import compat_open as open
from .compat import compat_os_name
from .compat import compat_str
from .compat import compat_tokenize_tokenize
from .compat import compat_urllib_error
from .compat import compat_urllib_parse
from .compat import compat_urllib_request
from .compat import compat_urllib_request_DataHandler
from .downloader import get_suitable_downloader
from .downloader.rtmp import rtmpdump_version
from .extractor import gen_extractor_classes
from .extractor import get_info_extractor
from .postprocessor import FFmpegFixupM3u8PP
from .postprocessor import FFmpegFixupM4aPP
from .postprocessor import FFmpegFixupStretchedPP
from .postprocessor import FFmpegMergerPP
from .postprocessor import FFmpegPostProcessor
from .postprocessor import get_postprocessor
from .utils import DEFAULT_OUTTMPL
from .utils import ContentTooShortError
from .utils import DateRange
from .utils import DownloadError
from .utils import ExtractorError
from .utils import GeoRestrictedError
from .utils import ISO3166Utils
from .utils import LazyList
from .utils import MaxDownloadsReached
from .utils import PagedList
from .utils import PerRequestProxyHandler
from .utils import PostProcessingError
from .utils import SameFileError
from .utils import UnavailableVideoError
from .utils import YoutubeDLCookieJar
from .utils import YoutubeDLCookieProcessor
from .utils import YoutubeDLHandler
from .utils import YoutubeDLRedirectHandler
from .utils import _UnsafeExtensionError
from .utils import age_restricted
from .utils import args_to_str
from .utils import bug_reports_message
from .utils import date_from_str
from .utils import determine_ext
from .utils import determine_protocol
from .utils import encode_compat_str
from .utils import encodeFilename
from .utils import error_to_compat_str
from .utils import expand_path
from .utils import format_bytes
from .utils import formatSeconds
from .utils import int_or_none
from .utils import join_nonempty
from .utils import locked_file
from .utils import make_HTTPS_handler
from .utils import orderedSet
from .utils import parse_filesize
from .utils import platform_name
from .utils import preferredencoding
from .utils import prepend_extension
from .utils import process_communicate_or_kill
from .utils import render_table
from .utils import replace_extension
from .utils import sanitize_filename
from .utils import sanitize_path
from .utils import sanitize_url
from .utils import sanitized_Request
from .utils import std_headers
from .utils import str_or_none
from .utils import subtitles_filename
from .utils import traverse_obj
from .utils import url_basename
from .utils import version_tuple
from .utils import write_json_file
from .utils import write_string
from .utils import ytdl_is_updateable
from .version import __version__

if compat_os_name == 'nt':
    pass

logger = logging.getLogger('soundcloudutil.downloader')

TAGGED_LOG_MSG_REGEX = re.compile(r'^\[(?P<tag>\w+)(:(?P<subtag>\w+))?\]\s*(?P<msg>.+)$')


def _catch_unsafe_file_extension(func):
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except _UnsafeExtensionError as error:
            self.report_error(
                '{} found; to avoid damaging your system, this value is disallowed.'
                ' If you believe this is an error{}'.format(error_to_compat_str(error), bug_reports_message(','))
            )

    return wrapper


class YoutubeDL:
    """YoutubeDL class.

    YoutubeDL objects are the ones responsible of downloading the
    actual video file and writing it to disk if the user has requested
    it, among some other tasks. In most cases there should be one per
    program. As, given a video URL, the downloader doesn't know how to
    extract all the needed information, task that InfoExtractors do, it
    has to pass the URL to one of them.

    For this, YoutubeDL objects have a method that allows
    InfoExtractors to be registered in a given order. When it is passed
    a URL, the YoutubeDL object handles it to the first InfoExtractor it
    finds that reports being able to handle it. The InfoExtractor extracts
    all the information about the video or videos the URL refers to, and
    YoutubeDL process the extracted information, possibly using a File
    Downloader to download the video.

    YoutubeDL objects accept a lot of parameters. In order not to saturate
    the object constructor with arguments, it receives a dictionary of
    options instead. These options are available through the params
    attribute for the InfoExtractors to use. The YoutubeDL also
    registers itself as the downloader in charge for the InfoExtractors
    that are added to it, so this is a "mutual registration".

    Available options:

    username:          Username for authentication purposes.
    password:          Password for authentication purposes.
    videopassword:     Password for accessing a video.
    ap_mso:            Adobe Pass multiple-system operator identifier.
    ap_username:       Multiple-system operator account username.
    ap_password:       Multiple-system operator account password.
    usenetrc:          Use netrc for authentication instead.
    verbose:           Print additional info to stdout.
    quiet:             Do not print messages to stdout.
    no_warnings:       Do not print out anything for warnings.
    forceurl:          Force printing final URL.
    forcetitle:        Force printing title.
    forceid:           Force printing ID.
    forcethumbnail:    Force printing thumbnail URL.
    forcedescription:  Force printing description.
    forcefilename:     Force printing final filename.
    forceduration:     Force printing duration.
    forcejson:         Force printing info_dict as JSON.
    dump_single_json:  Force printing the info_dict of the whole playlist
                       (or video) as a single JSON line.
    simulate:          Do not download the video files.
    format:            Video format code. See options.py for more information.
    outtmpl:           Template for output names.
    outtmpl_na_placeholder: Placeholder for unavailable meta fields.
    restrictfilenames: Do not allow "&" and spaces in file names
    ignoreerrors:      Do not stop on download errors.
    nooverwrites:      Prevent overwriting files.
    playliststart:     Playlist item to start at.
    playlistend:       Playlist item to end at.
    playlist_items:    Specific indices of playlist to download.
    playlistreverse:   Download playlist items in reverse order.
    playlistrandom:    Download playlist items in random order.
    matchtitle:        Download only matching titles.
    rejecttitle:       Reject downloads for matching titles.
    logtostderr:       Log messages to stderr instead of stdout.
    writedescription:  Write the video description to a .description file
    writeinfojson:     Write the video description to a .info.json file
    writeannotations:  Write the video annotations to a .annotations.xml file
    writethumbnail:    Write the thumbnail image to a file
    write_all_thumbnails:  Write all thumbnail formats to files
    writesubtitles:    Write the video subtitles to a file
    writeautomaticsub: Write the automatically generated subtitles to a file
    allsubtitles:      Downloads all the subtitles of the video
                       (requires writesubtitles or writeautomaticsub)
    listsubtitles:     Lists all available subtitles for the video
    subtitlesformat:   The format code for subtitles
    subtitleslangs:    List of languages of the subtitles to download
    keepvideo:         Keep the video file after post-processing
    daterange:         A DateRange object, download only if the upload_date is in the range.
    skip_download:     Skip the actual download of the video file
    cachedir:          Location of the cache files in the filesystem.
                       False to disable filesystem cache.
    noplaylist:        Download single video instead of a playlist if in doubt.
    age_limit:         An integer representing the user's age in years.
                       Unsuitable videos for the given age are skipped.
    min_views:         An integer representing the minimum view count the video
                       must have in order to not be skipped.
                       Videos without view count information are always
                       downloaded. None for no limit.
    max_views:         An integer representing the maximum view count.
                       Videos that are more popular than that are not
                       downloaded.
                       Videos without view count information are always
                       downloaded. None for no limit.
    download_archive:  File name of a file where all downloads are recorded.
                       Videos already present in the file are not downloaded
                       again.
    cookiefile:        File name where cookies should be read from and dumped to.
    nocheckcertificate:Do not verify SSL certificates
    prefer_insecure:   Use HTTP instead of HTTPS to retrieve information.
                       At the moment, this is only supported by YouTube.
    proxy:             URL of the proxy server to use
    socket_timeout:    Time to wait for unresponsive hosts, in seconds
    debug_printtraffic:Print out sent and received HTTP traffic
    include_ads:       Download ads as well
    default_search:    Prepend this string if an input url is not valid.
                       'auto' for elaborate guessing
    encoding:          Use this encoding instead of the system-specified.
    extract_flat:      Do not resolve URLs, return the immediate result.
                       Pass in 'in_playlist' to only show this behavior for
                       playlist items.
    postprocessors:    A list of dictionaries, each with an entry
                       * key:  The name of the postprocessor. See
                               youtube_dl/postprocessor/__init__.py for a list.
                       as well as any further keyword arguments for the
                       postprocessor.
    progress_hooks:    A list of functions that get called on download
                       progress, with a dictionary with the entries
                       * status: One of "downloading", "error", or "finished".
                                 Check this first and ignore unknown values.

                       If status is one of "downloading", or "finished", the
                       following properties may also be present:
                       * filename: The final filename (always present)
                       * tmpfilename: The filename we're currently writing to
                       * downloaded_bytes: Bytes on disk
                       * total_bytes: Size of the whole file, None if unknown
                       * total_bytes_estimate: Guess of the eventual file size,
                                               None if unavailable.
                       * elapsed: The number of seconds since download started.
                       * eta: The estimated time in seconds, None if unknown
                       * speed: The download speed in bytes/second, None if
                                unknown
                       * fragment_index: The counter of the currently
                                         downloaded video fragment.
                       * fragment_count: The number of fragments (= individual
                                         files that will be merged)

                       Progress hooks are guaranteed to be called at least once
                       (with status "finished") if the download is successful.
    merge_output_format: Extension to use when merging formats.
    fixup:             Automatically correct known faults of the file.
                       One of:
                       - "never": do nothing
                       - "warn": only emit a warning
                       - "detect_or_warn": check whether we can do anything
                                           about it, warn otherwise (default)
    source_address:    Client-side IP address to bind to.
    call_home:         Boolean, true iff we are allowed to contact the
                       youtube-dl servers for debugging.
    sleep_interval:    Number of seconds to sleep before each download when
                       used alone or a lower bound of a range for randomized
                       sleep before each download (minimum possible number
                       of seconds to sleep) when used along with
                       max_sleep_interval.
    max_sleep_interval:Upper bound of a range for randomized sleep before each
                       download (maximum possible number of seconds to sleep).
                       Must only be used along with sleep_interval.
                       Actual sleep time will be a random float from range
                       [sleep_interval; max_sleep_interval].
    listformats:       Print an overview of available video formats and exit.
    list_thumbnails:   Print a table of all thumbnails and exit.
    match_filter:      A function that gets called with the info_dict of
                       every video.
                       If it returns a message, the video is ignored.
                       If it returns None, the video is downloaded.
                       match_filter_func in utils.py is one example for this.
    no_color:          Do not emit color codes in output.

    The following options determine which downloader is picked:
    external_downloader: Executable of the external downloader to call.
                       None or unset for standard (built-in) downloader.
    hls_prefer_native: Use the native HLS downloader instead of ffmpeg/avconv
                       if True, otherwise use ffmpeg/avconv if False, otherwise
                       use downloader suggested by extractor if None.

    The following parameters are not used by YoutubeDL itself, they are used by
    the downloader (see youtube_dl/downloader/common.py):
    nopart, updatetime, buffersize, ratelimit, min_filesize, max_filesize, test,
    noresizebuffer, retries, continuedl, noprogress,
    xattr_set_filesize, external_downloader_args, hls_use_mpegts,
    http_chunk_size.

    The following options are used by the post processors:
    prefer_ffmpeg:     If False, use avconv instead of ffmpeg if both are available,
                       otherwise prefer ffmpeg.
    ffmpeg_location:   Location of the ffmpeg/avconv binary; either the path
                       to the binary or its containing directory.
    postprocessor_args: A list of additional command-line arguments for the
                        postprocessor.

    The following options are used by the Youtube extractor:
    youtube_include_dash_manifest: If True (default), DASH manifests and related
                        data will be downloaded and processed by extractor.
                        You can reduce network I/O by disabling it if you don't
                        care about DASH.
    """

    _NUMERIC_FIELDS: ClassVar[set[str]] = {
        'width',
        'height',
        'tbr',
        'abr',
        'asr',
        'vbr',
        'fps',
        'filesize',
        'filesize_approx',
        'timestamp',
        'upload_year',
        'upload_month',
        'upload_day',
        'duration',
        'view_count',
        'like_count',
        'dislike_count',
        'repost_count',
        'average_rating',
        'comment_count',
        'age_limit',
        'start_time',
        'end_time',
        'chapter_number',
        'season_number',
        'episode_number',
        'track_number',
        'disc_number',
        'release_year',
        'playlist_index',
    }

    params = None
    _ies = []
    _pps = []
    _download_retcode = None
    _num_downloads = None
    _playlist_level = 0
    _playlist_urls = set()
    _screen_file = None

    def __init__(self, params=None, auto_init=True):
        """Create a FileDownloader object with the given options."""
        if params is None:
            params = {}
        self._ies = []
        self._ies_instances = {}
        self._pps = []
        self._progress_hooks = []
        self._download_retcode = 0
        self._num_downloads = 0
        self._screen_file = [sys.stdout, sys.stderr][params.get('logtostderr', False)]
        self._err_file = sys.stderr
        self.params = {
            # Default parameters
            'nocheckcertificate': False,
        }
        self.params.update(params)
        self.cache = Cache(self)

        self._header_cookies = []
        self._load_cookies_from_headers(self.params.get('http_headers'))

        if (
            sys.platform != 'win32'
            and sys.getfilesystemencoding() in ['ascii', 'ANSI_X3.4-1968']
            and not params.get('restrictfilenames', False)
        ):
            # Unicode filesystem API will throw errors (#1474, #13027)
            self.report_warning(
                'Assuming --restrict-filenames since file system encoding '
                'cannot encode all characters. '
                'Set the LC_ALL environment variable to fix this.'
            )
            self.params['restrictfilenames'] = True

        if isinstance(params.get('outtmpl'), bytes):
            self.report_warning(
                'Parameter outtmpl is bytes, but should be a unicode string. '
                'Put  from __future__ import unicode_literals  at the top of your code file or consider switching to Python 3.x.'
            )

        self._setup_opener()

        if auto_init:
            self.print_debug_header()
            self.add_default_info_extractors()

        for pp_def_raw in self.params.get('postprocessors', []):
            pp_class = get_postprocessor(pp_def_raw['key'])
            pp_def = dict(pp_def_raw)
            del pp_def['key']
            pp = pp_class(self, **compat_kwargs(pp_def))
            self.add_post_processor(pp)

        for ph in self.params.get('progress_hooks', []):
            self.add_progress_hook(ph)

    def __enter__(self) -> YoutubeDL:
        return self

    def __exit__(self, *args: Any) -> None:
        if self.params.get('cookiefile') is not None:
            self.cookiejar.save(ignore_discard=True, ignore_expires=True)

    def warn_if_short_id(self, argv):
        # short YouTube ID starting with dash?
        idxs = [i for i, a in enumerate(argv) if re.match(r'^-[0-9A-Za-z_-]{10}$', a)]
        if idxs:
            correct_argv = (
                ['youtube-dl'] + [a for i, a in enumerate(argv) if i not in idxs] + ['--'] + [argv[i] for i in idxs]
            )
            self.report_warning(
                'Long argument string detected. '
                f'Use -- to separate parameters and URLs, like this:\n{args_to_str(correct_argv)}\n'
            )

    def add_info_extractor(self, ie):
        """Add an InfoExtractor object to the end of the list."""
        self._ies.append(ie)
        if not isinstance(ie, type):
            self._ies_instances[ie.ie_key()] = ie
            ie.set_downloader(self)

    def get_info_extractor(self, ie_key):
        """
        Get an instance of an IE with name ie_key, it will try to get one from
        the _ies list, if there's no instance it will create a new one and add
        it to the extractor list.
        """
        ie = self._ies_instances.get(ie_key)
        if ie is None:
            ie = get_info_extractor(ie_key)()
            self.add_info_extractor(ie)
        return ie

    def add_default_info_extractors(self):
        """
        Add the InfoExtractors returned by gen_extractors to the end of the list
        """
        for ie in gen_extractor_classes():
            self.add_info_extractor(ie)

    def add_post_processor(self, pp):
        """Add a PostProcessor object to the end of the chain."""
        self._pps.append(pp)
        pp.set_downloader(self)

    def add_progress_hook(self, ph):
        """Add the progress hook (currently only for the file downloader)"""
        self._progress_hooks.append(ph)

    def to_screen(self, message, skip_eol: bool = False):
        """Print message to stdout if not in quiet mode."""
        return self.to_stdout(message, skip_eol, check_quiet=True)

    def _write_string(self, s: str, out: io.TextIOWrapper | None = None) -> None:
        write_string(s, out=out, encoding=self.params.get('encoding'))

    def to_stdout(self, message, skip_eol: bool = False, check_quiet: bool = False):
        """Print message to stdout if not in quiet mode."""
        quiet = check_quiet and self.params.get('quiet', False)

        debug: bool
        if message.startswith('[debug]'):
            debug = True
            message = message.removeprefix('[debug]').lstrip()
        elif message.startswith('[info]'):
            debug = False
            message = message.removeprefix('[info]').lstrip()
        elif quiet:
            debug = True
        else:
            debug = False

        _logger = logger
        if m := TAGGED_LOG_MSG_REGEX.match(message):
            tag = m.group('tag')
            subtag = m.group('subtag')
            _logger_name = f'youtube_dl.{tag}'
            if m.group('subtag'):
                _logger_name += f'.{subtag}'
            _logger = logging.getLogger(_logger_name)
            message = m.group('msg')

        if debug:
            _logger.debug(message)
        else:
            _logger.info(message)

    def to_stderr(self, message: str) -> None:
        logger.error(message)

    def to_screen(self, message, skip_eol=False):
        """Print message to stdout if not in quiet mode."""
        return self.to_stdout(message, skip_eol, check_quiet=True)

    def trouble(self, *args, **kwargs):
        """Determine action to take when a download problem appears.

        Depending on if the downloader has been configured to ignore
        download errors or not, this method may throw an exception or
        not when errors are found, after printing the message.

        tb, if given, is additional traceback information.
        """
        # message=None, tb=None, is_error=True
        message = args[0] if len(args) > 0 else kwargs.get('message', None)
        tb = args[1] if len(args) > 1 else kwargs.get('tb', None)
        is_error = args[2] if len(args) > 2 else kwargs.get('is_error', True)

        if message is not None:
            self.to_stderr(message)
        if self.params.get('verbose'):
            if tb is None:
                if sys.exc_info()[0]:  # if .trouble has been called from an except block
                    tb = ''
                    if hasattr(sys.exc_info()[1], 'exc_info') and sys.exc_info()[1].exc_info[0]:
                        tb += ''.join(traceback.format_exception(*sys.exc_info()[1].exc_info))
                    tb += encode_compat_str(traceback.format_exc())
                else:
                    tb_data = traceback.format_list(traceback.extract_stack())
                    tb = ''.join(tb_data)
            if tb:
                self.to_stderr(tb)
        if not is_error:
            return
        if not self.params.get('ignoreerrors', False):
            if sys.exc_info()[0] and hasattr(sys.exc_info()[1], 'exc_info') and sys.exc_info()[1].exc_info[0]:
                exc_info = sys.exc_info()[1].exc_info
            else:
                exc_info = sys.exc_info()
            raise DownloadError(message, exc_info)
        self._download_retcode = 1

    def report_warning(self, message: str, only_once: bool = False, _cache: dict[int, int] | None = None) -> None:
        _cache = _cache or {}
        if only_once:
            m_hash = hash((self, message))
            m_cnt = _cache.setdefault(m_hash, 0)
            _cache[m_hash] = m_cnt + 1
            if m_cnt > 0:
                return

        if self.params.get('no_warnings'):
            return
        logger.warning(message)

    # TODO: re-implement :meth:`trouble` to output tracebacks with RichHandler
    def report_error(self, message: str, *args: Any, **kwargs: Any) -> None:
        logger.error(message)
        kwargs['message'] = f'ERROR: {message}'
        self.trouble(*args, **kwargs)

    def write_debug(self, message, only_once=False):
        """Log debug message or Print message to stderr"""
        if not self.params.get('verbose', False):
            return
        message = f'[debug] {message}'
        self.to_stderr(message)

    def report_unscoped_cookies(self, *args, **kwargs):
        # message=None, tb=False, is_error=False
        if len(args) <= 2:
            kwargs.setdefault('is_error', False)
            if len(args) <= 0:
                kwargs.setdefault('message', 'Unscoped cookies are not allowed: please specify some sort of scoping')
        self.report_error(*args, **kwargs)

    def report_file_already_downloaded(self, file_name):
        """Report file has already been fully downloaded."""
        try:
            self.to_screen(f'[download] {file_name} has already been downloaded')
        except UnicodeEncodeError:
            self.to_screen('[download] The file has already been downloaded')

    def prepare_filename(self, info_dict):
        """Generate the output filename."""
        try:
            template_dict = dict(info_dict)

            template_dict['epoch'] = int(time.time())
            template_dict['autonumber'] = self.params.get('autonumber_start', 1) - 1 + self._num_downloads
            if template_dict.get('resolution') is None:
                if template_dict.get('width') and template_dict.get('height'):
                    template_dict['resolution'] = '%dx%d' % (template_dict['width'], template_dict['height'])
                elif template_dict.get('height'):
                    template_dict['resolution'] = '{}p'.format(template_dict['height'])
                elif template_dict.get('width'):
                    template_dict['resolution'] = '%dx?' % template_dict['width']

            def sanitize(k, v):
                return sanitize_filename(
                    compat_str(v),
                    restricted=self.params.get('restrictfilenames'),
                    is_id=(k == 'id' or k.endswith('_id')),
                )

            template_dict = dict(
                (k, v if isinstance(v, compat_numeric_types) else sanitize(k, v))
                for k, v in template_dict.items()
                if v is not None and not isinstance(v, (list, tuple, dict))
            )
            template_dict = collections.defaultdict(
                lambda: self.params.get('outtmpl_na_placeholder', 'NA'), template_dict
            )

            outtmpl = self.params.get('outtmpl', DEFAULT_OUTTMPL)

            # For fields playlist_index and autonumber convert all occurrences
            # of %(field)s to %(field)0Nd for backward compatibility
            field_size_compat_map = {
                'playlist_index': len(str(template_dict['n_entries'])),
                'autonumber': 5,
            }
            FIELD_SIZE_COMPAT_RE = r'(?<!%)%\((?P<field>autonumber|playlist_index)\)s'
            mobj = re.search(FIELD_SIZE_COMPAT_RE, outtmpl)
            if mobj:
                outtmpl = re.sub(
                    FIELD_SIZE_COMPAT_RE, r'%%(\1)0%dd' % field_size_compat_map[mobj.group('field')], outtmpl
                )

            # Missing numeric fields used together with integer presentation types
            # in format specification will break the argument substitution since
            # string NA placeholder is returned for missing fields. We will patch
            # output template for missing fields to meet string presentation type.
            for numeric_field in self._NUMERIC_FIELDS:
                if numeric_field not in template_dict:
                    # As of [1] format syntax is:
                    #  %[mapping_key][conversion_flags][minimum_width][.precision][length_modifier]type
                    # 1. https://docs.python.org/2/library/stdtypes.html#string-formatting
                    FORMAT_RE = r"""(?x)
                        (?<!%)
                        %
                        \({0}\)  # mapping key
                        (?:[#0\-+ ]+)?  # conversion flags (optional)
                        (?:\d+)?  # minimum field width (optional)
                        (?:\.\d+)?  # precision (optional)
                        [hlL]?  # length modifier (optional)
                        [diouxXeEfFgGcrs%]  # conversion type
                    """
                    outtmpl = re.sub(FORMAT_RE.format(numeric_field), rf'%({numeric_field})s', outtmpl)

            # expand_path translates '%%' into '%' and '$$' into '$'
            # correspondingly that is not what we want since we need to keep
            # '%%' intact for template dict substitution step. Working around
            # with boundary-alike separator hack.
            sep = ''.join([random.choice(ascii_letters) for _ in range(32)])
            outtmpl = outtmpl.replace('%%', f'%{sep}%').replace('$$', f'${sep}$')

            # outtmpl should be expand_path'ed before template dict substitution
            # because meta fields may contain env variables we don't want to
            # be expanded. For example, for outtmpl "%(title)s.%(ext)s" and
            # title "Hello $PATH", we don't want `$PATH` to be expanded.
            filename = expand_path(outtmpl).replace(sep, '') % template_dict

            # Temporary fix for #4787
            # 'Treat' all problem characters by passing filename through preferredencoding
            # to workaround encoding issues with subprocess on python2 @ Windows
            if sys.version_info < (3, 0) and sys.platform == 'win32':
                filename = encodeFilename(filename, True).decode(preferredencoding())
            return sanitize_path(filename)
        except ValueError as err:
            self.report_error(
                'Error in output template: '
                + error_to_compat_str(err)
                + ' (encoding: '
                + repr(preferredencoding())
                + ')'
            )
            return None

    def _match_entry(self, info_dict, incomplete):
        """Returns None iff the file should be downloaded"""

        video_title = info_dict.get('title', info_dict.get('id', 'video'))
        if 'title' in info_dict:
            # This can happen when we're just evaluating the playlist
            title = info_dict['title']
            matchtitle = self.params.get('matchtitle', False)
            if matchtitle:
                if not re.search(matchtitle, title, re.IGNORECASE):
                    return '"' + title + '" title did not match pattern "' + matchtitle + '"'
            rejecttitle = self.params.get('rejecttitle', False)
            if rejecttitle:
                if re.search(rejecttitle, title, re.IGNORECASE):
                    return '"' + title + '" title matched reject pattern "' + rejecttitle + '"'
        date = info_dict.get('upload_date')
        if date is not None:
            dateRange = self.params.get('daterange', DateRange())
            if date not in dateRange:
                return f'{date_from_str(date).isoformat()} upload date is not in range {dateRange}'
        view_count = info_dict.get('view_count')
        if view_count is not None:
            min_views = self.params.get('min_views')
            if min_views is not None and view_count < min_views:
                return 'Skipping %s, because it has not reached minimum view count (%d/%d)' % (
                    video_title,
                    view_count,
                    min_views,
                )
            max_views = self.params.get('max_views')
            if max_views is not None and view_count > max_views:
                return 'Skipping %s, because it has exceeded the maximum view count (%d/%d)' % (
                    video_title,
                    view_count,
                    max_views,
                )
        if age_restricted(info_dict.get('age_limit'), self.params.get('age_limit')):
            return f'Skipping "{video_title}" because it is age restricted'
        if self.in_download_archive(info_dict):
            return f'{video_title} has already been recorded in archive'

        if not incomplete:
            match_filter = self.params.get('match_filter')
            if match_filter is not None:
                ret = match_filter(info_dict)
                if ret is not None:
                    return ret

        return None

    @staticmethod
    def add_extra_info(info_dict, extra_info):
        """Set the keys from extra_info in info dict if they are missing"""
        for key, value in extra_info.items():
            info_dict.setdefault(key, value)

    def extract_info(self, url, download=True, ie_key=None, extra_info={}, process=True):
        """
        Return a list with a dictionary for each video extracted.

        Arguments:
        url -- URL to extract

        Keyword arguments:
        download -- whether to download videos during extraction
        ie_key -- extractor key hint
        extra_info -- dictionary containing the extra values to add to each result
        process -- whether to resolve all unresolved references (URLs, playlist items),
            must be True for download to work.
        """
        if ie_key:
            ies = [self.get_info_extractor(ie_key)]
        else:
            ies = self._ies

        for ie in ies:
            if not ie.suitable(url):
                continue

            ie = self.get_info_extractor(ie.ie_key())
            return self.__extract_info(url, ie, download, extra_info, process)
        else:
            self.report_error(f'no suitable InfoExtractor for URL {url}')

    def __handle_extraction_exceptions(func):
        def wrapper(self, *args, **kwargs):
            try:
                return func(self, *args, **kwargs)
            except GeoRestrictedError as e:
                msg = e.msg
                if e.countries:
                    msg += '\nThis video is available in {}.'.format(
                        ', '.join(map(ISO3166Utils.short2full, e.countries))
                    )
                msg += '\nYou might want to use a VPN or a proxy server (with --proxy) to workaround.'
                self.report_error(msg)
            except ExtractorError as e:  # An error we somewhat expected
                self.report_error(compat_str(e), tb=e.format_traceback())
            except MaxDownloadsReached:
                raise
            except Exception as e:
                if self.params.get('ignoreerrors', False):
                    self.report_error(error_to_compat_str(e), tb=encode_compat_str(traceback.format_exc()))
                else:
                    raise

        return wrapper

    def _remove_cookie_header(self, http_headers):
        """Filters out `Cookie` header from an `http_headers` dict
        The `Cookie` header is removed to prevent leaks as a result of unscoped cookies.
        See: https://github.com/yt-dlp/yt-dlp/security/advisories/GHSA-v8mc-9377-rwjj

        @param http_headers     An `http_headers` dict from which any `Cookie` header
                                should be removed, or None
        """
        return dict(filter(lambda pair: pair[0].lower() != 'cookie', (http_headers or {}).items()))

    def _load_cookies(self, data, **kwargs):
        """Loads cookies from a `Cookie` header

        This tries to work around the security vulnerability of passing cookies to every domain.

        @param data         The Cookie header as a string to load the cookies from
        @param autoscope    If `False`, scope cookies using Set-Cookie syntax and error for cookie without domains
                            If `True`, save cookies for later to be stored in the jar with a limited scope
                            If a URL, save cookies in the jar with the domain of the URL
        """
        # autoscope=True (kw-only)
        autoscope = kwargs.get('autoscope', True)

        for cookie in compat_http_cookies_SimpleCookie(data).values() if data else []:
            if autoscope and any(cookie.values()):
                raise ValueError('Invalid syntax in Cookie Header')

            domain = cookie.get('domain') or ''
            expiry = cookie.get('expires')
            if expiry == '':  # 0 is valid so we check for `''` explicitly
                expiry = None
            prepared_cookie = compat_http_cookiejar_Cookie(
                cookie.get('version') or 0,
                cookie.key,
                cookie.value,
                None,
                False,
                domain,
                True,
                True,
                cookie.get('path') or '',
                bool(cookie.get('path')),
                bool(cookie.get('secure')),
                expiry,
                False,
                None,
                None,
                {},
            )

            if domain:
                self.cookiejar.set_cookie(prepared_cookie)
            elif autoscope is True:
                self.report_warning(
                    'Passing cookies as a header is a potential security risk; '
                    'they will be scoped to the domain of the downloaded urls. '
                    'Please consider loading cookies from a file or browser instead.',
                    only_once=True,
                )
                self._header_cookies.append(prepared_cookie)
            elif autoscope:
                self.report_warning(
                    'The extractor result contains an unscoped cookie as an HTTP header. '
                    'If you are specifying an input URL, ' + bug_reports_message(),
                    only_once=True,
                )
                self._apply_header_cookies(autoscope, [prepared_cookie])
            else:
                self.report_unscoped_cookies()

    def _load_cookies_from_headers(self, headers):
        self._load_cookies(traverse_obj(headers, 'cookie', casesense=False))

    def _apply_header_cookies(self, url, cookies=None):
        """This method applies stray header cookies to the provided url

        This loads header cookies and scopes them to the domain provided in `url`.
        While this is not ideal, it helps reduce the risk of them being sent to
        an unintended destination.
        """
        parsed = compat_urllib_parse.urlparse(url)
        if not parsed.hostname:
            return

        for cookie in map(copy.copy, cookies or self._header_cookies):
            cookie.domain = '.' + parsed.hostname
            self.cookiejar.set_cookie(cookie)

    @__handle_extraction_exceptions
    def __extract_info(self, url, ie, download, extra_info, process):
        # Compat with passing cookies in http headers
        self._apply_header_cookies(url)

        ie_result = ie.extract(url)
        if (
            ie_result is None
        ):  # Finished already (backwards compatibility; listformats and friends should be moved here)
            return

        if isinstance(ie_result, list):
            # Backwards compatibility: old IE result format
            ie_result = {
                '_type': 'compat_list',
                'entries': ie_result,
            }

        self.add_default_extra_info(ie_result, ie, url)
        if process:
            return self.process_ie_result(ie_result, download, extra_info)
        else:
            return ie_result

    def add_default_extra_info(self, ie_result, ie, url):
        self.add_extra_info(
            ie_result,
            {
                'extractor': ie.IE_NAME,
                'webpage_url': url,
                'webpage_url_basename': url_basename(url),
                'extractor_key': ie.ie_key(),
            },
        )

    def process_ie_result(self, ie_result, download=True, extra_info={}):
        """
        Take the result of the ie (may be modified) and resolve all unresolved
        references (URLs, playlist items).

        It will also download the videos if 'download'.
        Returns the resolved ie_result.
        """
        result_type = ie_result.get('_type', 'video')

        if result_type in ('url', 'url_transparent'):
            ie_result['url'] = sanitize_url(ie_result['url'])
            extract_flat = self.params.get('extract_flat', False)
            if (extract_flat == 'in_playlist' and 'playlist' in extra_info) or extract_flat is True:
                self.__forced_printings(ie_result, self.prepare_filename(ie_result), incomplete=True)
                return ie_result

        if result_type == 'video':
            self.add_extra_info(ie_result, extra_info)
            return self.process_video_result(ie_result, download=download)
        elif result_type == 'url':
            # We have to add extra_info to the results because it may be
            # contained in a playlist
            return self.extract_info(ie_result['url'], download, ie_key=ie_result.get('ie_key'), extra_info=extra_info)
        elif result_type == 'url_transparent':
            # Use the information from the embedding page
            info = self.extract_info(
                ie_result['url'], ie_key=ie_result.get('ie_key'), extra_info=extra_info, download=False, process=False
            )

            # extract_info may return None when ignoreerrors is enabled and
            # extraction failed with an error, don't crash and return early
            # in this case
            if not info:
                return info

            force_properties = dict((k, v) for k, v in ie_result.items() if v is not None)
            for f in ('_type', 'url', 'id', 'extractor', 'extractor_key', 'ie_key'):
                force_properties.pop(f, None)
            new_result = info.copy()
            new_result.update(force_properties)

            # Extracted info may not be a video result (i.e.
            # info.get('_type', 'video') != video) but rather an url or
            # url_transparent. In such cases outer metadata (from ie_result)
            # should be propagated to inner one (info). For this to happen
            # _type of info should be overridden with url_transparent. This
            # fixes issue from https://github.com/ytdl-org/youtube-dl/pull/11163.
            if new_result.get('_type') == 'url':
                new_result['_type'] = 'url_transparent'

            return self.process_ie_result(new_result, download=download, extra_info=extra_info)
        elif result_type in ('playlist', 'multi_video'):
            # Protect from infinite recursion due to recursively nested playlists
            # (see https://github.com/ytdl-org/youtube-dl/issues/27833)
            webpage_url = ie_result.get('webpage_url')  # not all pl/mv have this
            if webpage_url and webpage_url in self._playlist_urls:
                self.to_screen(
                    '[download] Skipping already downloaded playlist: {}'.format(ie_result.get('title'))
                    or ie_result.get('id')
                )
                return

            self._playlist_level += 1
            self._playlist_urls.add(webpage_url)
            new_result = dict((k, v) for k, v in extra_info.items() if k not in ie_result)
            if new_result:
                new_result.update(ie_result)
                ie_result = new_result
            try:
                return self.__process_playlist(ie_result, download)
            finally:
                self._playlist_level -= 1
                if not self._playlist_level:
                    self._playlist_urls.clear()
        elif result_type == 'compat_list':
            self.report_warning(
                'Extractor {} returned a compat_list result. It needs to be updated.'.format(ie_result.get('extractor'))
            )

            def _fixup(r):
                self.add_extra_info(
                    r,
                    {
                        'extractor': ie_result['extractor'],
                        'webpage_url': ie_result['webpage_url'],
                        'webpage_url_basename': url_basename(ie_result['webpage_url']),
                        'extractor_key': ie_result['extractor_key'],
                    },
                )
                return r

            ie_result['entries'] = [
                self.process_ie_result(_fixup(r), download, extra_info) for r in ie_result['entries']
            ]
            return ie_result
        else:
            raise Exception(f'Invalid result type: {result_type}')

    def __process_playlist(self, ie_result, download):
        # We process each entry in the playlist
        playlist = ie_result.get('title') or ie_result.get('id')

        self.to_screen(f'[download] Downloading playlist: {playlist}')

        playlist_results = []

        playliststart = self.params.get('playliststart', 1) - 1
        playlistend = self.params.get('playlistend')
        # For backwards compatibility, interpret -1 as whole list
        if playlistend == -1:
            playlistend = None

        playlistitems_str = self.params.get('playlist_items')
        playlistitems = None
        if playlistitems_str is not None:

            def iter_playlistitems(format):
                for string_segment in format.split(','):
                    if '-' in string_segment:
                        start, end = string_segment.split('-')
                        for item in range(int(start), int(end) + 1):
                            yield int(item)
                    else:
                        yield int(string_segment)

            playlistitems = orderedSet(iter_playlistitems(playlistitems_str))

        ie_entries = ie_result['entries']

        def make_playlistitems_entries(list_ie_entries):
            num_entries = len(list_ie_entries)
            return [list_ie_entries[i - 1] for i in playlistitems if -num_entries <= i - 1 < num_entries]

        def report_download(num_entries):
            self.to_screen('[%s] playlist %s: Downloading %d videos' % (ie_result['extractor'], playlist, num_entries))

        if isinstance(ie_entries, list):
            n_all_entries = len(ie_entries)
            if playlistitems:
                entries = make_playlistitems_entries(ie_entries)
            else:
                entries = ie_entries[playliststart:playlistend]
            n_entries = len(entries)
            self.to_screen(
                '[%s] playlist %s: Collected %d video ids (downloading %d of them)'
                % (ie_result['extractor'], playlist, n_all_entries, n_entries)
            )
        elif isinstance(ie_entries, PagedList):
            if playlistitems:
                entries = []
                for item in playlistitems:
                    entries.extend(ie_entries.getslice(item - 1, item))
            else:
                entries = ie_entries.getslice(playliststart, playlistend)
            n_entries = len(entries)
            report_download(n_entries)
        else:  # iterable
            if playlistitems:
                entries = make_playlistitems_entries(list(itertools.islice(ie_entries, 0, max(playlistitems))))
            else:
                entries = list(itertools.islice(ie_entries, playliststart, playlistend))
            n_entries = len(entries)
            report_download(n_entries)

        if self.params.get('playlistreverse', False):
            entries = entries[::-1]

        if self.params.get('playlistrandom', False):
            random.shuffle(entries)

        x_forwarded_for = ie_result.get('__x_forwarded_for_ip')

        for i, entry in enumerate(entries, 1):
            self.to_screen(f'[download] Downloading video {i} of {n_entries}')
            # This __x_forwarded_for_ip thing is a bit ugly but requires
            # minimal changes
            if x_forwarded_for:
                entry['__x_forwarded_for_ip'] = x_forwarded_for
            extra = {
                'n_entries': n_entries,
                'playlist': playlist,
                'playlist_id': ie_result.get('id'),
                'playlist_title': ie_result.get('title'),
                'playlist_uploader': ie_result.get('uploader'),
                'playlist_uploader_id': ie_result.get('uploader_id'),
                'playlist_index': playlistitems[i - 1] if playlistitems else i + playliststart,
                'extractor': ie_result['extractor'],
                'webpage_url': ie_result['webpage_url'],
                'webpage_url_basename': url_basename(ie_result['webpage_url']),
                'extractor_key': ie_result['extractor_key'],
            }

            reason = self._match_entry(entry, incomplete=True)
            if reason is not None:
                self.to_screen('[download] ' + reason)
                continue

            entry_result = self.__process_iterable_entry(entry, download, extra)
            # TODO: skip failed (empty) entries?
            playlist_results.append(entry_result)
        ie_result['entries'] = playlist_results
        self.to_screen(f'[download] Finished downloading playlist: {playlist}')
        return ie_result

    @__handle_extraction_exceptions
    def __process_iterable_entry(self, entry, download, extra_info):
        return self.process_ie_result(entry, download=download, extra_info=extra_info)

    def _build_format_filter(self, filter_spec):
        "Returns a function to filter the formats according to the filter_spec"

        OPERATORS = {
            '<': operator.lt,
            '<=': operator.le,
            '>': operator.gt,
            '>=': operator.ge,
            '=': operator.eq,
            '!=': operator.ne,
        }
        operator_rex = re.compile(
            r"""(?x)\s*
            (?P<key>width|height|tbr|abr|vbr|asr|filesize|filesize_approx|fps)
            \s*(?P<op>{})(?P<none_inclusive>\s*\?)?\s*
            (?P<value>[0-9.]+(?:[kKmMgGtTpPeEzZyY]i?[Bb]?)?)
            $
            """.format('|'.join(map(re.escape, OPERATORS.keys())))
        )
        m = operator_rex.search(filter_spec)
        if m:
            try:
                comparison_value = int(m.group('value'))
            except ValueError:
                comparison_value = parse_filesize(m.group('value'))
                if comparison_value is None:
                    comparison_value = parse_filesize(m.group('value') + 'B')
                if comparison_value is None:
                    raise ValueError(
                        'Invalid value {!r} in format specification {!r}'.format(m.group('value'), filter_spec)
                    )
            op = OPERATORS[m.group('op')]

        if not m:
            STR_OPERATORS = {
                '=': operator.eq,
                '^=': lambda attr, value: attr.startswith(value),
                '$=': lambda attr, value: attr.endswith(value),
                '*=': lambda attr, value: value in attr,
            }
            str_operator_rex = re.compile(
                r"""(?x)
                \s*(?P<key>ext|acodec|vcodec|container|protocol|format_id|language)
                \s*(?P<negation>!\s*)?(?P<op>{})(?P<none_inclusive>\s*\?)?
                \s*(?P<value>[a-zA-Z0-9._-]+)
                \s*$
                """.format('|'.join(map(re.escape, STR_OPERATORS.keys())))
            )
            m = str_operator_rex.search(filter_spec)
            if m:
                comparison_value = m.group('value')
                str_op = STR_OPERATORS[m.group('op')]
                if m.group('negation'):

                    def op(attr, value):
                        return not str_op(attr, value)
                else:
                    op = str_op

        if not m:
            raise ValueError(f'Invalid filter specification {filter_spec!r}')

        def _filter(f):
            actual_value = f.get(m.group('key'))
            if actual_value is None:
                return m.group('none_inclusive')
            return op(actual_value, comparison_value)

        return _filter

    def _default_format_spec(self, info_dict, download=True):
        def can_merge():
            merger = FFmpegMergerPP(self)
            return merger.available and merger.can_merge()

        def prefer_best():
            if self.params.get('simulate', False):
                return False
            if not download:
                return False
            if self.params.get('outtmpl', DEFAULT_OUTTMPL) == '-':
                return True
            if info_dict.get('is_live'):
                return True
            if not can_merge():
                return True
            return False

        req_format_list = ['bestvideo+bestaudio', 'best']
        if prefer_best():
            req_format_list.reverse()
        return '/'.join(req_format_list)

    def build_format_selector(self, format_spec):
        def syntax_error(note, start):
            message = 'Invalid format specification: {}\n\t{}\n\t{}^'.format(note, format_spec, ' ' * start[1])
            return SyntaxError(message)

        PICKFIRST = 'PICKFIRST'
        MERGE = 'MERGE'
        SINGLE = 'SINGLE'
        GROUP = 'GROUP'
        FormatSelector = collections.namedtuple('FormatSelector', ['type', 'selector', 'filters'])

        def _parse_filter(tokens):
            filter_parts = []
            for type, string, start, _, _ in tokens:
                if type == tokenize.OP and string == ']':
                    return ''.join(filter_parts)
                else:
                    filter_parts.append(string)

        def _remove_unused_ops(tokens):
            # Remove operators that we don't use and join them with the surrounding strings
            # for example: 'mp4' '-' 'baseline' '-' '16x9' is converted to 'mp4-baseline-16x9'
            ALLOWED_OPS = ('/', '+', ',', '(', ')')
            last_string, last_start, last_end, last_line = None, None, None, None
            for type, string, start, end, line in tokens:
                if type == tokenize.OP and string == '[':
                    if last_string:
                        yield tokenize.NAME, last_string, last_start, last_end, last_line
                        last_string = None
                    yield type, string, start, end, line
                    # everything inside brackets will be handled by _parse_filter
                    for type, string, start, end, line in tokens:
                        yield type, string, start, end, line
                        if type == tokenize.OP and string == ']':
                            break
                elif type == tokenize.OP and string in ALLOWED_OPS:
                    if last_string:
                        yield tokenize.NAME, last_string, last_start, last_end, last_line
                        last_string = None
                    yield type, string, start, end, line
                elif type in [tokenize.NAME, tokenize.NUMBER, tokenize.OP]:
                    if not last_string:
                        last_string = string
                        last_start = start
                        last_end = end
                    else:
                        last_string += string
            if last_string:
                yield tokenize.NAME, last_string, last_start, last_end, last_line

        def _parse_format_selection(tokens, inside_merge=False, inside_choice=False, inside_group=False):
            selectors = []
            current_selector = None
            for type, string, start, _, _ in tokens:
                # ENCODING is only defined in python 3.x
                if type == getattr(tokenize, 'ENCODING', None):
                    continue
                elif type in [tokenize.NAME, tokenize.NUMBER]:
                    current_selector = FormatSelector(SINGLE, string, [])
                elif type == tokenize.OP:
                    if string == ')':
                        if not inside_group:
                            # ')' will be handled by the parentheses group
                            tokens.restore_last_token()
                        break
                    elif inside_merge and string in ['/', ',']:
                        tokens.restore_last_token()
                        break
                    elif inside_choice and string == ',':
                        tokens.restore_last_token()
                        break
                    elif string == ',':
                        if not current_selector:
                            raise syntax_error('"," must follow a format selector', start)
                        selectors.append(current_selector)
                        current_selector = None
                    elif string == '/':
                        if not current_selector:
                            raise syntax_error('"/" must follow a format selector', start)
                        first_choice = current_selector
                        second_choice = _parse_format_selection(tokens, inside_choice=True)
                        current_selector = FormatSelector(PICKFIRST, (first_choice, second_choice), [])
                    elif string == '[':
                        if not current_selector:
                            current_selector = FormatSelector(SINGLE, 'best', [])
                        format_filter = _parse_filter(tokens)
                        current_selector.filters.append(format_filter)
                    elif string == '(':
                        if current_selector:
                            raise syntax_error('Unexpected "("', start)
                        group = _parse_format_selection(tokens, inside_group=True)
                        current_selector = FormatSelector(GROUP, group, [])
                    elif string == '+':
                        if inside_merge:
                            raise syntax_error('Unexpected "+"', start)
                        video_selector = current_selector
                        audio_selector = _parse_format_selection(tokens, inside_merge=True)
                        if not video_selector or not audio_selector:
                            raise syntax_error('"+" must be between two format selectors', start)
                        current_selector = FormatSelector(MERGE, (video_selector, audio_selector), [])
                    else:
                        raise syntax_error(f'Operator not recognized: "{string}"', start)
                elif type == tokenize.ENDMARKER:
                    break
            if current_selector:
                selectors.append(current_selector)
            return selectors

        def _build_selector_function(selector):
            if isinstance(selector, list):
                fs = [_build_selector_function(s) for s in selector]

                def selector_function(ctx):
                    for f in fs:
                        yield from f(ctx)

                return selector_function
            elif selector.type == GROUP:
                selector_function = _build_selector_function(selector.selector)
            elif selector.type == PICKFIRST:
                fs = [_build_selector_function(s) for s in selector.selector]

                def selector_function(ctx):
                    for f in fs:
                        picked_formats = list(f(ctx))
                        if picked_formats:
                            return picked_formats
                    return []
            elif selector.type == SINGLE:
                format_spec = selector.selector

                def selector_function(ctx):
                    formats = list(ctx['formats'])
                    if not formats:
                        return
                    if format_spec == 'all':
                        yield from formats
                    elif format_spec in ['best', 'worst', None]:
                        format_idx = 0 if format_spec == 'worst' else -1
                        audiovideo_formats = [
                            f for f in formats if f.get('vcodec') != 'none' and f.get('acodec') != 'none'
                        ]
                        if audiovideo_formats:
                            yield audiovideo_formats[format_idx]
                        # for extractors with incomplete formats (audio only (soundcloud)
                        # or video only (imgur)) we will fallback to best/worst
                        # {video,audio}-only format
                        elif ctx['incomplete_formats']:
                            yield formats[format_idx]
                    elif format_spec == 'bestaudio':
                        audio_formats = [f for f in formats if f.get('vcodec') == 'none']
                        if audio_formats:
                            yield audio_formats[-1]
                    elif format_spec == 'worstaudio':
                        audio_formats = [f for f in formats if f.get('vcodec') == 'none']
                        if audio_formats:
                            yield audio_formats[0]
                    elif format_spec == 'bestvideo':
                        video_formats = [f for f in formats if f.get('acodec') == 'none']
                        if video_formats:
                            yield video_formats[-1]
                    elif format_spec == 'worstvideo':
                        video_formats = [f for f in formats if f.get('acodec') == 'none']
                        if video_formats:
                            yield video_formats[0]
                    else:
                        extensions = ['mp4', 'flv', 'webm', '3gp', 'm4a', 'mp3', 'ogg', 'aac', 'wav']
                        if format_spec in extensions:

                            def filter_f(f):
                                return f['ext'] == format_spec
                        else:

                            def filter_f(f):
                                return f['format_id'] == format_spec

                        matches = list(filter(filter_f, formats))
                        if matches:
                            yield matches[-1]
            elif selector.type == MERGE:

                def _merge(formats_info):
                    format_1, format_2 = [f['format_id'] for f in formats_info]
                    # The first format must contain the video and the
                    # second the audio
                    if formats_info[0].get('vcodec') == 'none':
                        self.report_error(
                            f'The first format must contain the video, try using "-f {format_2}+{format_1}"'
                        )
                        return
                    # Formats must be opposite (video+audio)
                    if formats_info[0].get('acodec') == 'none' and formats_info[1].get('acodec') == 'none':
                        self.report_error(
                            f'Both formats {format_1} and {format_2} are video-only, you must specify "-f video+audio"'
                        )
                        return
                    output_ext = (
                        formats_info[0]['ext']
                        if self.params.get('merge_output_format') is None
                        else self.params['merge_output_format']
                    )
                    return {
                        'requested_formats': formats_info,
                        'format': '{}+{}'.format(formats_info[0].get('format'), formats_info[1].get('format')),
                        'format_id': '{}+{}'.format(formats_info[0].get('format_id'), formats_info[1].get('format_id')),
                        'width': formats_info[0].get('width'),
                        'height': formats_info[0].get('height'),
                        'resolution': formats_info[0].get('resolution'),
                        'fps': formats_info[0].get('fps'),
                        'vcodec': formats_info[0].get('vcodec'),
                        'vbr': formats_info[0].get('vbr'),
                        'stretched_ratio': formats_info[0].get('stretched_ratio'),
                        'acodec': formats_info[1].get('acodec'),
                        'abr': formats_info[1].get('abr'),
                        'ext': output_ext,
                    }

                def selector_function(ctx):
                    def selector_fn(x):
                        return _build_selector_function(x)(ctx)

                    for pair in itertools.product(*map(selector_fn, selector.selector)):
                        yield _merge(pair)

            filters = [self._build_format_filter(f) for f in selector.filters]

            def final_selector(ctx):
                ctx_copy = dict(ctx)
                for _filter in filters:
                    ctx_copy['formats'] = list(filter(_filter, ctx_copy['formats']))
                return selector_function(ctx_copy)

            return final_selector

        stream = io.BytesIO(format_spec.encode('utf-8'))
        try:
            tokens = list(_remove_unused_ops(compat_tokenize_tokenize(stream.readline)))
        except tokenize.TokenError:
            raise syntax_error('Missing closing/opening brackets or parenthesis', (0, len(format_spec)))

        class TokenIterator:
            def __init__(self, tokens):
                self.tokens = tokens
                self.counter = 0

            def __iter__(self):
                return self

            def __next__(self):
                if self.counter >= len(self.tokens):
                    raise StopIteration()
                value = self.tokens[self.counter]
                self.counter += 1
                return value

            next = __next__

            def restore_last_token(self):
                self.counter -= 1

        parsed_selector = _parse_format_selection(iter(TokenIterator(tokens)))
        return _build_selector_function(parsed_selector)

    def _calc_headers(self, info_dict, load_cookies=False):
        if load_cookies:  # For --load-info-json
            # load cookies from http_headers in legacy info.json
            self._load_cookies(
                traverse_obj(info_dict, ('http_headers', 'Cookie'), casesense=False), autoscope=info_dict['url']
            )
            # load scoped cookies from info.json
            self._load_cookies(info_dict.get('cookies'), autoscope=False)

        cookies = self.cookiejar.get_cookies_for_url(info_dict['url'])
        if cookies:
            # Make a string like name1=val1; attr1=a_val1; ...name2=val2; ...
            # By convention a cookie name can't be a well-known attribute name
            # so this syntax is unambiguous and can be parsed by (eg) SimpleCookie
            encoder = compat_http_cookies_SimpleCookie()
            values = []
            attributes = (('Domain', '='), ('Path', '='), ('Secure',), ('Expires', '='), ('Version', '='))
            attributes = tuple([x[0].lower(), *list(x)] for x in attributes)
            for cookie in cookies:
                _, value = encoder.value_encode(cookie.value)
                # Py 2 '' --> '', Py 3 '' --> '""'
                if value == '':
                    value = '""'
                values.append('='.join((cookie.name, value)))
                for attr in attributes:
                    value = getattr(cookie, attr[0], None)
                    if value:
                        values.append('{}{}'.format(''.join(attr[1:]), value if len(attr) == 3 else ''))
            info_dict['cookies'] = '; '.join(values)

        res = std_headers.copy()
        res.update(info_dict.get('http_headers') or {})
        res = self._remove_cookie_header(res)

        if 'X-Forwarded-For' not in res:
            x_forwarded_for_ip = info_dict.get('__x_forwarded_for_ip')
            if x_forwarded_for_ip:
                res['X-Forwarded-For'] = x_forwarded_for_ip

        return res or None

    def _calc_cookies(self, info_dict):
        pr = sanitized_Request(info_dict['url'])
        self.cookiejar.add_cookie_header(pr)
        return pr.get_header('Cookie')

    def _fill_common_fields(self, info_dict, final=True):
        for ts_key, date_key in (
            ('timestamp', 'upload_date'),
            ('release_timestamp', 'release_date'),
        ):
            if info_dict.get(date_key) is None and info_dict.get(ts_key) is not None:
                # Working around out-of-range timestamp values (e.g. negative ones on Windows,
                # see http://bugs.python.org/issue1646728)
                try:
                    upload_date = datetime.datetime.utcfromtimestamp(info_dict[ts_key])
                    info_dict[date_key] = compat_str(upload_date.strftime('%Y%m%d'))
                except (ValueError, OverflowError, OSError):
                    pass

        # Auto generate title fields corresponding to the *_number fields when missing
        # in order to always have clean titles. This is very common for TV series.
        if final:
            for field in ('chapter', 'season', 'episode'):
                if info_dict.get(f'{field}_number') is not None and not info_dict.get(field):
                    info_dict[field] = '%s %d' % (field.capitalize(), info_dict[f'{field}_number'])

    def process_video_result(self, info_dict, download=True):
        assert info_dict.get('_type', 'video') == 'video'

        if 'id' not in info_dict:
            raise ExtractorError('Missing "id" field in extractor result')
        if 'title' not in info_dict:
            raise ExtractorError('Missing "title" field in extractor result')

        def report_force_conversion(field, field_not, conversion):
            self.report_warning(
                f'"{field}" field is not {field_not} - forcing {conversion} conversion, there is an error in extractor'
            )

        def sanitize_string_field(info, string_field):
            field = info.get(string_field)
            if field is None or isinstance(field, compat_str):
                return
            report_force_conversion(string_field, 'a string', 'string')
            info[string_field] = compat_str(field)

        def sanitize_numeric_fields(info):
            for numeric_field in self._NUMERIC_FIELDS:
                field = info.get(numeric_field)
                if field is None or isinstance(field, compat_numeric_types):
                    continue
                report_force_conversion(numeric_field, 'numeric', 'int')
                info[numeric_field] = int_or_none(field)

        sanitize_string_field(info_dict, 'id')
        sanitize_numeric_fields(info_dict)

        if 'playlist' not in info_dict:
            # It isn't part of a playlist
            info_dict['playlist'] = None
            info_dict['playlist_index'] = None

        thumbnails = info_dict.get('thumbnails')
        if thumbnails is None:
            thumbnail = info_dict.get('thumbnail')
            if thumbnail:
                info_dict['thumbnails'] = thumbnails = [{'url': thumbnail}]
        if thumbnails:
            thumbnails.sort(
                key=lambda t: (
                    t.get('preference') if t.get('preference') is not None else -1,
                    t.get('width') if t.get('width') is not None else -1,
                    t.get('height') if t.get('height') is not None else -1,
                    t.get('id') if t.get('id') is not None else '',
                    t.get('url'),
                )
            )
            for i, t in enumerate(thumbnails):
                t['url'] = sanitize_url(t['url'])
                if t.get('width') and t.get('height'):
                    t['resolution'] = '%dx%d' % (t['width'], t['height'])
                if t.get('id') is None:
                    t['id'] = '%d' % i

        if self.params.get('list_thumbnails'):
            self.list_thumbnails(info_dict)
            return

        thumbnail = info_dict.get('thumbnail')
        if thumbnail:
            info_dict['thumbnail'] = sanitize_url(thumbnail)
        elif thumbnails:
            info_dict['thumbnail'] = thumbnails[-1]['url']

        if 'display_id' not in info_dict and 'id' in info_dict:
            info_dict['display_id'] = info_dict['id']

        self._fill_common_fields(info_dict)

        for cc_kind in ('subtitles', 'automatic_captions'):
            cc = info_dict.get(cc_kind)
            if cc:
                for _, subtitle in cc.items():
                    for subtitle_format in subtitle:
                        if subtitle_format.get('url'):
                            subtitle_format['url'] = sanitize_url(subtitle_format['url'])
                        if subtitle_format.get('ext') is None:
                            subtitle_format['ext'] = determine_ext(subtitle_format['url']).lower()

        automatic_captions = info_dict.get('automatic_captions')
        subtitles = info_dict.get('subtitles')

        if self.params.get('listsubtitles', False):
            if 'automatic_captions' in info_dict:
                self.list_subtitles(info_dict['id'], automatic_captions, 'automatic captions')
            self.list_subtitles(info_dict['id'], subtitles, 'subtitles')
            return

        info_dict['requested_subtitles'] = self.process_subtitles(info_dict['id'], subtitles, automatic_captions)

        # We now pick which formats have to be downloaded
        if info_dict.get('formats') is None:
            # There's only one format available
            formats = [info_dict]
        else:
            formats = info_dict['formats']

        def is_wellformed(f):
            url = f.get('url')
            if not url:
                self.report_warning('"url" field is missing or empty - skipping format, there is an error in extractor')
                return False
            if isinstance(url, bytes):
                sanitize_string_field(f, 'url')
            return True

        # Filter out malformed formats for better extraction robustness
        formats = list(filter(is_wellformed, formats or []))

        if not formats:
            raise ExtractorError('No video formats found!')

        formats_dict = {}

        # We check that all the formats have the format and format_id fields
        for i, format in enumerate(formats):
            sanitize_string_field(format, 'format_id')
            sanitize_numeric_fields(format)
            format['url'] = sanitize_url(format['url'])
            if not format.get('format_id'):
                format['format_id'] = compat_str(i)
            else:
                # Sanitize format_id from characters used in format selector expression
                format['format_id'] = re.sub(r'[\s,/+\[\]()]', '_', format['format_id'])
            format_id = format['format_id']
            if format_id not in formats_dict:
                formats_dict[format_id] = []
            formats_dict[format_id].append(format)

        # Make sure all formats have unique format_id
        for format_id, ambiguous_formats in formats_dict.items():
            if len(ambiguous_formats) > 1:
                for i, format in enumerate(ambiguous_formats):
                    format['format_id'] = '%s-%d' % (format_id, i)

        for i, format in enumerate(formats):
            if format.get('format') is None:
                format['format'] = '{id} - {res}{note}'.format(
                    id=format['format_id'],
                    res=self.format_resolution(format),
                    note=' ({})'.format(format['format_note']) if format.get('format_note') is not None else '',
                )
            # Automatically determine file extension if missing
            if format.get('ext') is None:
                format['ext'] = determine_ext(format['url']).lower()
            # Automatically determine protocol if missing (useful for format
            # selection purposes)
            if format.get('protocol') is None:
                format['protocol'] = determine_protocol(format)
            # Add HTTP headers, so that external programs can use them from the
            # json output
            format['http_headers'] = self._calc_headers(ChainMap(format, info_dict), load_cookies=True)

        # Safeguard against old/insecure infojson when using --load-info-json
        info_dict['http_headers'] = self._remove_cookie_header(info_dict.get('http_headers') or {}) or None

        # Remove private housekeeping stuff (copied to http_headers in _calc_headers())
        if '__x_forwarded_for_ip' in info_dict:
            del info_dict['__x_forwarded_for_ip']

        # TODO Central sorting goes here

        if formats[0] is not info_dict:
            # only set the 'formats' fields if the original info_dict list them
            # otherwise we end up with a circular reference, the first (and unique)
            # element in the 'formats' field in info_dict is info_dict itself,
            # which can't be exported to json
            info_dict['formats'] = formats
        if self.params.get('listformats'):
            self.list_formats(info_dict)
            return

        req_format = self.params.get('format')
        if req_format is None:
            req_format = self._default_format_spec(info_dict, download=download)
            if self.params.get('verbose'):
                self._write_string(f'[debug] Default format spec: {req_format}\n')

        format_selector = self.build_format_selector(req_format)

        # While in format selection we may need to have an access to the original
        # format set in order to calculate some metrics or do some processing.
        # For now we need to be able to guess whether original formats provided
        # by extractor are incomplete or not (i.e. whether extractor provides only
        # video-only or audio-only formats) for proper formats selection for
        # extractors with such incomplete formats (see
        # https://github.com/ytdl-org/youtube-dl/pull/5556).
        # Since formats may be filtered during format selection and may not match
        # the original formats the results may be incorrect. Thus original formats
        # or pre-calculated metrics should be passed to format selection routines
        # as well.
        # We will pass a context object containing all necessary additional data
        # instead of just formats.
        # This fixes incorrect format selection issue (see
        # https://github.com/ytdl-org/youtube-dl/issues/10083).
        incomplete_formats = (
            # All formats are video-only or
            all(f.get('vcodec') != 'none' and f.get('acodec') == 'none' for f in formats)
            # all formats are audio-only
            or all(f.get('vcodec') == 'none' and f.get('acodec') != 'none' for f in formats)
        )

        ctx = {
            'formats': formats,
            'incomplete_formats': incomplete_formats,
        }

        formats_to_download = list(format_selector(ctx))
        if not formats_to_download:
            raise ExtractorError('requested format not available', expected=True)

        if download:
            if len(formats_to_download) > 1:
                self.to_screen(
                    '[info] {}: downloading video in {} formats'.format(info_dict['id'], len(formats_to_download))
                )
            for format in formats_to_download:
                new_info = dict(info_dict)
                new_info.update(format)
                self.process_info(new_info)
        # We update the info dict with the best quality format (backwards compatibility)
        info_dict.update(formats_to_download[-1])
        return info_dict

    def process_subtitles(self, video_id, normal_subtitles, automatic_captions):
        """Select the requested subtitles and their format"""
        available_subs = {}
        if normal_subtitles and self.params.get('writesubtitles'):
            available_subs.update(normal_subtitles)
        if automatic_captions and self.params.get('writeautomaticsub'):
            for lang, cap_info in automatic_captions.items():
                if lang not in available_subs:
                    available_subs[lang] = cap_info

        if (not self.params.get('writesubtitles') and not self.params.get('writeautomaticsub')) or not available_subs:
            return None

        if self.params.get('allsubtitles', False):
            requested_langs = available_subs.keys()
        else:
            if self.params.get('subtitleslangs', False):
                requested_langs = self.params.get('subtitleslangs')
            elif 'en' in available_subs:
                requested_langs = ['en']
            else:
                requested_langs = [next(iter(available_subs.keys()))]

        formats_query = self.params.get('subtitlesformat', 'best')
        formats_preference = formats_query.split('/') if formats_query else []
        subs = {}
        for lang in requested_langs:
            formats = available_subs.get(lang)
            if formats is None:
                self.report_warning(f'{lang} subtitles not available for {video_id}')
                continue
            for ext in formats_preference:
                if ext == 'best':
                    f = formats[-1]
                    break
                matches = list(filter(lambda f: f['ext'] == ext, formats))
                if matches:
                    f = matches[-1]
                    break
            else:
                f = formats[-1]
                self.report_warning(
                    'No subtitle format found matching "{}" for language {}, using {}'.format(
                        formats_query, lang, f['ext']
                    )
                )
            subs[lang] = f
        return subs

    def __forced_printings(self, info_dict, filename, incomplete):
        def print_mandatory(field):
            if self.params.get(f'force{field}', False) and (not incomplete or info_dict.get(field) is not None):
                self.to_stdout(info_dict[field])

        def print_optional(field):
            if self.params.get(f'force{field}', False) and info_dict.get(field) is not None:
                self.to_stdout(info_dict[field])

        print_mandatory('title')
        print_mandatory('id')
        if self.params.get('forceurl', False) and not incomplete:
            if info_dict.get('requested_formats') is not None:
                for f in info_dict['requested_formats']:
                    self.to_stdout(f['url'] + f.get('play_path', ''))
            else:
                # For RTMP URLs, also include the playpath
                self.to_stdout(info_dict['url'] + info_dict.get('play_path', ''))
        print_optional('thumbnail')
        print_optional('description')
        if self.params.get('forcefilename', False) and filename is not None:
            self.to_stdout(filename)
        if self.params.get('forceduration', False) and info_dict.get('duration') is not None:
            self.to_stdout(formatSeconds(info_dict['duration']))
        print_mandatory('format')
        if self.params.get('forcejson', False):
            self.to_stdout(json.dumps(self.sanitize_info(info_dict)))

    @_catch_unsafe_file_extension
    def process_info(self, info_dict):
        """Process a single resolved IE result."""

        assert info_dict.get('_type', 'video') == 'video'

        max_downloads = int_or_none(self.params.get('max_downloads')) or float('inf')
        if self._num_downloads >= max_downloads:
            raise MaxDownloadsReached()

        # TODO: backward compatibility, to be removed
        info_dict['fulltitle'] = info_dict['title']

        if 'format' not in info_dict:
            info_dict['format'] = info_dict['ext']

        reason = self._match_entry(info_dict, incomplete=False)
        if reason is not None:
            self.to_screen('[download] ' + reason)
            return

        self._num_downloads += 1

        info_dict['_filename'] = filename = self.prepare_filename(info_dict)

        # Forced printings
        self.__forced_printings(info_dict, filename, incomplete=False)

        # Do nothing else if in simulate mode
        if self.params.get('simulate', False):
            return

        if filename is None:
            return

        def ensure_dir_exists(path):
            try:
                dn = os.path.dirname(path)
                if dn and not os.path.exists(dn):
                    os.makedirs(dn)
                return True
            except OSError as err:
                if isinstance(err, OSError) and err.errno == errno.EEXIST:
                    return True
                self.report_error('unable to create directory ' + error_to_compat_str(err))
                return False

        if not ensure_dir_exists(sanitize_path(encodeFilename(filename))):
            return

        if self.params.get('writedescription', False):
            descfn = replace_extension(filename, 'description', info_dict.get('ext'))
            if self.params.get('nooverwrites', False) and os.path.exists(encodeFilename(descfn)):
                self.to_screen('[info] Video description is already present')
            elif info_dict.get('description') is None:
                self.report_warning("There's no description to write.")
            else:
                try:
                    self.to_screen('[info] Writing video description to: ' + descfn)
                    with open(encodeFilename(descfn), 'w', encoding='utf-8') as descfile:
                        descfile.write(info_dict['description'])
                except OSError:
                    self.report_error('Cannot write description file ' + descfn)
                    return

        if self.params.get('writeannotations', False):
            annofn = replace_extension(filename, 'annotations.xml', info_dict.get('ext'))
            if self.params.get('nooverwrites', False) and os.path.exists(encodeFilename(annofn)):
                self.to_screen('[info] Video annotations are already present')
            elif not info_dict.get('annotations'):
                self.report_warning('There are no annotations to write.')
            else:
                try:
                    self.to_screen('[info] Writing video annotations to: ' + annofn)
                    with open(encodeFilename(annofn), 'w', encoding='utf-8') as annofile:
                        annofile.write(info_dict['annotations'])
                except (KeyError, TypeError):
                    self.report_warning('There are no annotations to write.')
                except OSError:
                    self.report_error('Cannot write annotations file: ' + annofn)
                    return

        subtitles_are_requested = any([self.params.get('writesubtitles', False), self.params.get('writeautomaticsub')])

        if subtitles_are_requested and info_dict.get('requested_subtitles'):
            # subtitles download errors are already managed as troubles in relevant IE
            # that way it will silently go on when used with unsupporting IE
            subtitles = info_dict['requested_subtitles']
            ie = self.get_info_extractor(info_dict['extractor_key'])
            for sub_lang, sub_info in subtitles.items():
                sub_format = sub_info['ext']
                sub_filename = subtitles_filename(filename, sub_lang, sub_format, info_dict.get('ext'))
                if self.params.get('nooverwrites', False) and os.path.exists(encodeFilename(sub_filename)):
                    self.to_screen(f'[info] Video subtitle {sub_lang}.{sub_format} is already present')
                else:
                    self.to_screen('[info] Writing video subtitles to: ' + sub_filename)
                    if sub_info.get('data') is not None:
                        try:
                            # Use newline='' to prevent conversion of newline characters
                            # See https://github.com/ytdl-org/youtube-dl/issues/10268
                            with open(encodeFilename(sub_filename), 'w', encoding='utf-8', newline='') as subfile:
                                subfile.write(sub_info['data'])
                        except OSError:
                            self.report_error('Cannot write subtitles file ' + sub_filename)
                            return
                    else:
                        try:
                            sub_data = ie._request_webpage(sub_info['url'], info_dict['id'], note=False).read()
                            with open(encodeFilename(sub_filename), 'wb') as subfile:
                                subfile.write(sub_data)
                        except (ExtractorError, OSError, ValueError) as err:
                            self.report_warning(
                                f'Unable to download subtitle for "{sub_lang}": {error_to_compat_str(err)}'
                            )
                            continue

        self._write_info_json(
            'video description', info_dict, replace_extension(filename, 'info.json', info_dict.get('ext'))
        )

        self._write_thumbnails(info_dict, filename)

        if not self.params.get('skip_download', False):
            try:

                def checked_get_suitable_downloader(info_dict, params):
                    ed_args = params.get('external_downloader_args')
                    dler = get_suitable_downloader(info_dict, params)
                    if ed_args and not params.get('external_downloader_args'):
                        # external_downloader_args was cleared because external_downloader was rejected
                        self.report_warning(
                            'Requested external downloader cannot be used: ignoring --external-downloader-args.'
                        )
                    return dler

                def dl(name, info):
                    fd = checked_get_suitable_downloader(info, self.params)(self, self.params)
                    for ph in self._progress_hooks:
                        fd.add_progress_hook(ph)
                    if self.params.get('verbose'):
                        self.to_screen('[debug] Invoking downloader on {!r}'.format(info.get('url')))

                    new_info = dict((k, v) for k, v in info.items() if not k.startswith('__p'))
                    new_info['http_headers'] = self._calc_headers(new_info)

                    return fd.download(name, new_info)

                if info_dict.get('requested_formats') is not None:
                    downloaded = []
                    success = True
                    merger = FFmpegMergerPP(self)
                    if not merger.available:
                        postprocessors = []
                        self.report_warning(
                            'You have requested multiple '
                            'formats but ffmpeg or avconv are not installed.'
                            " The formats won't be merged."
                        )
                    else:
                        postprocessors = [merger]

                    def compatible_formats(formats):
                        video, audio = formats
                        # Check extension
                        video_ext, audio_ext = video.get('ext'), audio.get('ext')
                        if video_ext and audio_ext:
                            COMPATIBLE_EXTS = (
                                ('mp3', 'mp4', 'm4a', 'm4p', 'm4b', 'm4r', 'm4v', 'ismv', 'isma'),
                                ('webm'),
                            )
                            for exts in COMPATIBLE_EXTS:
                                if video_ext in exts and audio_ext in exts:
                                    return True
                        # TODO: Check acodec/vcodec
                        return False

                    exts = [info_dict['ext']]
                    requested_formats = info_dict['requested_formats']
                    if self.params.get('merge_output_format') is None and not compatible_formats(requested_formats):
                        info_dict['ext'] = 'mkv'
                        self.report_warning('Requested formats are incompatible for merge and will be merged into mkv.')
                    exts.append(info_dict['ext'])

                    # Ensure filename always has a correct extension for successful merge
                    def correct_ext(filename, ext=exts[1]):
                        if filename == '-':
                            return filename
                        f_name, f_real_ext = os.path.splitext(filename)
                        f_real_ext = f_real_ext[1:]
                        filename_wo_ext = f_name if f_real_ext in exts else filename
                        if ext is None:
                            ext = f_real_ext or None
                        return join_nonempty(filename_wo_ext, ext, delim='.')

                    filename = correct_ext(filename)
                    if os.path.exists(encodeFilename(filename)):
                        self.to_screen(f'[download] {filename} has already been downloaded and merged')
                    else:
                        for f in requested_formats:
                            new_info = dict(info_dict)
                            new_info.update(f)
                            fname = prepend_extension(
                                correct_ext(self.prepare_filename(new_info), new_info['ext']),
                                'f{}'.format(f['format_id']),
                                new_info['ext'],
                            )
                            if not ensure_dir_exists(fname):
                                return
                            downloaded.append(fname)
                            partial_success = dl(fname, new_info)
                            success = success and partial_success
                        info_dict['__postprocessors'] = postprocessors
                        info_dict['__files_to_merge'] = downloaded
                else:
                    # Just a single file
                    success = dl(filename, info_dict)
            except (OSError, compat_urllib_error.URLError, compat_http_client.HTTPException) as err:
                self.report_error(f'unable to download video data: {error_to_compat_str(err)}')
                return
            except OSError as err:
                raise UnavailableVideoError(err)
            except (ContentTooShortError,) as err:
                self.report_error(f'content too short (expected {err.expected} bytes and served {err.downloaded})')
                return

            if success and filename != '-':
                # Fixup content
                fixup_policy = self.params.get('fixup')
                if fixup_policy is None:
                    fixup_policy = 'detect_or_warn'

                INSTALL_FFMPEG_MESSAGE = 'Install ffmpeg or avconv to fix this automatically.'

                stretched_ratio = info_dict.get('stretched_ratio')
                if stretched_ratio is not None and stretched_ratio != 1:
                    if fixup_policy == 'warn':
                        self.report_warning('{}: Non-uniform pixel ratio ({})'.format(info_dict['id'], stretched_ratio))
                    elif fixup_policy == 'detect_or_warn':
                        stretched_pp = FFmpegFixupStretchedPP(self)
                        if stretched_pp.available:
                            info_dict.setdefault('__postprocessors', [])
                            info_dict['__postprocessors'].append(stretched_pp)
                        else:
                            self.report_warning(
                                '{}: Non-uniform pixel ratio ({}). {}'.format(
                                    info_dict['id'], stretched_ratio, INSTALL_FFMPEG_MESSAGE
                                )
                            )
                    else:
                        assert fixup_policy in ('ignore', 'never')

                if info_dict.get('requested_formats') is None and info_dict.get('container') == 'm4a_dash':
                    if fixup_policy == 'warn':
                        self.report_warning(
                            '{}: writing DASH m4a. Only some players support this container.'.format(info_dict['id'])
                        )
                    elif fixup_policy == 'detect_or_warn':
                        fixup_pp = FFmpegFixupM4aPP(self)
                        if fixup_pp.available:
                            info_dict.setdefault('__postprocessors', [])
                            info_dict['__postprocessors'].append(fixup_pp)
                        else:
                            self.report_warning(
                                '{}: writing DASH m4a. Only some players support this container. {}'.format(
                                    info_dict['id'], INSTALL_FFMPEG_MESSAGE
                                )
                            )
                    else:
                        assert fixup_policy in ('ignore', 'never')

                if info_dict.get('protocol') == 'm3u8_native' or (
                    info_dict.get('protocol') == 'm3u8' and self.params.get('hls_prefer_native')
                ):
                    if fixup_policy == 'warn':
                        self.report_warning('{}: malformed AAC bitstream detected.'.format(info_dict['id']))
                    elif fixup_policy == 'detect_or_warn':
                        fixup_pp = FFmpegFixupM3u8PP(self)
                        if fixup_pp.available:
                            info_dict.setdefault('__postprocessors', [])
                            info_dict['__postprocessors'].append(fixup_pp)
                        else:
                            self.report_warning(
                                '{}: malformed AAC bitstream detected. {}'.format(
                                    info_dict['id'], INSTALL_FFMPEG_MESSAGE
                                )
                            )
                    else:
                        assert fixup_policy in ('ignore', 'never')

                try:
                    self.post_process(filename, info_dict)
                except PostProcessingError as err:
                    self.report_error(f'postprocessing: {error_to_compat_str(err)}')
                    return
                self.record_download_archive(info_dict)
                # avoid possible nugatory search for further items (PR #26638)
                if self._num_downloads >= max_downloads:
                    raise MaxDownloadsReached()

    def download(self, url_list):
        """Download a given list of URLs."""
        outtmpl = self.params.get('outtmpl', DEFAULT_OUTTMPL)
        if len(url_list) > 1 and outtmpl != '-' and '%' not in outtmpl and self.params.get('max_downloads') != 1:
            raise SameFileError(outtmpl)

        for url in url_list:
            try:
                # It also downloads the videos
                res = self.extract_info(url)
            except UnavailableVideoError:
                self.report_error('unable to download video')
            except MaxDownloadsReached:
                self.to_screen('[info] Maximum number of downloaded files reached.')
                raise
            else:
                if self.params.get('dump_single_json', False):
                    self.to_stdout(json.dumps(self.sanitize_info(res)))

        return self._download_retcode

    def download_with_info_file(self, info_filename):
        with open(info_filename, encoding='utf-8') as f:
            info = self.filter_requested_info(json.load(f))
        try:
            self.process_ie_result(info, download=True)
        except DownloadError:
            webpage_url = info.get('webpage_url')
            if webpage_url is not None:
                self.report_warning(f'The info failed to download, trying with "{webpage_url}"')
                return self.download([webpage_url])
            else:
                raise
        return self._download_retcode

    @staticmethod
    def sanitize_info(info_dict, remove_private_keys=False):
        """Sanitize the infodict for converting to json"""
        if info_dict is None:
            return info_dict

        if remove_private_keys:

            def reject(k, v):
                return v is None or k.startswith('__') or k in ('requested_formats', 'requested_subtitles')
        else:

            def reject(k, v):
                return False

        def filter_fn(obj):
            if isinstance(obj, dict):
                return dict((k, filter_fn(v)) for k, v in obj.items() if not reject(k, v))
            elif isinstance(obj, (list, tuple, set, LazyList)):
                return list(map(filter_fn, obj))
            elif obj is None or any(isinstance(obj, c) for c in (compat_integer_types, (compat_str, float, bool))):
                return obj
            else:
                return repr(obj)

        return filter_fn(info_dict)

    @classmethod
    def filter_requested_info(cls, info_dict):
        return cls.sanitize_info(info_dict, True)

    def post_process(self, filename, ie_info):
        """Run all the postprocessors on the given file."""
        info = dict(ie_info)
        info['filepath'] = filename
        pps_chain = []
        if ie_info.get('__postprocessors') is not None:
            pps_chain.extend(ie_info['__postprocessors'])
        pps_chain.extend(self._pps)
        for pp in pps_chain:
            files_to_delete = []
            try:
                files_to_delete, info = pp.run(info)
            except PostProcessingError as e:
                self.report_error(e.msg)
            if files_to_delete and not self.params.get('keepvideo', False):
                for old_filename in files_to_delete:
                    self.to_screen(f'Deleting original file {old_filename} (pass -k to keep)')
                    try:
                        os.remove(encodeFilename(old_filename))
                    except OSError:
                        self.report_warning('Unable to remove downloaded original file')

    def _make_archive_id(self, info_dict):
        video_id = info_dict.get('id')
        if not video_id:
            return
        # Future-proof against any change in case
        # and backwards compatibility with prior versions
        extractor = info_dict.get('extractor_key') or info_dict.get('ie_key')  # key in a playlist
        if extractor is None:
            url = str_or_none(info_dict.get('url'))
            if not url:
                return
            # Try to find matching extractor for the URL and take its ie_key
            for ie in self._ies:
                if ie.suitable(url):
                    extractor = ie.ie_key()
                    break
            else:
                return
        return extractor.lower() + ' ' + video_id

    def in_download_archive(self, info_dict):
        fn = self.params.get('download_archive')
        if fn is None:
            return False

        vid_id = self._make_archive_id(info_dict)
        if not vid_id:
            return False  # Incomplete video information

        try:
            with locked_file(fn, 'r', encoding='utf-8') as archive_file:
                for line in archive_file:
                    if line.strip() == vid_id:
                        return True
        except OSError as ioe:
            if ioe.errno != errno.ENOENT:
                raise
        return False

    def record_download_archive(self, info_dict):
        fn = self.params.get('download_archive')
        if fn is None:
            return
        vid_id = self._make_archive_id(info_dict)
        assert vid_id
        with locked_file(fn, 'a', encoding='utf-8') as archive_file:
            archive_file.write(vid_id + '\n')

    @staticmethod
    def format_resolution(format, default='unknown'):
        if format.get('vcodec') == 'none':
            return 'audio only'
        if format.get('resolution') is not None:
            return format['resolution']
        if format.get('height') is not None:
            if format.get('width') is not None:
                res = '{}x{}'.format(format['width'], format['height'])
            else:
                res = '{}p'.format(format['height'])
        elif format.get('width') is not None:
            res = '%dx?' % format['width']
        else:
            res = default
        return res

    def _format_note(self, fdict):
        res = ''
        if fdict.get('ext') in ['f4f', 'f4m']:
            res += '(unsupported) '
        if fdict.get('language'):
            if res:
                res += ' '
            res += '[{}] '.format(fdict['language'])
        if fdict.get('format_note') is not None:
            res += fdict['format_note'] + ' '
        if fdict.get('tbr') is not None:
            res += '%4dk ' % fdict['tbr']
        if fdict.get('container') is not None:
            if res:
                res += ', '
            res += '{} container'.format(fdict['container'])
        if fdict.get('vcodec') is not None and fdict.get('vcodec') != 'none':
            if res:
                res += ', '
            res += fdict['vcodec']
            if fdict.get('vbr') is not None:
                res += '@'
        elif fdict.get('vbr') is not None and fdict.get('abr') is not None:
            res += 'video@'
        if fdict.get('vbr') is not None:
            res += '%4dk' % fdict['vbr']
        if fdict.get('fps') is not None:
            if res:
                res += ', '
            res += '{}fps'.format(fdict['fps'])
        if fdict.get('acodec') is not None:
            if res:
                res += ', '
            if fdict['acodec'] == 'none':
                res += 'video only'
            else:
                res += '%-5s' % fdict['acodec']
        elif fdict.get('abr') is not None:
            if res:
                res += ', '
            res += 'audio'
        if fdict.get('abr') is not None:
            res += '@%3dk' % fdict['abr']
        if fdict.get('asr') is not None:
            res += ' (%5dHz)' % fdict['asr']
        if fdict.get('filesize') is not None:
            if res:
                res += ', '
            res += format_bytes(fdict['filesize'])
        elif fdict.get('filesize_approx') is not None:
            if res:
                res += ', '
            res += '~' + format_bytes(fdict['filesize_approx'])
        return res

    def list_formats(self, info_dict):
        formats = info_dict.get('formats', [info_dict])
        table = [
            [f['format_id'], f['ext'], self.format_resolution(f), self._format_note(f)]
            for f in formats
            if f.get('preference') is None or f['preference'] >= -1000
        ]
        if len(formats) > 1:
            table[-1][-1] += (' ' if table[-1][-1] else '') + '(best)'

        header_line = ['format code', 'extension', 'resolution', 'note']
        self.to_screen('[info] Available formats for {}:\n{}'.format(info_dict['id'], render_table(header_line, table)))

    def list_thumbnails(self, info_dict):
        thumbnails = info_dict.get('thumbnails')
        if not thumbnails:
            self.to_screen('[info] No thumbnails present for {}'.format(info_dict['id']))
            return

        self.to_screen('[info] Thumbnails for {}:'.format(info_dict['id']))
        self.to_screen(
            render_table(
                ['ID', 'width', 'height', 'URL'],
                [[t['id'], t.get('width', 'unknown'), t.get('height', 'unknown'), t['url']] for t in thumbnails],
            )
        )

    def list_subtitles(self, video_id, subtitles, name='subtitles'):
        if not subtitles:
            self.to_screen(f'{video_id} has no {name}')
            return
        self.to_screen(f'Available {name} for {video_id}:')
        self.to_screen(
            render_table(
                ['Language', 'formats'],
                [[lang, ', '.join(f['ext'] for f in reversed(formats))] for lang, formats in subtitles.items()],
            )
        )

    def urlopen(self, req):
        """Start an HTTP download"""
        if isinstance(req, compat_basestring):
            req = sanitized_Request(req)
        return self._opener.open(req, timeout=self._socket_timeout)

    def print_debug_header(self):
        if not self.params.get('verbose'):
            return

        if str is not compat_str:
            # Python 2.6 on SLES11 SP1 (https://github.com/ytdl-org/youtube-dl/issues/3326)
            self.report_warning('Your Python is broken! Update to a newer and supported version')

        stdout_encoding = getattr(sys.stdout, 'encoding', f'missing ({type(sys.stdout).__name__})')
        encoding_str = f'[debug] Encodings: locale {locale.getpreferredencoding()}, fs {sys.getfilesystemencoding()}, out {stdout_encoding}, pref {self.get_encoding()}\n'
        write_string(encoding_str, encoding=None)

        def writeln_debug(*s):
            return self.write_debug(''.join(s))

        writeln_debug('youtube-dl version ', __version__)
        if ytdl_is_updateable():
            writeln_debug('Single file build')
        try:
            sp = subprocess.Popen(
                ['git', 'rev-parse', '--short', 'HEAD'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=os.path.dirname(os.path.abspath(__file__)),
            )
            out, err = process_communicate_or_kill(sp)
            out = out.decode().strip()
            if re.match('[0-9a-f]+', out):
                writeln_debug('Git HEAD: ', out)
        except Exception:
            try:
                sys.exc_clear()
            except Exception:
                pass

        def python_implementation():
            impl_name = platform.python_implementation()
            if impl_name == 'PyPy' and hasattr(sys, 'pypy_version_info'):
                return impl_name + ' version %d.%d.%d' % sys.pypy_version_info[:3]
            return impl_name

        def libc_ver():
            try:
                return platform.libc_ver()
            except OSError:  # We may not have access to the executable
                return []

        libc = join_nonempty(*libc_ver(), delim=' ')
        writeln_debug(
            'Python {} ({} {} {}) - {} - {}{}'.format(
                platform.python_version(),
                python_implementation(),
                platform.machine(),
                platform.architecture()[0],
                platform_name(),
                OPENSSL_VERSION,
                (f' - {libc}') if libc else '',
            )
        )

        exe_versions = FFmpegPostProcessor.get_versions(self)
        exe_versions['rtmpdump'] = rtmpdump_version()
        exe_str = ', '.join(f'{exe} {v}' for exe, v in sorted(exe_versions.items()) if v)
        if not exe_str:
            exe_str = 'none'
        writeln_debug(f'exe versions: {exe_str}')

        proxy_map = {}
        for handler in self._opener.handlers:
            if hasattr(handler, 'proxies'):
                proxy_map.update(handler.proxies)
        writeln_debug('Proxy map: ', compat_str(proxy_map))

        if self.params.get('call_home', False):
            ipaddr = self.urlopen('https://yt-dl.org/ip').read().decode('utf-8')
            writeln_debug(f'Public IP address: {ipaddr}')
            latest_version = self.urlopen('https://yt-dl.org/latest/version').read().decode('utf-8')
            if version_tuple(latest_version) > version_tuple(__version__):
                self.report_warning(
                    f'You are using an outdated version (newest version: {latest_version})! '
                    'See https://yt-dl.org/update if you need help updating.'
                )

    def _setup_opener(self):
        timeout_val = self.params.get('socket_timeout')
        self._socket_timeout = 600 if timeout_val is None else float(timeout_val)

        opts_cookiefile = self.params.get('cookiefile')
        opts_proxy = self.params.get('proxy')

        if opts_cookiefile is None:
            self.cookiejar = YoutubeDLCookieJar()
        else:
            opts_cookiefile = expand_path(opts_cookiefile)
            self.cookiejar = YoutubeDLCookieJar(opts_cookiefile)
            if os.access(opts_cookiefile, os.R_OK):
                self.cookiejar.load(ignore_discard=True, ignore_expires=True)

        cookie_processor = YoutubeDLCookieProcessor(self.cookiejar)
        if opts_proxy is not None:
            if opts_proxy == '':
                proxies = {}
            else:
                proxies = {'http': opts_proxy, 'https': opts_proxy}
        else:
            proxies = compat_urllib_request.getproxies()
            # Set HTTPS proxy to HTTP one if given (https://github.com/ytdl-org/youtube-dl/issues/805)
            if 'http' in proxies and 'https' not in proxies:
                proxies['https'] = proxies['http']
        proxy_handler = PerRequestProxyHandler(proxies)

        debuglevel = 1 if self.params.get('debug_printtraffic') else 0
        https_handler = make_HTTPS_handler(self.params, debuglevel=debuglevel)
        ydlh = YoutubeDLHandler(self.params, debuglevel=debuglevel)
        redirect_handler = YoutubeDLRedirectHandler()
        data_handler = compat_urllib_request_DataHandler()

        # When passing our own FileHandler instance, build_opener won't add the
        # default FileHandler and allows us to disable the file protocol, which
        # can be used for malicious purposes (see
        # https://github.com/ytdl-org/youtube-dl/issues/8227)
        file_handler = compat_urllib_request.FileHandler()

        def file_open(*args, **kwargs):
            raise compat_urllib_error.URLError(
                'file:// scheme is explicitly disabled in youtube-dl for security reasons'
            )

        file_handler.file_open = file_open

        opener = compat_urllib_request.build_opener(
            proxy_handler, https_handler, cookie_processor, ydlh, redirect_handler, data_handler, file_handler
        )

        # Delete the default user-agent header, which would otherwise apply in
        # cases where our custom HTTP handler doesn't come into play
        # (See https://github.com/ytdl-org/youtube-dl/issues/1309 for details)
        opener.addheaders = []
        self._opener = opener

    def encode(self, s):
        if isinstance(s, bytes):
            return s  # Already encoded

        try:
            return s.encode(self.get_encoding())
        except UnicodeEncodeError as err:
            err.reason = err.reason + '. Check your system encoding configuration or use the --encoding option.'
            raise

    def get_encoding(self):
        encoding = self.params.get('encoding')
        if encoding is None:
            encoding = preferredencoding()
        return encoding

    def _write_info_json(
        self,
        label: str,
        info_dict: dict[str, Any],
        infofn: str,
        overwrite: bool | None = None,
    ) -> bool | str | None:
        if not self.params.get('writeinfojson', False):
            return False

        def msg(fmt, lbl):
            return fmt % (lbl + ' metadata',)

        if overwrite is None:
            overwrite = not self.params.get('nooverwrites', False)

        if not overwrite and os.path.exists(encodeFilename(infofn)):
            self.to_screen(msg('[info] %s is already present', label.title()))
            return 'exists'
        else:
            self.to_screen(msg('[info] Writing %s as JSON to: ', label) + infofn)
            try:
                write_json_file(self.filter_requested_info(info_dict), infofn)
                return True
            except OSError:
                self.report_error(msg('Cannot write %s to JSON file ', label) + infofn)
                return None

    def _write_thumbnails(self, info_dict, filename):
        if self.params.get('writethumbnail', False):
            thumbnails = info_dict.get('thumbnails')
            if thumbnails:
                thumbnails = [thumbnails[-1]]
        elif self.params.get('write_all_thumbnails', False):
            thumbnails = info_dict.get('thumbnails')
        else:
            return

        if not thumbnails:
            # No thumbnails present, so return immediately
            return

        for t in thumbnails:
            thumb_ext = determine_ext(t['url'], 'jpg')
            suffix = '_{}'.format(t['id']) if len(thumbnails) > 1 else ''
            thumb_display_id = '{} '.format(t['id']) if len(thumbnails) > 1 else ''
            t['filename'] = thumb_filename = replace_extension(filename + suffix, thumb_ext, info_dict.get('ext'))

            if self.params.get('nooverwrites', False) and os.path.exists(encodeFilename(thumb_filename)):
                self.to_screen(
                    '[{}] {}: Thumbnail {}is already present'.format(
                        info_dict['extractor'], info_dict['id'], thumb_display_id
                    )
                )
            else:
                self.to_screen(
                    '[{}] {}: Downloading thumbnail {}...'.format(
                        info_dict['extractor'], info_dict['id'], thumb_display_id
                    )
                )
                try:
                    uf = self.urlopen(t['url'])
                    with open(encodeFilename(thumb_filename), 'wb') as thumbf:
                        shutil.copyfileobj(uf, thumbf)
                    self.to_screen(
                        '[{}] {}: Writing thumbnail {}to: {}'.format(
                            info_dict['extractor'], info_dict['id'], thumb_display_id, thumb_filename
                        )
                    )
                except (OSError, compat_urllib_error.URLError, compat_http_client.HTTPException) as err:
                    self.report_warning(
                        'Unable to download thumbnail "{}": {}'.format(t['url'], error_to_compat_str(err))
                    )
