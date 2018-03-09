from __future__ import absolute_import
import logging
import sys
import re

from flask import request, current_app
from flask.ctx import has_request_context

from pythonjsonlogger.jsonlogger import JsonFormatter as BaseJSONFormatter

LOG_FORMAT = '%(asctime)s %(app_name)s %(name)s %(levelname)s ' \
             '%(trace_id)s "%(message)s" [in %(pathname)s:%(lineno)d]'

logger = logging.getLogger(__name__)


def init_app(app):
    app.config.setdefault('DM_LOG_LEVEL', 'INFO')
    app.config.setdefault('DM_APP_NAME', 'none')

    @app.after_request
    def after_request(response):
        current_app.logger.log(
            logging.ERROR if response.status_code // 100 == 5 else logging.INFO,
            '{method} {url} {status}',
            extra={
                'method': request.method,
                'url': request.url,
                'status': response.status_code
            })
        return response

    logging.getLogger().addHandler(logging.NullHandler())

    del app.logger.handlers[:]

    handler = get_handler(app)
    loglevel = logging.getLevelName(app.config['DM_LOG_LEVEL'])
    loggers = [app.logger, logging.getLogger('dmutils'), logging.getLogger('dmapiclient')]
    for logger in loggers:
        logger.addHandler(handler)
        logger.setLevel(loglevel)

    app.logger.info("Logging configured")


def configure_handler(handler, app, formatter):
    handler.setLevel(logging.getLevelName(app.config['DM_LOG_LEVEL']))
    handler.setFormatter(formatter)
    handler.addFilter(AppNameFilter(app.config['DM_APP_NAME']))
    handler.addFilter(RequestExtraContextFilter())

    return handler


def get_handler(app):
    if app.config.get('DM_PLAIN_TEXT_LOGS'):
        formatter = CustomLogFormatter(LOG_FORMAT)
    else:
        formatter = JSONFormatter(LOG_FORMAT)

    if app.config.get('DM_LOG_PATH'):
        handler = logging.FileHandler(app.config['DM_LOG_PATH'])
    else:
        handler = logging.StreamHandler(sys.stdout)

    return configure_handler(handler, app, formatter)


class AppNameFilter(logging.Filter):
    def __init__(self, app_name):
        self.app_name = app_name

    def filter(self, record):
        record.app_name = self.app_name

        return record


class RequestExtraContextFilter(logging.Filter):
    """
        Filter which will pull extra context from the current request's `get_extra_log_context` method (if present)
        and make this available on log records
    """
    def filter(self, record):
        if has_request_context() and callable(getattr(request, "get_extra_log_context", None)):
            for key, value in request.get_extra_log_context().items():
                setattr(record, key, value)

        return record


class CustomLogFormatter(logging.Formatter):
    """Accepts a format string for the message and formats it with the extra fields"""

    FORMAT_STRING_FIELDS_PATTERN = re.compile(r'\((.+?)\)', re.IGNORECASE)

    def add_fields(self, record):
        for field in self.FORMAT_STRING_FIELDS_PATTERN.findall(self._fmt):
            record.__dict__[field] = record.__dict__.get(field)
        return record

    def format(self, record):
        record = self.add_fields(record)
        msg = super(CustomLogFormatter, self).format(record)

        try:
            msg = msg.format(**record.__dict__)
        except:  # noqa
            # We know that KeyError, ValueError and IndexError are all possible things that can go
            # wrong here - there is no guarantee that the message passed into the logger is
            # actually suitable to be used as a format string. This is particularly so where an
            # we are logging arbitrary exception that may reference code.
            #
            # We catch all exceptions rather than just those three, because _any_ failure to format the
            # message must not result in an error, otherwise the original log message will never be
            # returned and written to the logs, and that might be important info such as an
            # exception.
            #
            # NB do not attempt to log either the exception or `msg` here, or you will
            # find that too fails and you end up with an infinite recursion / stack overflow.
            logger.info("failed to format log message")
        return msg


class JSONFormatter(BaseJSONFormatter):
    def process_log_record(self, log_record):
        for key, newkey in (
            ("asctime", "time",),
            ("trace_id", "requestId",),
            ("span_id", "spanId",),
            ("parent_span_id", "parentSpanId",),
            ("app_name", "application",),
        ):
            try:
                log_record[newkey] = log_record.pop(key)
            except KeyError:
                pass
        log_record['logType'] = "application"
        try:
            log_record['message'] = log_record['message'].format(**log_record)
        except KeyError as e:
            logger.exception("failed to format log message: {} not found".format(e))
        return log_record
