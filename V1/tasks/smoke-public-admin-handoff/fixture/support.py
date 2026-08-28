REQUESTS = []

def submit_request(email, subject, body):
    """Create and return a pending request dict."""
    raise NotImplementedError('public intake not implemented')

def admin_list(status=None):
    raise NotImplementedError('admin listing not implemented')

def admin_resolve(request_id, note):
    """Resolve a request and store the note in admin_note."""
    raise NotImplementedError('admin resolution not implemented')
