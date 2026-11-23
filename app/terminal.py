"""TerminalService — PTY real do host + WebSocket (ARCHITECTURE.md §8)."""

from __future__ import annotations

import asyncio
import fcntl
import os
import pty
import re
import shutil
import signal
import struct
import termios
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from app import config, provider

MAX_TABS = 6
IDLE_TIMEOUT_S = 30 * 60
REPLAY_LIMIT_BYTES = 256 * 1024


class TerminalError(RuntimeError):
    pass


_EDITOR_VARS = ("EDITOR", "VISUAL", "KUBE_EDITOR", "GIT_EDITOR")


_SECRET_CMD_RE = re.compile(r"(token|password|passwd|api[_-]?key|secret|sk-[a-z0-9]{8,}|export\s+\w*KEY)", re.I)

EXAM_VIMRC_TEXT = """set nocompatible
filetype plugin indent on
syntax on
set encoding=utf-8
set tabstop=2
set shiftwidth=2
set softtabstop=2
set expandtab
set autoindent
set backspace=indent,eol,start
set number
set ruler
set showcmd
set showmode
set cursorline
set incsearch
set hlsearch
set ignorecase
set smartcase
set wildmenu
set scrolloff=3
set ttimeout
set ttimeoutlen=10
set nobackup
set nowritebackup
set noswapfile
set pastetoggle=<F2>
autocmd FileType yaml,yml setlocal ts=2 sts=2 sw=2 expandtab autoindent indentkeys-=0# indentkeys-=<:>
"""
_VIMRC_TEXT = EXAM_VIMRC_TEXT

_CKA_ENV_SH = r"""# CKA Arena Exam-Ready Shell Profile
if command -v vim >/dev/null 2>&1; then
  export KUBE_EDITOR=vim
  export EDITOR=vim
  export VISUAL=vim
  alias vi=vim
fi
alias k=kubectl
export do="--dry-run=client -o yaml"
export now="--force --grace-period=0"

if command -v kubectl >/dev/null 2>&1; then
  if [ -n "${ZSH_VERSION:-}" ]; then
    autoload -Uz compinit 2>/dev/null && compinit -C -d "$CKA_ARENA_WORKDIR/.zcompdump" 2>/dev/null
    source <(kubectl completion zsh) 2>/dev/null || true
    compdef k=kubectl 2>/dev/null || true
    _cka_preexec() {
      [ -n "$1" ] && printf '%s\n' "$1" >> "$CKA_ARENA_WORKDIR/.cmd_history.log" 2>/dev/null || true
    }
    autoload -Uz add-zsh-hook 2>/dev/null && add-zsh-hook preexec _cka_preexec 2>/dev/null || true
  elif [ -n "${BASH_VERSION:-}" ]; then
    source <(kubectl completion bash) 2>/dev/null || true
    complete -o default -F __start_kubectl k 2>/dev/null || true
    PROMPT_COMMAND='history 1 | sed "s/^[ ]*[0-9]*[ ]*//" >> "$CKA_ARENA_WORKDIR/.cmd_history.log" 2>/dev/null || true'
  fi
fi
"""

_ZSHRC_TEXT = r"""# CKA Arena Exam Shell (.zshrc) — clean PSI exam environment
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin${PATH:+:$PATH}"
bindkey -e
setopt interactive_comments prompt_subst
HISTFILE="$CKA_ARENA_WORKDIR/.zsh_history"
HISTSIZE=2000
SAVEHIST=2000

_cka_kctx() {
  [ -r "${KUBECONFIG:-}" ] || { printf 'cka'; return; }
  awk '/^current-context:/{print $2; found=1; exit} END{if(!found) print "cka"}' "$KUBECONFIG" 2>/dev/null
}

PROMPT='%F{green}candidate@cka-arena%f %F{cyan}[$(_cka_kctx)]%f %F{blue}%1~%f $ '
[ -f "$CKA_EXAM_PROFILE" ] && source "$CKA_EXAM_PROFILE" 2>/dev/null || true
"""


def _resolve_exam_editor() -> str:
    """Prefer vim over vi so benign search misses do not exit 1 on kubectl edit."""
    vim_bin = shutil.which("vim") or ("/usr/bin/vim" if os.access("/usr/bin/vim", os.X_OK) else None)
    if vim_bin:
        return vim_bin
    return shutil.which("nano") or "vi"


