from __future__ import annotations

from .extractors import *

_ALL_CLASSES = [klass for name, klass in globals().items() if name.endswith('IE')]


def gen_extractor_classes():
    """Return a list of supported extractors.
    The order does matter; the first extractor matched is the one handling the URL.
    """
    return _ALL_CLASSES


def gen_extractors():
    """Return a list of an instance of every supported extractor.
    The order does matter; the first extractor matched is the one handling the URL.
    """
    return [klass() for klass in gen_extractor_classes()]


def list_extractors(age_limit):
    """
    Return a list of extractors that are suitable for the given age,
    sorted by extractor ID.
    """

    return sorted(filter(lambda ie: ie.is_suitable(age_limit), gen_extractors()), key=lambda ie: ie.IE_NAME.lower())


def get_info_extractor(ie_name):
    """Returns the info extractor class with the given ie_name"""
    return globals()[ie_name + 'IE']
