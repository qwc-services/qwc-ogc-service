import _locale
import json
import os

# Since musl-locale is incomplete, allow overriding localeconv settings by
# monkey-patching _locale.localeconv
_original_localeconv = _locale.localeconv

def patched_localeconv():
    native_dict = _original_localeconv()
    native_dict.update(json.loads(os.getenv("LOCALECONV_OVERRIDES", "{}")))
    return native_dict

_locale.localeconv = patched_localeconv
