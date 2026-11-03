# Egress scan

`python -m aicomply egress <target>` answers one question an auditor always asks and a codebase rarely answers in one place: what leaves this system, to whom, and carrying what.

It reads, without running anything:

- source trees (JavaScript, TypeScript, Vue, Svelte, Python, Go, Ruby, Java, Kotlin, Swift, PHP, C#, Rust, Dart, HTML, config files),
- built bundles, including minified single-line JavaScript,
- Electron `.asar` archives, read entry by entry in place, whatever their size.

Text files over 25 MB and unreadable archives are listed under "Not scanned" instead of disappearing. Credentials that appear in evidence snippets are masked before they are written to `egress.json`.

This is the static half of reverse engineering. For a native binary, a mobile app or a closed desktop app, recover the endpoints with [REA](https://github.com/morluto/rea) and pass them in with `--extra-hosts`.

## What it finds

| signal | example | evidence kind |
|---|---|---|
| A URL next to a network call, or loaded by a tag | `fetch("https://eu.i.posthog.com/capture")`, `<script src="https://www.googletagmanager.com/...">` | `call` |
| An SDK import | `from openai import OpenAI`, `import * as Sentry from "@sentry/node"` | `import` |
| A credential for a known vendor | `os.environ["SLACK_WEBHOOK"]`, `ANTHROPIC_API_KEY` | `credential` |
| A risky setting | `send_default_pii=True`, `maskAllText: false`, `autocapture: true` | setting |

Each destination is matched against `aicomply/egress/vendors.json` (55 vendors: LLM providers, vector databases, analytics and session replay, error tracking, email, messaging, payments, storage, identity, CDNs) for its category and region. A vendor that offers EU hosting is marked EU when every host the code calls is its EU endpoint. Hosts that are only mentioned (a docs link in a string) are ignored unless something calls them; URLs in comments never count.

## Data in reach

For a URL the scanner reads the statement around the call; for an SDK import or a credential it reads the whole file, because that file can feed the vendor. It reports the personal data it sees there: e-mail, phone, name, address, national id, financial data, date of birth, CV, IP address, and the special categories (health, ethnicity, religion, biometrics), plus prompts sent to a model.

## Risk and controls

Likelihood is 5 when a call, import or credential confirms the flow, 3 for a bare mention. Impact is 5 for special-category data, 4 for other personal data, 3 for analytics, session replay, CDNs and prompts, 2 otherwise, plus one when the destination is outside the EU and personal data or prompts are in reach.

Every category maps to the controls it puts in play (for an LLM provider: GDPR-PII-TO-EXTERNAL-LLM, GDPR-PROCESSOR-DPA, A.5.19-SUPPLIER, A.8.12-DLP, PII27018-CONSENT). Passed to `audit --egress`, a destination carrying personal data raises the likelihood of those controls in the risk matrix.

## In CI

```bash
python -m aicomply egress . --own acme.eu --strict
```

`--strict` exits 1 when personal data is in reach of a destination outside the EU, or a risky setting is on.
