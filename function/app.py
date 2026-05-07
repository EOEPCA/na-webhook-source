import os
import hmac
import hashlib
import json
from typing import Optional, Dict
from pathlib import Path
from flask import Flask, request, jsonify
from cloudevents.http import CloudEvent, to_structured
import requests

app = Flask(__name__)

K_SINK = os.environ.get('K_SINK')
K_CE_OVERRIDES = os.environ.get('K_CE_OVERRIDES', '{}')
PROJECTS_CONFIG = os.environ.get('PROJECTS_CONFIG', '{}')
GITHUB_SECRET = os.environ.get('GITHUB_WEBHOOK_SECRET')
GITLAB_SECRET = os.environ.get('GITLAB_WEBHOOK_SECRET')
OIDC_TOKEN_PATH = os.environ.get('OIDC_TOKEN_PATH', '/var/run/secrets/kubernetes.io/serviceaccount/token')
OIDC_AUDIENCE = os.environ.get('OIDC_AUDIENCE', '')

_projects_cache: Optional[Dict] = None


def load_projects_config() -> Dict:
    global _projects_cache
    if _projects_cache is not None:
        return _projects_cache

    try:
        config = json.loads(PROJECTS_CONFIG)
        if not isinstance(config, dict):
            app.logger.warning('PROJECTS_CONFIG is not a valid JSON object, using empty config')
            _projects_cache = {}
            return _projects_cache

        _projects_cache = config
        app.logger.info(f'Loaded {len(_projects_cache)} project(s) from configuration')
        return _projects_cache
    except json.JSONDecodeError as e:
        app.logger.warning(f'Failed to parse PROJECTS_CONFIG: {e}, using empty config')
        _projects_cache = {}
        return _projects_cache


def get_project_config(project_name: str) -> Optional[Dict]:
    projects = load_projects_config()
    return projects.get(project_name)


def verify_github_signature(payload: bytes, signature: str, secret: Optional[str] = None) -> bool:
    webhook_secret = secret or GITHUB_SECRET

    if not webhook_secret:
        return True

    if not signature:
        return False

    hash_algorithm, signature_value = signature.split('=', 1)
    mac = hmac.new(webhook_secret.encode(), msg=payload, digestmod=hashlib.sha256)
    expected_signature = mac.hexdigest()

    return hmac.compare_digest(expected_signature, signature_value)


def verify_gitlab_signature(token: str, secret: Optional[str] = None) -> bool:
    webhook_secret = secret or GITLAB_SECRET

    if not webhook_secret:
        return True

    if not token:
        return False

    return hmac.compare_digest(webhook_secret, token)


def get_oidc_token() -> Optional[str]:
    try:
        token_path = Path(OIDC_TOKEN_PATH)
        if token_path.exists():
            token = token_path.read_text().strip()
            app.logger.debug('Successfully read OIDC token from service account')
            return token
        else:
            app.logger.warning(f'OIDC token path does not exist: {OIDC_TOKEN_PATH}')
            return None
    except Exception as e:
        app.logger.error(f'Failed to read OIDC token: {e}')
        return None


def parse_ce_overrides() -> dict:
    try:
        overrides = json.loads(K_CE_OVERRIDES)
        if not isinstance(overrides, dict):
            app.logger.warning('K_CE_OVERRIDES is not a valid JSON object, ignoring')
            return {}
        return overrides
    except json.JSONDecodeError as e:
        app.logger.warning(f'Failed to parse K_CE_OVERRIDES: {e}')
        return {}


def create_cloudevent(webhook_type: str, event_type: str, data: dict, source: str, project: Optional[str] = None) -> CloudEvent:
    attributes = {
        'type': f'org.eoepca.webhook.{webhook_type}.{event_type}',
        'source': source,
        'webhooksource': webhook_type,
    }

    if project:
        attributes['subject'] = project

    overrides = parse_ce_overrides()
    if overrides:
        app.logger.debug(f'Applying CloudEvents overrides: {overrides}')
        attributes.update(overrides)

    return CloudEvent(attributes, data)


