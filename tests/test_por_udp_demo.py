from por.udp_demo import run_demo


def test_udp_demo_expert_mode_streams_over_process_nodes():
    result = run_demo(timeout=8.0)

    assert result.selected_peer_id == "expert_art"
    assert result.degraded_anonymity is True
    assert result.fallback_used is False
    assert "[wire-harness expert_reply]" in result.response_text
    assert "llm_called=no" in result.response_text
    assert "event=forward_hop" in result.node_logs
    assert "event=expert_exit" in result.node_logs
    assert "prompt_visible=no" in result.node_logs
    assert "prompt_visible=yes" in result.node_logs
    assert "event=circuit_hop" in result.node_logs
    assert "event=stream_chunk" in result.client_logs
