# AI compliance audit: Acme CV screening assistant

Assessed 2026-11-03. Overall **11.5** (Critical fail) across 13 in-scope frameworks; 271 of 271 controls assessed.

## Scores

| Framework | Reference | Score | Band | Critical | High | Medium | Low |
|---|---|---:|---|---:|---:|---:|---:|
| ISO 22301 | ISO 22301:2019 + Amd 1:2024 | n/a | Out of scope | 0 | 0 | 0 | 0 |
| ISO 23894 | ISO/IEC 23894:2023 | 4.7 | Critical fail | 3 | 17 | 0 | 0 |
| ISO 24027 | ISO/IEC TR 24027:2021 | 0.0 | Critical fail | 2 | 12 | 0 | 0 |
| ISO 25059 | ISO/IEC 25059:2023 | 11.8 | Critical fail | 4 | 9 | 0 | 0 |
| ISO 27001 | ISO/IEC 27001:2022 + Amd 1:2024 | 11.5 | Critical fail | 5 | 25 | 1 | 0 |
| ISO 27005 | ISO/IEC 27005:2022 | 0.0 | Critical fail | 2 | 12 | 1 | 0 |
| ISO 27017 | ISO/IEC 27017:2026 | 0.0 | Critical fail | 1 | 9 | 1 | 0 |
| ISO 27018 | ISO/IEC 27018:2025 | n/a | Out of scope | 0 | 0 | 0 | 0 |
| ISO 27701 | ISO/IEC 27701:2025 | 10.0 | Critical fail | 3 | 6 | 0 | 0 |
| ISO 38507 | ISO/IEC 38507:2022 | 55.8 | Partial | 0 | 8 | 0 | 0 |
| ISO 42001 | ISO/IEC 42001:2023 | 14.9 | Critical fail | 5 | 14 | 0 | 0 |
| ISO 42005 | ISO/IEC 42005:2025 | 0.0 | Critical fail | 2 | 12 | 0 | 0 |
| ISO 5338 | ISO/IEC 5338:2023 | 7.0 | Critical fail | 2 | 11 | 0 | 0 |
| EU AI Act | Regulation (EU) 2024/1689 as amended by (EU) 2026/1744 | 22.8 | Critical fail | 0 | 16 | 1 | 0 |
| GDPR | Regulation (EU) 2016/679 | 11.4 | Critical fail | 7 | 12 | 0 | 0 |

## Failed criticals

- `RID-1` AI-specific risk identification
- `RID-BIAS` Bias and fairness risk
- `TRT-1` Risk treatment
- `BIAS24027-DATA` Data bias: representation, measurement and historical
- `BIAS24027-GROUPS` Define protected groups and fairness goals
- `Q25059-CORRECT` Functional correctness
- `Q25059-ROBUST` Robustness
- `Q25059-SECURITY` Security of data, model and pipeline
- `Q25059-SOCIETAL` Societal and ethical risk mitigation
- `A.8.24-ENCRYPT-DATA` Encryption in transit and at rest
- `ISMS-6.1.2-RISK` Information security risk assessment
- `RM27005-PROCESS` Information security risk management process
- `RM27005-TREATMENT-OPT` Selection of risk treatment options
- `CLD27017-ROLES` Shared roles and responsibilities between provider and customer
- `P.7.2.1-LAWFUL` PII processing: lawful basis and purpose
- `AI-RISK-ASSESS` AI risk assessment
- `AI-RISK-TREAT` AI risk treatment
- `AI-IMPACT` AI system impact assessment
- `AI-DATA-MGMT` Data management for AI
- `AI-MONITOR` Operational monitoring and event handling
- `IA42005-STAKEHOLDERS` Identify affected parties
- `IA42005-IDENTIFY` Identify potential harms and benefits
- `LC5338-DATA` Data engineering and data quality
- `LC5338-MONITOR` Continuous validation and drift monitoring
- `GDPR-LAWFUL-BASIS` Lawful basis
- `GDPR-SPECIAL-CATEGORY` Special category data
- `GDPR-PII-TO-EXTERNAL-LLM` PII sent to external LLM API
- `GDPR-PROCESSOR-DPA` Processor agreement
- `GDPR-SECURITY` Security of processing

## Treatment plan (top 25 by risk)

