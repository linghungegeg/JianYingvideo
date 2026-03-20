from flask import Blueprint, jsonify, session

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    return jsonify({'ok': True, 'message': 'API service only. Use /api/auth/login.'})


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    return jsonify({'ok': True, 'message': 'API service only. Use /api/auth/register.'})


@auth_bp.route('/logout')
def logout():
    session.clear()
    return jsonify({'ok': True, 'message': 'Logged out'})
