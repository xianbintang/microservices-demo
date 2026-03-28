# Development Guide 

This doc explains how to build and run the Online Boutique source code locally using the `skaffold` command-line tool.  

## Prerequisites

- [Docker for Desktop](https://www.docker.com/products/docker-desktop)
- [kubectl](https://kubernetes.io/docs/tasks/tools/) (can be installed via `gcloud components install kubectl` for Option 1 - GKE)
- [skaffold **2.0.2+**](https://skaffold.dev/docs/install/) (latest version recommended), a tool that builds and deploys Docker images in bulk. 
- Clone the repository.
    ```sh
    git clone https://github.com/GoogleCloudPlatform/microservices-demo
    cd microservices-demo/
    ```
- A Google Cloud project with Google Container Registry enabled. (for Option 1 - GKE)
- SSH access to remote server (for Option 2 - Remote Kind Cluster)

## Option 1: Google Kubernetes Engine (GKE)

> 💡 Recommended if you're using Google Cloud and want to try it on
> a realistic cluster. **Note**: If your cluster has Workload Identity enabled, 
> [see these instructions](https://cloud.google.com/kubernetes-engine/docs/how-to/workload-identity#enable)

1.  Create a Google Kubernetes Engine cluster and make sure `kubectl` is pointing
    to the cluster.

    ```sh
    gcloud services enable container.googleapis.com
    ```

    ```sh
    gcloud container clusters create-auto demo --region=us-central1
    ```

    ```
    kubectl get nodes
    ```

2.  Enable Artifact Registry (AR) on your GCP project and configure the
    `docker` CLI to authenticate to AR:

    ```sh
    gcloud services enable artifactregistry.googleapis.com
    ```

    ```sh
    gcloud artifacts repositories create microservices-demo \
      --repository-format=docker \
      --location=us \
    ```

    ```sh
    gcloud auth configure-docker -q 
    ```

3.  In the root of this repository, run:

    ```
    skaffold run --default-repo=us-docker.pkg.dev/PROJECT_ID/microservices-demo
    ```
    
    Where `PROJECT_ID` is replaced by your Google Cloud project ID.

    This command:

    - Builds the container images.
    - Pushes them to AR.
    - Applies the `./kubernetes-manifests` deploying the application to
      Kubernetes.

    **Troubleshooting:** If you get "No space left on device" error on Google
    Cloud Shell, you can build the images on Google Cloud Build: [Enable the
    Cloud Build
    API](https://console.cloud.google.com/flows/enableapi?apiid=cloudbuild.googleapis.com),
    then run `skaffold run -p gcb --default-repo=us-docker.pkg.dev/[PROJECT_ID]/microservices-demo` instead.

4.  Find the IP address of your application, then visit the application on your
    browser to confirm installation.

        kubectl get service frontend-external

5.  Navigate to `http://EXTERNAL-IP` to access the web frontend.

## Option 2 - Remote Kind Cluster

Deploy Online Boutique to a remote server using Kind (Kubernetes in Docker). The remote server runs both the Kind cluster and the observability stack (Prometheus/Grafana/Loki/Tempo).

1. Sync the project code to the remote server:

    ```shell
    rsync -avz --exclude='.git' --exclude='node_modules' ./ root@47.83.217.162:/opt/microservices-demo/
    ```

2. Run the deployment script on the remote server:

    ```shell
    ssh root@47.83.217.162 'cd /opt/microservices-demo && bash deploy/kind/deploy-remote.sh up'
    ```

    The script automatically handles Kind cluster creation, image preparation, monitoring stack deployment, and application deployment.

3. Access the application:
    - Frontend: http://47.83.217.162:9999
    - Grafana: http://47.83.217.162:3000 (admin/admin)

4. Check cluster status:

    ```shell
    ssh root@47.83.217.162 'cd /opt/microservices-demo && bash deploy/kind/deploy-remote.sh status'
    ```

5. Tear down:

    ```shell
    ssh root@47.83.217.162 'cd /opt/microservices-demo && bash deploy/kind/deploy-remote.sh down'
    ```

## Adding a new microservice

In general, the set of core microservices for Online Boutique is fairly complete and unlikely to change in the future, but it can be useful to add an additional optional microservice that can be deployed to complement the core services.

See the [Adding a new microservice](adding-new-microservice.md) guide for instructions on how to add a new microservice.

## Cleanup

If you've deployed the application with `skaffold run` command, you can run
`skaffold delete` to clean up the deployed resources.
