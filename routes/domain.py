"""
DNS 记录验证 — SPF / DKIM / DMARC
"""
from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

domain_bp = Blueprint('domain', __name__)


@domain_bp.route('/verify', methods=['POST'])
@jwt_required()
def verify_domain():
    uid = int(get_jwt_identity())
    from flask import request
    data = request.get_json()
    domain = (data.get('domain') or '').strip().lower()
    if not domain:
        return jsonify(msg='请输入域名'), 400

    records = {
        'spf': {'status': 'unknown', 'value': None, 'expected': f'v=spf1 include:amazonses.com ~all'},
        'dkim': {'status': 'unknown', 'value': None, 'expected': None},
        'dmarc': {'status': 'unknown', 'value': None, 'expected': 'v=DMARC1; p=quarantine; rua=mailto:dmarc@{domain}'},
    }

    try:
        import dns.resolver
        # SPF
        try:
            answers = dns.resolver.resolve(domain, 'TXT')
            for a in answers:
                txt = a.to_text().strip('"')
                if 'v=spf1' in txt:
                    records['spf']['value'] = txt
                    records['spf']['status'] = 'passed' if 'amazonses.com' in txt else 'warning'
        except Exception:
            records['spf']['status'] = 'missing'

        # DKIM
        dkim_domains = [
            f'_domainkey.{domain}',
            f'google._domainkey.{domain}',
            f'selector1._domainkey.{domain}',
            f'selector2._domainkey.{domain}',
            f'pam._domainkey.{domain}',
        ]
        for dkim_domain in dkim_domains:
            try:
                answers = dns.resolver.resolve(dkim_domain, 'CNAME')
                for a in answers:
                    val = a.to_text().rstrip('.')
                    if 'amazon' in val.lower() or 'dkim' in val.lower():
                        records['dkim']['value'] = f'{dkim_domain} → {val}'
                        records['dkim']['status'] = 'passed'
                        break
                if records['dkim']['status'] == 'passed':
                    break
            except Exception:
                continue
        if records['dkim']['status'] == 'unknown':
            records['dkim']['status'] = 'missing'
            records['dkim']['expected'] = '需要在AWS SES中获取DKIM记录'

        # DMARC
        try:
            answers = dns.resolver.resolve(f'_dmarc.{domain}', 'TXT')
            for a in answers:
                txt = a.to_text().strip('"')
                if 'v=DMARC1' in txt:
                    records['dmarc']['value'] = txt
                    records['dmarc']['status'] = 'passed'
        except Exception:
            records['dmarc']['status'] = 'missing'
            records['dmarc']['expected'] = records['dmarc']['expected'].replace('{domain}', domain)

    except ImportError:
        return jsonify(msg='dns.resolver 不可用，请安装 dnspython'), 500
    except Exception as e:
        return jsonify(msg=f'DNS查询失败: {str(e)}'), 500

    all_pass = all(r['status'] == 'passed' for r in records.values())
    return jsonify(dict(domain=domain, records=records, all_pass=all_pass)), 200