"""Shared paths for music-library-tools.

Each setting comes from (first match wins): an environment variable, the JSON config file
~/.config/music-library-tools/config.json, or the default below.

  key            env var          default
  library        MLT_LIBRARY      ~/Music/Music/Media            Music's media folder
  data           MLT_DATA         ~/Music/Library Tools          database + snapshots
  reports        MLT_REPORTS      <data>/reports                 dated reports
  recovery_dir   MLT_RECOVERY     <reports>                      backup-recovery work files
  primary_mac    MLT_PRIMARY_MAC  (none)                         computer name whose recoveries go to <data>/Recovered

Example config.json:
  {"library": "~/Music/iTunes/iTunes Media", "data": "~/Music/Recovered",
   "reports": "~/Library/Mobile Documents/com~apple~CloudDocs/Recovered Music"}
"""
import os, json

REPO = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.expanduser('~/.config/music-library-tools/config.json')
try:
    with open(CONFIG_FILE) as f: _cfg = json.load(f)
except (OSError, ValueError):
    _cfg = {}

def _get(key, env, default):
    v = os.environ.get(env) or _cfg.get(key) or default
    return os.path.expanduser(v) if isinstance(v, str) else v

LIBRARY      = _get('library', 'MLT_LIBRARY', '~/Music/Music/Media')
DATA         = _get('data', 'MLT_DATA', '~/Music/Library Tools')
REPORTS      = _get('reports', 'MLT_REPORTS', os.path.join(DATA, 'reports'))
RECOVERY_DIR = _get('recovery_dir', 'MLT_RECOVERY', REPORTS)
PRIMARY_MAC  = _get('primary_mac', 'MLT_PRIMARY_MAC', '')
DB           = os.path.join(DATA, 'audio-hashes.sqlite')
SNAPS        = os.path.join(DATA, 'snapshots')
USER         = os.environ.get('USER') or os.path.basename(os.path.expanduser('~'))

for _d in (DATA, REPORTS, SNAPS):
    os.makedirs(_d, exist_ok=True)
