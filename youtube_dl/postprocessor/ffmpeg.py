from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from ..compat import compat_open as open
from ..utils import ISO639Utils
from ..utils import PostProcessingError
from ..utils import dfxp2srt
from ..utils import encodeArgument
from ..utils import encodeFilename
from ..utils import get_exe_version
from ..utils import is_outdated_version
from ..utils import prepend_extension
from ..utils import process_communicate_or_kill
from ..utils import replace_extension
from ..utils import shell_quote
from ..utils import subtitles_filename
from .common import AudioConversionError
from .common import PostProcessor

EXT_TO_OUT_FORMATS = {
    'aac': 'adts',
    'flac': 'flac',
    'm4a': 'ipod',
    'mka': 'matroska',
    'mkv': 'matroska',
    'mpg': 'mpeg',
    'ogv': 'ogg',
    'ts': 'mpegts',
    'wma': 'asf',
    'wmv': 'asf',
}
ACODECS = {
    'mp3': 'libmp3lame',
    'aac': 'aac',
    'flac': 'flac',
    'm4a': 'aac',
    'opus': 'libopus',
    'vorbis': 'libvorbis',
    'wav': None,
}


class FFmpegPostProcessorError(PostProcessingError):
    pass


class FFmpegPostProcessor(PostProcessor):
    def __init__(self, downloader=None):
        PostProcessor.__init__(self, downloader)
        self._determine_executables()

    def check_version(self):
        if not self.available:
            raise FFmpegPostProcessorError('ffmpeg or avconv not found. Please install one.')

        required_version = '10-0' if self.basename == 'avconv' else '1.0'
        if is_outdated_version(self._versions[self.basename], required_version):
            warning = f'Your copy of {self.basename} is outdated, update {self.basename} to version {required_version} or newer if you encounter any errors.'
            if self._downloader:
                self._downloader.report_warning(warning)

    @staticmethod
    def get_versions(downloader=None):
        return FFmpegPostProcessor(downloader)._versions

    def _determine_executables(self):
        # ordered to match prefer_ffmpeg!
        convs = ['ffmpeg', 'avconv']
        probes = ['ffprobe', 'avprobe']
        prefer_ffmpeg = True
        programs = convs + probes

        def get_ffmpeg_version(path):
            ver = get_exe_version(path, args=['-version'])
            if ver:
                regexs = [
                    r'(?:\d+:)?([0-9.]+)-[0-9]+ubuntu[0-9.]+$',  # Ubuntu, see [1]
                    r'n([0-9.]+)$',  # Arch Linux
                    # 1. http://www.ducea.com/2006/06/17/ubuntu-package-version-naming-explanation/
                ]
                for regex in regexs:
                    mobj = re.match(regex, ver)
                    if mobj:
                        ver = mobj.group(1)
            return ver

        self.basename = None
        self.probe_basename = None

        self._paths = None
        self._versions = None
        location = None
        if self._downloader:
            prefer_ffmpeg = self._downloader.params.get('prefer_ffmpeg', True)
            location = self._downloader.params.get('ffmpeg_location')
            if location is not None:
                if not os.path.exists(location):
                    self._downloader.report_warning(
                        f'ffmpeg-location {location} does not exist! Continuing without avconv/ffmpeg.'
                    )
                    self._versions = {}
                    return
                elif not os.path.isdir(location):
                    basename = os.path.splitext(os.path.basename(location))[0]
                    if basename not in programs:
                        self._downloader.report_warning(
                            'Cannot identify executable {}, its basename should be one of {}. '
                            'Continuing without avconv/ffmpeg.'.format(location, ', '.join(programs))
                        )
                        self._versions = {}
                        return None
                    location = os.path.dirname(os.path.abspath(location))
                    if basename in ('ffmpeg', 'ffprobe'):
                        prefer_ffmpeg = True
        self._paths = dict((p, p if location is None else os.path.join(location, p)) for p in programs)
        self._versions = dict(
            x for x in ((p, get_ffmpeg_version(self._paths[p])) for p in programs) if x[1] is not None
        )

        basenames = [None, None]
        for i, progs in enumerate((convs, probes)):
            for p in progs[:: -1 if prefer_ffmpeg is False else 1]:
                if self._versions.get(p):
                    basenames[i] = p
                    break
        self.basename, self.probe_basename = basenames

    @property
    def available(self):
        return self.basename is not None

    @property
    def executable(self):
        return self._paths[self.basename]

    @property
    def probe_available(self):
        return self.probe_basename is not None

    @property
    def probe_executable(self):
        return self._paths[self.probe_basename]

    def get_audio_codec(self, path):
        if not self.probe_available and not self.available:
            raise PostProcessingError('ffprobe/avprobe and ffmpeg/avconv not found. Please install one.')
        try:
            if self.probe_available:
                cmd = [encodeFilename(self.probe_executable, True), encodeArgument('-show_streams')]
            else:
                cmd = [encodeFilename(self.executable, True), encodeArgument('-i')]
            cmd.append(encodeFilename(self._ffmpeg_filename_argument(path), True))
            if self._downloader.params.get('verbose', False):
                self._downloader.to_screen(f'[debug] {self.basename} command line: {shell_quote(cmd)}')
            handle = subprocess.Popen(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, stdin=subprocess.PIPE)
            stdout_data, stderr_data = process_communicate_or_kill(handle)
            expected_ret = 0 if self.probe_available else 1
            if handle.wait() != expected_ret:
                return None
        except OSError:
            return None
        output = (stdout_data if self.probe_available else stderr_data).decode('ascii', 'ignore')
        if self.probe_available:
            audio_codec = None
            for line in output.split('\n'):
                if line.startswith('codec_name='):
                    audio_codec = line.split('=')[1].strip()
                elif line.strip() == 'codec_type=audio' and audio_codec is not None:
                    return audio_codec
        else:
            # Stream #FILE_INDEX:STREAM_INDEX[STREAM_ID](LANGUAGE): CODEC_TYPE: CODEC_NAME
            mobj = re.search(r'Stream\s*#\d+:\d+(?:\[0x[0-9a-f]+\])?(?:\([a-z]{3}\))?:\s*Audio:\s*([0-9a-z]+)', output)
            if mobj:
                return mobj.group(1)
        return None

    def run_ffmpeg_multiple_files(self, input_paths, out_path, opts):
        self.check_version()

        oldest_mtime = min(os.stat(encodeFilename(path)).st_mtime for path in input_paths)

        opts += self._configuration_args()

        files_cmd = []
        for path in input_paths:
            files_cmd.extend([encodeArgument('-i'), encodeFilename(self._ffmpeg_filename_argument(path), True)])
        cmd = [encodeFilename(self.executable, True), encodeArgument('-y')]
        # avconv does not have repeat option
        if self.basename == 'ffmpeg':
            cmd += [encodeArgument('-loglevel'), encodeArgument('repeat+info')]
        cmd += (
            files_cmd
            + [encodeArgument(o) for o in opts]
            + [encodeFilename(self._ffmpeg_filename_argument(out_path), True)]
        )

        if self._downloader.params.get('verbose', False):
            self._downloader.to_screen(f'[debug] ffmpeg command line: {shell_quote(cmd)}')
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE)
        stdout, stderr = process_communicate_or_kill(p)
        if p.returncode != 0:
            stderr = stderr.decode('utf-8', 'replace')
            msgs = stderr.strip().split('\n')
            msg = msgs[-1]
            if self._downloader.params.get('verbose', False):
                self._downloader.to_screen('[debug] ' + '\n'.join(msgs[:-1]))
            raise FFmpegPostProcessorError(msg)
        self.try_utime(out_path, oldest_mtime, oldest_mtime)

    def run_ffmpeg(self, path, out_path, opts):
        self.run_ffmpeg_multiple_files([path], out_path, opts)

    def _ffmpeg_filename_argument(self, fn):
        # Always use 'file:' because the filename may contain ':' (ffmpeg
        # interprets that as a protocol) or can start with '-' (-- is broken in
        # ffmpeg, see https://ffmpeg.org/trac/ffmpeg/ticket/2127 for details)
        # Also leave '-' intact in order not to break streaming to stdout.
        return 'file:' + fn if fn != '-' else fn


