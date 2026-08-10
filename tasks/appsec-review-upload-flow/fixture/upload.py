import os
UPLOAD_ROOT = "/srv/uploads"

def save_upload(filename, content):
    path = os.path.join(UPLOAD_ROOT, filename)
    with open(path, "w") as f:
        f.write(content)
    return path