def write_exam_shell_files(workdir: Path) -> None:
    """Create isolated .vimrc, .cka_env.sh, and ZDOTDIR .zshrc inside scratch workdir."""
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "tmp").mkdir(parents=True, exist_ok=True)
    (workdir / ".vimrc").write_text(EXAM_VIMRC_TEXT)
    (workdir / ".cka_env.sh").write_text(_CKA_ENV_SH)
    (workdir / ".zshrc").write_text(_ZSHRC_TEXT)


def terminal_env(workdir: Path | None = None) -> dict[str, str]:
    """Ambiente do PTY isolado do resto do sistema.

    - Editor: limpa variáveis herdadas e, com workdir de sessão, fixa KUBE_EDITOR/
      EDITOR/VISUAL em vim (evitando `error: there was a problem with the editor "vi"`).
    - kubectl: sempre o kubeconfig dedicado do CKA Arena — nunca a config global
      do usuário (contextos EKS etc.).
    - Arquivos: o shell nasce numa workdir scratch por aba (cwd/TMPDIR), com aliases CKA
      (`.cka_env.sh` + `.vimrc`) e `.zshrc` PSI limpo isolados dentro da pasta scratch.
    """
    drop = _EDITOR_VARS + ("KUBECONFIG",)
    env = {key: value for key, value in os.environ.items() if key not in drop}
    env["TERM"] = "xterm-256color"
    env["KUBECONFIG"] = str(config.KUBECONFIG_PATH)
    env["CKA_ASSETS"] = str(config.ASSETS_DIR)
    if workdir is not None:
        editor = _resolve_exam_editor()
        env["KUBE_EDITOR"] = editor
        env["EDITOR"] = editor
        env["VISUAL"] = editor
        env["CKA_ARENA_WORKDIR"] = str(workdir)
        env["TMPDIR"] = str(workdir / "tmp")
        env["VIMINIT"] = f"source {workdir / '.vimrc'}"
        env["CKA_EXAM_PROFILE"] = str(workdir / ".cka_env.sh")
        env["ZDOTDIR"] = str(workdir)
        env["BASH_ENV"] = str(workdir / ".cka_env.sh")
    return env


_REPLAY_NOISE = (
    re.compile(r"\x1b\](?:4|10|11|12);\?[^\x07\x1b]*(?:\x07|\x1b\\)"),
    re.compile(r"\x1b\][^\x07\x1b]*\?[^\x07\x1b]*(?:\x07|\x1b\\)"),
    re.compile(r"(?:\x1b\])?(?:10|11|12);rgb:[0-9a-fA-F]{1,4}/[0-9a-fA-F]{1,4}/[0-9a-fA-F]{1,4}(?:\x07|\x1b\\)?"),
    re.compile(r"\x1b\[[?>]?[0-9;]*c"),
    re.compile(r"\x1b\[[0-9;]*n"),
    re.compile(r"\x1b\[[?>]?[0-9;]*\$[py]"),
    re.compile(r"(?:\x1b\[)?[?>]?[0-9;]*\$y"),
    re.compile(r"\x1b\[[0-9;]*t"),
    re.compile(r"\x1b\[[0-9;]*R"),
    re.compile(r"(?:\x1b\[)?[0-9]+;[0-9]+R"),
    re.compile(r"\x1bP.*?\x1b\\", re.S),
)


def sanitize_replay(text: str) -> str:
    """Remove do replay sequências que solicitam/responsabilizam o terminal.

    O p10k (e outros prompts) pergunta cores/posição ao terminal; ao reattach, o xterm
    responderia queries históricas e as respostas voltariam ao PTY — loop visível como
    `rgb:...`/`$y` no prompt. SGR (cores), OSC de título e movimentos de cursor são mantidos.
    """
    for pattern in _REPLAY_NOISE:
        text = pattern.sub("", text)
    return text


def scratch_dir(tab_id: str) -> Path:
    """Workdir isolada de uma aba — sempre dentro de SCRATCH_ROOT (guarda de caminho)."""
    return config.SCRATCH_ROOT / tab_id


