# Coding Conventions

> Guidelines for coding style, package design, typing, and dependency management in the `lemonade-cashier` codebase.

## Python Version & Environment

- **Target Version**: Python 3.11+ is strictly required.
- **Future Imports**: Use `from __future__ import annotations` at the top of all new modules to support forward-declared type hints.
- **Platform Constraints**: Code must run end-to-end on a local workstation environment (AMD Strix Halo). Avoid assumptions about cloud hosting or network-backed resources.

## Dependency Management

- **Zero Third-Party Runtime Dependencies in Core**: The financial core package (`src/lemonade_cashier/core/`) must rely *only* on the Python standard library. No third-party packages may be imported in `src/lemonade_cashier/core/`.
- **Developer Extras**: Third-party libraries are limited to development, testing, and documentation extras defined in `pyproject.toml` (e.g., `pytest`, `ruff`, `mypy`, `mkdocs`).

## Code Formatting & Style

- **Linter & Formatter**: We use Ruff for both linting and code formatting.
- **Line Length**: Hard limit of **100 characters** (configured as `line-length = 100` in `pyproject.toml`).
- **Import Sorting**: Ruff `I` rule is active. Imports must be sorted alphabetically and grouped correctly (standard library, third-party, local package).

## Static Type Checking

- **Strict Type Checking**: Mypy is used with strict settings (`strict = true` in `pyproject.toml`).
- **Required Annotations**: Every function, method parameter, and return value must be fully type-annotated.
- **No Implicit Optionals**: Use explicit union typing for optional parameters or return values, e.g., `value: str | None = None`.

## Class Design & Data Models

- **Immutable Dataclasses**: Dataclasses are the preferred container for structured configuration and contracts. Use `@dataclass(frozen=True)` to ensure immutability and thread safety.
- **Post-Init Validation**: Perform schema and value validation inside `__post_init__` to catch configuration bugs at construction time.

## Error Handling & Money

- **Money is Decimal**: Always use `Decimal` for currency calculations, never `float`.
- **Explicit Failures**: Do not silently swallow exceptions.
- **Custom Exceptions**: Define custom exception classes that inherit from standard built-ins (e.g., `CashierError(ValueError)`). Raise them early to prevent malformed data from cascading.

## Build Order & Layering

We follow a strict, layer-by-layer dependency build order. Reliability must be verified at each tier before autonomous features are integrated.

- **Layer Sequence**: `inventory` ➔ `cart` ➔ `totals` ➔ `cash` ➔ `receipts` ➔ `audit` ➔ `replay` ➔ `CIT` ➔ `safety` ➔ `agents` ➔ `cameras` ➔ `speech` ➔ `sensor fusion`
- **Reliability Before Autonomy**: Deterministic financial math and event chain logging must remain completely functional and validated even if external agents or ML-based sensor models are slow, fail, or are completely unreachable.
- **Documentation**: Layer specifications and completion checklists are located in [BUILD_ORDER](../BUILD_ORDER.md).

## Related

- [[README]] — project wiki entry point
- [[architecture]] — high-level system view and event envelope
- [[runbook]] — operational tasks and ports
- [[agents]] — safety guidelines and PIN thresholds
- [BUILD_ORDER](../BUILD_ORDER.md) — build order specifications and completeness checklists