class FFmpegExtractAudioPP(FFmpegPostProcessor):
    def __init__(self, downloader=None, preferredcodec=None, preferredquality=None, nopostoverwrites=False):
        FFmpegPostProcessor.__init__(self, downloader)
        if preferredcodec is None:
            preferredcodec = 'best'
        self._preferredcodec = preferredcodec
        self._preferredquality = preferredquality
        self._nopostoverwrites = nopostoverwrites

    def run_ffmpeg(self, path, out_path, codec, more_opts):
        if codec is None:
            acodec_opts = []
        else:
            acodec_opts = ['-acodec', codec]
        opts = ['-vn', *acodec_opts, *more_opts]
        try:
            FFmpegPostProcessor.run_ffmpeg(self, path, out_path, opts)
        except FFmpegPostProcessorError as err:
            raise AudioConversionError(err.msg)

    def run(self, information):
        path = information['filepath']

        filecodec = self.get_audio_codec(path)
        if filecodec is None:
            raise PostProcessingError('WARNING: unable to obtain file audio codec with ffprobe')

        more_opts = []
        if (
            self._preferredcodec == 'best'
            or self._preferredcodec == filecodec
            or (self._preferredcodec == 'm4a' and filecodec == 'aac')
        ):
            if filecodec == 'aac' and self._preferredcodec in ['m4a', 'best']:
                # Lossless, but in another container
                acodec = 'copy'
                extension = 'm4a'
                more_opts = ['-bsf:a', 'aac_adtstoasc']
            elif filecodec in ['aac', 'flac', 'mp3', 'vorbis', 'opus']:
                # Lossless if possible
                acodec = 'copy'
                extension = filecodec
                if filecodec == 'aac':
                    more_opts = ['-f', 'adts']
                if filecodec == 'vorbis':
                    extension = 'ogg'
            else:
                # MP3 otherwise.
                acodec = 'libmp3lame'
                extension = 'mp3'
                more_opts = []
                if self._preferredquality is not None:
                    if int(self._preferredquality) < 10:
                        more_opts += ['-q:a', self._preferredquality]
                    else:
                        more_opts += ['-b:a', self._preferredquality + 'k']
        else:
            # We convert the audio (lossy if codec is lossy)
            acodec = ACODECS[self._preferredcodec]
            extension = self._preferredcodec
            more_opts = []
            if self._preferredquality is not None:
                # The opus codec doesn't support the -aq option
                if int(self._preferredquality) < 10 and extension != 'opus':
                    more_opts += ['-q:a', self._preferredquality]
                else:
                    more_opts += ['-b:a', self._preferredquality + 'k']
            if self._preferredcodec == 'aac':
                more_opts += ['-f', 'adts']
            if self._preferredcodec == 'm4a':
                more_opts += ['-bsf:a', 'aac_adtstoasc']
            if self._preferredcodec == 'vorbis':
                extension = 'ogg'
            if self._preferredcodec == 'wav':
                extension = 'wav'
                more_opts += ['-f', 'wav']

        prefix, sep, ext = path.rpartition(
            '.'
        )  # not os.path.splitext, since the latter does not work on unicode in all setups
        new_path = prefix + sep + extension

        information['filepath'] = new_path
        information['ext'] = extension

        # If we download foo.mp3 and convert it to... foo.mp3, then don't delete foo.mp3, silly.
        if new_path == path or (self._nopostoverwrites and os.path.exists(encodeFilename(new_path))):
            self._downloader.to_screen(f'[ffmpeg] Post-process file {new_path} exists, skipping')
            return [], information

        try:
            self._downloader.to_screen('[ffmpeg] Destination: ' + new_path)
            self.run_ffmpeg(path, new_path, acodec, more_opts)
        except AudioConversionError as e:
            raise PostProcessingError('audio conversion failed: ' + e.msg)
        except Exception:
            raise PostProcessingError('error running ' + self.basename)

        # Try to update the date time for extracted audio file.
        if information.get('filetime') is not None:
            self.try_utime(new_path, time.time(), information['filetime'], errnote='Cannot update utime of audio file')

        return [path], information


