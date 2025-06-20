from __future__ import annotations

import subprocess

from ..compat import compat_shlex_quote
from ..utils import PostProcessingError
from ..utils import encodeArgument
from .common import PostProcessor


class ExecAfterDownloadPP(PostProcessor):
    def __init__(self, downloader, exec_cmd):
        super().__init__(downloader)
        self.exec_cmd = exec_cmd

    def run(self, information):
        cmd = self.exec_cmd
        if '{}' not in cmd:
            cmd += ' {}'

        cmd = cmd.replace('{}', compat_shlex_quote(information['filepath']))

        self._downloader.to_screen(f'[exec] Executing command: {cmd}')
        retCode = subprocess.call(encodeArgument(cmd), shell=True)
        if retCode != 0:
            raise PostProcessingError(
                'Command returned error code %d' % retCode)

        return [], information
