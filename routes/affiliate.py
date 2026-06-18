"""
联盟营销 — 推荐链接追踪与佣金
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, Referral, ReferralClick, ReferralSignup, Commission
from datetime import datetime
import secrets

affiliate_bp = Blueprint('affiliate', __name__)


@affiliate_bp.route('/link', methods=['GET'])
@jwt_required()
def get_referral_link():
    uid = int(get_jwt_identity())
    ref = Referral.query.filter_by(referrer_id=uid).first()
    if ref:
        link = request.host_url.rstrip('/') + f'/api/affiliate/r/{ref.code}'
        signups = ReferralSignup.query.filter_by(referral_id=ref.id).count()
        commissions_q = Commission.query.filter_by(referrer_id=uid).all()
        return jsonify(dict(
            code=ref.code, link=link, clicks=ref.click_count,
            signups=signups,
            commissions=[dict(amount=float(c.amount), status=c.status, created_at=c.created_at.strftime('%Y-%m-%d %H:%M:%S')) for c in commissions_q],
            total_paid=sum(float(c.amount) for c in commissions_q if c.status == 'paid'),
            total_pending=sum(float(c.amount) for c in commissions_q if c.status == 'pending'),
        )), 200
    code = secrets.token_urlsafe(8)[:12]
    ref = Referral(referrer_id=uid, code=code, click_count=0)
    db.session.add(ref)
    db.session.commit()
    link = request.host_url.rstrip('/') + f'/api/affiliate/r/{code}'
    return jsonify(dict(code=code, link=link, clicks=0, signups=0, commissions=[], total_paid=0, total_pending=0)), 200


@affiliate_bp.route('/r/<code>', methods=['GET'])
def referral_redirect(code):
    code = code.strip()
    ref = Referral.query.filter_by(code=code).first()
    if not ref:
        return jsonify(msg='无效的推荐链接'), 404
    ref.click_count = (ref.click_count or 0) + 1
    db.session.add(ReferralClick(referral_id=ref.id, ip=request.remote_addr or ''))
    db.session.commit()
    target_url = f"{request.host_url.rstrip('/')}/#/login?ref={code}"
    return f'<html><head><meta http-equiv="refresh" content="0;url={target_url}"></head>' \
           f'<body>Redirecting to <a href="{target_url}">login</a>...</body></html>', 200


@affiliate_bp.route('/stats', methods=['GET'])
@jwt_required()
def get_stats():
    uid = int(get_jwt_identity())
    ref = Referral.query.filter_by(referrer_id=uid).first()
    if not ref:
        return jsonify(dict(code=None, clicks=0, signups=0, commissions=[], total_paid=0, total_pending=0)), 200
    signups = ReferralSignup.query.filter_by(referral_id=ref.id).count()
    commissions_q = Commission.query.filter_by(referrer_id=uid).all()
    return jsonify(dict(
        code=ref.code,
        clicks=ref.click_count or 0,
        signups=signups,
        commissions=[dict(amount=float(c.amount), status=c.status, created_at=c.created_at.strftime('%Y-%m-%d %H:%M:%S')) for c in commissions_q],
        total_paid=sum(float(c.amount) for c in commissions_q if c.status == 'paid'),
        total_pending=sum(float(c.amount) for c in commissions_q if c.status == 'pending'),
    )), 200


@affiliate_bp.route('/commissions', methods=['GET'])
@jwt_required()
def list_commissions():
    uid = int(get_jwt_identity())
    commissions_q = Commission.query.filter_by(referrer_id=uid).all()
    return jsonify([dict(amount=float(c.amount), status=c.status, created_at=c.created_at.strftime('%Y-%m-%d %H:%M:%S')) for c in commissions_q]), 200