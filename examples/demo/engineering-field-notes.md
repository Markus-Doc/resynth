# Engineering Field Notes on Credential Storage

## What we run in production

Argon2id is the preferred password hashing algorithm across our fleet and we
have seen no operational issues at the recommended parameters.

For the services still on bcrypt, our load testing found a work factor of 10
is sufficient and higher values caused unacceptable login latency on the
older application servers.

## Policy reminders

Plaintext password storage is forbidden in all environments, including
fixtures and test databases.

## Migration practice

Legacy hashes should be upgraded opportunistically by rehashing each
password at the user's next successful login rather than by bulk migration.
