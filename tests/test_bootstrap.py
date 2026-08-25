from pathlib import Path

from app.bootstrap import build_application
from app.config import Settings


def test_bootstrap_connects_real_adapters_and_workflow(tmp_path: Path) -> None:
    customer_file = tmp_path / "clientes.csv"
    customer_file.write_text(
        "cpf,nome,data_nascimento,limite_credito,score\n"
        "00000000000,Ana Exemplo,1990-05-20,2500.00,650\n",
        encoding="utf-8",
    )
    settings = Settings(
        project_root=tmp_path,
        customer_file=customer_file,
        audit_file=tmp_path / "audit.jsonl",
        pseudonymization_key=b"test-only-pseudonymization-key-32-bytes",
        uses_ephemeral_audit_key=False,
    )

    application = build_application(settings=settings)
    state = application.workflow.start()
    state = application.workflow.respond(state, "00000000000")
    state = application.workflow.respond(state, "20/05/1990")

    assert application.uses_ephemeral_audit_key is False
    assert state["authenticated"] is True
    assert settings.audit_file.exists()
