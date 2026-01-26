# EOEPCA NA - Webhook Source - Knative Function

A Knative function that receives GitHub and GitLab webhooks and forwards them as CloudEvents to a configured sink. Compatible with Knative SinkBinding.

## Features

- **Multi-Project Support**: Configure multiple projects with individual webhook secrets
- **GitHub Webhook Support**: Receives and validates GitHub webhooks with HMAC signature verification
- **GitLab Webhook Support**: Receives and validates GitLab webhooks with token authentication
- **CloudEvents**: Converts webhooks to CloudEvents format for standardized event processing
- **SinkBinding Compatible**: Works seamlessly with Knative SinkBinding for dynamic sink configuration
- **OIDC Authentication**: Automatically uses Kubernetes service account tokens for authenticating with the sink
- **Health Checks**: Includes `/health` and `/ready` endpoints for Kubernetes probes

## Endpoints

### Project-Specific Endpoints
- `POST /<project>/github` - GitHub webhook endpoint for a specific project
- `POST /<project>/gitlab` - GitLab webhook endpoint for a specific project

### Global Endpoints (Backward Compatible)
- `POST /github` - GitHub webhook endpoint (uses global secret)
- `POST /gitlab` - GitLab webhook endpoint (uses global secret)
- `POST /` - Auto-detects GitHub or GitLab based on headers

### Health Endpoints
- `GET /health` - Health check endpoint
- `GET /ready` - Readiness check endpoint

## Environment Variables

- `K_SINK` - Target sink URL (automatically injected by SinkBinding)
- `K_CE_OVERRIDES` - JSON object to override CloudEvents attributes (default: `{}`)
- `PROJECTS_CONFIG` - JSON object defining projects and their webhook secrets (default: `{}`)
- `GITHUB_WEBHOOK_SECRET` - Optional global secret for GitHub webhook signature verification
- `GITLAB_WEBHOOK_SECRET` - Optional global secret for GitLab webhook token verification
- `OIDC_TOKEN_PATH` - Path to Kubernetes service account token (default: `/var/run/secrets/kubernetes.io/serviceaccount/token`)
- `OIDC_AUDIENCE` - Optional OIDC audience claim for token validation
- `PORT` - HTTP server port (default: 8080)

## Multi-Project Configuration

You can configure multiple projects, each with their own webhook secrets. This allows you to use different endpoints for different repositories or teams.

### Configuration Format

The `PROJECTS_CONFIG` environment variable accepts a JSON object:

```json
{
  "project-alpha": {
    "github_secret": "github-webhook-secret-for-alpha",
    "gitlab_secret": "gitlab-webhook-secret-for-alpha",
    "description": "Alpha project webhooks"
  },
  "project-beta": {
    "github_secret": "github-webhook-secret-for-beta",
    "gitlab_secret": "gitlab-webhook-secret-for-beta",
    "description": "Beta project webhooks"
  }
}
```

### Using Project Endpoints

Once configured, you can use project-specific endpoints:

- **GitHub**: `https://your-domain/project-alpha/github`
- **GitLab**: `https://your-domain/project-beta/gitlab`

Each project endpoint will:
1. Validate the webhook using the project's specific secret
2. Add the project name to the CloudEvent `subject` attribute
3. Return a 404 if the project is not configured

### Backward Compatibility

The global endpoints (`/github`, `/gitlab`, `/`) continue to work using the `GITHUB_WEBHOOK_SECRET` and `GITLAB_WEBHOOK_SECRET` environment variables. This ensures existing integrations are not broken.

## CloudEvent Format

Events are forwarded with the following CloudEvent attributes:

- **type**: `org.eoepca.webhook.{github|gitlab}.{event_type}`
- **source**: Repository URL (e.g., `https://github.com/user/repo`)
- **webhooksource**: Source type - either `github` or `gitlab`
- **subject**: Project name (only when using project-specific endpoints)
- **data**: Original webhook payload

### CloudEvents Attribute Overrides

You can override or add CloudEvents attributes using the `K_CE_OVERRIDES` environment variable. This follows the Knative convention for CloudEvents customization.

**Example:**
```bash
export K_CE_OVERRIDES='{"type":"custom.webhook.event","subject":"my-repo"}'
```

This will:
- Override the default `type` attribute
- Add a new `subject` attribute to all events

**Common use cases:**
- Setting a custom event type for filtering
- Adding a `subject` for event routing
- Adding custom extension attributes (e.g., `"myextension":"value"`)

**Note:** Overrides are applied after the base attributes are set, so they will replace any default values.

## OIDC Authentication

The function automatically reads the Kubernetes service account token and includes it in the `Authorization: Bearer <token>` header when forwarding events to the sink. This enables secure communication with OIDC-protected endpoints.

**Key Points:**
- The service account token is automatically mounted by Kubernetes at `/var/run/secrets/kubernetes.io/serviceaccount/token`
- The token is read on each request to ensure fresh credentials
- If the token is not available, the request is sent without authentication (useful for development)
- The deployment includes a dedicated `ServiceAccount` resource for proper RBAC configuration

## Deployment

### Using SinkBinding

1. **Build and push the container image:**

```bash
docker build -t your-registry/webhook-source:latest .
docker push your-registry/webhook-source:latest
```

