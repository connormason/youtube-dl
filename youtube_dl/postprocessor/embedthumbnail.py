from __future__ import annotations

import logging
import os
import subprocess

from ..compat import compat_open as open
from ..utils import PostProcessingError
from ..utils import check_executable
from ..utils import encodeArgument
from ..utils import encodeFilename
from ..utils import prepend_extension
from ..utils import process_communicate_or_kill
from ..utils import replace_extension
from ..utils import shell_quote
from .ffmpeg import FFmpegPostProcessor

logger = logging.getLogger('soundcloudutil.downloader')


class EmbedThumbnailPPError(PostProcessingError):
    pass


class EmbedThumbnailPP(FFmpegPostProcessor):
    def __init__(self, downloader=None, already_have_thumbnail=False):
        super().__init__(downloader)
        self._already_have_thumbnail = already_have_thumbnail

    def run(self, info):
        filename = info['filepath']
        temp_filename = prepend_extension(filename, 'temp')

        if not info.get('thumbnails'):
            self._downloader.to_screen("[embedthumbnail] There aren't any thumbnails to embed")
            return [], info

        thumbnail_filename = info['thumbnails'][-1]['filename']

        if not os.path.exists(encodeFilename(thumbnail_filename)):
            self._downloader.report_warning('Skipping embedding the thumbnail because the file is missing.')
            return [], info

        def is_webp(path):
            with open(encodeFilename(path), 'rb') as f:
                b = f.read(12)
            return b[0:4] == b'RIFF' and b[8:] == b'WEBP'

        # Correct extension for WebP file with wrong extension (see #25687, #25717)
        _, thumbnail_ext = os.path.splitext(thumbnail_filename)
        if thumbnail_ext:
            thumbnail_ext = thumbnail_ext[1:].lower()
            if thumbnail_ext != 'webp' and is_webp(thumbnail_filename):
                self._downloader.to_screen(
                    f'[ffmpeg] Correcting extension to webp and escaping path for thumbnail "{thumbnail_filename}"'
                )
                thumbnail_webp_filename = replace_extension(thumbnail_filename, 'webp')
                os.rename(encodeFilename(thumbnail_filename), encodeFilename(thumbnail_webp_filename))
                thumbnail_filename = thumbnail_webp_filename
                thumbnail_ext = 'webp'

        # Convert unsupported thumbnail formats to JPEG (see #25687, #25717)
        if thumbnail_ext not in ['jpg', 'png']:
            # NB: % is supposed to be escaped with %% but this does not work
            # for input files so working around with standard substitution
            escaped_thumbnail_filename = thumbnail_filename.replace('%', '#')
            os.rename(encodeFilename(thumbnail_filename), encodeFilename(escaped_thumbnail_filename))
            escaped_thumbnail_jpg_filename = replace_extension(escaped_thumbnail_filename, 'jpg')
            self._downloader.to_screen(f'[ffmpeg] Converting thumbnail "{escaped_thumbnail_filename}" to JPEG')
            self.run_ffmpeg(escaped_thumbnail_filename, escaped_thumbnail_jpg_filename, ['-bsf:v', 'mjpeg2jpeg'])
            os.remove(encodeFilename(escaped_thumbnail_filename))
            thumbnail_jpg_filename = replace_extension(thumbnail_filename, 'jpg')
            # Rename back to unescaped for further processing
            os.rename(encodeFilename(escaped_thumbnail_jpg_filename), encodeFilename(thumbnail_jpg_filename))
            thumbnail_filename = thumbnail_jpg_filename

        if info['ext'] == 'mp3':
            options = [
                '-c',
                'copy',
                '-map',
                '0',
                '-map',
                '1',
                '-metadata:s:v',
                'title="Album cover"',
                '-metadata:s:v',
                'comment="Cover (Front)"',
            ]

            self._downloader.to_screen(f'[ffmpeg] Adding thumbnail to "{filename}"')

            self.run_ffmpeg_multiple_files([filename, thumbnail_filename], temp_filename, options)

            if not self._already_have_thumbnail:
                os.remove(encodeFilename(thumbnail_filename))
            os.remove(encodeFilename(filename))
            os.rename(encodeFilename(temp_filename), encodeFilename(filename))

        elif info['ext'] in ['m4a', 'mp4']:
            atomicparsley = next((x for x in ['AtomicParsley', 'atomicparsley'] if check_executable(x, ['-v'])), None)

            if atomicparsley is None:
                raise EmbedThumbnailPPError('AtomicParsley was not found. Please install.')

            cmd = [
                encodeFilename(atomicparsley, True),
                encodeFilename(filename, True),
                encodeArgument('--artwork'),
                encodeFilename(thumbnail_filename, True),
                encodeArgument('-o'),
                encodeFilename(temp_filename, True),
            ]

            self._downloader.to_screen(f'[atomicparsley] Adding thumbnail to "{filename}"')

            if self._downloader.params.get('verbose', False):
                self._downloader.to_screen(f'[debug] AtomicParsley command line: {shell_quote(cmd)}')

            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, stderr = process_communicate_or_kill(p)

            if p.returncode != 0:
                msg = stderr.decode('utf-8', 'replace').strip()
                raise EmbedThumbnailPPError(msg)

            if not self._already_have_thumbnail:
                os.remove(encodeFilename(thumbnail_filename))
            # for formats that don't support thumbnails (like 3gp) AtomicParsley
            # won't create to the temporary file
            if b'No changes' in stdout:
                self._downloader.report_warning("The file format doesn't support embedding a thumbnail")
            else:
                os.remove(encodeFilename(filename))
                os.rename(encodeFilename(temp_filename), encodeFilename(filename))
        else:
            logger.warning('Only mp3 and m4a/mp4 are supported for thumbnail embedding for now.')
            # raise EmbedThumbnailPPError('Only mp3 and m4a/mp4 are supported for thumbnail embedding for now.')

        return [], info
