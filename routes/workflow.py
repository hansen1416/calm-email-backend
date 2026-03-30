import json
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, Workflow, EmailTemplate, EmailLog, Contact, ContactGroup
from routes.email import send_ses_email

workflow_bp = Blueprint('workflow', __name__)

def wf_to_dict(w):
    return dict(id=w.id, name=w.name, flow_data=json.loads(w.flow_data),
                created_at=w.created_at.strftime('%Y-%m-%d %H:%M:%S'))

@workflow_bp.route('', methods=['GET'])
@jwt_required()
def list_workflows():
    uid = int(get_jwt_identity())
    wfs = Workflow.query.filter_by(user_id=uid).order_by(Workflow.created_at.desc()).all()
    return jsonify([wf_to_dict(w) for w in wfs]), 200

@workflow_bp.route('', methods=['POST'])
@jwt_required()
def create_workflow():
    uid = int(get_jwt_identity())
    data = request.get_json()
    if not data.get('name'):
        return jsonify(msg='名称不能为空'), 400
    w = Workflow(user_id=uid, name=data['name'], flow_data=json.dumps(data.get('flow_data', {})))
    db.session.add(w)
    db.session.commit()
    return jsonify(wf_to_dict(w)), 201

@workflow_bp.route('/<int:wid>', methods=['PUT'])
@jwt_required()
def update_workflow(wid):
    uid = int(get_jwt_identity())
    w = Workflow.query.filter_by(id=wid, user_id=uid).first()
    if not w:
        return jsonify(msg='工作流不存在'), 404
    data = request.get_json()
    w.name = data.get('name', w.name)
    w.flow_data = json.dumps(data.get('flow_data', json.loads(w.flow_data)))
    db.session.commit()
    return jsonify(wf_to_dict(w)), 200

@workflow_bp.route('/<int:wid>', methods=['DELETE'])
@jwt_required()
def delete_workflow(wid):
    uid = int(get_jwt_identity())
    w = Workflow.query.filter_by(id=wid, user_id=uid).first()
    if not w:
        return jsonify(msg='工作流不存在'), 404
    db.session.delete(w)
    db.session.commit()
    return jsonify(msg='删除成功'), 200

@workflow_bp.route('/<int:wid>/execute', methods=['POST'])
@jwt_required()
def execute_workflow(wid):
    uid = int(get_jwt_identity())
    w = Workflow.query.filter_by(id=wid, user_id=uid).first()
    if not w:
        return jsonify(msg='工作流不存在'), 404

    flow = json.loads(w.flow_data)
    nodes = flow.get('nodes', [])
    edges = flow.get('edges', [])
    results = []

    # 构建节点ID到节点数据的映射
    node_map = {n['id']: n for n in nodes}

    # 构建邻接表，找出每个节点的下一个节点列表
    next_map = {}
    for e in edges:
        source = e.get('source')
        target = e.get('target')
        if source and target:
            if source not in next_map:
                next_map[source] = []
            next_map[source].append(target)

    # 找到起始节点（没有入边的节点）
    target_ids = {e.get('target') for e in edges if e.get('target')}
    start_nodes = [n for n in nodes if n['id'] not in target_ids]

    # 按位置排序起始节点：先左后右，先上后下
    start_nodes.sort(key=lambda n: (n.get('x', 0), n.get('y', 0)))

    # 按连接顺序执行节点
    def execute_node(node):
        data = node.get('data', {})
        template_id = data.get('template_id')
        contact_ids = data.get('contact_ids', [])
        group_ids = data.get('group_ids', [])
        label = data.get('label', '未命名节点')

        if not template_id:
            return

        tpl = EmailTemplate.query.filter_by(id=template_id, user_id=uid).first()
        if not tpl:
            return

        emails = set()
        if contact_ids:
            for c in Contact.query.filter(Contact.id.in_(contact_ids), Contact.user_id==uid).all():
                emails.add(c.email)
        if group_ids:
            for g in ContactGroup.query.filter(ContactGroup.id.in_(group_ids), ContactGroup.user_id==uid).all():
                for c in g.contacts:
                    emails.add(c.email)

        for addr in emails:
            ok = send_ses_email(addr, tpl.subject, tpl.body)
            log = EmailLog(user_id=uid, template_id=tpl.id, recipient_email=addr,
                           subject=tpl.subject, status='sent' if ok else 'failed')
            db.session.add(log)
            results.append(dict(node=label, template=tpl.name, email=addr, status='sent' if ok else 'failed'))

    # 从起始节点开始，按边连接顺序依次执行（先左后右，先上后下）
    def traverse_from(start_node, visited):
        start_id = start_node['id']
        if start_id in visited:
            return
        visited.add(start_id)
        if start_id in node_map:
            execute_node(node_map[start_id])
        
        # 获取下一个节点列表，按位置排序
        next_ids = next_map.get(start_id, [])
        next_nodes = [node_map[nid] for nid in next_ids if nid in node_map]
        next_nodes.sort(key=lambda n: (n.get('x', 0), n.get('y', 0)))
        
        for next_node in next_nodes:
            traverse_from(next_node, visited)

    visited = set()
    for start_node in start_nodes:
        traverse_from(start_node, visited)

    # 如果没有边，按位置排序执行
    if not edges:
        sorted_nodes = sorted(nodes, key=lambda n: (n.get('x', 0), n.get('y', 0)))
        for node in sorted_nodes:
            execute_node(node)

    db.session.commit()
    return jsonify(results=results), 200