def remove_scratch(path: Path | None) -> None:
    """Apaga uma workdir scratch; recusa caminho fora de SCRATCH_ROOT."""
    if path is None:
        return
    try:
        resolved = path.resolve()
        root = config.SCRATCH_ROOT.resolve()
        if resolved == root or root not in resolved.parents:
            return
        shutil.rmtree(resolved, ignore_errors=True)
    except OSError:
        pass


@dataclass
class TerminalSession:
    tab_id: str
    preset: str
    node: str | None = None
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    master_fd: int = -1
    pid: int = -1
    exit_status: int | None = None
    spawned: bool = False
    workdir: Path | None = None
    _buffer: list[str] = field(default_factory=list)
    _buffer_bytes: int = 0
    _subscribers: set[asyncio.Queue] = field(default_factory=set)
    _loop: asyncio.AbstractEventLoop | None = None

    def spawn(self) -> None:
        if self.spawned:
            return
        self.spawned = True
        if self.preset == "host":
            config.ensure_dirs()
            self.workdir = scratch_dir(self.tab_id)
            write_exam_shell_files(self.workdir)
            assets_link = self.workdir / "assets"
            if config.ASSETS_DIR.is_dir() and not assets_link.exists():
                try:
                    assets_link.symlink_to(config.ASSETS_DIR)
                except OSError:
                    pass
        master_fd, slave_fd = pty.openpty()
        self.master_fd = master_fd
        self._set_winsize(120, 30)
        pid = os.fork()
        if pid == 0:  # ---- child
            try:
                os.setsid()
                fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
                os.dup2(slave_fd, 0)
                os.dup2(slave_fd, 1)
                os.dup2(slave_fd, 2)
                os.close(master_fd)
                os.close(slave_fd)
                env = terminal_env(self.workdir)
                env["CKA_ARENA_TAB"] = self.tab_id
                if self.preset == "node" and self.node:
                    # multipass → `ssh cka-<node>`; kind → `docker exec -it <ctr> bash`
                    cmd = provider.get().terminal_command(self.node)
                    os.execvpe(cmd[0], cmd, env)
                if self.workdir is not None:
                    os.chdir(self.workdir)
                shell = env.get("SHELL", "/bin/zsh")
                os.execvpe(shell, [shell, "-l"], env)
            except Exception:
                os._exit(127)
        os.close(slave_fd)
        self.pid = pid
        self._loop = asyncio.get_running_loop()
        self._loop.add_reader(self.master_fd, self._on_readable)

    # ------------------------------------------------------------ io

    def _on_readable(self) -> None:
        try:
            data = os.read(self.master_fd, 65536)
        except OSError:
            data = b""
        if not data:
            self.close(exit_status=self.exit_status or 0)
            return
        text = data.decode("utf-8", errors="replace")
        self.last_activity = time.time()
        self._append_buffer(text)
        self._broadcast({"type": "output", "data": text})

    def _append_buffer(self, text: str) -> None:
        self._buffer.append(text)
        self._buffer_bytes += len(text.encode("utf-8", errors="replace"))
        while self._buffer_bytes > REPLAY_LIMIT_BYTES and len(self._buffer) > 1:
            removed = self._buffer.pop(0)
            self._buffer_bytes -= len(removed.encode("utf-8", errors="replace"))

    def replay(self) -> str:
        return sanitize_replay("".join(self._buffer))

    def write(self, data: str) -> None:
        if self.master_fd < 0:
            return
        self.last_activity = time.time()
        try:
            os.write(self.master_fd, data.encode("utf-8", errors="replace"))
        except OSError:
            self.close(exit_status=1)

    def resize(self, cols: int, rows: int) -> None:
        cols = max(20, min(400, int(cols)))
        rows = max(5, min(200, int(rows)))
        self._set_winsize(cols, rows)

    def _set_winsize(self, cols: int, rows: int) -> None:
        if self.master_fd < 0:
            return
        try:
            fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ,
                        struct.pack("HHHH", rows, cols, 0, 0))
        except OSError:
            pass

    # ------------------------------------------------------------ pub/sub

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=512)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def _broadcast(self, message: dict) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                pass

    # ------------------------------------------------------------ lifecycle

    def close(self, exit_status: int = 0) -> None:
        if self.exit_status is not None:
            return
        self.exit_status = exit_status
        if self._loop and self.master_fd >= 0:
            try:
                self._loop.remove_reader(self.master_fd)
            except (OSError, ValueError):
                pass
        if self.pid > 0:
            try:
                os.killpg(self.pid, signal.SIGHUP)
            except ProcessLookupError:
                pass
            try:
                os.waitpid(self.pid, os.WNOHANG)
            except ChildProcessError:
                pass
        if self.master_fd >= 0:
            try:
                os.close(self.master_fd)
            except OSError:
                pass
            self.master_fd = -1
        remove_scratch(self.workdir)
        self._broadcast({"type": "exit", "code": exit_status})

    def info(self) -> dict:
        return {
            "tab_id": self.tab_id,
            "preset": self.preset,
            "node": self.node,
            "created_at": self.created_at,
            "last_activity": self.last_activity,
            "alive": self.exit_status is None,
            "spawned": self.spawned,
            "subscribers": len(self._subscribers),
            "workdir": str(self.workdir) if self.workdir else None,
        }


