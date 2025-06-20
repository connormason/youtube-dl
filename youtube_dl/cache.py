from __future__ import annotations

import errno
import json
import os
import re
import shutil
import traceback

from .compat import compat_getenv
from .compat import compat_open as open
from .compat import compat_os_makedirs
from .utils import error_to_compat_str
from .utils import escape_rfc3986
from .utils import expand_path
from .utils import is_outdated_version
from .utils import traverse_obj
from .utils import write_json_file
from .version import __version__


class Cache:
    _YTDL_DIR = 'youtube-dl'
    _VERSION_KEY = _YTDL_DIR + '_version'
    _DEFAULT_VERSION = '2021.12.17'

    def __init__(self, ydl):
        self._ydl = ydl

    def _write_debug(self, *args, **kwargs):
        self._ydl.write_debug(*args, **kwargs)

    def _report_warning(self, *args, **kwargs):
        self._ydl.report_warning(*args, **kwargs)

    def _to_screen(self, *args, **kwargs):
        self._ydl.to_screen(*args, **kwargs)

    def _get_param(self, k, default=None):
        return self._ydl.params.get(k, default)

    def _get_root_dir(self):
        res = self._get_param('cachedir')
        if res is None:
            cache_root = compat_getenv('XDG_CACHE_HOME', '~/.cache')
            res = os.path.join(cache_root, self._YTDL_DIR)
        return expand_path(res)

    def _get_cache_fn(self, section, key, dtype):
        assert re.match(r'^[\w.-]+$', section), f'invalid section {section!r}'
        key = escape_rfc3986(key, safe='').replace('%', ',')  # encode non-ascii characters
        return os.path.join(self._get_root_dir(), section, f'{key}.{dtype}')

    @property
    def enabled(self):
        return self._get_param('cachedir') is not False

    def store(self, section, key, data, dtype='json'):
        assert dtype in ('json',)

        if not self.enabled:
            return

        fn = self._get_cache_fn(section, key, dtype)
        try:
            compat_os_makedirs(os.path.dirname(fn), exist_ok=True)
            self._write_debug(f'Saving {section}.{key} to cache')
            write_json_file({self._VERSION_KEY: __version__, 'data': data}, fn)
        except Exception:
            tb = traceback.format_exc()
            self._report_warning(f'Writing cache to {fn!r} failed: {tb}')

    def clear(self, section, key, dtype='json'):
        if not self.enabled:
            return

        fn = self._get_cache_fn(section, key, dtype)
        self._write_debug(f'Clearing {section}.{key} from cache')
        try:
            os.remove(fn)
        except Exception as e:
            if getattr(e, 'errno') == errno.ENOENT:
                # file not found
                return
            tb = traceback.format_exc()
            self._report_warning(f'Clearing cache from {fn!r} failed: {tb}')

    def _validate(self, data, min_ver):
        version = traverse_obj(data, self._VERSION_KEY)
        if not version:  # Backward compatibility
            data, version = {'data': data}, self._DEFAULT_VERSION
        if not is_outdated_version(version, min_ver or '0', assume_new=False):
            return data['data']
        self._write_debug(f'Discarding old cache from version {version} (needs {min_ver})')

    def load(self, section, key, dtype='json', default=None, **kw_min_ver):
        assert dtype in ('json',)
        min_ver = kw_min_ver.get('min_ver')

        if not self.enabled:
            return default

        cache_fn = self._get_cache_fn(section, key, dtype)
        try:
            with open(cache_fn, encoding='utf-8') as cachef:
                self._write_debug(f'Loading {section}.{key} from cache', only_once=True)
                return self._validate(json.load(cachef), min_ver)
        except (ValueError, KeyError):
            try:
                file_size = 'size: %d' % os.path.getsize(cache_fn)
            except OSError as oe:
                file_size = error_to_compat_str(oe)
            self._report_warning(f'Cache retrieval from {cache_fn} failed ({file_size})')
        except Exception as e:
            if getattr(e, 'errno') == errno.ENOENT:
                # no cache available
                return
            self._report_warning(f'Cache retrieval from {cache_fn} failed')

        return default

    def remove(self):
        if not self.enabled:
            self._to_screen('Cache is disabled (Did you combine --no-cache-dir and --rm-cache-dir?)')
            return

        cachedir = self._get_root_dir()
        if not any((term in cachedir) for term in ('cache', 'tmp')):
            raise Exception(f'Not removing directory {cachedir} - this does not look like a cache dir')

        (self._to_screen(f'Removing cache dir {cachedir} .', skip_eol=True),)
        if os.path.exists(cachedir):
            self._to_screen('.', skip_eol=True)
            shutil.rmtree(cachedir)
        self._to_screen('.')
