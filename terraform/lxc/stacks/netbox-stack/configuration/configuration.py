####
## We recommend to not edit this file.
## Create separate files to overwrite the settings.
## See `extra.py` as an example.
####

import re
from os import environ
from os.path import abspath, dirname, join
from typing import Any, Callable

# For reference see https://docs.netbox.dev/en/stable/configuration/
# Based on https://github.com/netbox-community/netbox/blob/develop/netbox/netbox/configuration_example.py

###
# NetBox-Docker Helper functions
###

# Read secret from file
def _read_secret(secret_name: str, default: str | None = None) -> str | None:
    try:
        f = open('/run/secrets/' + secret_name, 'r', encoding='utf-8')
    except EnvironmentError:
        return default
    else:
        with f:
            return f.readline().strip()

def _environ_get_and_map(variable_name: str, default: str | None = None, map_fn: Callable[[str], Any | None] = None) -> Any | None:
    env_value = environ.get(variable_name, default)

    if env_value is None:
        return env_value

    if not map_fn:
        return env_value

    return map_fn(env_value)

def _AS_BOOL(value): return value.lower() == 'true'
def _AS_INT(value): return int(value)
def _AS_LIST(value): return list(filter(None, value.split(' ')))

_BASE_DIR = dirname(dirname(abspath(__file__)))

#########################
#                       #
#   Required settings   #
#                       #
#########################

ALLOWED_HOSTS = environ.get('ALLOWED_HOSTS', '*').split(' ')
if '*' not in ALLOWED_HOSTS and 'localhost' not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append('localhost')

DATABASES = {
    'default': {
        'NAME': environ.get('DB_NAME', 'netbox'),
        'USER': environ.get('DB_USER', ''),
        'PASSWORD': _read_secret('db_password', environ.get('DB_PASSWORD', '')),
        'HOST': environ.get('DB_HOST', 'localhost'),
        'PORT': environ.get('DB_PORT', ''),
        'OPTIONS': {'sslmode': environ.get('DB_SSLMODE', 'prefer')},
        'CONN_MAX_AGE': _environ_get_and_map('DB_CONN_MAX_AGE', '300', _AS_INT),
        'DISABLE_SERVER_SIDE_CURSORS': _environ_get_and_map('DB_DISABLE_SERVER_SIDE_CURSORS', 'False', _AS_BOOL),
    }
}

REDIS = {
    'tasks': {
        'HOST': environ.get('REDIS_HOST', 'localhost'),
        'PORT': _environ_get_and_map('REDIS_PORT', 6379, _AS_INT),
        'SENTINELS': [tuple(uri.split(':')) for uri in _environ_get_and_map('REDIS_SENTINELS', '', _AS_LIST) if uri != ''],
        'SENTINEL_SERVICE': environ.get('REDIS_SENTINEL_SERVICE', 'default'),
        'SENTINEL_TIMEOUT': _environ_get_and_map('REDIS_SENTINEL_TIMEOUT', 10, _AS_INT),
        'USERNAME': environ.get('REDIS_USERNAME', ''),
        'PASSWORD': _read_secret('redis_password', environ.get('REDIS_PASSWORD', '')),
        'DATABASE': _environ_get_and_map('REDIS_DATABASE', 0, _AS_INT),
        'SSL': _environ_get_and_map('REDIS_SSL', 'False', _AS_BOOL),
        'INSECURE_SKIP_TLS_VERIFY': _environ_get_and_map('REDIS_INSECURE_SKIP_TLS_VERIFY', 'False', _AS_BOOL),
    },
    'caching': {
        'HOST': environ.get('REDIS_CACHE_HOST', environ.get('REDIS_HOST', 'localhost')),
        'PORT': _environ_get_and_map('REDIS_CACHE_PORT', environ.get('REDIS_PORT', '6379'), _AS_INT),
        'SENTINELS': [tuple(uri.split(':')) for uri in _environ_get_and_map('REDIS_CACHE_SENTINELS', '', _AS_LIST) if uri != ''],
        'SENTINEL_SERVICE': environ.get('REDIS_CACHE_SENTINEL_SERVICE', environ.get('REDIS_SENTINEL_SERVICE', 'default')),
        'USERNAME': environ.get('REDIS_CACHE_USERNAME', environ.get('REDIS_USERNAME', '')),
        'PASSWORD': _read_secret('redis_cache_password', environ.get('REDIS_CACHE_PASSWORD', environ.get('REDIS_PASSWORD', ''))),
        'DATABASE': _environ_get_and_map('REDIS_CACHE_DATABASE', '1', _AS_INT),
        'SSL': _environ_get_and_map('REDIS_CACHE_SSL', environ.get('REDIS_SSL', 'False'), _AS_BOOL),
        'INSECURE_SKIP_TLS_VERIFY': _environ_get_and_map('REDIS_CACHE_INSECURE_SKIP_TLS_VERIFY', environ.get('REDIS_INSECURE_SKIP_TLS_VERIFY', 'False'), _AS_BOOL),
    },
}

