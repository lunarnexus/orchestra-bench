STORAGE_ROOT = '/safe/uploads'
UPLOADS = []

def submit_upload(user_id, filename, content):
    raise NotImplementedError('upload intake not implemented')

def admin_list(status=None):
    raise NotImplementedError('admin list not implemented')

def admin_approve(upload_id):
    raise NotImplementedError('admin approve not implemented')
