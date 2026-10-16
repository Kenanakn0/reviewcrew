## Security review checklist

Look for vulnerabilities introduced by the change, including:

- Injection: SQL/NoSQL queries built from strings or f-strings with external input, OS command
  injection (`shell=True`, `os.system`, string-built commands), LDAP/XPath/template injection,
  path traversal in file operations.
- Hardcoded secrets: API keys, tokens, passwords, private keys or connection strings with
  credentials committed in code or config.
- Broken authentication or authorization: missing or bypassable permission checks, removed
  checks, insecure session or token handling, JWTs accepted without signature verification.
- Cross-site scripting and unsafe HTML rendering (`innerHTML`, `dangerouslySetInnerHTML`,
  disabled template auto-escaping, `mark_safe` on user input).
- Insecure deserialization (`pickle`, `yaml.load` without a safe loader, `eval`/`exec` on input).
- Server-side request forgery, open redirects, and unvalidated URLs.
- Weak cryptography: MD5/SHA1 for passwords, ECB mode, hardcoded IVs or salts, `random` for
  security tokens, disabled TLS verification (`verify=False`).
- Sensitive data exposure: secrets or personal data written to logs, verbose error messages
  returned to clients, overly permissive CORS.
- Security misconfiguration: debug mode in production settings, permissive file permissions.

Severity: critical = exploitable now with serious impact (e.g. SQL injection on a public
endpoint, a live credential); high = likely exploitable; medium = a weakness that needs
preconditions; low = hardening.

Do not report style, performance or test coverage issues; other reviewers handle those.
