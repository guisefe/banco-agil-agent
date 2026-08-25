import json
from pathlib import Path

from app.agents.triage import TriageAgent
from app.audit.writer import JsonlAuditWriter
from app.models.conversation import initial_state
from app.repositories.customers import CsvCustomerRepository

PROJECT_ROOT = Path(__file__).parent.parent
PSEUDONYMIZATION_KEY = b"integration-test-pseudonym-key-32-bytes"


def test_triage_authenticates_sample_customer_and_persists_safe_audit(
    tmp_path: Path,
) -> None:
    audit_path = tmp_path / "audit.jsonl"
    agent = TriageAgent(
        customer_repository=CsvCustomerRepository(PROJECT_ROOT / "data" / "clientes.csv"),
        audit_writer=JsonlAuditWriter(audit_path),
        pseudonymization_key=PSEUDONYMIZATION_KEY,
    )

    state = agent.start(initial_state())
    state = agent.respond(state, "000.000.000-00")
    state = agent.respond(state, "20/05/1990")
    state = agent.respond(state, "Quero consultar meu limite")

    assert state["authenticated"] is True
    assert state["active_agent"] == "credit"

    serialized_audit = audit_path.read_text(encoding="utf-8")
    records = [json.loads(line) for line in serialized_audit.splitlines()]
    assert [record["event_type"] for record in records] == [
        "conversation_started",
        "authentication_attempted",
        "agent_handoff",
    ]
    assert "00000000000" not in serialized_audit
    assert "20/05/1990" not in serialized_audit
    assert "1990-05-20" not in serialized_audit
    assert "Ana Exemplo" not in serialized_audit