| Risk | Framework | Control | Owner | Due | Action |
|---|---|---|---|---|---|
| 25 critical | GDPR | `GDPR-LAWFUL-BASIS` Lawful basis | DPO | 2026-11-17 | Pick one basis per purpose; for legitimate interest run and record a balancing test (LIA). |
| 25 critical | GDPR | `GDPR-PII-TO-EXTERNAL-LLM` PII sent to external LLM API | Engineering lead | 2026-11-17 | Redact or tokenise PII pre-send, or use an EU-region/self-hosted model with a signed DPA. |
| 25 critical | GDPR | `GDPR-PROCESSOR-DPA` Processor agreement | Legal | 2026-11-17 | Sign the provider DPA and confirm in writing your prompts are not used for their model training. |
| 20 critical | ISO 23894 | `RID-1` AI-specific risk identification | AI governance lead | 2026-11-17 | Use a checklist of AI risk sources (Annex-style) to drive identification; record one or more risks per category or justify n/a. |
| 20 critical | ISO 23894 | `RID-BIAS` Bias and fairness risk | ML lead | 2026-11-17 | Define fairness metrics for the use case, test across relevant subgroups, document residual bias and mitigations. |
| 20 critical | ISO 23894 | `TRT-1` Risk treatment | AI governance lead | 2026-11-17 | For each treated risk assign an owner and control, implement it, then record and sign off residual risk. |
| 20 critical | ISO 24027 | `BIAS24027-DATA` Data bias: representation, measurement and historical | ML lead | 2026-11-17 | Profile each dataset by relevant group and document gaps before training. |
| 20 critical | ISO 24027 | `BIAS24027-GROUPS` Define protected groups and fairness goals | AI governance lead | 2026-11-17 | Choose groups and fairness definitions up front with legal and product input. |
| 20 critical | ISO 25059 | `Q25059-CORRECT` Functional correctness | ML lead | 2026-11-17 | Define task-specific correctness metrics and run them on representative data before release. |
| 20 critical | ISO 25059 | `Q25059-ROBUST` Robustness | ML lead | 2026-11-17 | Add edge-case and adversarial inputs to the regression suite and set pass thresholds. |
| 20 critical | ISO 25059 | `Q25059-SECURITY` Security of data, model and pipeline | CISO | 2026-11-17 | Threat-model the AI pipeline and test against poisoning, extraction and injection. |
| 20 critical | ISO 25059 | `Q25059-SOCIETAL` Societal and ethical risk mitigation | AI governance lead | 2026-11-17 | Run an impact assessment and make unresolved high risks a release blocker. |
| 20 critical | ISO 27001 | `A.5.19-SUPPLIER` Supplier and LLM vendor security | CISO | 2026-11-17 | Inventory LLM vendors, confirm data is not used for training without consent, verify their certifications and retention terms. |
| 20 critical | ISO 27001 | `A.8.12-DLP` Data leakage prevention | CISO | 2026-11-17 | Restrict outbound destinations, add leak detection on outputs and test cross-tenant isolation. |
| 20 critical | ISO 27001 | `A.8.15-LOGGING` Logging | Engineering lead | 2026-11-17 | Log auth and admin events centrally, protect against tampering, scrub secrets and PII from log output. |
| 20 critical | ISO 27001 | `A.8.24-ENCRYPT-DATA` Encryption in transit and at rest | Engineering lead | 2026-11-17 | Enforce TLS everywhere, enable at-rest encryption on databases and backups, retire weak ciphers. |
| 20 critical | ISO 27001 | `ISMS-6.1.2-RISK` Information security risk assessment | CISO | 2026-11-17 | Adopt a documented method, run it on all in-scope assets including model pipelines, and assign an owner per risk. |
| 20 critical | ISO 27005 | `RM27005-PROCESS` Information security risk management process | CISO | 2026-11-17 | Adopt a documented method and run it on a schedule rather than ad hoc. |
| 20 critical | ISO 27005 | `RM27005-TREATMENT-OPT` Selection of risk treatment options | CISO | 2026-11-17 | Record the option per risk and justify any choice to retain a risk above the threshold. |
| 20 critical | ISO 27017 | `CLD27017-ROLES` Shared roles and responsibilities between provider and customer | CISO | 2026-11-17 | Write a matrix per service for both directions (what you rely on from hosting and model vendors, and what customers must do in your product) and publish it. |
| 20 critical | ISO 27701 | `P.7.2.1-LAWFUL` PII processing: lawful basis and purpose | DPO | 2026-11-17 | Maintain a RoPA, document a lawful basis per purpose, drop PII fields not needed for the purpose. |
| 20 critical | ISO 27701 | `P.7.2.4-CONSENT` Consent determination and records | DPO | 2026-11-17 | Store a consent record per person and purpose, and wire withdrawal to stop the processing. |
| 20 critical | ISO 27701 | `P.7.5-TRANSFER` Transfers and disclosure to third parties | Legal | 2026-11-17 | Register every cross-border transfer with its legal basis and keep a log of third-party disclosures. |
| 20 critical | ISO 42001 | `AI-DATA-MGMT` Data management for AI | ML lead | 2026-11-17 | Document each dataset's source, quality checks and preparation; restrict and log access; record what feeds each model. |
| 20 critical | ISO 42001 | `AI-IMPACT` AI system impact assessment | AI governance lead | 2026-11-17 | Run an impact assessment before deployment covering fairness, safety and societal effects; re-run on material change. |

## Data egress

7 outbound destinations; 2 outside the EU with personal data in reach.

| Destination | Category | Region | Data in reach | Risk |
|---|---|---|---|---:|
| OpenAI | llm | US | cv / resume, email, name, prompt / messages | 25 |
| Slack | messaging | US | cv / resume, email, name, prompt / messages | 25 |
| PostHog | analytics | EU | email | 20 |
| Sentry | error-tracking | configurable | cv / resume, email, name, prompt / messages | 20 |
| Google Analytics / Tag Manager | analytics | US | none seen | 15 |
| Google Fonts | cdn | US | none seen | 15 |
| api.acme-demo.example-hr.io | unknown | unknown | none seen | 10 |

The full register, per framework and per part, is in `risk-matrix.html`.
