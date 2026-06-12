"""Deprecated alias package: ``cowork_dash`` is now ``langstage``.

Kept for one transition window so existing imports keep working. Import
``langstage`` instead.
"""
import sys as _sys
import warnings as _warnings

import langstage as _new
from langstage import *  # noqa: F401,F403
from langstage import app, cli, config  # noqa: F401

_warnings.warn(
    "cowork_dash has been renamed to langstage; "
    "this alias package will be removed in a future release.",
    DeprecationWarning,
    stacklevel=2,
)

_sys.modules[__name__ + ".app"] = app
_sys.modules[__name__ + ".cli"] = cli
_sys.modules[__name__ + ".config"] = config
__version__ = getattr(_new, "__version__", "0")