SECRET_KEY = _read_secret('secret_key', environ.get('SECRET_KEY', ''))

API_TOKEN_PEPPERS = {}
if api_token_pepper := _read_secret('api_token_pepper_1', environ.get('API_TOKEN_PEPPER_1', '')):
    API_TOKEN_PEPPERS.update({1: api_token_pepper})


#########################
#                       #
#   Optional settings   #
#                       #
#########################

if 'ALLOWED_URL_SCHEMES' in environ:
    ALLOWED_URL_SCHEMES = _environ_get_and_map('ALLOWED_URL_SCHEMES', None, _AS_LIST)

if 'BANNER_TOP' in environ:
    BANNER_TOP = environ.get('BANNER_TOP', None)
if 'BANNER_BOTTOM' in environ:
    BANNER_BOTTOM = environ.get('BANNER_BOTTOM', None)

if 'BANNER_LOGIN' in environ:
    BANNER_LOGIN = environ.get('BANNER_LOGIN', None)

if 'CHANGELOG_RETENTION' in environ:
    CHANGELOG_RETENTION = _environ_get_and_map('CHANGELOG_RETENTION', None, _AS_INT)

if 'JOB_RETENTION' in environ:
    JOB_RETENTION = _environ_get_and_map('JOB_RETENTION', None, _AS_INT)
elif 'JOBRESULT_RETENTION' in environ:
    JOB_RETENTION = _environ_get_and_map('JOBRESULT_RETENTION', None, _AS_INT)

CORS_ORIGIN_ALLOW_ALL = _environ_get_and_map('CORS_ORIGIN_ALLOW_ALL', 'False', _AS_BOOL)
CORS_ORIGIN_WHITELIST = _environ_get_and_map('CORS_ORIGIN_WHITELIST', 'https://localhost', _AS_LIST)
CORS_ORIGIN_REGEX_WHITELIST = [re.compile(r) for r in _environ_get_and_map('CORS_ORIGIN_REGEX_WHITELIST', '', _AS_LIST)]

DEBUG = _environ_get_and_map('DEBUG', 'False', _AS_BOOL)

DEVELOPER = _environ_get_and_map('DEVELOPER', 'False', _AS_BOOL)

EMAIL = {
    'SERVER': environ.get('EMAIL_SERVER', 'localhost'),
    'PORT': _environ_get_and_map('EMAIL_PORT', 25, _AS_INT),
    'USERNAME': environ.get('EMAIL_USERNAME', ''),
    'PASSWORD': _read_secret('email_password', environ.get('EMAIL_PASSWORD', '')),
    'USE_SSL': _environ_get_and_map('EMAIL_USE_SSL', 'False', _AS_BOOL),
    'USE_TLS': _environ_get_and_map('EMAIL_USE_TLS', 'False', _AS_BOOL),
    'SSL_CERTFILE': environ.get('EMAIL_SSL_CERTFILE', ''),
    'SSL_KEYFILE': environ.get('EMAIL_SSL_KEYFILE', ''),
    'TIMEOUT': _environ_get_and_map('EMAIL_TIMEOUT', 10, _AS_INT),
    'FROM_EMAIL': environ.get('EMAIL_FROM', ''),
}

if 'ENFORCE_GLOBAL_UNIQUE' in environ:
    ENFORCE_GLOBAL_UNIQUE = _environ_get_and_map('ENFORCE_GLOBAL_UNIQUE', None, _AS_BOOL)

if 'CENSUS_REPORTING_ENABLED' in environ:
    CENSUS_REPORTING_ENABLED = _environ_get_and_map('CENSUS_REPORTING_ENABLED', None, _AS_BOOL)

EXEMPT_VIEW_PERMISSIONS = _environ_get_and_map('EXEMPT_VIEW_PERMISSIONS', '', _AS_LIST)

HTTP_PROXIES = {
    'http': environ.get('HTTP_PROXY', None),
    'https': environ.get('HTTPS_PROXY', None),
}

INTERNAL_IPS = _environ_get_and_map('INTERNAL_IPS', '127.0.0.1 ::1', _AS_LIST)

