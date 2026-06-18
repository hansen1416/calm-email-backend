"""
OAuth2 集成中心 — Gmail/Outlook 一键登录与发件
"""
from flask import Blueprint, request, jsonify, redirect
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, OAuthConfig
from datetime import datetime
import secrets
import requests

oauth_bp = Blueprint('oauth', __name__)

# 内存存储（token 仍需持久化，现阶段保留在内存）
_oauth_tokens = {}

# OAuth 固定端点配置（不存DB）
OAUTH_PROVIDERS = {
    'google': {
        'auth_url': 'https://accounts.google.com/o/oauth2/v2/auth',
        'token_url': 'https://oauth2.googleapis.com/token',
        'scope': 'email profile https://www.googleapis.com/auth/gmail.send',
    },
    'outlook': {
        'auth_url': 'https://login.microsoftonline.com/common/oauth2/v2.0/authorize',
        'token_url': 'https://login.microsoftonline.com/common/oauth2/v2.0/token',
        'scope': 'offline_access openid profile email https://outlook.office.com/SMTP.Send',
    }
}


def _get_config(uid, provider):
    """获取用户的 OAuth 配置（client_id / client_secret）"""
    row = OAuthConfig.query.filter_by(user_id=uid, provider=provider).first()
    if row:
        return {'client_id': row.client_id, 'client_secret': row.client_secret}
    return {'client_id': '', 'client_secret': ''}


@oauth_bp.route('/providers', methods=['GET'])
@jwt_required()
def list_providers():
    uid = int(get_jwt_identity())
    result = []
    for pid, cfg in OAUTH_PROVIDERS.items():
        tokens = _oauth_tokens.get(uid, {}).get(pid)
        db_config = _get_config(uid, pid)
        result.append({
            'id': pid,
            'name': {'google': 'Google', 'outlook': 'Outlook'}[pid],
            'configured': bool(db_config.get('client_id')),
            'connected': bool(tokens),
            'email': tokens.get('email') if tokens else None,
        })
    return jsonify(result), 200


@oauth_bp.route('/auth-url', methods=['POST'])
@jwt_required()
def get_auth_url():
    uid = int(get_jwt_identity())
    data = request.get_json()
    provider = data.get('provider', 'google')
    if provider not in OAUTH_PROVIDERS:
        return jsonify(msg='不支持的提供商'), 400

    db_config = _get_config(uid, provider)
    if not db_config.get('client_id'):
        return jsonify(msg=f'{provider} client_id 未配置，请在设置页面配置'), 400

    cfg = OAUTH_PROVIDERS[provider]
    state = secrets.token_urlsafe(16)
    redirect_uri = request.host_url.rstrip('/') + '/api/oauth/callback'
    url = (f"{cfg['auth_url']}?client_id={db_config['client_id']}&redirect_uri={redirect_uri}"
           f"&response_type=code&scope={cfg['scope']}&state={state}&access_type=offline&prompt=consent")
    return jsonify(dict(url=url, state=state)), 200


@oauth_bp.route('/callback', methods=['GET'])
def oauth_callback():
    provider = request.args.get('state', '').split(':', 1)[-1] if ':' in (request.args.get('state', '') or '') else 'google'
    code = request.args.get('code')
    if not code:
        return jsonify(msg='OAuth授权失败'), 400

    cfg = OAUTH_PROVIDERS.get(provider)
    if not cfg:
        return jsonify(msg='未知提供商'), 400

    try:
        redirect_uri = request.host_url.rstrip('/') + '/api/oauth/callback'
        # 从数据库查找任意一个已配置该 provider 的用户
        row = OAuthConfig.query.filter_by(provider=provider).filter(OAuthConfig.client_id != '').first()
        if not row:
            return redirect(f"{request.host_url.rstrip('/')}/#/oauth?provider={provider}&error=未找到有效配置")

        resp = requests.post(cfg['token_url'], data={
            'code': code, 'client_id': row.client_id,
            'client_secret': row.client_secret,
            'redirect_uri': redirect_uri, 'grant_type': 'authorization_code'
        }, timeout=30)
        token_data = resp.json()

        access_token = token_data.get('access_token')
        refresh_token = token_data.get('refresh_token', '')
        email = token_data.get('email', '')

        if provider == 'google' and not email:
            userinfo = requests.get('https://www.googleapis.com/oauth2/v2/userinfo',
                                    headers={'Authorization': f'Bearer {access_token}'}).json()
            email = userinfo.get('email', '')

        if provider == 'outlook' and not email:
            userinfo = requests.get('https://graph.microsoft.com/v1.0/me',
                                    headers={'Authorization': f'Bearer {access_token}'}).json()
            email = userinfo.get('mail') or userinfo.get('userPrincipalName', '')

        # 存入内存 token（后续可持久化到 DB）
        uid = row.user_id
        if uid not in _oauth_tokens:
            _oauth_tokens[uid] = {}
        _oauth_tokens[uid][provider] = {
            'access_token': access_token,
            'refresh_token': refresh_token,
            'email': email,
            'connected_at': datetime.utcnow().isoformat()
        }

        return redirect(f"{request.host_url.rstrip('/')}/#/oauth?provider={provider}&success=1")
    except Exception as e:
        return redirect(f"{request.host_url.rstrip('/')}/#/oauth?provider={provider}&error={str(e)}")


@oauth_bp.route('/config', methods=['GET', 'PUT'])
@jwt_required()
def oauth_config():
    uid = int(get_jwt_identity())
    if request.method == 'PUT':
        data = request.get_json()
        provider = data.get('provider', '')
        if provider not in OAUTH_PROVIDERS:
            return jsonify(msg='不支持的提供商'), 400

        row = OAuthConfig.query.filter_by(user_id=uid, provider=provider).first()
        if not row:
            row = OAuthConfig(user_id=uid, provider=provider, client_id='', client_secret='')
            db.session.add(row)
        if 'client_id' in data:
            row.client_id = data['client_id']
        if 'client_secret' in data:
            row.client_secret = data['client_secret']
        db.session.commit()
        return jsonify(msg='配置已保存'), 200

    # GET
    result = {}
    for pid in OAUTH_PROVIDERS.keys():
        db_config = _get_config(uid, pid)
        mask = '****' + db_config['client_secret'][-4:] if db_config.get('client_secret') else ''
        result[pid] = {
            'client_id': db_config.get('client_id', ''),
            'client_secret_mask': mask,
        }
    return jsonify(result), 200