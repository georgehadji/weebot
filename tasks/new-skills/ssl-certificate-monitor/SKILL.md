---
name: ssl-certificate-monitor
description: "Use when checking SSL/TLS certificates for expiry or configuration issues. Trigger: SSL, TLS, certificate, HTTPS, expiry, domain cert."
license: MIT
---
# SSL Certificate Monitor

## When to use
Check SSL/TLS certificates for domains — expiry dates, issuer, chain validity.

## Workflow
1. **Check certificate** — use openssl or Python ssl module to connect to each domain.
2. **Extract:** expiry date, days remaining, issuer, SANs, chain completeness.
3. **Flag warnings** for certs expiring within 30 days.
4. **Report** — table of domains with status, expiry, issuer.

## Output
A certificate status report with expiry warnings.