class FFmpegVideoConvertorPP(FFmpegPostProcessor):
    def __init__(self, downloader=None, preferedformat=None):
        super().__init__(downloader)
        self._preferedformat = preferedformat

    def run(self, information):
        path = information['filepath']
        if information['ext'] == self._preferedformat:
            self._downloader.to_screen(
                f'[ffmpeg] Not converting video file {path} - already is in target format {self._preferedformat}'
            )
            return [], information
        options = []
        if self._preferedformat == 'avi':
            options.extend(['-c:v', 'libxvid', '-vtag', 'XVID'])
        prefix, sep, ext = path.rpartition('.')
        outpath = prefix + sep + self._preferedformat
        self._downloader.to_screen(
            '['
            + 'ffmpeg'
            + '] Converting video from {} to {}, Destination: '.format(information['ext'], self._preferedformat)
            + outpath
        )
        self.run_ffmpeg(path, outpath, options)
        information['filepath'] = outpath
        information['format'] = self._preferedformat
        information['ext'] = self._preferedformat
        return [path], information


class FFmpegEmbedSubtitlePP(FFmpegPostProcessor):
    def run(self, information):
        if information['ext'] not in ('mp4', 'webm', 'mkv'):
            self._downloader.to_screen('[ffmpeg] Subtitles can only be embedded in mp4, webm or mkv files')
            return [], information
        subtitles = information.get('requested_subtitles')
        if not subtitles:
            self._downloader.to_screen("[ffmpeg] There aren't any subtitles to embed")
            return [], information

        filename = information['filepath']

        ext = information['ext']
        sub_langs = []
        sub_filenames = []
        webm_vtt_warn = False

        for lang, sub_info in subtitles.items():
            sub_ext = sub_info['ext']
            if ext != 'webm' or (ext == 'webm' and sub_ext == 'vtt'):
                sub_langs.append(lang)
                sub_filenames.append(subtitles_filename(filename, lang, sub_ext, ext))
            else:
                if not webm_vtt_warn and ext == 'webm' and sub_ext != 'vtt':
                    webm_vtt_warn = True
                    self._downloader.to_screen('[ffmpeg] Only WebVTT subtitles can be embedded in webm files')

        if not sub_langs:
            return [], information

        input_files = [filename, *sub_filenames]

        opts = [
            '-map',
            '0',
            '-c',
            'copy',
            # Don't copy the existing subtitles, we may be running the
            # postprocessor a second time
            '-map',
            '-0:s',
            # Don't copy Apple TV chapters track, bin_data (see #19042, #19024,
            # https://trac.ffmpeg.org/ticket/6016)
            '-map',
            '-0:d',
        ]
        if information['ext'] == 'mp4':
            opts += ['-c:s', 'mov_text']
        for i, lang in enumerate(sub_langs):
            opts.extend(['-map', '%d:0' % (i + 1)])
            lang_code = ISO639Utils.short2long(lang) or lang
            opts.extend(['-metadata:s:s:%d' % i, f'language={lang_code}'])

        temp_filename = prepend_extension(filename, 'temp')
        self._downloader.to_screen(f"[ffmpeg] Embedding subtitles in '{filename}'")
        self.run_ffmpeg_multiple_files(input_files, temp_filename, opts)
        os.remove(encodeFilename(filename))
        os.rename(encodeFilename(temp_filename), encodeFilename(filename))

        return sub_filenames, information


