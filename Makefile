# Local deployment helper for the account statement service (API) and RustFS object storage.
# Run `make help` for targets. Override settings on the command line, e.g. `make up KUBE_CONTEXT=rancher-desktop`.

SHELL := /bin/bash
.DEFAULT_GOAL := help

# ---- configuration -----------------------------------------------------------
KUBE_CONTEXT  ?= colima
NAMESPACE     ?= customer-statements
LOCAL_DIR     := .local
SECRETS_FILE  := $(LOCAL_DIR)/secrets.env
TIMEOUT       ?= 5m           # how long helm waits for pods to become ready

APP_CHART     := charts/account-statement-svc
APP_IMAGE     ?= account-statement-svc
APP_PORT      ?= 8000
APP_RELEASE   ?= account-statement-svc
APP_SERVICE   := account-statement-svc
APP_TAG       ?= 0.1.0
APP_PLATFORM  ?= linux/amd64  # the image platform the cluster runs; must match the target node

RUSTFS_ACCESS_KEY ?= rustfsadmin
RUST_FS_CONSOLE_PORT  ?= 9001
RUSTFS_IMAGE_REPO ?= rustfs/rustfs
RUSTFS_IMAGE_TAG  ?= 1.0.4
RUSTFS_RELEASE ?= rustfs      # keep "rustfs": the API's default S3_ENDPOINT is rustfs:9000

# Local image registry: a `registry:2` container on the host (see registry-up).
REGISTRY_CONTAINER ?= local-registry
REGISTRY_IMAGE     ?= registry:2
# 5000 is taken by macOS AirPlay Receiver (ControlCenter), which answers with 403.
REGISTRY_PORT      ?= 5001
REGISTRY_HOST      ?= localhost:$(REGISTRY_PORT)

# Only local clusters may be targeted. This stops deploy/teardown from reaching a remote cluster by mistake.
LOCAL_CONTEXT_RE := ^(colima|rancher-desktop|docker-desktop|minikube|kind-.+)$

KCTL := kubectl --context $(KUBE_CONTEXT)
HELM := helm --kube-context $(KUBE_CONTEXT) --namespace $(NAMESPACE)

.PHONY: help up down clean status logs forward docker-build secrets check-context namespace \
        registry-up registry-down deploy-rustfs deploy-app lint test

# ---- entry points -------------------------------------------------------------
help: ## Show this help
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""
	@echo "Current: KUBE_CONTEXT=$(KUBE_CONTEXT) NAMESPACE=$(NAMESPACE)"

up: check-context secrets docker-build namespace deploy-rustfs deploy-app ## Start the entire application and deploy all related components
	@echo ""
	@echo "Deployed to '$(KUBE_CONTEXT)', namespace '$(NAMESPACE)'."
	@echo "Run 'make forward' to reach the API on http://localhost:$(APP_PORT)."

down: check-context ## Uninstall the API and RustFS releases
	@for r in $(APP_RELEASE) $(RUSTFS_RELEASE); do \
	  if $(HELM) status $$r >/dev/null 2>&1; then \
	    echo "Uninstalling $$r"; $(HELM) uninstall $$r --wait; \
	  else \
	    echo "$$r is not installed"; \
	  fi; \
	done

clean: check-context ## Delete the whole namespace, all data, and the local secrets (CONFIRM=yes to skip prompt)
	@if [ "$(CONFIRM)" != "yes" ]; then \
	  read -r -p "Delete namespace '$(NAMESPACE)' on '$(KUBE_CONTEXT)' including all RustFS data? [y/N] " answer; \
	  [ "$$answer" = "y" ] || { echo "Aborted."; exit 1; }; \
	fi
	$(KCTL) delete namespace $(NAMESPACE) --ignore-not-found --wait
	rm -rf $(LOCAL_DIR)
	@echo "Purged. Next 'make up' generates new secrets."

status: check-context ## Show Helm releases, pods, services and PVCs
	@$(HELM) list
	@$(KCTL) -n $(NAMESPACE) get pods,svc,pvc 2>/dev/null || echo "Namespace '$(NAMESPACE)' does not exist."

logs: check-context ## Follow API logs
	$(KCTL) -n $(NAMESPACE) logs deploy/$(APP_SERVICE) -f --tail=100

forward: check-context ## Port-forward the API and RustFS console (Ctrl-C to stop)
	@echo "API:            http://localhost:$(APP_PORT)/docs"
	@echo "RustFS console: http://localhost:$(RUST_FS_CONSOLE_PORT)  (user: $(RUSTFS_ACCESS_KEY), password: RUSTFS_SECRET_KEY in $(SECRETS_FILE))"
	@$(KCTL) -n $(NAMESPACE) port-forward svc/$(APP_SERVICE) $(APP_PORT):8000 & p1=$$!; \
	 $(KCTL) -n $(NAMESPACE) port-forward svc/$(RUSTFS_RELEASE) $(RUST_FS_CONSOLE_PORT):9001 & p2=$$!; \
	 trap "kill $$p1 $$p2 2>/dev/null" EXIT INT TERM; \
	 wait

