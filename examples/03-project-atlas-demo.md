# DEMO — Atlas Project Brief

Atlas is a fictional project name used to test the work-document assistant.

## Goal
Build an internal document portal to reduce the time spent searching for processes and guides.
The MVP includes document uploads, cited search, and personal notes.
The MVP does not include email sending, calendar integrations, or department-level permissions.

## Acceptance Criteria
- Users can upload text-based PDFs, TXT, and Markdown.
- Answers about documents show verifiable reference sources.
- When information is missing, the assistant says so instead of inventing details.
- Identical documents are indexed only once.

## Risks and Mitigations
Documents may be outdated: the owner should verify the version before making a decision.
Scanned PDFs without a text layer: run OCR externally before importing.
Sensitive data: obtain organizational approval before sending it to an external model service.
