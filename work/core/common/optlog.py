import logging
from logging.handlers import RotatingFileHandler
import inspect, os
import re
from datetime import datetime

# --- Global logger instance ---
optlog: logging.Logger | None = None

MAX_BYTES = 10_000_000 
BACKUP_COUNT = 5 # num of files
F_LEVEL = logging.DEBUG # file logging level
S_LEVEL = logging.DEBUG # stream logging level

LOG_INDENT = "                        "

LEVEL_MAP = {
    'DEBUG': 'D',
    'INFO': 'I',
    'WARNING': 'WARN',
    'ERROR': 'ERROR',
    'CRITICAL': 'CRITICAL'
}

# note that .milisecond(3 digits) is missing here.
DATE_FMT = "%m%d_%H%M%S"

ppd_ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) # ../..
log_dir = os.path.join(ppd_, 'log')
os.makedirs(log_dir, exist_ok=True)

class BriefFormatter(logging.Formatter):

    def format(self, record):
        # Replace levelname with short version
        record.shortlevel = LEVEL_MAP.get(record.levelname, '[ ]')
        # Take only the first letter of the logger's name
        if record.name: 
            if 'server' in record.name.lower():
                record.shortname = 'sv'
            elif 'client' in record.name.lower():
                record.shortname = 'cl'
            else:
                record.shortname = record.name
        else:
            record.shortname = '[ ]'
        return super().format(record)

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
    
    if fname is None:
        fname = os.path.splitext(os.path.basename(frame.filename))[0]

    optlog = logging.getLogger(fname) # name is necessary not to override root logger
    optlog.setLevel(flevel)
    optlog.propagate = False

    if not optlog.handlers:  # avoid duplicate handlers on re-import
        formatter = BriefFormatter(
            "%(asctime)s.%(msecs)03d [%(shortlevel)s] %(shortname)s> %(message)s",
            datefmt=DATE_FMT
        )
        log_file = os.path.join(log_dir, f'{fname}.log')
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
    logger.critical(msg)
    raise Exception(msg) 

# can assign default_name to name argument
class ModuleLogger:
    def __init__(self, logger, default_name=None):
        self._logger = logger
        self._default_name = default_name

    # let the name checker checking possible
    # def debug(self): pass
    # def info(self): pass
    # def warning(self): pass
    # def error(self): pass
    # def critical(self): pass

    def __getattr__(self, attr):
        # dynamically wrap debug/info/warning/error/critical
        orig = getattr(self._logger, attr)
        def wrapper(msg, *args, **kwargs):
            orig(msg, *args, name=self._default_name, **kwargs)
        return wrapper

# --- usage ---
# logger = ModuleLogger(optlog, default_name="KIS_ORIGNIAL_CODES")
# logger.info("Hello world")       # logs: "KIS_ORIGNIAL_CODES> Hello world"
# logger.error("Something failed") # logs: "KIS_ORIGINAL_CODES> Something failed"# 



# -------------------------------------------------------------------------------
# Filter Functions
# -------------------------------------------------------------------------------
date_pattern = DATE_FMT.replace("%m", r"\d{2}") \
                .replace("%d", r"\d{2}") \
                .replace("%H", r"\d{2}") \
                .replace("%M", r"\d{2}") \
                .replace("%S", r"\d{2}")

LOG_START_PATTERN = re.compile(rf"^({date_pattern}\.\d{{3}}) \[({'|'.join(LEVEL_MAP.values())})\]")
LEVEL_ORDER = {v: i * 10 for i, v in enumerate(LEVEL_MAP.values(), start=1)}  # auto derive from LEVEL_MAP

def parse_timestamp(ts: str) -> datetime:
    fmt = DATE_FMT + ".%f"
    return datetime.strptime(ts, fmt)

def log_filter(
    infile_name: str, # name only (without .log)
    start_time: str | None = None,
    end_time: str | None = None,
    level: str = next(iter(LEVEL_MAP)),  # default to first key (DEBUG)
    outfile: str | None = None,
):
    """Filter logs by time range and minimum level."""
    # --- prepare thresholds ---
    min_level_value = LEVEL_ORDER.get(LEVEL_MAP.get(level, 'W'), 0)

    start_dt = parse_timestamp(start_time) if start_time else None
    end_dt = parse_timestamp(end_time) if end_time else None

    # --- read file ---
    infile = os.path.join(log_dir, infile_name+'.log')

    with open(infile, "r", encoding="utf-8") as f:
        lines = f.readlines()

    blocks, current_block = [], []
    for line in lines:
        if LOG_START_PATTERN.match(line):
            if current_block:
                blocks.append("".join(current_block))
                current_block = []
        current_block.append(line)
    if current_block:
        blocks.append("".join(current_block))

    # --- filter ---
    filtered = []
    for block in blocks:
        m = LOG_START_PATTERN.match(block)
        if not m:
            continue
        ts_str, lvl = m.groups()
        lvl_value = LEVEL_ORDER.get(lvl, 0)
        if lvl_value < min_level_value:
            continue

        ts = parse_timestamp(ts_str)
        if start_dt and ts < start_dt:
            continue
        if end_dt and ts > end_dt:
            continue

        filtered.append(block)

    # --- output ---
    outfile = outfile or f"{infile.rsplit('.', 1)[0]}_{level}.log"
    with open(outfile, "w", encoding="utf-8") as f:
        f.writelines(filtered)

    print(f"Extracted {len(filtered)} log entries → {outfile}")


def grep_logs(search_str: str, infile_name: str, outfile: str | None = None):
    """
    Search logs for blocks containing `search_str` (like grep), considering multi-line log entries.
    Ignores any initial lines that don't match LOG_START_PATTERN.
    """
    infile = os.path.join(log_dir, infile_name+'.log')
    with open(infile, "r", encoding="utf-8") as f:
        lines = f.readlines()

    blocks = []
    current_block = []
    collecting = False  # flag: have we started the first matching log?

    for line in lines:
        if LOG_START_PATTERN.match(line):
            if current_block:
                blocks.append("".join(current_block))
            current_block = [line]
            collecting = True
        else:
            if collecting:
                current_block.append(line)
            # else: still skipping lines until first match

    if current_block:
        blocks.append("".join(current_block))

    # filter blocks containing the search string
    filtered = [b for b in blocks if search_str in b]

    # output
    outfile = outfile or f"{infile.rsplit('.', 1)[0]}_{search_str}.log"
    with open(outfile, "w", encoding="utf-8") as f:
        f.writelines(filtered)

    print(f"Found {len(filtered)} matching log entries → {outfile}")
