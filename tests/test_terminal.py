"""Testes do ambiente do PTY (editor não pode herdar `true` do servidor)."""

from __future__ import annotations

from app.terminal import terminal_env


def test_terminal_env_scrubs_inherited_editor(monkeypatch) -> None:
    monkeypatch.setenv("EDITOR", "true")
    monkeypatch.setenv("KUBE_EDITOR", "/usr/bin/true")
    monkeypatch.setenv("VISUAL", "true")
    monkeypatch.setenv("GIT_EDITOR", "true")
    env = terminal_env()
    for key in ("EDITOR", "VISUAL", "KUBE_EDITOR", "GIT_EDITOR"):
        assert key not in env, f"{key} não deve vazar para o terminal"
    assert env["TERM"] == "xterm-256color"


def test_terminal_env_keeps_unrelated_variables(monkeypatch) -> None:
    monkeypatch.setenv("CKA_CUSTOM_VAR", "keep-me")
    assert terminal_env().get("CKA_CUSTOM_VAR") == "keep-me"


def test_sanitize_replay_strips_queries_but_keeps_colors() -> None:
    from app.terminal import sanitize_replay

    raw = (
        "\x1b]11;?\x07\x1b[?1;2c\x1b[6n\x1b[?2026$p\x1b[2R"
        "\x1b]11;rgb:0b0b/0e0e/1414\x07"
        "hello \x1b[31mred\x1b[0m"
    )
    clean = sanitize_replay(raw)
    assert "rgb:" not in clean
    assert "$p" not in clean and "$y" not in clean
    assert "\x1b[6n" not in clean
    assert "\x1b[?1;2c" not in clean
    assert "\x1b[2R" not in clean
    assert "hello" in clean
    assert "\x1b[31m" in clean and "\x1b[0m" in clean


def test_registry_create_is_lazy() -> None:
    from app.terminal import TerminalRegistry

    registry = TerminalRegistry()
    session = registry.create("host")
    try:
        info = session.info()
        assert info["spawned"] is False
        assert info["subscribers"] == 0
        assert info["alive"] is True
    finally:
        registry.close(session.tab_id)


def test_terminal_env_isolates_kubeconfig_and_tmp(monkeypatch, tmp_path) -> None:
    from app import config
    from app.terminal import terminal_env

    monkeypatch.setenv("KUBECONFIG", "/home/user/.kube/config")
    workdir = tmp_path / "scratch-tab"
    env = terminal_env(workdir)
    assert env["KUBECONFIG"] == str(config.KUBECONFIG_PATH)
    assert env["CKA_ARENA_WORKDIR"] == str(workdir)
    assert env["TMPDIR"] == str(workdir / "tmp")


def test_scratch_helpers_guard_paths(tmp_path, monkeypatch) -> None:
    from app.terminal import TerminalRegistry, remove_scratch, scratch_dir

    root = tmp_path / "scratch"
    monkeypatch.setattr("app.config.SCRATCH_ROOT", root)
    inside = scratch_dir("tab01")
    outside = tmp_path / "project"
    assert inside == root / "tab01"

    outside.mkdir()
    remove_scratch(outside)
    assert outside.exists()          # fora de SCRATCH_ROOT: intocável
    root.mkdir(parents=True)
    remove_scratch(root)             # a raiz em si: intocável
    assert root.is_dir()

    registry = TerminalRegistry()
    session = registry.create("host")
    (root / session.tab_id).mkdir(parents=True)
    (root / "deadbeef").mkdir(parents=True)
    removed = registry.sweep_scratch()
    assert "deadbeef" in removed
    assert not (root / "deadbeef").exists()
    assert (root / session.tab_id).is_dir()    # aba viva permanece
    registry.close(session.tab_id)


def test_terminal_env_workdir_sets_vim_and_exam_files(tmp_path) -> None:
    from app.terminal import _resolve_exam_editor, terminal_env, write_exam_shell_files

    workdir = tmp_path / "tab-psi"
    write_exam_shell_files(workdir)
    env = terminal_env(workdir)

    expected_editor = _resolve_exam_editor()
    assert env["KUBE_EDITOR"] == expected_editor
    assert env["EDITOR"] == expected_editor
    assert env["VISUAL"] == expected_editor
    assert expected_editor.endswith("vim") or "nano" in expected_editor

    vimrc = (workdir / ".vimrc").read_text()
    assert "set nocompatible" in vimrc
    assert "syntax on" in vimrc
    assert "set backspace=indent,eol,start" in vimrc
    assert "set noswapfile" in vimrc
    assert "set ttimeoutlen=10" in vimrc
    assert "autocmd FileType yaml,yml" in vimrc
    assert "\nset paste\n" not in vimrc

    cka_env = (workdir / ".cka_env.sh").read_text()
    assert "alias vi=vim" in cka_env
    assert "alias k=kubectl" in cka_env
    assert "export KUBE_EDITOR=vim" in cka_env

    zshrc = (workdir / ".zshrc").read_text()
    assert "$HOME/.zshrc" not in zshrc
    assert "candidate@cka-arena" in zshrc


def test_vim_pty_exits_zero_after_search_miss(tmp_path) -> None:
    import os
    import pty
    import select
    import subprocess
    import time

    from app.terminal import _resolve_exam_editor, write_exam_shell_files

    editor = _resolve_exam_editor()
    if not editor.endswith("vim") or not os.access(editor, os.X_OK):
        return

    workdir = tmp_path / "vim-pty"
    write_exam_shell_files(workdir)
    target = workdir / "sample.yaml"
    target.write_text("apiVersion: v1\nkind: Pod\n")

    master, slave = pty.openpty()
    env = dict(os.environ)
    env["VIMINIT"] = f"source {workdir / '.vimrc'}"
    env["TERM"] = "xterm-256color"
    proc = subprocess.Popen(
        [editor, str(target)],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env=env,
        close_fds=True,
    )
    os.close(slave)
    try:
        time.sleep(0.25)
        os.write(master, b"/notfound\r:wq\r")
        deadline = time.time() + 3.0
        while proc.poll() is None and time.time() < deadline:
            ready, _, _ = select.select([master], [], [], 0.1)
            if ready:
                try:
                    os.read(master, 4096)
                except OSError:
                    break
        assert proc.wait(timeout=2) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
        os.close(master)
