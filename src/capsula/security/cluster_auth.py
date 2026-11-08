"""OIDC validation for CAPSULA's tenant-scoped cluster API.

Do not use this verifier as an authorization layer for legacy single-admin routes.
OIDC issuer/audience/JWKS are operator-pinned; no arbitrary token-provided keys.
"""
from dataclasses import dataclass
import os
import re
from urllib.parse import urlsplit
import jwt
from jwt import PyJWKClient

TENANT_RE=re.compile(r"^[a-z][a-z0-9-]{2,62}$")
ROLE_LEVEL={"viewer":0,"operator":1,"admin":2,"owner":3}
_CACHED={}

@dataclass(frozen=True)
class Principal:
    subject:str
    tenant:str
    role:str
    issuer:str

def oidc_config():
    issuer=os.getenv("CAPSULA_OIDC_ISSUER","").rstrip("/")
    audience=os.getenv("CAPSULA_OIDC_AUDIENCE","")
    jwks=os.getenv("CAPSULA_OIDC_JWKS_URL","")
    parts=urlsplit(jwks)
    source=urlsplit(issuer)
    valid=(source.scheme=="https" and parts.scheme=="https"
       and source.hostname and parts.hostname and source.hostname==parts.hostname
       and parts.path and not (parts.username or parts.password or parts.query or parts.fragment)
       and not (source.username or source.password or source.query or source.fragment)
       and bool(audience))
    if not valid:
        raise RuntimeError("Pinned HTTPS OIDC issuer/audience and same-host JWKS URL required")
    return issuer,audience,jwks

def authenticate(raw, *, jwks_client=None, config=None):
    if not isinstance(raw,str) or not raw.startswith("Bearer ") or len(raw)>16384:
        raise PermissionError("Bearer token required")
    token=raw[7:]
    if not token or token.count(".")!=2:raise PermissionError("Malformed bearer token")
    issuer,audience,url=config or oidc_config()
    try:
        # Explicitly whitelist RS256, reject alg=none/HS256 and token-supplied URLs.
        client=jwks_client
        if client is None:
            client=_CACHED.get(url)
            if client is None:
                client=PyJWKClient(url,cache_jwk_set=True,lifespan=300,timeout=4)
                _CACHED[url]=client
        key=client.get_signing_key_from_jwt(token).key
        claims=jwt.decode(token,key,algorithms=["RS256"],audience=audience,
                          issuer=issuer,options={"require":["exp","iat","iss","aud","sub"]},
                          leeway=15)
    except (jwt.PyJWTError,ValueError,TypeError) as exc:
        raise PermissionError("OIDC signature or claims rejected") from exc
    tenant=claims.get("capsula_tenant")
    role=claims.get("capsula_role")
    subject=claims.get("sub")
    if not isinstance(tenant,str) or not TENANT_RE.fullmatch(tenant):
        raise PermissionError("Missing or invalid tenant claim")
    if role not in ROLE_LEVEL or not isinstance(subject,str) or not 1<=len(subject)<=256:
        raise PermissionError("Missing subject/role authority")
    return Principal(subject,tenant,role,issuer)

def authorize(principal,tenant,role="viewer"):
    if tenant!=principal.tenant or ROLE_LEVEL.get(principal.role,-1)<ROLE_LEVEL[role]:
        raise PermissionError("Tenant scope or required role denied")
