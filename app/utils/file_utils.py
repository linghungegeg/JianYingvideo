import os
from werkzeug.utils import secure_filename

def allowed_file(filename, allowed_extensions=None):
    if allowed_extensions is None:
        allowed_extensions = {'json', 'png', 'jpg', 'jpeg', 'webp'}
    return '.' in filename and            filename.rsplit('.', 1)[1].lower() in allowed_extensions

def save_uploaded_file(file, folder, filename=None):
    if filename is None:
        filename = secure_filename(file.filename)
    path = os.path.join(folder, filename)
    file.save(path)
    return path