class FFmpegMetadataPP(FFmpegPostProcessor):
    def run(self, info):
        metadata = {}

        def add(meta_list, info_list=None):
            if not info_list:
                info_list = meta_list
            if not isinstance(meta_list, (list, tuple)):
                meta_list = (meta_list,)
            if not isinstance(info_list, (list, tuple)):
                info_list = (info_list,)
            for info_f in info_list:
                if info.get(info_f) is not None:
                    for meta_f in meta_list:
                        metadata[meta_f] = info[info_f]
                    break

        # See [1-4] for some info on media metadata/metadata supported
        # by ffmpeg.
        # 1. https://kdenlive.org/en/project/adding-meta-data-to-mp4-video/
        # 2. https://wiki.multimedia.cx/index.php/FFmpeg_Metadata
        # 3. https://kodi.wiki/view/Video_file_tagging
        # 4. http://atomicparsley.sourceforge.net/mpeg-4files.html

        add('title', ('track', 'title'))
        add('date', 'upload_date')
        add(('description', 'comment'), 'description')
        add('purl', 'webpage_url')
        add('track', 'track_number')
        add('artist', ('artist', 'creator', 'uploader', 'uploader_id'))
        add('genre')
        add('album')
        add('album_artist')
        add('disc', 'disc_number')
        add('show', 'series')
        add('season_number')
        add('episode_id', ('episode', 'episode_id'))
        add('episode_sort', 'episode_number')

        if not metadata:
            self._downloader.to_screen("[ffmpeg] There isn't any metadata to add")
            return [], info

        filename = info['filepath']
        temp_filename = prepend_extension(filename, 'temp')
        in_filenames = [filename]
        options = []

        if info['ext'] == 'm4a':
            options.extend(['-vn', '-acodec', 'copy'])
        else:
            options.extend(['-c', 'copy'])

        for name, value in metadata.items():
            options.extend(['-metadata', f'{name}={value}'])

        chapters = info.get('chapters', [])
        if chapters:
            metadata_filename = replace_extension(filename, 'meta')
            with open(metadata_filename, 'w', encoding='utf-8') as f:

                def ffmpeg_escape(text):
                    return re.sub(r'(=|;|#|\\|\n)', r'\\\1', text)

                metadata_file_content = ';FFMETADATA1\n'
                for chapter in chapters:
                    metadata_file_content += '[CHAPTER]\nTIMEBASE=1/1000\n'
                    metadata_file_content += 'START=%d\n' % (chapter['start_time'] * 1000)
                    metadata_file_content += 'END=%d\n' % (chapter['end_time'] * 1000)
                    chapter_title = chapter.get('title')
                    if chapter_title:
                        metadata_file_content += f'title={ffmpeg_escape(chapter_title)}\n'
                f.write(metadata_file_content)
                in_filenames.append(metadata_filename)
                options.extend(['-map_metadata', '1'])

        self._downloader.to_screen(f"[ffmpeg] Adding metadata to '{filename}'")
        self.run_ffmpeg_multiple_files(in_filenames, temp_filename, options)
        if chapters:
            os.remove(metadata_filename)
        os.remove(encodeFilename(filename))
        os.rename(encodeFilename(temp_filename), encodeFilename(filename))
        return [], info


