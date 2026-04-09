# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Module Is

`l10n_cl_fe` is an Odoo 16.0 module implementing Chilean Electronic Invoicing (Facturación Electrónica / DTE - Documento Tributario Electrónico). It integrates with Chile's SII (Servicio de Impuestos Internos) for digital submission and validation of tax documents.

Key external dependencies:
- `facturacion_electronica` (PyPI) — core DTE XML generation and digital signature library
- `apicaf.cl` — folio authorization API
- `sre.cl` — company registry lookups
- MEPCO (diariooficial.cl) — diesel/gasoline tax rate sync

## Development Environment

This is a standard Odoo module. Install it via the Odoo Apps interface or with:

```bash
# Restart Odoo with module update
./odoo-bin -u l10n_cl_fe -d <database>

# Install Python requirements
pip install -r requirements.txt
```

### Code Quality (pre-commit)

```bash
# Install hooks
pre-commit install

# Run all checks manually
pre-commit run --all-files

# Run individual tools
black --line-length 120 <file>
flake8 <file>                  # max-line-length: 200, max-complexity: 25
isort <file>
pylint --load-plugins pylint_odoo <file>
```

Line length limits: **120** for black/pylint, **200** for flake8.

There are no automated tests in this repository.

## Architecture Overview

### Core Document Flow

1. **Folios (CAF)** — `models/caf.py` (`dte.caf`): Chilean tax authority pre-authorizes batches of document numbers (folios). The CAF XML file from SII is uploaded here. The module tracks available folios per document type.

2. **Digital Signature** — `models/sii_firma.py` (`sii.firma`): Stores the company's digital certificate (PEM format via `OpenSSL.crypto`). Used to sign all DTE documents. Monitors expiration and sends alerts.

3. **Account Move / Invoice** — `models/account_move.py` (2400+ lines, the central model): Extends Odoo's `account.move` with all DTE-specific fields and logic — XML generation, folio assignment, PDF417 barcode, SII submission, and status tracking.

4. **XML Envelope** — `models/sii_xml_envio.py` (`sii.xml.envio`): Wraps one or more signed DTE documents into a submission envelope sent to SII. Tracks submission state: `draft → NoEnviado → Enviado → EnProceso → Aceptado/Rechazado`.

5. **Queue Processing** — Uses `queue_job` for async SII communication (sending envelopes, polling status).

### Document Types Supported

Invoices (33), Exempt Invoices (34), Credit Notes (61), Debit Notes (56), Receipts/Boletas (39, 41), Dispatch Guides (52), Purchase Invoices (46), Export Invoices (110, 111, 112), Professional Fees (71, partial).

### Key Models

| Model | File | Purpose |
|---|---|---|
| `account.move` | `models/account_move.py` | Core invoicing + DTE integration |
| `dte.caf` | `models/caf.py` | Folio authorization management |
| `sii.firma` | `models/sii_firma.py` | Digital certificate storage |
| `sii.xml.envio` | `models/sii_xml_envio.py` | SII submission envelopes |
| `sii.dte.claim` | `models/sii_dte_claim.py` | Document claim/rejection responses |
| `mail.message.dte` | `models/mail_message_dte.py` | Inbound DTE email processing |
| `account.move.consumo_folios` | `models/consumo_folios.py` | Boleta folio consumption report |
| `account.libro` | `models/libro.py` | Purchase/Sales books (Libros CV) |

### Controllers

- `controllers/main.py` — primary HTTP endpoints
- `controllers/dte.py` — DTE-specific endpoints (inbound XML reception)
- `controllers/boleta.py` — Boleta/receipt endpoints
- `controllers/downloader.py` — document download
- `controllers/firma_alerts.py` — signature expiration alert bus

### Important Wizards

- `wizard/upload_xml.py` — imports incoming DTE XML from suppliers (~50KB, most complex wizard)
- `wizard/masive_send_dte.py` / `masive_dte_process.py` / `masive_dte_accept.py` — bulk DTE operations
- `wizard/apicaf.py` — requests folios from apicaf.cl API
- `wizard/notas.py` — creates credit/debit notes from existing DTE

### Migrations

Migration scripts live in `migrations/` using Odoo's standard `pre-migrate.py` / `post-migrate.py` convention. The module has been migrated from 12.0 through multiple 16.0 versions (current: 0.40.3).

## Chilean Tax / SII Concepts

- **DTE**: Documento Tributario Electrónico — any tax document (invoice, receipt, etc.)
- **CAF**: Certificado de Autorización de Folios — SII-issued authorization to use a range of document numbers
- **Folio**: Sequential document number within a CAF range
- **Boleta**: Consumer receipt (does not require buyer RUT)
- **Guía de Despacho**: Shipping/dispatch guide (document type 52)
- **Libro CV**: Monthly purchase/sales register submitted to SII
- **MEPCO**: Monthly diesel/gasoline tax rate published in Diario Oficial
- **Timbre Electrónico**: Digital stamp (PDF417 barcode) embedded in each DTE
- **RUT**: Chilean tax ID number

## Odoo Conventions in This Module

- Models use `_name` and extend existing Odoo models via `_inherit`
- The `BigInt` field (`models/bigint.py`) is a custom field type used for folio numbers exceeding standard integer limits
- Timezone is always `America/Santiago` for date handling in DTE documents
- The `facturacion_electronica` library handles low-level XML generation and cryptographic signing — avoid reimplementing its functionality
- `sii_cola_envio` (queue) manages async SII communication; direct synchronous calls are avoided for reliability
