import functools
from configparser import ConfigParser
import logging
import io


class CustomLogger:

    def __init__(self, config_ini='config/config.ini'):
        self.config = ConfigParser()
        self.config.read(config_ini)
        logging.basicConfig(format='%(asctime)s - %(levelname)s - %(module)s - %(message)s',
                            level=self.config['LOG']['level'])
        self.logger = logging.getLogger()

    def info(self, msg, *args, **kwargs):
        self.logger.info(msg, *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        self.logger.warning(msg, *args, **kwargs)

    def exception(self, msg, *args, **kwargs):
        self.logger.exception(msg, *args, **kwargs)

    def critical(self, msg, *args, **kwargs):
        self.logger.critical(msg, *args, **kwargs)

    def debug(self, msg, *args, **kwargs):
        self.logger.debug(msg, *args, **kwargs)

    def log(self, _func=None, *, my_logger=None):
        def decorator_log(func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                logger = self.logger
                try:
                    if my_logger is None:
                        first_args = next(iter(args), None)  # capture first arg to check for `self`
                        logger_params = [  # does kwargs have any logger
                            x
                            for x in kwargs.values()
                            if isinstance(x, logging.Logger) or isinstance(x, CustomLogger)
                        ] + [  # # does args have any logger
                            x
                            for x in args
                            if isinstance(x, logging.Logger) or isinstance(x, CustomLogger)
                        ]
                        if hasattr(first_args, "__dict__"):  # is first argument `self`
                            logger_params = logger_params + [
                                x
                                for x in first_args.__dict__.values()  # does class (dict) members have any logger
                                if isinstance(x, logging.Logger)
                                or isinstance(x, CustomLogger)
                            ]
                        h_logger = next(iter(logger_params), CustomLogger())  # get the next/first/default logger
                    else:
                        h_logger = my_logger  # logger is passed explicitly to the decorator

                    if isinstance(h_logger, CustomLogger):
                        logger = h_logger.get_logger(func.__name__)
                    else:
                        logger = h_logger

                    args_repr = [repr(a) for a in args]
                    kwargs_repr = [f"{k}={v!r}" for k, v in kwargs.items()]
                    signature = ", ".join(args_repr + kwargs_repr)
                    logger.debug(f"function {func.__name__} called with args {signature}")
                except Exception:
                    pass

                try:
                    result = func(*args, **kwargs)
                    return result
                except Exception as e:
                    logger.exception(f"Exception raised in {func.__name__}. exception: {str(e)}")
                    raise e
            return wrapper

        if _func is None:
            return decorator_log
        else:
            return decorator_log(_func)


class TqdmToLogger(io.StringIO):
    """
        Output stream for TQDM which will output to logger module instead of
        the StdOut.
    """
    logger = None
    level = None
    buf = ''
    def __init__(self,logger,level=None):
        super(TqdmToLogger, self).__init__()
        self.logger = logger
        self.level = level or logging.INFO
    def write(self,buf):
        self.buf = buf.strip('\r\n\t ')
    def flush(self):
        self.logger.log(self.level, self.buf)