class FFmpegMergerPP(FFmpegPostProcessor):
    def run(self, info):
        filename = info['filepath']
        temp_filename = prepend_extension(filename, 'temp')
        args = ['-c', 'copy', '-map', '0:v:0', '-map', '1:a:0']
        self._downloader.to_screen(f'[ffmpeg] Merging formats into "{filename}"')
        self.run_ffmpeg_multiple_files(info['__files_to_merge'], temp_filename, args)
        os.rename(encodeFilename(temp_filename), encodeFilename(filename))
        return info['__files_to_merge'], info

    def can_merge(self):
        # TODO: figure out merge-capable ffmpeg version
        if self.basename != 'avconv':
            return True

        required_version = '10-0'
        if is_outdated_version(self._versions[self.basename], required_version):
            warning = (
                f'Your copy of {self.basename} is outdated and unable to properly mux separate video and audio files, '
                'youtube-dl will download single file media. '
                f'Update {self.basename} to version {required_version} or newer to fix this.'
            )
            if self._downloader:
                self._downloader.report_warning(warning)
            return False
        return True


class FFmpegFixupStretchedPP(FFmpegPostProcessor):
    def run(self, info):
        stretched_ratio = info.get('stretched_ratio')
        if stretched_ratio is None or stretched_ratio == 1:
            return [], info

        filename = info['filepath']
        temp_filename = prepend_extension(filename, 'temp')

        options = ['-c', 'copy', '-aspect', f'{stretched_ratio:f}']
        self._downloader.to_screen(f'[ffmpeg] Fixing aspect ratio in "{filename}"')
        self.run_ffmpeg(filename, temp_filename, options)

        os.remove(encodeFilename(filename))
        os.rename(encodeFilename(temp_filename), encodeFilename(filename))

        return [], info


