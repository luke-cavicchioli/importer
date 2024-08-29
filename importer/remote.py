"""Manage the remote repository."""
import logging
import warnings
from ipaddress import IPv4Address, IPv6Address, ip_address
from pathlib import Path
from subprocess import CompletedProcess, run
from typing import Optional, Tuple, Union

from .statuscb import StatusCB

logger = logging.getLogger("importer.remote")

IPAddr = Union[IPv4Address, IPv6Address]

LOCALHOST = ip_address("127.0.0.1")


class RemoteRepo:
    """Remote repository as context.

    :param mountpoint: Optional path in which the remote directory should be
        mounted, defaults to "./".
    :param server_ip: Ip address to check before mounting, defaults to 127.0.0.1.
    :param ch_st_cb: StatusCB instance to set the status spinner while checking
        the remote IP, defaults to StatusCB().
    :param mnt_st_cb: StatusCB instance to set the status spinner while mounting
        the remote directory, defaults to StatusCB()
    """

    def __init__(
        self,
        mountpoint: Optional[Path] = Path("."),
        server_ip: IPAddr = LOCALHOST,
        server_ck: Optional[bool] = None,
        ck_st_cb:  StatusCB = StatusCB(),
        mnt_st_cb: StatusCB = StatusCB()
    ):
        """Initialize remote repository manager."""
        self._mountpoint = mountpoint
        if self._mountpoint is None:
            logger.info("No mountpoint specified.")
            self._passthrough = True
        else:
            self._passthrough = False
        self._server_ip = ip_address(server_ip)
        self._server_ck = server_ck
        self._ck_st_cb = ck_st_cb
        self._mnt_st_cb = mnt_st_cb

    def _ip_ck_needed(self) -> bool:
        """If a check of the IP is needed."""
        if self._server_ck is None:
            if self._server_ip == LOCALHOST:
                logger.info("Server ip is localhost, skipping check.")
                return True
            else:
                return False

        return self._server_ck

    def __enter__(self) -> Optional[Union[Path, Exception]]:
        """Check remote repository and mount it.

        :return: Either an exception if it happened during checking and
            mounting, or a Path if everything was good.
        """
        if self._passthrough:
            return None

        if self._ip_ck_needed():
            self._ck_st_cb.start()
            ip_good, msg = self._ip_ck()
            self._ck_st_cb.stop()

            if not ip_good:
                logger.error(msg)
                return Exception("Error while checking server")

            logger.info(msg)

        self._mnt_st_cb.start()
        mnt_good, msg = self._mnt()
        self._mnt_st_cb.stop()

        if not mnt_good:
            logger.error(msg)
            return Exception("Error while mounting")

        logger.info(msg)

        return self._mountpoint.resolve()

    def __exit__(self, exc_type, exc_value, traceback):
        """Unmount the remote repository."""
        logger.debug(
            f"Exiting: {exc_type = }\n{exc_value = }\n{traceback = }")

        if not self._passthrough:
            self._umnt()

        return False

    def _ip_ck(self) -> tuple[bool, str]:
        """Check the IP.

        :return: A tuple containing a bool that indicates the success of the
            check, and a string with a message.
        """
        if self._ip_ck_needed():
            return ping(self._server_ip)
        else:
            return (True, "No check was performed")

    def _mnt(self) -> Tuple[bool, str]:
        """Mount the directory.

        :return: A tuple containing a bool that indicates the success of the
            mount, and a string with a message.
        """
        return mount_remote(self._mountpoint)

    def _umnt(self) -> Tuple[bool, str]:
        """Unmount the directory.

        :return: A tuple containing a bool that indicates the success of the
            unmount, and a string with a message.
        """
        return unmount_remote(self._mountpoint)


def ping(addr: IPAddr, npkgs: int = 3, timeout: float = 2.0) -> Tuple[bool, str]:
    """Ping the specified IP address.

    :param addr: The IP address to ping.
    :param npkgs: The number of packages to send, defaults to 3.
    :param timeout: The timeout, in seconds, to wait, defaults to 2.
    """
    addrstr = str(addr)
    n = int(npkgs)
    t = float(timeout)
    cmd = ["ping", f"-c{n}", f"-l{n}", f"-W{t}", f"{addrstr}"]
    logger.debug(f"cmd = {' '.join(cmd)}")
    ret = run(cmd, capture_output=True)

    if ret.returncode == 1:
        msg = f"Server at {addrstr} did not respond."
        return (False, msg)
    elif ret.returncode == 2:
        msg = f"Error while checking server at {addrstr}:\n{ret.stderr}"

    try:
        msg = parse_ping_res(ret)
        return (True, msg)
    except Exception as e:
        warnings.warn(f"Error while parsing ping response: {e}. Continuing.")
        return (True, "")


def parse_ping_res(ret: CompletedProcess) -> str:
    """Parse the response of the ping command.

    :param ret: The return value of the subprocess call to ping command.
    :return: A string representing the ping message. 
    """
    stdout = ret.stdout.decode("utf-8")
    status_msg = stdout.split("\n")

    ip_line = status_msg[0].split(" ")
    ip = ip_line[1]

    loss_line = status_msg[-3].split(" ")
    tr = loss_line[0]
    rec = loss_line[3]
    loss_str = f"{tr}/{rec} packets received."

    time_line = status_msg[-2].split(" ")
    times = time_line[3].split("/")
    tmin = times[0]
    tmax = times[1]
    unit = time_line[4][:-1]
    time_str = f"Ping ({unit}): min {tmin}, max {tmax}"

    return f"Server check for {ip}:\n\t{loss_str}\n\t{time_str}"


def mount_remote(mountpoint: Path) -> tuple[bool, str]:
    """Mount remote directory to specified mountpoint.

    :param mountpoint: The path to which the remote directory will be mounted.
    :return: A tuple where the first element represents the success of the
        mounting procedure, and the second a string with a message.
    """
    logger.debug(f"Mounting {mountpoint = }")
    path = str(mountpoint)

    ret = run(["mountpoint", path, "-q"], capture_output=True)
    if ret.returncode == 0:
        return (True, f"{path} is already mounted.")

    ret = run(["mount", path], capture_output=True)
    if ret.returncode == 0:
        return (True, f"Mount of {path} successful.")
    else:
        return (False, ret.stderr.decode("utf-8"))


def unmount_remote(mountpoint: Path) -> tuple[bool, str]:
    """Unmount specified directory.

    :param mountpoint: The path to which the remote directory will be mounted.
    :return: A tuple where the first element represents the success of the
        mounting procedure, and the second a string with a message.
    """
    logger.debug(f"Unmounting {mountpoint = }")
    path = str(mountpoint)

    ret = run(["umount", path], capture_output=True)
    if ret == 0:
        return (True, "Unmount successful")
    else:
        return (False, ret.stderr.decode("utf8"))
