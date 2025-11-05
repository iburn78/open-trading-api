import logging
from logging.handlers import RotatingFileHandler
import inspect, os

# --- Global logger instance ---
optlog: logging.Logger | None = None

MAX_BYTES = 10_000_000 
BACKUP_COUNT = 5 # num of files
F_LEVEL = logging.DEBUG # file logging level
S_LEVEL = logging.DEBUG # stream logging level

def set_logger(fname: str|None = None, flevel = F_LEVEL, slevel= S_LEVEL,
            max_bytes=MAX_BYTES, backup_count=BACKUP_COUNT) -> logging.Logger:
    """
    max_bytes: max size in bytes before rotation
    backup_count: number of backup files to keep
    """
    global optlog

    if optlog is not None:
        return optlog  # already initialized

    frame = inspect.stack()[1]  # caller frame
    # imported from scripts.xxx
    importer_dir = os.path.dirname(os.path.abspath(frame.filename))
    # log_dir located the same level as scripts
    log_dir = os.path.dirname(importer_dir)
    os.makedirs(os.path.join(log_dir, 'log'), exist_ok=True)
    
    if fname is None:
        fname = os.path.splitext(os.path.basename(frame.filename))[0]

    optlog = logging.getLogger(fname) # name is necessary not to override root logger
    optlog.setLevel(flevel)
    optlog.propagate = False

    if not optlog.handlers:  # avoid duplicate handlers on re-import
        formatter = logging.Formatter(
            "%(asctime)s.%(msecs)03d [%(levelname)s] %(name)s> %(message)s",
            datefmt="%m/%d %H:%M:%S"
        )
        log_file = os.path.join(log_dir, 'log', f'{fname}.log')
        fh = RotatingFileHandler(log_file, maxBytes=max_bytes, backupCount=backup_count)
        fh.setFormatter(formatter)
        fh.setLevel(flevel)

        sh = logging.StreamHandler()
        sh.setFormatter(formatter)
        sh.setLevel(slevel)

        optlog.addHandler(fh)
        optlog.addHandler(sh)

        # --- Wrap standard methods to allow name= dynamically ---
        for level in ["debug", "info", "warning", "error", "critical"]:
            orig = getattr(optlog, level)
            def wrapper(*args, _orig=orig, name=None, msg=None, **kwargs):
                text = msg or (args[0] if args else "")
                if name:
                    text = f"{name}> {text}"
                _orig(text, **kwargs)
            setattr(optlog, level, wrapper)

    return optlog

def log_raise(msg, logger=None, name=None):
    logger = logger or optlog # arg default value looped up only once in reading func def. when dynamically initiallizing, need to catch dynamically.
    if name:
        msg = f"{name}> {msg}"
    logger.error(msg)
    raise Exception(msg) 