class FFmpegFixupM4aPP(FFmpegPostProcessor):
    def run(self, info):
        if info.get('container') != 'm4a_dash':
            return [], info

        filename = info['filepath']
        temp_filename = prepend_extension(filename, 'temp')

        options = ['-c', 'copy', '-f', 'mp4']
        self._downloader.to_screen(f'[ffmpeg] Correcting container in "{filename}"')
        self.run_ffmpeg(filename, temp_filename, options)

        os.remove(encodeFilename(filename))
        os.rename(encodeFilename(temp_filename), encodeFilename(filename))

        return [], info


class FFmpegFixupM3u8PP(FFmpegPostProcessor):
    def run(self, info):
        filename = info['filepath']
        if self.get_audio_codec(filename) == 'aac':
            temp_filename = prepend_extension(filename, 'temp')

            options = ['-c', 'copy', '-f', 'mp4', '-bsf:a', 'aac_adtstoasc']
            self._downloader.to_screen(f'[ffmpeg] Fixing malformed AAC bitstream in "{filename}"')
            self.run_ffmpeg(filename, temp_filename, options)

            os.remove(encodeFilename(filename))
            os.rename(encodeFilename(temp_filename), encodeFilename(filename))
        return [], info


class FFmpegSubtitlesConvertorPP(FFmpegPostProcessor):
    def __init__(self, downloader=None, format=None):
        super().__init__(downloader)
        self.format = format

    def run(self, info):
        subs = info.get('requested_subtitles')
        filename = info['filepath']
        new_ext = self.format
        new_format = new_ext
        if new_format == 'vtt':
            new_format = 'webvtt'
        if subs is None:
            self._downloader.to_screen("[ffmpeg] There aren't any subtitles to convert")
            return [], info
        self._downloader.to_screen('[ffmpeg] Converting subtitles')
        sub_filenames = []
        for lang, sub in subs.items():
            ext = sub['ext']
            if ext == new_ext:
                self._downloader.to_screen(f'[ffmpeg] Subtitle file for {new_ext} is already in the requested format')
                continue
            old_file = subtitles_filename(filename, lang, ext, info.get('ext'))
            sub_filenames.append(old_file)
            new_file = subtitles_filename(filename, lang, new_ext, info.get('ext'))

            if ext in ('dfxp', 'ttml', 'tt'):
                self._downloader.report_warning(
                    'You have requested to convert dfxp (TTML) subtitles into another format, '
                    'which results in style information loss'
                )

                dfxp_file = old_file
                srt_file = subtitles_filename(filename, lang, 'srt', info.get('ext'))

                with open(dfxp_file, 'rb') as f:
                    srt_data = dfxp2srt(f.read())

                with open(srt_file, 'w', encoding='utf-8') as f:
                    f.write(srt_data)
                old_file = srt_file

                subs[lang] = {'ext': 'srt', 'data': srt_data}

                if new_ext == 'srt':
                    continue
                else:
                    sub_filenames.append(srt_file)

            self.run_ffmpeg(old_file, new_file, ['-f', new_format])

            with open(new_file, 'r', encoding='utf-8') as f:
                subs[lang] = {
                    'ext': new_ext,
                    'data': f.read(),
                }

        return sub_filenames, info


class ConvertAACToMP3PP(FFmpegPostProcessor):
    """
    Custom post processor that converts .aac files to .mp3 files
    """

    def run(self, info: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
        if info['ext'] == 'aac':
            aac_path = Path(info['filepath'])
            mp3_path = aac_path.with_suffix('.mp3')

            self._downloader.to_screen('[ffmpeg] Converting .aac to .mp3')
            options: list[str] = [
                '-codec:a',
                'libmp3lame',
                '-qscale:a',
                '0',
            ]
            self.run_ffmpeg(str(aac_path), str(mp3_path), options)
            aac_path.unlink()

            info['filepath'] = str(mp3_path)
            info['ext'] = 'mp3'

        return [], info