if 'GRAPHQL_ENABLED' in environ:
    GRAPHQL_ENABLED = _environ_get_and_map('GRAPHQL_ENABLED', None, _AS_BOOL)

LOGIN_PERSISTENCE = _environ_get_and_map('LOGIN_PERSISTENCE', 'False', _AS_BOOL)

LOGIN_REQUIRED = _environ_get_and_map('LOGIN_REQUIRED', 'True', _AS_BOOL)

LOGIN_TIMEOUT = _environ_get_and_map('LOGIN_TIMEOUT', 1209600, _AS_INT)

if 'MAINTENANCE_MODE' in environ:
    MAINTENANCE_MODE = _environ_get_and_map('MAINTENANCE_MODE', None, _AS_BOOL)

if 'MAPS_URL' in environ:
    MAPS_URL = environ.get('MAPS_URL', None)

if 'MAX_PAGE_SIZE' in environ:
    MAX_PAGE_SIZE = _environ_get_and_map('MAX_PAGE_SIZE', None, _AS_INT)

MEDIA_ROOT = environ.get('MEDIA_ROOT', join(_BASE_DIR, 'media'))

METRICS_ENABLED = _environ_get_and_map('METRICS_ENABLED', 'False', _AS_BOOL)

if 'PAGINATE_COUNT' in environ:
    PAGINATE_COUNT = _environ_get_and_map('PAGINATE_COUNT', None, _AS_INT)

if 'PREFER_IPV4' in environ:
    PREFER_IPV4 = _environ_get_and_map('PREFER_IPV4', None, _AS_BOOL)

if 'POWERFEED_DEFAULT_AMPERAGE' in environ:
    POWERFEED_DEFAULT_AMPERAGE = _environ_get_and_map('POWERFEED_DEFAULT_AMPERAGE', None, _AS_INT)

if 'POWERFEED_DEFAULT_MAX_UTILIZATION' in environ:
    POWERFEED_DEFAULT_MAX_UTILIZATION = _environ_get_and_map('POWERFEED_DEFAULT_MAX_UTILIZATION', None, _AS_INT)

if 'POWERFEED_DEFAULT_VOLTAGE' in environ:
    POWERFEED_DEFAULT_VOLTAGE = _environ_get_and_map('POWERFEED_DEFAULT_VOLTAGE', None, _AS_INT)

if 'RACK_ELEVATION_DEFAULT_UNIT_HEIGHT' in environ:
    RACK_ELEVATION_DEFAULT_UNIT_HEIGHT = _environ_get_and_map('RACK_ELEVATION_DEFAULT_UNIT_HEIGHT', None, _AS_INT)

if 'RACK_ELEVATION_DEFAULT_UNIT_WIDTH' in environ:
    RACK_ELEVATION_DEFAULT_UNIT_WIDTH = _environ_get_and_map('RACK_ELEVATION_DEFAULT_UNIT_WIDTH', None, _AS_INT)

REMOTE_AUTH_AUTO_CREATE_GROUPS = _environ_get_and_map('REMOTE_AUTH_AUTO_CREATE_GROUPS', 'False', _AS_BOOL)
REMOTE_AUTH_AUTO_CREATE_USER = _environ_get_and_map('REMOTE_AUTH_AUTO_CREATE_USER', 'False', _AS_BOOL)
REMOTE_AUTH_BACKEND = _environ_get_and_map('REMOTE_AUTH_BACKEND', 'netbox.authentication.RemoteUserBackend', _AS_LIST)
REMOTE_AUTH_DEFAULT_GROUPS = _environ_get_and_map('REMOTE_AUTH_DEFAULT_GROUPS', '', _AS_LIST)
REMOTE_AUTH_ENABLED = _environ_get_and_map('REMOTE_AUTH_ENABLED', 'False', _AS_BOOL)
REMOTE_AUTH_GROUP_HEADER = _environ_get_and_map('REMOTE_AUTH_GROUP_HEADER', 'HTTP_REMOTE_USER_GROUP')
REMOTE_AUTH_GROUP_SEPARATOR = _environ_get_and_map('REMOTE_AUTH_GROUP_SEPARATOR', '|')
REMOTE_AUTH_GROUP_SYNC_ENABLED = _environ_get_and_map('REMOTE_AUTH_GROUP_SYNC_ENABLED', 'False', _AS_BOOL)
REMOTE_AUTH_HEADER = environ.get('REMOTE_AUTH_HEADER', 'HTTP_REMOTE_USER')
REMOTE_AUTH_USER_EMAIL = environ.get('REMOTE_AUTH_USER_EMAIL', 'HTTP_REMOTE_USER_EMAIL')
REMOTE_AUTH_USER_FIRST_NAME = environ.get('REMOTE_AUTH_USER_FIRST_NAME', 'HTTP_REMOTE_USER_FIRST_NAME')
REMOTE_AUTH_USER_LAST_NAME = environ.get('REMOTE_AUTH_USER_LAST_NAME', 'HTTP_REMOTE_USER_LAST_NAME')
REMOTE_AUTH_SUPERUSER_GROUPS = _environ_get_and_map('REMOTE_AUTH_SUPERUSER_GROUPS', '', _AS_LIST)
REMOTE_AUTH_SUPERUSERS = _environ_get_and_map('REMOTE_AUTH_SUPERUSERS', '', _AS_LIST)
REMOTE_AUTH_STAFF_GROUPS = _environ_get_and_map('REMOTE_AUTH_STAFF_GROUPS', '', _AS_LIST)
REMOTE_AUTH_STAFF_USERS = _environ_get_and_map('REMOTE_AUTH_STAFF_USERS', '', _AS_LIST)

