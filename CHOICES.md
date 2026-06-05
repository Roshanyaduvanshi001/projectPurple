# CHOICES.md

## Model Selection

- **Chosen Model**: GPT‑OSS 120B (Medium)
- **Reasoning**: Provides a good balance between performance and computational cost for the challenge requirements.

## Schema Design

- **Event Log Schema**: JSONL entries with fields `event_id`, `timestamp`, `event_type`, `payload`.
- **Design Rationale**: Simplicity for validation, extensibility for future event types.

## API Architecture

- **Endpoints**:
  - `POST /events` – Accepts a single event in the defined schema.
  - `GET /events/{id}` – Retrieves a specific event.
- **Error Handling**: Returns HTTP 400 for schema violations, 404 for missing resources, and 500 for internal errors.

*Provide concrete details for each section before final submission.*
