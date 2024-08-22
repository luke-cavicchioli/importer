"""Process files as requested"""


import fnmatch
import os
import shutil
from pathlib import Path
from typing import List


class FileProcessor:
    def __init__(
            self,
            indir: Path,
            outpath: Path,
            repopath: Path,
            compress: bool,
            force: bool,
            ignore_patterns: List[str]
    ):
        self._indir = indir.resolve()
        self._outpath = outpath.resolve()
        self._repopath = repopath.resolve()
        self._compress = compress
        self._force = force
        self._ignore_patterns = ignore_patterns

    def count_files(self) -> int:

        n = 0
        for _, dns, fns in os.walk(self._indir):
            dns[:] = self._remove_ignored(dns)
            fns = self._remove_ignored(fns)
            n += len(fns)

        return n

    def copy(self, cb):
        pass

    def _remove_ignored(self, names) -> List[str]:
        ignor = set()
        for patt in self._ignore_patterns:
            matchsetd = set(fnmatch.filter(names, patt))
            ignor = ignor.union(matchsetd)
        return [x for x in names if x not in ignor]
