"""Unified por binary entry points."""

from __future__ import annotations

import pytest

from por.daemon.main import build_parser, legacy_client_main, legacy_expert_main, legacy_relay_main


def test_por_parser_requires_subcommand():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_legacy_entrypoints_callable():
    assert callable(legacy_relay_main)
    assert callable(legacy_expert_main)
    assert callable(legacy_client_main)


def test_udp_demo_spawns_unified_por_module():
    from por.udp_demo import _daemon_argv

    assert _daemon_argv("relay1") == ["-m", "por", "relay", "--config"]
    assert _daemon_argv("expert_art") == ["-m", "por", "expert", "--config"]


def test_python_m_por_main_importable():
    from por.daemon.main import main as por_main

    assert callable(por_main)
