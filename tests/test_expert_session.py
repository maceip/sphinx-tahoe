import sys
from pathlib import Path

from por.config import ExpertSessionConfig
from por.envelope import PromptRequestEnvelope
from por.expert_session import build_session_command, run_expert_session
from por.provider import stream_expert_reply


GOLDEN_DIR = Path(__file__).parent / "golden_assets"


def test_builds_default_claude_and_codex_resume_commands():
    claude = ExpertSessionConfig.from_dict(
        {"enabled": True, "engine": "claude_code", "session_ref": "claude-session-1"}
    )
    codex = ExpertSessionConfig.from_dict(
        {"enabled": True, "engine": "codex", "session_ref": "codex-session-1", "resume_mode": "resume"}
    )

    assert build_session_command(claude, "question") == [
        "claude",
        "--resume",
        "claude-session-1",
        "--fork-session",
        "-p",
        "question",
    ]
    assert build_session_command(codex, "question") == [
        "codex",
        "exec",
        "resume",
        "codex-session-1",
        "question",
    ]


def test_expert_session_runner_executes_against_session_material(tmp_path):
    session_file = GOLDEN_DIR / "topic_x_claude_session.jsonl"
    runner = tmp_path / "fake_session_runner.py"
    runner.write_text(
        "import pathlib, sys\n"
        "material = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')\n"
        "prompt = sys.argv[2]\n"
        "print('SESSION_MATERIAL=' + material.split(':', 1)[0])\n"
        "print('PROMPT=' + prompt)\n",
        encoding="utf-8",
    )
    config = ExpertSessionConfig.from_dict(
        {
            "enabled": True,
            "engine": "other",
            "cwd": str(tmp_path),
            "session_ref": str(session_file),
            "command_template": [sys.executable, str(runner), "{session_ref}", "{prompt}"],
            "prompt_template": "Answer from compiled material only: {prompt}",
        }
    )
    envelope = PromptRequestEnvelope.visible_prompt(
        prompt="How should topic X answer?",
        selected_peer_id="peer-topic-x",
        requested_expertise="topic X",
    )

    result = run_expert_session(config, envelope)

    assert "SESSION_MATERIAL={\"type\"" in result.output
    assert "Answer from compiled material only" in result.output
    assert "How should topic X answer?" in result.output


def test_provider_uses_configured_expert_session(tmp_path):
    runner = tmp_path / "fake_claude.py"
    runner.write_text(
        "import sys\n"
        "print('expert-session-response:' + sys.argv[1] + ':' + sys.argv[2])\n",
        encoding="utf-8",
    )
    config = ExpertSessionConfig.from_dict(
        {
            "enabled": True,
            "engine": "claude_code",
            "session_ref": "compiled-session",
            "command_template": [sys.executable, str(runner), "{session_ref}", "{prompt}"],
        }
    )
    envelope = PromptRequestEnvelope.visible_prompt(
        prompt="user routed prompt",
        selected_peer_id="peer-topic-x",
        requested_expertise="topic X",
    )

    text = "".join(stream_expert_reply(envelope, "peer-topic-x", expert_session_config=config))

    assert "expert-session-response:compiled-session:user routed prompt" == text
