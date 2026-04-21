#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库表结构同步脚本

用途：检查并同步线上环境中的数据库表结构与代码中的模型定义一致。

使用方法：
    python db_sync.py [--dry-run] [--verbose]

参数：
    --dry-run: 仅显示差异，不执行修改
    --verbose: 显示详细信息
    --check-only: 仅检查差异
    --sync-all: 同步所有差异（添加列、修改类型、同步注释等）

环境变量：
    DATABASE_URI: 数据库连接URI（从.env文件或config.py读取）
"""

import sys
import os
import argparse
import json
from datetime import datetime

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 尝试加载 .env 文件
try:
    from dotenv import load_dotenv
    # 尝试加载项目根目录的 .env 文件
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
    if os.path.exists(env_path):
        load_dotenv(env_path)
        print(f"[DB Sync] Loaded .env from {env_path}")
    else:
        # 尝试加载当前目录的 .env
        load_dotenv()
        print("[DB Sync] Loaded .env from current directory")
except ImportError:
    print("[DB Sync] python-dotenv not installed, using environment variables directly")

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.exc import OperationalError, ProgrammingError

from models import db


def create_app():
    """创建 Flask 应用实例"""
    app = Flask(__name__)

    # 优先从环境变量读取 DATABASE_URI
    database_uri = os.getenv('DATABASE_URI') or os.getenv('SQLALCHEMY_DATABASE_URI')

    if database_uri:
        app.config['SQLALCHEMY_DATABASE_URI'] = database_uri
        print(f"[DB Sync] Using DATABASE_URI from environment")
    else:
        # 从 config.py 读取
        try:
            import config
            app.config.from_object(config)
            print(f"[DB Sync] Using config from config.py")
        except Exception as e:
            print(f"[DB Sync] Error loading config: {e}")
            raise RuntimeError(
                "Database configuration not found. Please set DATABASE_URI environment variable "
                "or create a .env file with DATABASE_URI=your_database_uri"
            )

    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    return app


def get_model_columns(model_class):
    """获取模型类定义的所有列信息"""
    columns = {}
    for column in model_class.__table__.columns:
        columns[column.name] = {
            'type': str(column.type),
            'nullable': column.nullable,
            'default': str(column.default.arg) if column.default else None,
            'primary_key': column.primary_key,
            'foreign_key': [str(fk) for fk in column.foreign_keys],
            'comment': column.comment
        }
    return columns


def get_db_columns(engine, table_name):
    """获取数据库表的实际列信息"""
    try:
        inspector = inspect(engine)
        columns = {}
        for col in inspector.get_columns(table_name):
            columns[col['name']] = {
                'type': str(col['type']),
                'nullable': col.get('nullable', True),
                'default': str(col.get('default')) if col.get('default') else None
            }
        return columns
    except Exception as e:
        return {'_error': str(e)}


def get_model_indexes(model_class):
    """获取模型类定义的索引"""
    indexes = {}
    for idx in model_class.__table__.indexes:
        indexes[idx.name] = {
            'columns': [col.name for col in idx.columns],
            'unique': idx.unique
        }
    return indexes


def get_db_indexes(engine, table_name):
    """获取数据库表的实际索引"""
    try:
        inspector = inspect(engine)
        indexes = {}
        for idx in inspector.get_indexes(table_name):
            indexes[idx['name']] = {
                'columns': idx['column_names'],
                'unique': idx['unique']
            }
        return indexes
    except Exception as e:
        return {'_error': str(e)}


def normalize_type(type_str):
    """标准化类型字符串用于比较"""
    type_str = type_str.upper()

    # 移除 COLLATE 子句
    import re
    type_str = re.sub(r'COLLATE\s+["\']?[^"\']+["\']?', '', type_str)

    # 移除长度信息进行比较
    type_str = re.sub(r'\(\d+\)', '', type_str)

    # 统一 VARCHAR/STRING
    if 'STRING' in type_str:
        type_str = type_str.replace('STRING', 'VARCHAR')

    # 统一 BOOLEAN/TINYINT (MySQL 中 BOOLEAN 是 TINYINT(1) 的别名)
    if type_str == 'TINYINT' or type_str == 'TINY':
        type_str = 'BOOLEAN'

    # 清理空白
    type_str = type_str.strip()

    return type_str


def compare_columns(model_cols, db_cols, verbose=False):
    """比较模型定义和数据库表的列差异"""
    differences = []

    # 检查模型中有但数据库中没有的列
    for col_name in model_cols:
        if col_name not in db_cols:
            differences.append({
                'type': 'missing_column',
                'column': col_name,
                'model_def': model_cols[col_name],
                'message': f"列 '{col_name}' 在模型中定义但数据库中不存在"
            })

    # 检查数据库中有但模型中没有的列
    for col_name in db_cols:
        if col_name.startswith('_'):
            continue
        if col_name not in model_cols:
            differences.append({
                'type': 'extra_column',
                'column': col_name,
                'db_def': db_cols[col_name],
                'message': f"列 '{col_name}' 在数据库中存在但模型中未定义"
            })

    # 检查列定义差异
    for col_name in model_cols:
        if col_name in db_cols:
            model_col = model_cols[col_name]
            db_col = db_cols[col_name]

            # 类型比较
            model_type = normalize_type(model_col['type'])
            db_type = normalize_type(db_col['type'])

            if model_type != db_type:
                differences.append({
                    'type': 'type_diff',
                    'column': col_name,
                    'model_type': model_col['type'],
                    'db_type': db_col['type'],
                    'message': f"列 '{col_name}' 类型不一致：模型={model_col['type']}, 数据库={db_col['type']}"
                })

            # 可空性比较
            if model_col['nullable'] != db_col['nullable']:
                differences.append({
                    'type': 'nullable_diff',
                    'column': col_name,
                    'model_nullable': model_col['nullable'],
                    'db_nullable': db_col['nullable'],
                    'message': f"列 '{col_name}' 可空性不一致：模型={model_col['nullable']}, 数据库={db_col['nullable']}"
                })

    return differences


def sync_comments(engine, model_class, verbose=False):
    """同步表和列的注释"""
    changes = []
    table_name = model_class.__tablename__

    # 同步表注释
    table_comment = getattr(model_class.__table__, 'comment', None)
    if table_comment:
        try:
            # MySQL 语法
            sql = f"ALTER TABLE {table_name} COMMENT = :comment"
            engine.execute(text(sql), {'comment': table_comment})
            changes.append(f"表 {table_name} 注释已更新")
        except Exception as e:
            if verbose:
                print(f"  警告: 无法更新表注释: {e}")

    # 同步列注释
    for column in model_class.__table__.columns:
        if column.comment:
            try:
                # MySQL 语法
                col_type = str(column.type)
                if column.nullable:
                    nullable = "NULL"
                else:
                    nullable = "NOT NULL"

                sql = f"ALTER TABLE {table_name} MODIFY COLUMN {column.name} {col_type} {nullable} COMMENT :comment"
                engine.execute(text(sql), {'comment': column.comment})
                changes.append(f"列 {table_name}.{column.name} 注释已更新")
            except Exception as e:
                if verbose:
                    print(f"  警告: 无法更新列注释 {column.name}: {e}")

    return changes


def add_missing_columns(engine, model_class, differences, dry_run=False, verbose=False):
    """添加缺失的列"""
    changes = []
    table_name = model_class.__tablename__

    for diff in differences:
        if diff['type'] == 'missing_column':
            col_def = diff['model_def']
            col_name = diff['column']

            # 构建列定义
            col_sql = f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_def['type']}"

            if not col_def['nullable']:
                col_sql += " NOT NULL"
            else:
                col_sql += " NULL"

            if col_def['default']:
                col_sql += f" DEFAULT {col_def['default']}"

            if col_def.get('comment'):
                col_sql += f" COMMENT '{col_def['comment']}'"

            if dry_run:
                changes.append(f"[DRY-RUN] {col_sql}")
            else:
                try:
                    engine.execute(text(col_sql))
                    changes.append(f"已添加列: {table_name}.{col_name}")
                except Exception as e:
                    changes.append(f"错误: 添加列 {col_name} 失败: {e}")

    return changes


def modify_columns(engine, model_class, differences, dry_run=False, verbose=False):
    """修改现有列"""
    changes = []
    table_name = model_class.__tablename__

    for diff in differences:
        if diff['type'] == 'type_diff' or diff['type'] == 'nullable_diff':
            col_name = diff['column']

            # 获取模型定义
            model_cols = get_model_columns(model_class)
            if col_name not in model_cols:
                continue

            model_def = model_cols[col_name]

            # 构建 MODIFY COLUMN 语句
            col_type = model_def['type']
            if model_def['nullable']:
                nullable = "NULL"
            else:
                nullable = "NOT NULL"

            col_sql = f"ALTER TABLE {table_name} MODIFY COLUMN {col_name} {col_type} {nullable}"

            if model_def.get('comment'):
                col_sql += f" COMMENT '{model_def['comment']}'"

            if dry_run:
                changes.append(f"[DRY-RUN] {col_sql}")
            else:
                try:
                    engine.execute(text(col_sql))
                    changes.append(f"已修改列: {table_name}.{col_name}")
                except Exception as e:
                    changes.append(f"错误: 修改列 {col_name} 失败: {e}")

    return changes


def generate_migration_sql(model_class, differences):
    """生成 SQL 迁移脚本"""
    table_name = model_class.__tablename__
    sql_statements = []

    for diff in differences:
        if diff['type'] == 'missing_column':
            col_def = diff['model_def']
            col_name = diff['column']

            # 构建列定义
            col_sql = f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_def['type']}"

            if not col_def['nullable']:
                col_sql += " NOT NULL"
            else:
                col_sql += " NULL"

            if col_def['default']:
                col_sql += f" DEFAULT {col_def['default']}"

            if col_def.get('comment'):
                col_sql += f" COMMENT '{col_def['comment']}'"

            sql_statements.append(col_sql + ";")

        elif diff['type'] == 'extra_column':
            col_name = diff['column']
            sql_statements.append(f"-- 警告: 数据库中存在但未在模型中定义的列: {table_name}.{col_name}")
            sql_statements.append(f"-- ALTER TABLE {table_name} DROP COLUMN {col_name}; -- 如需删除请取消注释")

        elif diff['type'] == 'type_diff' or diff['type'] == 'nullable_diff':
            col_name = diff['column']
            model_cols = get_model_columns(model_class)
            if col_name in model_cols:
                model_def = model_cols[col_name]
                col_type = model_def['type']
                nullable = "NULL" if model_def['nullable'] else "NOT NULL"

                sql = f"ALTER TABLE {table_name} MODIFY COLUMN {col_name} {col_type} {nullable}"
                if model_def.get('comment'):
                    sql += f" COMMENT '{model_def['comment']}'"
                sql_statements.append(sql + ";")

    return sql_statements


def check_all_tables(app, engine, verbose=False):
    """检查所有模型表"""
    from models import (
        User, Contact, ContactGroup, EmailTemplate,
        Workflow, WorkflowInstance, EmailLog, EmailEvent, NodeExecution
    )

    models = [
        User, Contact, ContactGroup, EmailTemplate,
        Workflow, WorkflowInstance, EmailLog, EmailEvent, NodeExecution
    ]

    results = {}
    total_differences = 0

    print("\n" + "=" * 80)
    print("数据库表结构检查报告")
    print("=" * 80)
    print(f"检查时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"数据库: {app.config.get('SQLALCHEMY_DATABASE_URI', 'unknown')}")
    print("=" * 80 + "\n")

    for model_class in models:
        table_name = model_class.__tablename__
        print(f"\n检查表: {table_name}")
        print("-" * 40)

        # 检查表是否存在 - 使用 inspector 更可靠
        try:
            inspector = inspect(engine)
            existing_tables = inspector.get_table_names()
            table_exists = table_name in existing_tables
        except Exception as e:
            print(f"  错误: 无法获取表列表 - {e}")
            table_exists = False

        if not table_exists:
            print(f"  警告: 表不存在，需要创建")
            results[table_name] = {'exists': False}
            continue

        # 获取模型定义
        model_cols = get_model_columns(model_class)
        model_indexes = get_model_indexes(model_class)

        # 获取数据库实际结构
        db_cols = get_db_columns(engine, table_name)

        if '_error' in db_cols:
            print(f"  错误: 无法读取表结构 - {db_cols['_error']}")
            results[table_name] = {'error': db_cols['_error']}
            continue

        # 比较列差异
        differences = compare_columns(model_cols, db_cols, verbose)

        if differences:
            print(f"  发现 {len(differences)} 个差异:")
            for diff in differences:
                print(f"    - {diff['message']}")
            total_differences += len(differences)
        else:
            print("  [OK] 表结构一致")

        results[table_name] = {
            'columns': len(model_cols),
            'differences': differences,
            'exists': True
        }

    print("\n" + "=" * 80)
    print(f"检查完成: 共发现 {total_differences} 个差异")
    print("=" * 80 + "\n")

    return results


def sync_database(app, engine, dry_run=True, verbose=False, sync_all=False):
    """同步数据库"""
    from models import (
        User, Contact, ContactGroup, EmailTemplate,
        Workflow, WorkflowInstance, EmailLog, EmailEvent, NodeExecution
    )

    models = [
        User, Contact, ContactGroup, EmailTemplate,
        Workflow, WorkflowInstance, EmailLog, EmailEvent, NodeExecution
    ]

    all_changes = []
    all_sql = []

    print("\n" + "=" * 80)
    if dry_run:
        print("数据库同步预览模式 (dry-run)")
    else:
        print("数据库同步执行模式")
    print("=" * 80 + "\n")

    for model_class in models:
        table_name = model_class.__tablename__
        print(f"\n处理表: {table_name}")

        # 检查表是否存在 - 使用 inspector 更可靠
        try:
            inspector = inspect(engine)
            existing_tables = inspector.get_table_names()
            table_exists = table_name in existing_tables
        except Exception as e:
            print(f"  错误: 无法获取表列表 - {e}")
            table_exists = False

        if not table_exists:
            print(f"  表不存在，需要创建")
            if not dry_run:
                model_class.__table__.create(engine)
                all_changes.append(f"创建表 {table_name}")
            continue

        # 获取差异
        model_cols = get_model_columns(model_class)
        db_cols = get_db_columns(engine, table_name)
        differences = compare_columns(model_cols, db_cols, verbose)

        if not differences:
            print("  ✓ 无需同步")
            continue

        print(f"  发现 {len(differences)} 个差异")

        if sync_all:
            # 添加缺失的列
            column_changes = add_missing_columns(
                engine, model_class, differences,
                dry_run=dry_run, verbose=verbose
            )
            all_changes.extend(column_changes)

            # 修改现有列
            if not dry_run:
                modify_changes = modify_columns(
                    engine, model_class, differences,
                    dry_run=dry_run, verbose=verbose
                )
                all_changes.extend(modify_changes)

        # 同步注释
        comment_changes = sync_comments(engine, model_class, verbose)
        if comment_changes:
            all_changes.extend(comment_changes)

        # 生成 SQL
        sql_statements = generate_migration_sql(model_class, differences)
        all_sql.extend(sql_statements)

    # 输出汇总
    print("\n" + "=" * 80)
    if dry_run:
        print("预览模式完成，以下是需要执行的 SQL:")
        print("-" * 80)
        for sql in all_sql:
            print(sql)
    else:
        print(f"同步完成，共执行 {len(all_changes)} 个变更:")
        for change in all_changes:
            print(f"  - {change}")
    print("=" * 80 + "\n")

    return all_changes if not dry_run else all_sql


def main():
    parser = argparse.ArgumentParser(description='数据库表结构同步工具')
    parser.add_argument('--dry-run', action='store_true',
                       help='仅显示差异，不执行修改')
    parser.add_argument('--verbose', action='store_true',
                       help='显示详细信息')
    parser.add_argument('--check-only', action='store_true',
                       help='仅检查，不生成SQL')
    parser.add_argument('--sync-all', action='store_true',
                       help='同步所有差异（添加列、修改类型、同步注释等）')
    parser.add_argument('--sync-comments', action='store_true',
                       help='仅同步注释')

    args = parser.parse_args()

    # 创建应用
    app = create_app()

    with app.app_context():
        engine = db.engine

        if args.check_only:
            # 仅检查模式
            check_all_tables(app, engine, args.verbose)
        elif args.sync_comments:
            # 仅同步注释
            from models import (
                User, Contact, ContactGroup, EmailTemplate,
                Workflow, WorkflowInstance, EmailLog, EmailEvent, NodeExecution
            )
            models = [User, Contact, ContactGroup, EmailTemplate,
                     Workflow, WorkflowInstance, EmailLog, EmailEvent, NodeExecution]
            for model_class in models:
                changes = sync_comments(engine, model_class, args.verbose)
                for change in changes:
                    print(change)
        else:
            # 同步模式
            if args.dry_run:
                # 先检查
                check_all_tables(app, engine, args.verbose)
                # 再生成 SQL
                sync_database(app, engine, dry_run=True, verbose=args.verbose, sync_all=args.sync_all)
            else:
                # 执行同步
                confirm = input("确认要执行数据库修改吗？此操作不可逆！(yes/no): ")
                if confirm.lower() == 'yes':
                    sync_database(app, engine, dry_run=False, verbose=args.verbose, sync_all=args.sync_all)
                else:
                    print("操作已取消")


if __name__ == '__main__':
    main()
