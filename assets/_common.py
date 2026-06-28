"""
AstrBot Skill - SSH common library.

Shared foundation for all remote-operation tools in this skill. Provides:
  - login.config discovery + parsing (single source of truth)
  - connection management (single client per operation, no re-connect per call)
  - exec / read_file / write_file / upload_file / download_file primitives
  - ExecResult dataclass for structured command output

Design rules:
  - Never print to stdout from library code; return structured results.
    CLI wrappers decide what to print.
  - Raise specific exceptions (SshConfigError, SshExecError) so callers can
    catch granularly.
  - All file writes go through SFTP (no heredoc, no BOM issues).

Imported by: ssh-exec.py, config-tool.py, plugin-scaffold.py (for sync),
astrbot-api.py does NOT use this (it does pure HTTP).

Usage:
    import sys; sys.path.insert(0, str(Path(__file__).parent))
    from _common import load_credentials, connect, exec_command, read_file, write_file
"""
from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path

try:
    import paramiko
except ImportError as e:
    raise ImportError(
        "paramiko not installed. Run: pip install paramiko"
    ) from e


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SshConfigError(Exception):
    """login.config missing / malformed."""


class SshExecError(Exception):
    """Remote command failed (non-zero exit or SSH error)."""


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class Credentials:
    host: str
    port: int
    username: str
    password: str

    def __str__(self) -> str:
        return f"{self.username}@{self.host}:{self.port}"


@dataclass
class ExecResult:
    rc: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.rc == 0


# ---------------------------------------------------------------------------
# login.config discovery + parsing  (single source of truth)
# ---------------------------------------------------------------------------

LOGIN_CONFIG_FILENAME = "login.config"
ENV_VAR = "ASTRBOT_LOGIN_CONFIG"


def find_login_config(explicit: str | None = None) -> Path | None:
    """Locate login.config.

    Order: explicit arg > $ASTRBOT_LOGIN_CONFIG > ./login.config and walk up
    parent directories until found or root reached.
    """
    if explicit:
        p = Path(explicit).expanduser().resolve()
        return p if p.is_file() else None
    env = os.environ.get(ENV_VAR)
    if env:
        p = Path(env).expanduser().resolve()
        return p if p.is_file() else None
    cwd = Path.cwd()
    for d in [cwd, *cwd.parents]:
        cand = d / LOGIN_CONFIG_FILENAME
        if cand.is_file():
            return cand
    return None


def parse_login_config(path: Path) -> Credentials:
    """Parse login.config into Credentials.

    Accepted formats (both work; unprefixed is preferred for new files):

    Unprefixed (recommended):
        IP:PORT
        username
        password
        https://github.com/user          # optional, line 4

    Prefixed (legacy, still supported):
        ssh:IP:PORT
        name:username
        psw:password

    The function tolerates either style per line so old files keep working
    without migration. New files should use the unprefixed form.
    """
    text = path.read_text(encoding="utf-8")
    lines = [ln.rstrip() for ln in text.strip().splitlines() if ln.strip()]
    if len(lines) < 3:
        raise SshConfigError(
            f"login.config needs >=3 non-empty lines, got {len(lines)}: {path}"
        )

    def split_kv(line: str) -> tuple[str, str]:
        for prefix in ("ssh:", "name:", "psw:"):
            if line.lower().startswith(prefix):
                return prefix.rstrip(":"), line[len(prefix):].strip()
        return "", line.strip()

    host = port = user = psw = ""
    for i, line in enumerate(lines[:4]):
        key, val = split_kv(line)
        if i == 0 and (key == "ssh" or key == ""):
            parts = val.split(":")
            host = parts[0]
            port = parts[1] if len(parts) > 1 else "22"
        elif key == "name" or (i == 1 and key == ""):
            user = val
        elif key == "psw" or (i == 2 and key == ""):
            psw = val

    if not (host and port and user):
        raise SshConfigError(
            f"login.config parse failed at {path}. "
            f"host={host!r} port={port!r} user={user!r}"
        )
    try:
        port_int = int(port)
    except ValueError as e:
        raise SshConfigError(f"login.config port not integer: {port!r}") from e
    return Credentials(host=host, port=port_int, username=user, password=psw)


def load_credentials(
    *,
    explicit_path: str | None = None,
    host: str | None = None,
    port: int | None = None,
    user: str | None = None,
    password: str | None = None,
    quiet: bool = False,
) -> Credentials:
    """Resolve credentials: prefer explicit fields, else read login.config.

    If `quiet` is False, prints the source (stderr) so the user can see which
    login.config was used. CLI wrappers may set quiet=True to suppress.
    """
    if host and user and password:
        return Credentials(
            host=host, port=port or 22, username=user, password=password
        )
    cfg = find_login_config(explicit_path)
    if cfg is None:
        raise SshConfigError(
            "login.config not found. Provide --host/--user/--pass, or "
            "--login-config, or set $ASTRBOT_LOGIN_CONFIG, or place "
            "login.config in the project root."
        )
    creds = parse_login_config(cfg)
    if not quiet:
        import sys
        sys.stderr.write(f"[_common] using {creds} (from {cfg})\n")
    return creds


# ---------------------------------------------------------------------------
# Connection + exec primitives
# ---------------------------------------------------------------------------

def connect(creds: Credentials, timeout: int = 15) -> paramiko.SSHClient:
    """Open a new SSH client. Caller is responsible for closing.

    For multi-step operations prefer: `with connect(creds) as client:`
    """
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(
        creds.host,
        port=creds.port,
        username=creds.username,
        password=creds.password,
        timeout=timeout,
    )
    return c


