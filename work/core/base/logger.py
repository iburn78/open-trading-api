import logging
from logging.handlers import RotatingFileHandler
import inspect, os, platform
system = platform.system()
if system == "Windows": import winsound

from .settings import LOG_DIR, Service

class LogSetup: # this is container that has logger
    MAX_BYTES = 10_000_000 
    BACKUP_COUNT = 9 # num of files
    F_LEVEL = logging.DEBUG # file logging level
    S_LEVEL = logging.DEBUG # stream logging level
    DATE_FMT = "%m%d_%H%M%S"

    def __init__(self, service: Service, fname=None):
        """
        max_bytes: max size in bytes before rotation
        backup_count: number of backup files to keep
        file names are automatically shifted
        - .1 is the newest
        - .n is the oldest
        """
        if fname is None:
            fname = os.path.splitext(os.path.basename(inspect.currentframe().f_back.f_code.co_filename))[0]

        fname += "_" + service

        os.makedirs(LOG_DIR, exist_ok=True)
        log_file = os.path.join(LOG_DIR, f'{fname}.log')
    
        self.logger = logging.getLogger(fname) 
        self.logger.setLevel(self.F_LEVEL)
        self.logger.propagate = False

        formatter = BriefFormatter(
            "%(asctime)s.%(msecs)03d [%(shortlevel)s] %(owner)s> %(message)s",
            datefmt=self.DATE_FMT
        )
        fh = RotatingFileHandler(log_file, maxBytes=self.MAX_BYTES, backupCount=self.BACKUP_COUNT, encoding='utf-8')
        fh.setFormatter(formatter)
        fh.setLevel(self.F_LEVEL)

        sh = logging.StreamHandler()
        sh.setFormatter(formatter)
        sh.setLevel(self.S_LEVEL)

        self.logger.addHandler(fh)
        self.logger.addHandler(sh)
        self.logger.addFilter(BeepFilter())

class BriefFormatter(logging.Formatter):
    LEVEL_MAP = {
        'DEBUG': 'D',
        'INFO': 'I',
        'WARNING': 'WARN',
        'ERROR': 'ERROR',
        'CRITICAL': 'CRITICAL'
    }

    # use extra={"owner": 'to_express_shortname'}
    def format(self, record: logging.LogRecord):
        record.shortlevel = self.LEVEL_MAP.get(record.levelname, '[ ]')
        record.owner = getattr(record, "owner", "")
        return super().format(record)

class BeepFilter(logging.Filter):
    BEEP_LEVEL = logging.WARNING 

    def filter(self, record):
        if record.levelno >= self.BEEP_LEVEL:
            self.log_beep(record.levelno)
        return True

    def log_beep(self, levelno):
        if levelno >= logging.CRITICAL:
            freq, dur = 900, 500
        elif levelno >= logging.ERROR:
            freq, dur = 600, 400
        elif levelno >= logging.WARNING:
            freq, dur = 400, 200
        else: 
            freq, dur = 400, 200
        notice_beep(freq, dur, msg=False)

def notice_beep(freq=400, dur=200, msg=True):
    if system == "Windows":
        if msg: 
            winsound.MessageBeep()
        else:
            winsound.Beep(freq, dur)
    elif system == "Darwin":
        os.system("say 'beep'")
    else:  # Linux / Unix
        print('\a') # makes sound
