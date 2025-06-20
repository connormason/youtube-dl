from __future__ import annotations

from .embedthumbnail import EmbedThumbnailPP
from .execafterdownload import ExecAfterDownloadPP
from .ffmpeg import ConvertAACToMP3PP
from .ffmpeg import FFmpegEmbedSubtitlePP
from .ffmpeg import FFmpegExtractAudioPP
from .ffmpeg import FFmpegFixupM3u8PP
from .ffmpeg import FFmpegFixupM4aPP
from .ffmpeg import FFmpegFixupStretchedPP
from .ffmpeg import FFmpegMergerPP
from .ffmpeg import FFmpegMetadataPP
from .ffmpeg import FFmpegPostProcessor
from .ffmpeg import FFmpegSubtitlesConvertorPP
from .ffmpeg import FFmpegVideoConvertorPP
from .metadatafromtitle import MetadataFromTitlePP
from .xattrpp import XAttrMetadataPP


def get_postprocessor(key):
    return globals()[key + 'PP']


__all__ = [
    'ConvertAACToMP3PP',
    'EmbedThumbnailPP',
    'ExecAfterDownloadPP',
    'FFmpegEmbedSubtitlePP',
    'FFmpegExtractAudioPP',
    'FFmpegFixupM3u8PP',
    'FFmpegFixupM4aPP',
    'FFmpegFixupStretchedPP',
    'FFmpegMergerPP',
    'FFmpegMetadataPP',
    'FFmpegPostProcessor',
    'FFmpegSubtitlesConvertorPP',
    'FFmpegVideoConvertorPP',
    'MetadataFromTitlePP',
    'XAttrMetadataPP',
]
