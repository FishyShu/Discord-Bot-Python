# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability, **please do not open a public GitHub issue**.

Instead, report it privately:

- **GitHub private advisory:** Use [Security → Report a vulnerability](https://github.com/FishyShu/Discord-Bot-Python/security/advisories/new) on the repo page.
- **Direct message:** Contact the maintainer via Discord or the contact info in their GitHub profile.

Please include:
- A description of the vulnerability and its potential impact
- Steps to reproduce
- Any suggested mitigations (optional)

You will receive a response within **72 hours**. Once the issue is confirmed and patched, a public advisory will be published with credit to the reporter (unless you prefer to remain anonymous).

## Secrets & Configuration

- **Never commit `.env` or any file containing tokens, passwords, or API keys.**
- The `.gitignore` in this repo already excludes `.env`.
- All sensitive values must be loaded via environment variables as documented in the README.

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.1.x   | Yes       |
| < 1.1   | No        |