# SSO Configuration
SOCIAL_AUTH_OKTA_OPENIDCONNECT_KEY = environ.get('SOCIAL_AUTH_OKTA_OPENIDCONNECT_KEY')
SOCIAL_AUTH_OKTA_OPENIDCONNECT_SECRET = _read_secret('okta_openidconnect_secret', environ.get('SOCIAL_AUTH_OKTA_OPENIDCONNECT_SECRET', ''))
SOCIAL_AUTH_OKTA_OPENIDCONNECT_API_URL = environ.get('SOCIAL_AUTH_OKTA_OPENIDCONNECT_API_URL')
SOCIAL_AUTH_GOOGLE_OAUTH2_KEY = environ.get('SOCIAL_AUTH_GOOGLE_OAUTH2_KEY')
SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET = _read_secret('google_oauth2_secret', environ.get('SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET', ''))

# OIDC Configuration
SOCIAL_AUTH_OIDC_OIDC_ENDPOINT = environ.get('SOCIAL_AUTH_OIDC_OIDC_ENDPOINT')
SOCIAL_AUTH_OIDC_KEY = environ.get('SOCIAL_AUTH_OIDC_KEY')
SOCIAL_AUTH_OIDC_SECRET = _read_secret('oidc_secret', environ.get('SOCIAL_AUTH_OIDC_SECRET', ''))
SOCIAL_AUTH_OIDC_SCOPE = _environ_get_and_map('SOCIAL_AUTH_OIDC_SCOPE', '', _AS_LIST)
LOGOUT_REDIRECT_URL = environ.get('LOGOUT_REDIRECT_URL', '/')
SOCIAL_AUTH_OIDC_JWT_ALGORITHMS = _environ_get_and_map('SOCIAL_AUTH_OIDC_JWT_ALGORITHMS', "RS256", _AS_LIST)

RELEASE_CHECK_URL = environ.get('RELEASE_CHECK_URL', None)

RQ_DEFAULT_TIMEOUT = _environ_get_and_map('RQ_DEFAULT_TIMEOUT', 300, _AS_INT)

CSRF_COOKIE_NAME = environ.get('CSRF_COOKIE_NAME', 'csrftoken')

CSRF_TRUSTED_ORIGINS = _environ_get_and_map('CSRF_TRUSTED_ORIGINS', '', _AS_LIST)

SESSION_COOKIE_NAME = environ.get('SESSION_COOKIE_NAME', 'sessionid')

SECURE_HSTS_INCLUDE_SUBDOMAINS = _environ_get_and_map('SECURE_HSTS_INCLUDE_SUBDOMAINS', 'False', _AS_BOOL)

SECURE_HSTS_PRELOAD = _environ_get_and_map('SECURE_HSTS_PRELOAD', 'False', _AS_BOOL)

SECURE_HSTS_SECONDS = _environ_get_and_map('SECURE_HSTS_SECONDS', 0, _AS_INT)

SECURE_SSL_REDIRECT = _environ_get_and_map('SECURE_SSL_REDIRECT', 'False', _AS_BOOL)

SESSION_FILE_PATH = environ.get('SESSION_FILE_PATH', environ.get('SESSIONS_ROOT', None))

TIME_ZONE = environ.get('TIME_ZONE', 'UTC')

ISOLATED_DEPLOYMENT = _environ_get_and_map('ISOLATED_DEPLOYMENT', 'False', _AS_BOOL)

COPILOT_ENABLED = _environ_get_and_map('COPILOT_ENABLED', 'True', _AS_BOOL)
