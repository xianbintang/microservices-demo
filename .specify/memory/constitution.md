<!--
Sync Impact Report
==================
Version change: 0.0.0 → 1.0.0 (Initial ratification)
Added principles:
  - I. Testing Discipline
  - II. Observability First
  - III. Cloud-Native by Default
Added sections:
  - Technology Stack
  - Development Workflow
Removed sections: None (initial version)
Templates requiring updates:
  - .specify/templates/plan-template.md: ✅ Compatible (Constitution Check section exists)
  - .specify/templates/spec-template.md: ✅ Compatible (Requirements section aligns)
  - .specify/templates/tasks-template.md: ✅ Compatible (Phase structure supports principles)
Follow-up TODOs: None
-->

# Online Boutique Constitution

## Core Principles

### I. Testing Discipline

All services MUST have automated tests covering critical paths. Unit tests are required for business logic; integration tests are required for service-to-service communication via gRPC contracts.

**Rationale**: Microservices complexity demands reliable testing. A bug in one service cascades across the system. Testing discipline prevents regressions and enables confident refactoring.

**Requirements**:
- Unit tests for all business logic modules
- Integration tests for gRPC service endpoints
- Contract tests when service interfaces change
- Load tests for performance-critical services (e.g., currencyservice)

### II. Observability First

Every service MUST emit structured logs, expose health endpoints, and propagate trace context across gRPC calls. Metrics MUST be exposed for key operations.

**Rationale**: Distributed systems are opaque without observability. When 11 services interact, debugging requires traces, logs must be correlated, and health must be monitorable.

**Requirements**:
- Structured JSON logging with correlation IDs
- `/health` and `/ready` endpoints for Kubernetes probes
- OpenTelemetry trace propagation for gRPC calls
- Prometheus metrics for request latency, error rates, and throughput

### III. Cloud-Native by Default

All services MUST be containerized, configurable via environment variables, and deployable to Kubernetes without code changes. Resource limits and health checks are mandatory.

**Rationale**: Online Boutique demonstrates cloud-native patterns. Each service must run identically locally and in production, scale independently, and degrade gracefully.

**Requirements**:
- Dockerfile in each service directory
- Configuration via environment variables (no hardcoded values)
- Kubernetes manifests with resource requests/limits
- Liveness and readiness probes defined
- Graceful shutdown on SIGTERM

## Technology Stack

This is a polyglot microservices project. Language choices are intentional and reflect service-specific requirements.

### Languages & Runtimes

| Service | Language | Justification |
|---------|----------|---------------|
| frontend, checkoutservice, productcatalogservice, shippingservice | Go | High throughput, gRPC-native |
| cartservice | C# (.NET) | Redis client ecosystem |
| currencyservice, paymentservice | Node.js | High I/O concurrency |
| emailservice, recommendationservice, loadgenerator | Python | Rapid development, ML integration |
| adservice | Java | Enterprise ecosystem |

### Communication

- **Inter-service**: gRPC with Protocol Buffers (see `/protos`)
- **Frontend-to-user**: HTTP/HTTPS

### Infrastructure

- **Container orchestration**: Kubernetes (GKE or compatible)
- **Service mesh**: Optional (Istio/CSM for production)
- **Cache**: Redis (for cart storage)
- **Observability**: OpenTelemetry Collector, Prometheus, Grafana

### Constraints

- Do not add new languages without architectural review
- gRPC proto changes must follow backward compatibility rules
- Third-party dependencies require license review

## Development Workflow

### Code Review

- All changes require pull request review
- At least one approval from a maintainer
- CI must pass before merge
- Breaking changes require documentation update

### CI/CD Pipeline

**Continuous Integration** (required):
1. Lint and format check
2. Unit tests execution
3. Container image build verification
4. Security vulnerability scan

**Continuous Deployment** (optional, per environment):
1. Integration tests against staging
2. Kubernetes manifest validation
3. Canary deployment with automated rollback
4. Production deployment after manual approval

### Branch Strategy

- `main` is the stable branch
- Feature branches: `###-feature-name`
- Hotfix branches: `hotfix-description`
- No direct commits to `main`

## Governance

This constitution supersedes all other development practices. Amendments require:

1. Proposal documented in a pull request
2. Discussion period of at least 48 hours
3. Approval from at least two maintainers
4. Update to this document with version bump
5. Propagation to affected templates and documentation

**Compliance**: All pull requests must verify compliance with these principles. Complexity introduced without necessity will be rejected.

**Guidance**: For runtime development guidance, see `README.md` and `docs/development-guide.md`.

**Version**: 1.0.0 | **Ratified**: 2026-03-01 | **Last Amended**: 2026-03-01