2. **Update the image in deployment.yaml:**

Edit `config/deployment.yaml` and replace `webhook-source:latest` with your image.

3. **Create project configuration (optional):**

For multi-project support, create a ConfigMap with your projects:

```bash
kubectl apply -f config/configmap.yaml
```

Edit `config/configmap.yaml` to add your projects and their webhook secrets.

**Alternative:** For global secrets only, edit `config/sinkbinding.yaml` and apply:

```bash
kubectl apply -f config/sinkbinding.yaml
```

4. **Deploy the application:**

```bash
kubectl apply -f config/deployment.yaml
```

This creates:
- A `ServiceAccount` for OIDC token access
- A `Deployment` configured to use the service account
- A `Service` to expose the webhook endpoints

5. **Configure SinkBinding:**

The SinkBinding will inject the `K_SINK` environment variable into your deployment. Edit `config/sinkbinding.yaml` to configure your sink (Broker, Channel, or Service).

**Note:** The deployment automatically mounts the Kubernetes service account token, which is used for OIDC authentication with the sink.

### Using Knative Functions CLI

```bash
func deploy --registry your-registry
```

## Configuration Examples

### GitHub Webhook Configuration

**For project-specific webhooks:**
In your GitHub repository settings:
- **Payload URL**: `https://your-domain/<project-name>/github`
- **Content type**: `application/json`
- **Secret**: Set to match the project's `github_secret` in `PROJECTS_CONFIG`
- **Events**: Select the events you want to receive

**For global webhooks:**
In your GitHub repository settings:
- **Payload URL**: `https://your-domain/github` or `https://your-domain/`
- **Content type**: `application/json`
- **Secret**: Set to match `GITHUB_WEBHOOK_SECRET`
- **Events**: Select the events you want to receive

### GitLab Webhook Configuration

**For project-specific webhooks:**
In your GitLab project settings:
- **URL**: `https://your-domain/<project-name>/gitlab`
- **Secret token**: Set to match the project's `gitlab_secret` in `PROJECTS_CONFIG`
- **Trigger**: Select the events you want to receive

**For global webhooks:**
In your GitLab project settings:
- **URL**: `https://your-domain/gitlab` or `https://your-domain/`
- **Secret token**: Set to match `GITLAB_WEBHOOK_SECRET`
- **Trigger**: Select the events you want to receive

### SinkBinding to Broker

```yaml
apiVersion: sources.knative.dev/v1
kind: SinkBinding
metadata:
  name: webhook-source-binding
spec:
  subject:
    apiVersion: apps/v1
    kind: Deployment
    name: webhook-source
  sink:
    ref:
      apiVersion: eventing.knative.dev/v1
      kind: Broker
      name: default
```

### SinkBinding to Service

```yaml
apiVersion: sources.knative.dev/v1
kind: SinkBinding
metadata:
  name: webhook-source-binding
spec:
  subject:
    apiVersion: apps/v1
    kind: Deployment
    name: webhook-source
  sink:
    ref:
      apiVersion: v1
      kind: Service
      name: event-display
```

## Local Development

1. **Install dependencies:**

```bash
pip install -e .
```

2. **Set environment variables:**

```bash
export K_SINK=http://localhost:8081/events

# Option 1: Multi-project configuration
export PROJECTS_CONFIG='{"my-project":{"github_secret":"gh-secret","gitlab_secret":"gl-secret"}}'

# Option 2: Global secrets (backward compatible)
export GITHUB_WEBHOOK_SECRET=your-secret
export GITLAB_WEBHOOK_SECRET=your-secret

# Optional: CloudEvents overrides
export K_CE_OVERRIDES='{"myextension":"value"}'
```

3. **Run the function:**

```bash
python main.py
```

4. **Test with curl:**

```bash
# Project-specific GitHub webhook
curl -X POST http://localhost:8080/my-project/github \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: push" \
  -d '{"repository": {"html_url": "https://github.com/test/repo"}}'

# Project-specific GitLab webhook
curl -X POST http://localhost:8080/my-project/gitlab \
  -H "Content-Type: application/json" \
  -H "X-Gitlab-Event: Push Hook" \
  -d '{"project": {"web_url": "https://gitlab.com/test/repo"}}'

# Global GitHub webhook (backward compatible)
curl -X POST http://localhost:8080/github \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: push" \
  -d '{"repository": {"html_url": "https://github.com/test/repo"}}'

# Global GitLab webhook (backward compatible)
curl -X POST http://localhost:8080/gitlab \
  -H "Content-Type: application/json" \
  -H "X-Gitlab-Event: Push Hook" \
  -d '{"project": {"web_url": "https://gitlab.com/test/repo"}}'
```

## Security

### Webhook Verification
- GitHub webhooks are validated using HMAC-SHA256 signature verification
- GitLab webhooks are validated using secret token comparison
- If secrets are not configured, signature verification is skipped (useful for development)
- Always configure secrets in production environments

### OIDC Authentication
- The function uses Kubernetes service account tokens for authenticating with the sink
- Tokens are automatically rotated by Kubernetes
- The service account should be granted appropriate RBAC permissions for your use case
- The sink must be configured to accept and validate OIDC tokens from your Kubernetes cluster

## License

MIT
