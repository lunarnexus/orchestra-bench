# Release Policy

Migrations must be reversible and preserve unknown fields for compatibility.

Release notes may include record counts and public field names, but must never include secret-bearing values from fields named `token` or `private_note`.
