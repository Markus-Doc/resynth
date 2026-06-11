# Security Policy

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub's private
vulnerability reporting on this repository (Security tab, then Report a
vulnerability). Do not open a public issue for security problems.

Reports are reviewed on a best effort basis. RESYNTH runs entirely locally,
makes no network calls at runtime and stores all state as plain text in your
own files, which keeps the attack surface small. The areas most worth
scrutiny are the intake conversion helpers (pandoc, pdftotext) and the
installer scripts.
