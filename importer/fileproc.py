"""Process files as requested."""


import fnmatch
import logging
import os
import shutil
from pathlib import Path
from typing import Callable, List

logger = logging.getLogger("importer.fileproc")


def transplant_path(src: Path, src_root: Path, dst_root: Path):
    """
    Transplant the root of an absolute path.

    Get the root that src, under src_root, would have had if it were, instead,
    under dst_root.
    """
    relp = src.relative_to(src_root.resolve())
    return dst_root.resolve().joinpath(relp)


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

    def __call__(self, cb: Callable[[str], None]) -> int:
        if not self._compress:
            logger.info("Files will be copied.")
            return self.copy(cb)
        else:
            logger.info("Files will be archived.")
            return self.archive(cb)

    def count_files(self) -> int:

        n = 0
        for _, dns, fns in os.walk(self._indir):
            dns[:] = self._remove_ignored(dns)
            fns = self._remove_ignored(fns)
            n += len(fns)

        return n

    def copy(self, cb: Callable[[str], None]) -> int:
        src_root = self._indir
        dst_root = self._repopath.joinpath(src_root.name)
        logger.debug(f"{src_root = }\n{dst_root = }")
        try:
            dst_root.mkdir(exist_ok=self._force)
        except FileExistsError as e:
            logger.error(f"Error while copying files: {e}")
            return 17  # EEXIST: File exists

        for curr, dns, fns in os.walk(src_root):
            curr = Path(curr)
            dst = transplant_path(curr, src_root, dst_root)
            logger.debug(f"{curr = }\n{dst = }")

            try:
                dst.mkdir(exist_ok=self._force)
            except FileExistsError as e:
                logger.error(f"Error while copying files: {e}")
                return 17

            shutil.copystat(curr, dst)

            dns[:] = self._remove_ignored(dns)
            fns = self._remove_ignored(fns)

            for f in fns:
                f_src_path = curr.joinpath(Path(f))
                f_dst_path = transplant_path(f_src_path, src_root, dst_root)
                f_disp = f_src_path.relative_to(src_root)
                description = f"Copying {f_disp}"
                cb(str(description))
                shutil.copy2(f_src_path, f_dst_path)

        if self._outpath != self._repopath:
            link_dst = self._outpath.joinpath(src_root.name)
            logger.info(f"Linking {dst_root} to {link_dst}")
            if link_dst.exists():
                if self._force:
                    os.remove(link_dst)
                else:
                    logger.error("{link_dst} already exists")
                    return 17
            link_dst.symlink_to(dst_root)
        else:
            logger.info(
                "Output path equal to repo path, skipping symlink creation.")

        return 0

    def archive(self, cb: Callable[[str], None]) -> int:
        return 0

    def _remove_ignored(self, names) -> List[str]:
        ignor: set[str] = set()
        for patt in self._ignore_patterns:
            matchsetd = set(fnmatch.filter(names, patt))
            ignor = ignor.union(matchsetd)
        return [x for x in names if x not in ignor]
