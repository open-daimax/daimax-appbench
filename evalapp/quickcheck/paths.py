"""Default data location, independent of source checkout and global evalapp configuration."""
from pathlib import Path

def default_output_dir():
    return Path('~/eval_app_factory/quickcheck').expanduser()