def exec_command(
    creds: Credentials,
    command: str,
    *,
    timeout: int = 120,
    client: paramiko.SSHClient | None = None,
) -> ExecResult:
    """Run a shell command remotely. Returns ExecResult.

    If `client` is None, opens a fresh connection and closes it after.
    If `client` provided, reuses it (caller closes).
    """
    own_client = client is None
    if own_client:
        client = connect(creds)
    try:
        _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
        rc = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        return ExecResult(rc=rc, stdout=out, stderr=err)
    finally:
        if own_client:
            client.close()


def read_file(creds: Credentials, remote_path: str) -> str:
    """Read a remote file via SFTP. Raises SshExecError on missing/failed."""
    client = connect(creds)
    try:
        sftp = client.open_sftp()
        try:
            with sftp.open(remote_path, "r") as f:
                content = f.read().decode("utf-8", errors="replace")
            return content
        except FileNotFoundError as e:
            raise SshExecError(f"remote file not found: {remote_path}") from e
        finally:
            sftp.close()
    finally:
        client.close()


def write_file(creds: Credentials, remote_path: str, content: str) -> None:
    """Write string content to a remote path via SFTP (no BOM, no heredoc).

    Creates parent directories as needed (single connection, no re-connect).
    """
    client = connect(creds)
    try:
        sftp = client.open_sftp()
        try:
            remote_dir = str(Path(remote_path).parent)
            _ensure_remote_dir(sftp, remote_dir)
            with sftp.open(remote_path, "w") as f:
                f.write(content)
        finally:
            sftp.close()
    finally:
        client.close()


def upload_file(creds: Credentials, local_path: str, remote_path: str) -> None:
    """SFTP upload a local file. Creates remote parent dirs."""
    if not os.path.isfile(local_path):
        raise FileNotFoundError(f"local not found: {local_path}")
    client = connect(creds)
    try:
        sftp = client.open_sftp()
        try:
            remote_dir = str(Path(remote_path).parent)
            _ensure_remote_dir(sftp, remote_dir)
            sftp.put(local_path, remote_path)
        finally:
            sftp.close()
    finally:
        client.close()


def download_file(creds: Credentials, remote_path: str, local_path: str) -> None:
    """SFTP download a remote file to local."""
    client = connect(creds)
    try:
        sftp = client.open_sftp()
        try:
            sftp.get(remote_path, local_path)
        except FileNotFoundError as e:
            raise SshExecError(f"remote not found: {remote_path}") from e
        finally:
            sftp.close()
    finally:
        client.close()


def _ensure_remote_dir(sftp: "paramiko.SFTPClient", remote_dir: str) -> None:
    """Recursively ensure a remote directory exists via SFTP. Idempotent.

    Walks the path components and mkdir each if missing. Uses the SFTP client
    passed in (no new SSH connection).
    """
    if not remote_dir or remote_dir in (".", "/"):
        return
    # Normalize POSIX-style
    remote_dir = remote_dir.replace("\\", "/").rstrip("/")
    parts = remote_dir.split("/")
    # Reconstruct absolute path
    if remote_dir.startswith("/"):
        cur = ""
    else:
        cur = "."
    for part in parts:
        if not part:
            continue
        cur = f"{cur}/{part}" if cur else part
        try:
            sftp.stat(cur)
        except FileNotFoundError:
            try:
                sftp.mkdir(cur)
            except OSError:
                # Race or permission; ignore — stat above will catch real misses
                pass


# ---------------------------------------------------------------------------
# Convenience: invoke_shell for interactive commands (astrbot init etc.)
# ---------------------------------------------------------------------------

def invoke_shell_send(
    creds: Credentials,
    lines: list[str],
    *,
    read_timeout: float = 5.0,
    inter_send_delay: float = 1.5,
) -> str:
    """Open an interactive shell, send lines one by one, return full output.

    Use ONLY for commands that need terminal interaction (e.g. `astrbot init`
    with Y/n prompts). For normal commands use exec_command.

    `lines` example: ["cd /opt/astrbot", "astrbot init", "Y"]
    """
    import time
    client = connect(creds)
    try:
        ch = client.invoke_shell()
        ch.settimeout(read_timeout)
        out_buf: list[str] = []
        for i, line in enumerate(lines):
            if i == 0:
                # drain initial banner
                time.sleep(inter_send_delay)
                while ch.recv_ready():
                    out_buf.append(ch.recv(4096).decode("utf-8", errors="replace"))
            ch.send(line + "\n")
            time.sleep(inter_send_delay)
            while ch.recv_ready():
                out_buf.append(ch.recv(4096).decode("utf-8", errors="replace"))
        ch.close()
        return "".join(out_buf)
    finally:
        client.close()


# ---------------------------------------------------------------------------
# Self-test when run directly
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="SSH common lib self-test")
    p.add_argument("--login-config")
    sub = p.add_subparsers(dest="action")
    sub.add_parser("show-creds", help="parse + print credentials only")
    s_exec = sub.add_parser("exec", help="run one command to verify connectivity")
    s_exec.add_argument("command")
    args = p.parse_args()
    creds = load_credentials(explicit_path=args.login_config)
    if args.action in (None, "show-creds"):
        print(f"host={creds.host} port={creds.port} user={creds.username}")
    elif args.action == "exec":
        r = exec_command(creds, args.command)
        print(r.stdout, end="")
        if r.stderr:
            print(r.stderr, end="", file=os.stderr)
        print(f"[rc={r.rc}]", file=os.stderr)
