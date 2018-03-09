from __future__ import absolute_import
import tempfile
import logging
try:
    from StringIO import StringIO
except ImportError:
    from io import StringIO
import json

import mock

from flask import request

from dmutils.logging import init_app, RequestExtraContextFilter, JSONFormatter, CustomLogFormatter
from dmutils.logging import LOG_FORMAT


def test_request_extra_context_filter_not_in_app_context():
    # using spec_set to ensure no attribute-setting is attempted on this "record"
    result = RequestExtraContextFilter().filter(mock.Mock(spec_set=[]))
    assert result.called is False


def test_request_extra_context_filter_in_app_context(app):
    with app.test_request_context('/'):
        test_extra_log_context = {
            "poldy": "Old Ollebo, M. P.",
            "Dante": "Riordan",
        }
        # add a simple mock callable instead of using our full custom request implementation
        request.get_extra_log_context = mock.Mock(spec_set=[])
        request.get_extra_log_context.return_value = test_extra_log_context

        # using spec_set to ensure only our listed keys are set on this "record"
        result = RequestExtraContextFilter().filter(mock.Mock(spec_set=list(test_extra_log_context.keys())))

        assert request.get_extra_log_context.call_args_list == [()]  # a single zero-arg call
        # ...and the mock record should have all its values set appropriately
        assert {k: getattr(result, k) for k in test_extra_log_context.keys()} == test_extra_log_context


def test_request_extra_context_filter_no_method(app):
    with app.test_request_context('/'):
        # not adding a get_extra_log_context mock method to request to check we behave gracefully when not using a
        # request class that implements this

        # using spec_set to ensure no attribute-setting is attempted on this "record"
        result = RequestExtraContextFilter().filter(mock.Mock(spec_set=[]))
        assert result.called is False


def test_init_app_adds_stream_handler_without_log_path(app):
    init_app(app)

    assert len(app.logger.handlers) == 1
    assert isinstance(app.logger.handlers[0], logging.StreamHandler)
    assert isinstance(app.logger.handlers[0].formatter, JSONFormatter)


def test_init_app_adds_file_handler_with_log_path(app):
    with tempfile.NamedTemporaryFile() as f:
        app.config['DM_LOG_PATH'] = f.name
        init_app(app)

        assert len(app.logger.handlers) == 1
        assert isinstance(app.logger.handlers[0], logging.FileHandler)
        assert isinstance(app.logger.handlers[0].formatter, JSONFormatter)


def test_init_app_adds_stream_handler_with_plain_text_format_when_config_env_set(app):
    app.config['DM_PLAIN_TEXT_LOGS'] = True
    init_app(app)

    assert len(app.logger.handlers) == 1
    assert isinstance(app.logger.handlers[0], logging.StreamHandler)
    assert isinstance(app.logger.handlers[0].formatter, CustomLogFormatter)


def test_app_after_request_logs_responses_with_info_level(app):
    # since app.logger is a read-only property we need to patch the Flask class
    with mock.patch('flask.Flask.logger') as logger:
        app.test_client().get('/')

        logger.log.assert_called_once_with(
            logging.INFO,
            '{method} {url} {status}',
            extra={'url': u'http://localhost/', 'status': 404, 'method': 'GET'}
        )


def test_app_after_request_logs_5xx_responses_with_error_level(app):
    @app.route('/')
    def error_route():
        return 'error', 500

    # since app.logger is a read-only property we need to patch the Flask class
    with mock.patch('flask.Flask.logger') as logger:
        app.test_client().get('/')

        logger.log.assert_called_once_with(
            logging.ERROR,
            '{method} {url} {status}',
            extra={'url': u'http://localhost/', 'status': 500, 'method': 'GET'}
        )


class TestJSONFormatter(object):
    def _create_logger(self, name, formatter):
        logger = logging.getLogger(name)
        logger.setLevel(logging.DEBUG)
        buffer = StringIO()
        handler = logging.StreamHandler(buffer)
        handler.setFormatter(formatter)
        logger.addHandler(handler)

        return logger, buffer

    def setup(self):
        self.formatter = JSONFormatter(LOG_FORMAT)
        self.logger, self.buffer = self._create_logger('logging-test', self.formatter)
        self.dmlogger, self.dmbuffer = self._create_logger('dmutils', self.formatter)

    def teardown(self):
        del self.logger.handlers[:]
        del self.dmlogger.handlers[:]

    def test_json_formatter_renames_fields(self):
        self.logger.info("hello")
        result = json.loads(self.buffer.getvalue())
        self.dmbuffer.getvalue()

        assert 'time' in result
        assert 'asctime' not in result
        assert 'requestId' in result
        assert 'trace_id' not in result
        assert 'application' in result
        assert 'app_name' not in result

    def test_log_type_is_set_to_application(self):
        self.logger.info("hello")
        result = json.loads(self.buffer.getvalue())
        self.dmbuffer.getvalue()

        assert result['logType'] == 'application'

    def test_log_message_gets_formatted(self):
        self.logger.info("hello {foo}", extra={'foo': 'bar'})
        result = json.loads(self.buffer.getvalue())
        self.dmbuffer.getvalue()

        assert result['message'] == "hello bar"

    def test_log_message_is_unchanged_if_fields_are_not_found(self):
        self.logger.info("hello {bar}")
        result = json.loads(self.buffer.getvalue())

        assert result['message'] == "hello {bar}"

    def test_failed_log_message_formatting_logs_an_error(self):
        self.logger.info("hello {barry}")
        raw_result = self.dmbuffer.getvalue()
        result = json.loads(raw_result)

        assert result['message'].startswith("failed to format log message")


class TestCustomLogFormatter(object):
    def _create_logger(self, name, formatter):
        logger = logging.getLogger(name)
        logger.setLevel(logging.DEBUG)
        buffer = StringIO()
        handler = logging.StreamHandler(buffer)
        handler.setFormatter(formatter)
        logger.addHandler(handler)

        return logger, buffer

    def setup(self):
        self.formatter = CustomLogFormatter(LOG_FORMAT)
        self.logger, self.buffer = self._create_logger('logging-test', self.formatter)
        self.dmlogger, self.dmbuffer = self._create_logger('dmutils', self.formatter)

    def teardown(self):
        del self.logger.handlers[:]
        del self.dmlogger.handlers[:]

    def test_log_message_gets_formatted(self):
        self.logger.info("hello {foo}", extra={'foo': 'bar'})
        result = self.buffer.getvalue()

        assert '"hello bar"' in result

    def test_log_message_is_unchanged_if_fields_are_not_found(self):
        self.logger.info("hello {bar}")
        result = self.buffer.getvalue()

        assert '"hello {bar}"' in result

    def test_failed_log_message_formatting_logs_an_error(self):
        self.logger.info("hello {barry}")
        result = self.dmbuffer.getvalue()

        assert 'failed to format log message' in result

    def test_failed_log_message_formatting_still_logs(self):
        self.logger.info("hello {")

        assert 'failed to format log message' in self.dmbuffer.getvalue()
        assert 'hello {' in self.buffer.getvalue()
