import logging
from logging.handlers import RotatingFileHandler
import inspect, os

optlog: logging.Logger = None

MAX_BYTES = 10_000_000 
BACKUP_COUNT = 5 # num of files
LOGGING_LEVEL = logging.DEBUG

def set_logger(name: str|None = None, level=LOGGING_LEVEL,
            max_bytes=MAX_BYTES, backup_count=BACKUP_COUNT) -> logging.Logger:
    """
    max_bytes: max size in bytes before rotation
    backup_count: number of backup files to keep
    """
    global optlog
    frame = inspect.stack()[1]  # caller frame
    # imported from scripts.xxx
    importer_dir = os.path.dirname(os.path.abspath(frame.filename))
    # log_dir located the same level as scripts
    log_dir = os.path.dirname(importer_dir)

    if optlog is not None:
        return optlog  # already initialized
    
    if name is None:
        name = os.path.splitext(os.path.basename(frame.filename))[0]

    optlog = logging.getLogger(name) # name is necessary not to override root logger
    optlog.setLevel(level)
    optlog.propagate = False

    if not optlog.handlers:  # avoid duplicate handlers on re-import
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%m/%d %H:%M:%S"
        )
        log_file = os.path.join(log_dir, 'log', f'{name}.log')
        fh = RotatingFileHandler(log_file, maxBytes=max_bytes, backupCount=backup_count)
        fh.setFormatter(formatter)

        sh = logging.StreamHandler()
        sh.setFormatter(formatter)

        optlog.addHandler(fh)
        optlog.addHandler(sh)
    return optlog

def log_raise(msg, logger=None):
    logger = logger or optlog # arg default value looped up only once in reading func def. when dynamically initiallizing, need to catch dynamically.
    logger.error(msg)
    raise Exception(msg) 
