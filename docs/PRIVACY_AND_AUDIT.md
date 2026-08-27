# Privacy and audit design

This document records engineering safeguards inspired by the LGPD. It does not, by
itself, certify legal compliance. The controller must still define the purpose and legal
basis of each processing operation, retention periods, data-subject service procedures,
contracts, access policies, and incident response.

## Audit purpose

The audit trail exists to reconstruct security-sensitive and business-relevant actions:

- conversation start and end;
- authentication attempts, without credentials or raw identifiers;
- handoffs between agents;
- credit decisions and the version of the deterministic policy used;
- changes to the customer risk profile.
- exchange quote requests, without API payloads or raw customer identifiers.

Audit data must not be reused for advertising, model training, employee surveillance, or
another incompatible purpose without a new assessment.

## Data minimization contract

Allowed fields are event and conversation identifiers, UTC timestamp, turn number, agent,
event type, controlled outcome, controlled reason code, pseudonymous subject reference,
and policy version.

Never record raw CPF, birth date, customer name, income, expenses, debts, dependents,
messages, prompts, currency requests, API payloads, access tokens, secrets, or stack traces
containing those values. Reason codes are uppercase machine-readable identifiers, not free text.

Financial interview answers exist only in the in-memory conversation state while the five
questions are being completed. The UI replaces them with neutral labels, and the fields are
cleared after score recalculation or global conversation termination.

The customer's own chat uses proportional, partial masking instead of hiding all context:
the CPF keeps only its last two digits and the birth date keeps only the year. Raw values
remain available to the authentication operation but are not copied into chat history,
technical logs, or audit events.

## LLM data boundary

The LLM is a non-critical language interpreter, not a banking decision maker. After successful
authentication, Triagem, Credit, Interview, and Exchange may use it to identify an intent or
normalize one expected field. CPF and birth-date patterns are replaced before the request.
Customer name, current limit, score, stored profile, policy rows, and previous messages are not
added to its prompt.

The provider receives only the current message, truncated to 1,000 characters. Depending on
the active stage, that message may contain a requested amount or one financial interview
answer. Its output must match a closed JSON schema for intent/entity extraction or a single
normalized field. The Python domain validates the result and remains solely responsible for
authentication, score calculation, credit approval, and persistence. A timeout, HTTP failure,
invalid JSON, unsupported value, or inconsistent field activates the deterministic fallback.

Audit records only whether interpretation used the LLM or the fallback and the policy version.
It does not record the prompt, response, message, inferred intent, provider payload, or API key.
For real personal data, the controller would still need a lawful basis, provider assessment,
contractual safeguards, international-transfer analysis where applicable, retention controls,
and a documented data-flow inventory.

`subject_ref` is produced with HMAC-SHA-256 and a secret key of at least 32 bytes. The key
must come from a secret manager or protected environment variable and must never be stored
in Git. HMAC pseudonymization reduces exposure, but it is not anonymization: the reference
remains personal data while it can be related back to a person.

## Explainable credit decisions

Credit rules remain deterministic. Every approved or rejected decision records a
controlled `reason_code` and `policy_version`, never a hidden LLM rationale. This supports
reconstruction and human review. The product flow must inform the person that an automated
decision is involved and provide a channel to request information and review.

## Storage, access, and integrity

The JSONL writer is suitable only for this single-process technical challenge. It creates
the local audit file with owner-only permissions and forces each append to durable storage.
The file is excluded from Git.

For production, replace it with centralized append-only storage with encryption in transit
and at rest, service identities, least-privilege access, integrity protection, access logs,
backup rules, and deletion controls. Separate audit access from application administration.
An audit persistence failure must block a credit decision until it can be recorded; it may
be handled differently for non-critical telemetry.

The score update follows the same principle through compensation: if its critical profile
event cannot be appended, the previous score is restored. A later handoff-event failure is
non-critical and does not reverse a score update whose critical event was already recorded.

## Retention and data-subject rights

LGPD does not define one universal retention duration. Before using real data, document a
retention schedule per dataset and purpose, its legal or regulatory justification, and the
deletion or anonymization process. The MVP intentionally does not invent a legal deadline.

Maintain a secure mapping process that can locate events by `subject_ref` for authorized
requests. Access, correction, deletion, portability, information, and automated-decision
review requests must be authenticated, recorded, and answered through the controller's
formal process. Do not expose the HMAC key or raw audit store to the requester.

## Incident response

Keep an incident playbook with detection, containment, evidence preservation, impact and
risk assessment, controller escalation, and communications. A suspected leak must not be
copied into tickets or chat; reference the restricted incident record instead.

## Engineering checklist

- Map purpose, data categories, actors, systems, recipients, and legal basis.
- Use synthetic data in development and tests.
- Keep deterministic credit rules outside the LLM.
- Redact application and exception logs before they leave the process.
- Keep secrets outside Git and rotate them through a documented procedure.
- Review dependencies, permissions, and audit access regularly.
- Test data-subject and incident-response procedures before production.
- Reassess privacy risk whenever a new field, model, integration, or purpose is added.

## Current limitations

- JSONL is not tamper-proof and is not safe for multiple application instances.
- File permissions do not replace encryption or operating-system access controls.
- HMAC key rotation and historical lookup require a versioned key-management plan.
- Retention automation, request fulfillment, and incident notification are not implemented.
- Legal basis and regulatory retention for a real bank require controller, legal, security,
  and data-protection review.

## Official references

- [Lei Geral de Protecao de Dados Pessoais](https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709.htm),
  especially articles 6, 7, 20, 37, 46, 48, 49, and 50.
- [ANPD: direitos dos titulares](https://www.gov.br/anpd/pt-br/assuntos/titular-de-dados-1/direito-dos-titulares).
- [ANPD: comunicacao de incidente de seguranca](https://www.gov.br/anpd/pt-br/canais_atendimento/agente-de-tratamento/comunicado-de-incidente-de-seguranca-cis).
- [ANPD: guia de seguranca para agentes de pequeno porte](https://www.gov.br/anpd/pt-br/assuntos/noticias/anpd-publica-guia-de-seguranca-para-agentes-de-tratamento-de-pequeno-porte).
- [Governo Federal: orientacao sobre prazo de retencao](https://www.gov.br/dnit/pt-br/acesso-a-informacao/tratamento-de-dados-pessoais/perguntas-frequentes-sobre-a-lgpd-e-atuacao-da-agencia-nacional-de-protecao-de-dados-anpd/4-adequacao-a-lgpd/4-5-por-quanto-tempo).
