from flask import Blueprint, request, jsonify, session

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    return jsonify({'ok': True, 'message': 'API service only. Use /api/auth/login.'})

        print(f"DEBUG: username='{username}', password='{password}'")

        user = User.query.filter_by(username=username).first()
        print(f"DEBUG: user found: {user is not None}")

        if user:
            print(f"DEBUG: stored hash: {user.password_hash}")
            valid = check_password_hash(user.password_hash, password)
            print(f"DEBUG: password valid: {valid}")
        else:
            valid = False

        if user and valid:
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role
            flash('登录成功', 'success')
            return redirect(url_for('user.dashboard'))  # 跳转到仪表盘
        else:
            flash('用户名或密码错误', 'danger')
            return redirect(url_for('auth.login'))

    return jsonify({'ok': True, 'message': 'API service only'})

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    return jsonify({'ok': True, 'message': 'API service only. Use /api/auth/register.'})

        if User.query.filter_by(username=username).first():
            flash('用户名已存在', 'danger')
            return redirect(url_for('auth.register'))

        user = User(username=username, role='user')
        user.password = password
        db.session.add(user)
        db.session.commit()

        flash('注册成功，请登录', 'success')
        return redirect(url_for('auth.login'))

    return jsonify({'ok': True, 'message': 'API service only'})

@auth_bp.route('/logout')
def logout():
    session.clear()
    return jsonify({'ok': True, 'message': 'Logged out'})
