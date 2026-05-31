"""Local expert-session command runner.

This module is intentionally local-only: session ids, cwd, command templates,
and accessible tools/data never enter public manifests.
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .config import ExpertSessionConfig
from .envelope import PromptRequestEnvelope


class ExpertSessionError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class ExpertSessionResult:
    command: tuple[str, ...]
    cwd: str | None
    output: str


def run_expert_session(
    config: ExpertSessionConfig,
    envelope: PromptRequestEnvelope,
) -> ExpertSessionResult:
    if not config.enabled:
        raise ExpertSessionError("expert_session is not enabled")
    prompt = render_session_prompt(config, envelope)
    command = build_session_command(config, prompt)
    cwd = _session_cwd(config)
    try:
        proc = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=config.timeout_seconds,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ExpertSessionError(f"expert session command not found: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ExpertSessionError("expert session timed out", retryable=True) from exc
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        raise ExpertSessionError(
            f"expert session exited {proc.returncode}: {stderr or 'no stderr'}",
            retryable=False,
        )
    output = (proc.stdout or "").strip()
    if not output:
        raise ExpertSessionError("expert session returned empty output")
    return ExpertSessionResult(command=tuple(command), cwd=cwd, output=output)


def render_session_prompt(config: ExpertSessionConfig, envelope: PromptRequestEnvelope) -> str:
    prompt = envelope.prompt_text()
    return config.prompt_template.format(
        prompt=prompt,
        request_id=envelope.request_id,
        selected_peer_id=envelope.selected_peer_id or "",
        requested_expertise=envelope.intent_descriptor.get("requested_expertise") or "",
        session_ref=config.session_ref or "",
    )


def build_session_command(config: ExpertSessionConfig, rendered_prompt: str) -> list[str]:
    values = {
        "prompt": rendered_prompt,
        "session_ref": config.session_ref or "",
        "cwd": _session_cwd(config) or "",
        "engine": config.engine,
    }
    if config.command_template:
        return [part.format(**values) for part in config.command_template]
    if config.engine == "claude_code":
        command = [config.command_path or "claude", "--resume", config.session_ref or ""]
        if config.resume_mode == "fork":
            command.append("--fork-session")
        command.extend(["-p", rendered_prompt])
        return command
    if config.engine == "codex":
        command = [config.command_path or "codex", "exec", "resume", config.session_ref or ""]
        command.append(rendered_prompt)
        return command
    raise ExpertSessionError(
        "expert_session.command_template is required for engine=other; "
        f"got {config.engine!r}"
    )


def shell_quote_command(command: Sequence[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def _session_cwd(config: ExpertSessionConfig) -> str | None:
    if config.cwd is None:
        return None
    return str(Path(config.cwd).resolve())
