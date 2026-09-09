"""Exercise real CSV adapters and graph with isolated synthetic data, without a provider."""

import csv
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory

from app.bootstrap import build_application
from app.config import load_settings

SCENARIOS = (
    ("approval", "00000000000", "20/05/1990", "4000", "aprovado", "4000.00"),
    ("rejection", "33333333333", "08/09/1978", "4000", "rejeitado", "800.00"),
    ("missing_score", "22222222222", "14/02/1995", "4000", "pendente", "1200.00"),
)


def main() -> None:
    source = Path(__file__).resolve().parents[1] / "data"
    for name, cpf, birth, amount, expected_status, expected_limit in SCENARIOS:
        with TemporaryDirectory(prefix="banking-demo-") as directory:
            root = Path(directory)
            data = root / "data"
            data.mkdir()
            for filename in ("clientes.csv", "score_limite.csv"):
                copyfile(source / filename, data / filename)
            settings = load_settings(project_root=root, environment={})
            workflow = build_application(settings=settings).workflow
            state = workflow.start()
            for message in (cpf, birth, "aumentar limite", amount):
                state = workflow.respond(state, message)
            with settings.credit_request_file.open(newline="", encoding="utf-8") as stream:
                requests = list(csv.DictReader(stream))
            with settings.customer_file.open(newline="", encoding="utf-8") as stream:
                customer = next(row for row in csv.DictReader(stream) if row["cpf"] == cpf)
            if len(requests) != 1 or requests[0]["status_pedido"] != expected_status:
                raise RuntimeError(f"{name}: unexpected persisted request status")
            if customer["limite_credito"] != expected_limit:
                raise RuntimeError(f"{name}: unexpected persisted limit")
            if expected_status != "aprovado" and state["credit_stage"] != "offering_interview":
                raise RuntimeError(f"{name}: expected interview offer")
            print(f"PASS {name}: persisted status={expected_status}; expected limit verified")
    print("3/3 local scenarios passed; no live LLM or exchange request was made.")


if __name__ == "__main__":
    main()
