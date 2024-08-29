"""Process files as requested."""


import fnmatch
import logging
import os
import shutil
import warnings
from pathlib import Path
from typing import AnyStr, Callable, Iterable, List, Optional
from zipfile import ZIP_DEFLATED, ZipFile

logger = logging.getLogger("importer.fileproc")


def transplant_path(src: Path, src_root: Path, dst_root: Optional[Path]) -> Path:
    """
    Transplant the root of an absolute path.

    Get the root that src, under src_root, would have had if it were, instead,
    under dst_root.

    :param src: The source path.
    :param src_root: The root under which the path should be cut.
    :param dst_root: The root under which the path should be inserted; if None,
        no insertion will be performed.
    :return: The transplanted path.
    """
    relp = src.relative_to(src_root.resolve())
    if dst_root is None:
        return relp
    else:
        return dst_root.resolve().joinpath(relp)


class FileProcessor:
    """Process files according to settings.

    :param indir: The path of the input directory
    :param outpath: The path to which the output should symlink
    :param repopath: The path under which the files will be copied
    :param compress: Whether to compress the copied files in an archive
    :param force: Whether the copy should overwrite pre-existing stuff
    :param ignore_patterns: Globs to ignore for the copy
    """

    def __init__(
            self,
            indir: Path,
            outpath: Path,
            repopath: Path,
            compress: bool,
            force: bool,
            ignore_patterns: List[str]
    ):
        """Initialize processor."""
        self._indir = indir.resolve()
        self._outpath = outpath.resolve()
        self._repopath = repopath.resolve()
        self._compress = compress
        self._force = force
        self._ignore_patterns = ignore_patterns

    def __call__(self, cb: Callable[[str], None]) -> int:
        """Process the files with the required methods.

        :param cb: Callback, called once for each processed file.
        :return: An error code. Follows errno conventions (as much as possible).
        """
        if not self._compress:
            logger.info("Files will be copied.")
            return self.copy(cb)
        else:
            logger.info("Files will be archived.")
            return self.archive(cb)

    def count_files(self) -> int:
        """Count the files that will be processed.

        :return: The number of processed files.
        """
        n = 0
        for _, dns, fns in os.walk(self._indir):
            dns[:] = self._remove_ignored(dns)
            fns = self._remove_ignored(fns)
            n += len(fns)

        return n

    @property
    def src(self) -> Path:
        """The source directory."""
        return self._indir

    @property
    def dst(self) -> Path:
        """The destination directory or file."""
        dst_root = self._repopath.joinpath(self._indir.name)
        if self.compress:
            return dst_root.with_suffix(".zip")
        else:
            return dst_root

    @property
    def link_path(self) -> Optional[Path]:
        """The path for the symlink if needed.

        :return: The symlink path if a symlink is needed, else None.
        """
        if self._outpath != self._repopath:
            return self._outpath.joinpath(self._indir.name)
        else:
            return None

    @property
    def compress(self) -> bool:
        """Whether to create a compressed archive (True) or not (False)."""
        return self._compress

    @property
    def force(self) -> bool:
        """Overwrite if destination already exists (True) or not (False)."""
        return self._force

    def copy(self, cb: Callable[[str], None]) -> int:
        """Copy the files to destination.

        :param cb: Callback, called once for each processed file.
        :return: An error code. Follows errno conventions (as much as possible).
        """
        src_root = self.src
        dst_root = self.dst
        logger.debug(f"{src_root = }\n{dst_root = }")
        try:
            dst_root.mkdir(exist_ok=self._force)
        except FileExistsError as e:
            logger.error(f"Error while copying files: {e}")
            return 17  # EEXIST: File exists

        for curr, dns, fns in os.walk(src_root):
            curr = Path(curr).resolve()
            dst = transplant_path(curr, src_root, dst_root)
            logger.debug(f"{curr = }\n{dst = }")

            if dst != dst_root:
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

        self._symlink()

        return 0

    def archive(self, cb: Callable[[str], None]) -> int:
        """Archive the files to a compressed file.

        :param cb: Callback, called once for each processed file.
        :return: An error code. Follows errno conventions (as much as possible).
        """
        src_root = self.src
        dst_root = self.dst
        logger.debug(f"{src_root = }\n{dst_root = }")
        basename = dst_root.with_suffix("")
        if basename.exists():
            if self.force:
                warnings.warn(f"{basename} already exists, will be removed.")
                shutil.rmtree(str(basename))
            else:
                logger.error(f"{basename} already exists.")
                return 17

        mode = "w" if self.force else "a"

        zipf = ZipFile(
            dst_root,
            mode=mode,
            compression=ZIP_DEFLATED,
            compresslevel=9,
        )

        with zipf as z:
            for curr, dns, fns in os.walk(src_root):
                curr = Path(curr).resolve()
                dst = transplant_path(curr, src_root, None)
                logger.debug(f"{curr = }\n{dst = }")

                if dst != dst_root:
                    z.mkdir(str(dst))

                dns[:] = self._remove_ignored(dns)
                fns = self._remove_ignored(fns)

                for f in fns:
                    f_src_path = curr.joinpath(Path(f))
                    f_dst_path = f_src_path.relative_to(src_root)
                    description = f"Archiving {f_dst_path}"
                    cb(description)
                    z.write(f_src_path, arcname=f_dst_path)

        self._symlink()

        return 0

    def _remove_ignored(self, names: Iterable[AnyStr]) -> List[str]:
        """Remove directories and files that should be ignored.

        :param names: The filenames to filter
        :return: The filtered filenames
        """
        ignor: set[str] = set()
        for patt in self._ignore_patterns:
            matchsetd = set(fnmatch.filter(names, patt))
            ignor = ignor.union(matchsetd)
        return [x for x in names if x not in ignor]

    def _symlink(self):
        """Create a symlink of destination to outpath appropriate."""
        link_dst = self.link_path
        dst_root = self.dst
        if link_dst is not None:
            logger.info(f"Linking {dst_root} to {link_dst}")
            if link_dst.exists():
                if self._force:
                    os.remove(link_dst)
                else:
                    logger.error(f"{link_dst} already exists")
                    return 17
            link_dst.symlink_to(dst_root)
        else:
            logger.info(
                "Output path equal to repo path, skipping symlink creation.")
