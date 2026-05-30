import json
from io import StringIO

from por.log_events import PorLogEvent, emit_log_event, format_log_event


def test_json_log_event_redacts_prompt_and_token_fields():
    line = format_log_event(
        PorLogEvent(
            event="expert_selected",
            component="por-client",
            node_id="client-a",
            fields={"prompt": "private text", "score": 0.91, "nested": {"token": "secret"}},
        )
    )

    data = json.loads(line)

    assert data["schema"] == "por.log.v1"
    assert data["fields"]["prompt"] == "[redacted]"
    assert data["fields"]["nested"]["token"] == "[redacted]"
    assert data["fields"]["score"] == 0.91


def test_plain_log_event_is_stable_and_emit_writes_line():
    event = PorLogEvent(
        event="circuit_hop",
        component="por-relay",
        node_id="relay-a",
        role="relay",
        link_cid="abcd1234",
        fields={"next": "relay-b"},
    )
    stream = StringIO()

    emit_log_event(event, stream=stream, fmt="plain")

    line = stream.getvalue()
    assert "component=por-relay" in line
    assert "event=circuit_hop" in line
    assert "link_cid=abcd1234" in line
    assert "next=relay-b" in line
