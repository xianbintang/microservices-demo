## Product Requirements

This document contains a list of requirements that every change made to this repository should meet.
Every change must:
1. Preserve the golden user journey taken by Kubernetes beginners.
1. Preserve the simplicity of demos.
1. Preserve the simplicity of the GKE quickstart.

These requirements are about the default deployment (default configuration) of Online Boutique.
Changes that will violate any of these rules should not be built into the default configuration of Online Boutique.
Such changes should be opt-in only — ideally, as a [Kustomize Component](https://github.com/GoogleCloudPlatform/microservices-demo/tree/main/kustomize) if they align with the [purpose of Online Boutique](/docs/purpose.md).

### 1. Preserve the golden user journey taken by Kubernetes beginners

The following statement about Online Boutique should always be true:

> A user outside of Google can deploy Online Boutique's default configuration on a remote [Kind (Kubernetes in Docker)](https://kind.sigs.k8s.io/) cluster with integrated observability stack.

This statement describes the golden user journey that we expect new Kubernetes users to take while onboarding to Online Boutique.

Being able to run Online Boutique on a remote Kind cluster ensures that Online Boutique is free and cloud-agnostic. The deployment uses a dedicated remote server with pre-configured observability stack (Prometheus/Grafana/Loki/Tempo), providing a production-like environment accessible to all team members.

### 2. Preserve the simplicity of demos

New changes should not complicate the primary user journey showcased in live demos and tutorials.

Today, the primary user journey is as follows:
1. Visit Online Boutique on a web browser.
2. Select an item from the homepage and add the item to the cart.
3. The checkout form is pre-populated with placeholder data (e.g. the shipping address).
4. The user checks out and completes the order.

### 3. Preserve the simplicity of the GKE quickstart

New changes should not add additional complexity in the [main Online Boutique quickstart](https://github.com/GoogleCloudPlatform/microservices-demo#quickstart-gke).

In particular, new changes should not add extra required steps or additional required tools in that quickstart.

Ideally, extensions to Online Boutique's default functionality (such as a new microservice or a new cloud service integration) should be added as a [Kustomize Component](https://github.com/GoogleCloudPlatform/microservices-demo/tree/main/kustomize/components) which users can optionally opt into.