class TerminalRegistry:
    def __init__(self) -> None:
        self._sessions: dict[str, TerminalSession] = {}

    def create(self, preset: str, node: str | None = None) -> TerminalSession:
        if preset not in ("host", "node"):
            raise TerminalError(f"preset inválido: {preset}")
        alive = [s for s in self._sessions.values() if s.exit_status is None]
        if len(alive) >= MAX_TABS:
            raise TerminalError(f"limite de {MAX_TABS} abas ativas")
        tab_id = uuid.uuid4().hex[:10]
        session = TerminalSession(tab_id=tab_id, preset=preset, node=node)
        self._sessions[tab_id] = session  # shell só nasce quando o xterm conecta (spawn lazy)
        return session

    def get(self, tab_id: str) -> TerminalSession | None:
        return self._sessions.get(tab_id)

    def list(self) -> list[dict]:
        return [s.info() for s in self._sessions.values() if s.exit_status is None]

    def close(self, tab_id: str) -> bool:
        session = self._sessions.get(tab_id)
        if not session:
            return False
        session.close()
        return True

    def prune_idle(self) -> list[str]:
        """Fecha PTYs sem assinantes (reload tem 120s de graça) e shells ociosos (30 min)."""
        now = time.time()
        closed: list[str] = []
        for tab_id, session in list(self._sessions.items()):
            idle = now - session.last_activity
            abandoned = not session._subscribers and idle > 120
            expired = idle > IDLE_TIMEOUT_S
            if session.exit_status is not None or abandoned or expired:
                session.close()
                closed.append(tab_id)
        return closed

    def collect_command_history(self, session_id: str, session_item_id: str) -> list[str]:
        """Drain logged commands from active host tabs into DB command_audit (redacted)."""
        from app import db

        collected: list[str] = []
        now = time.time()
        for session in list(self._sessions.values()):
            if session.exit_status is not None or session.preset != "host" or not session.workdir:
                continue
            log_file = session.workdir / ".cmd_history.log"
            if not log_file.is_file():
                continue
            try:
                raw_lines = log_file.read_text(errors="replace").splitlines()
                log_file.write_text("")
            except OSError:
                continue
            for line in raw_lines:
                clean = line.strip()
                if not clean or _SECRET_CMD_RE.search(clean):
                    continue
                collected.append(clean[:400])

        if collected:
            try:
                with db.connect() as conn:
                    for cmd in collected[:100]:
                        conn.execute(
                            "INSERT INTO command_audit (id, session_id, session_item_id, command_text, ran_at)"
                            " VALUES (?, ?, ?, ?, ?)",
                            (f"ca-{uuid.uuid4().hex[:12]}", session_id, session_item_id, cmd, now),
                        )
            except Exception:
                pass
        return collected

    def sweep_scratch(self) -> list[str]:
        """Remove workdirs órfãs ( crash/reinício do servidor): no startup o
        registry está vazio, então toda workdir existente é lixo."""
        removed: list[str] = []
        if not config.SCRATCH_ROOT.is_dir():
            return removed
        live = {s.tab_id for s in self._sessions.values() if s.exit_status is None}
        for child in config.SCRATCH_ROOT.iterdir():
            if child.name in live:
                continue
            remove_scratch(child)
            removed.append(child.name)
        return removed