registry-up: ## Start the local image registry container (kept across runs; use registry-down to remove)
	@if [ -n "$$(docker ps -q -f name=^$(REGISTRY_CONTAINER)$$)" ]; then \
	  echo "Registry '$(REGISTRY_CONTAINER)' is already running on $(REGISTRY_HOST)."; \
	elif [ -n "$$(docker ps -aq -f name=^$(REGISTRY_CONTAINER)$$)" ]; then \
	  docker start $(REGISTRY_CONTAINER) >/dev/null && echo "Started existing registry '$(REGISTRY_CONTAINER)' on $(REGISTRY_HOST)."; \
	else \
	  docker run -d -p $(REGISTRY_PORT):5000 --name $(REGISTRY_CONTAINER) --restart always \
	    -v registry-data:/var/lib/registry $(REGISTRY_IMAGE) >/dev/null && \
	  echo "Started registry '$(REGISTRY_CONTAINER)' on $(REGISTRY_HOST)."; \
	fi

registry-down: ## Remove the registry container and its volume (all pushed images are deleted)
	docker stop $(REGISTRY_CONTAINER) || true
	docker rm $(REGISTRY_CONTAINER) || true
	docker volume rm registry-data || true

docker-build: registry-up ## Build the API image and push it to the local registry
	@echo "Building $(REGISTRY_HOST)/$(APP_IMAGE):$(APP_TAG) for $(APP_PLATFORM)."
	@echo "Building under emulation is slow (minutes, not seconds). Build steps stream below; set APP_PLATFORM=linux/arm64 for a native build."
	docker build --progress=plain --platform $(APP_PLATFORM) -t $(REGISTRY_HOST)/$(APP_IMAGE):$(APP_TAG) .
	@echo "Pushing $(REGISTRY_HOST)/$(APP_IMAGE):$(APP_TAG)."
	docker push $(REGISTRY_HOST)/$(APP_IMAGE):$(APP_TAG)
	@echo "Pushed $(REGISTRY_HOST)/$(APP_IMAGE):$(APP_TAG)."

lint: ## Lint the Helm charts
	helm lint charts/rustfs
	helm lint $(APP_CHART) --set-string apiKey=lint-only-lint-only --set-string linkSigningKey=lint-only-lint-only-lint-only-lint-only

test: ## Run unit tests (S3_INTEGRATION=1 also runs the live RustFS tests; set S3_ENDPOINT etc. as needed)
	uv run pytest -q

# ---- building blocks (run by `up`) -------------------------------------------
check-context:
	@echo "$(KUBE_CONTEXT)" | grep -Eq "$(LOCAL_CONTEXT_RE)" || { \
	  echo "Refusing to run: '$(KUBE_CONTEXT)' is not a local context (allowed: colima, rancher-desktop, docker-desktop, minikube, kind-*)." >&2; exit 1; }
	@kubectl config get-contexts -o name | grep -qx "$(KUBE_CONTEXT)" || { \
	  echo "kube context '$(KUBE_CONTEXT)' not found in kubeconfig." >&2; exit 1; }

secrets:
	@if [ ! -f $(SECRETS_FILE) ]; then \
	  mkdir -p $(LOCAL_DIR) && \
	  printf 'API_KEY=%s\nLINK_SIGNING_KEY=%s\nRUSTFS_SECRET_KEY=%s\n' \
	    "$$(openssl rand -hex 24)" "$$(openssl rand -hex 32)" "$$(openssl rand -hex 16)" > $(SECRETS_FILE) && \
	  chmod 600 $(SECRETS_FILE) && \
	  echo "Created $(SECRETS_FILE) (reused by later runs)."; \
	fi

namespace: check-context
	@$(KCTL) create namespace $(NAMESPACE) --dry-run=client -o yaml | $(KCTL) apply -f - >/dev/null

deploy-rustfs: check-context secrets namespace
	set -a; . $(SECRETS_FILE); set +a; \
	$(HELM) upgrade --install $(RUSTFS_RELEASE) charts/rustfs \
	  --set-string image.repository=$(RUSTFS_IMAGE_REPO) \
	  --set-string image.tag=$(RUSTFS_IMAGE_TAG) \
	  --set-string accessKey=$(RUSTFS_ACCESS_KEY) \
	  --set-string secretKey="$$RUSTFS_SECRET_KEY" \
	  --wait --timeout $(TIMEOUT) || { \
	    echo "RustFS did not become ready. Pod state:" >&2; \
	    $(KCTL) -n $(NAMESPACE) get pods -o wide >&2; \
	    $(KCTL) -n $(NAMESPACE) describe pods -l app.kubernetes.io/name=rustfs 2>/dev/null | tail -25 >&2; \
	    exit 1; }

deploy-app: check-context secrets namespace
	set -a; . $(SECRETS_FILE); set +a; \
	$(HELM) upgrade --install $(APP_RELEASE) $(APP_CHART) \
	  --set-string image.repository=$(REGISTRY_HOST)/$(APP_IMAGE) \
	  --set-string image.tag=$(APP_TAG) \
	  --set-string apiKey="$$API_KEY" \
	  --set-string linkSigningKey="$$LINK_SIGNING_KEY" \
	  --set-string s3.accessKey=$(RUSTFS_ACCESS_KEY) \
	  --set-string s3.secretKey="$$RUSTFS_SECRET_KEY" \
	  --set-string publicBaseUrl=http://localhost:$(APP_PORT) \
	  --wait --timeout $(TIMEOUT)