def forward_to_sink(event: CloudEvent) -> bool:
    if not K_SINK:
        app.logger.warning('K_SINK not configured, skipping forward')
        return False

    try:
        headers, body = to_structured(event)

        oidc_token = get_oidc_token()
        if oidc_token:
            headers['Authorization'] = f'Bearer {oidc_token}'
            app.logger.debug('Added OIDC token to request headers')
        else:
            app.logger.info('No OIDC token available, sending request without authentication')

        response = requests.post(K_SINK, headers=headers, data=body, timeout=30)
        response.raise_for_status()
        app.logger.info(f'Successfully forwarded event to sink: {K_SINK}')
        return True
    except Exception as e:
        app.logger.error(f'Failed to forward event to sink: {e}')
        raise


@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'healthy'}), 200


@app.route('/ready', methods=['GET'])
def ready():
    return jsonify({'status': 'ready'}), 200


def handle_github_webhook(project: Optional[str] = None):
    signature = request.headers.get('X-Hub-Signature-256', '')
    event_type = request.headers.get('X-GitHub-Event', 'unknown')
    delivery_id = request.headers.get('X-GitHub-Delivery', '')

    payload = request.get_data()

    secret = None
    if project:
        project_config = get_project_config(project)
        if not project_config:
            app.logger.warning(f'Project "{project}" not found in configuration')
            return jsonify({'error': 'Project not found'}), 404
        secret = project_config.get('github_secret')
        app.logger.info(f'Processing GitHub webhook for project: {project}')

    if not verify_github_signature(payload, signature, secret):
        app.logger.warning(f'Invalid GitHub signature for project: {project or "default"}')
        return jsonify({'error': 'Invalid signature'}), 401

    try:
        data = request.get_json(force=True)
    except Exception as e:
        app.logger.error(f'Failed to parse JSON: {e}')
        return jsonify({'error': 'Invalid JSON'}), 400

    source = data.get('repository', {}).get('html_url', 'github.com/unknown')

    event = create_cloudevent('github', event_type, data, source, project)

    try:
        forward_to_sink(event)
        return jsonify({'status': 'accepted', 'delivery_id': delivery_id, 'project': project}), 202
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def handle_gitlab_webhook(project: Optional[str] = None):
    token = request.headers.get('X-Gitlab-Token', '')
    event_type = request.headers.get('X-Gitlab-Event', 'unknown')

    secret = None
    if project:
        project_config = get_project_config(project)
        if not project_config:
            app.logger.warning(f'Project "{project}" not found in configuration')
            return jsonify({'error': 'Project not found'}), 404
        secret = project_config.get('gitlab_secret')
        app.logger.info(f'Processing GitLab webhook for project: {project}')

    if not verify_gitlab_signature(token, secret):
        app.logger.warning(f'Invalid GitLab token for project: {project or "default"}')
        return jsonify({'error': 'Invalid token'}), 401

    try:
        data = request.get_json(force=True)
    except Exception as e:
        app.logger.error(f'Failed to parse JSON: {e}')
        return jsonify({'error': 'Invalid JSON'}), 400

    source = data.get('project', {}).get('web_url', 'gitlab.com/unknown')

    event = create_cloudevent('gitlab', event_type.replace(' ', '_').lower(), data, source, project)

    try:
        forward_to_sink(event)
        return jsonify({'status': 'accepted', 'project': project}), 202
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/<project>/github', methods=['POST'])
def project_github_webhook(project):
    return handle_github_webhook(project)


@app.route('/<project>/gitlab', methods=['POST'])
def project_gitlab_webhook(project):
    return handle_gitlab_webhook(project)


@app.route('/github', methods=['POST'])
def github_webhook():
    return handle_github_webhook()


@app.route('/gitlab', methods=['POST'])
def gitlab_webhook():
    return handle_gitlab_webhook()


@app.route('/', methods=['POST'])
def generic_webhook():
    user_agent = request.headers.get('User-Agent', '').lower()

    if 'github' in user_agent or 'X-GitHub-Event' in request.headers:
        return handle_github_webhook()
    elif 'gitlab' in user_agent or 'X-Gitlab-Event' in request.headers:
        return handle_gitlab_webhook()
    else:
        return jsonify({'error': 'Unknown webhook source'}), 400
