# -*- coding: utf-8 -*-
import base64
from datetime import datetime

import mock
import pytest
from cryptography import fernet
from freezegun import freeze_time

from dmutils.config import init_app
from dmutils.email.tokens import (
    generate_token,
    decode_token,
    decode_invitation_token,
    decode_password_reset_token,
    _parse_fernet_timestamp
)
from dmutils.email.helpers import hash_string


@pytest.yield_fixture
def email_app(app):
    init_app(app)
    app.config['SHARED_EMAIL_KEY'] = 'Key'
    app.config['INVITE_EMAIL_SALT'] = 'Salt'
    app.config['SECRET_KEY'] = 'Secret'
    app.config['RESET_PASSWORD_SALT'] = 'PassSalt'
    yield app


@pytest.fixture
def data_api_client(user_json):
    user_json['users']['passwordChangedAt'] = '2016-01-01T12:00:00.30Z'
    data_api_client = mock.Mock()
    data_api_client.get_user.return_value = user_json
    return data_api_client


@pytest.fixture
def password_reset_token():
    return {'user': 123, 'email': 'test@example.com'}


def test_can_generate_and_decode_token():

    with freeze_time('2016-01-01T12:00:00Z'):
        encrypted_token = generate_token(
            {'key1': 'value1', 'key2': 'value2'},
            secret_key='1234567890',
            namespace='0987654321'
        )
        token, timestamp = decode_token(encrypted_token, '1234567890', '0987654321')
    assert token == {'key1': 'value1', 'key2': 'value2'}
    assert timestamp == datetime(2016, 1, 1, 12, 0, 0)


def test_cant_decode_token_with_wrong_salt():
    token = generate_token({
        'key1': 'value1',
        'key2': 'value2'},
        secret_key='1234567890',
        namespace='1234567890')

    with pytest.raises(fernet.InvalidToken):
        decode_token(token, '1234567890', 'failed')


def test_cant_decode_token_with_wrong_key():
    token = generate_token({
        'key1': 'value1',
        'key2': 'value2'},
        secret_key='1234567890',
        namespace='1234567890')

    with pytest.raises(fernet.InvalidToken):
        decode_token(token, 'failed', '1234567890')


@pytest.mark.parametrize('test, expected', [
    (u'test@example.com', b'lz3-Rj7IV4X1-Vr1ujkG7tstkxwk5pgkqJ6mXbpOgTs='),
    (u'☃@example.com', b'jGgXle8WEBTTIFhP25dF8Ck-FxQSCZ_N0iWYBWve4Ps='),
])
def test_hash_string(test, expected):
    expected = expected.decode('utf-8')
    result = hash_string(test)
    assert result == expected


def test_generate_token_does_not_contain_plaintext_email(email_app, data_api_client, password_reset_token):
    with email_app.app_context(), freeze_time('2016-01-01T12:00:00.30Z'):
        token = generate_token(password_reset_token, 'Secret', 'PassSalt')

    # a fernet string always starts with the version, which should be 128
    assert token[:4] == 'gAAA'

    token = token.encode('utf-8')

    # Personally identifiable information should not be readable without secret key
    assert b'test@example.com' not in base64.urlsafe_b64decode(token)

    # a fernet string contains the timestamp at which it was encrypted
    assert _parse_fernet_timestamp(token) == datetime(2016, 1, 1, 12)


def test_decrypt_token_ok_for_known_good_token():
    # encrypted on 2016-01-01T12:00:00.30Z with secret 'Secret' and namespace 'PassSalt'
    token = 'gAAAAABWhmpA1ecLpuzdKiIcJ_drdA1Vf4ip07TH3UqZ_fA-pD9yYlGMqSTi-Mpbd58Z-wlZfa5sXGE6FVHPilTpsZWEiMDRLdCBlccvBPbY9IOO5F3uabjkrk87mrlPxaSbMAza5Nku'  # noqa

    with freeze_time('2016-01-01T12:00:00.30Z'):
        data = decode_token(token, 'Secret', 'PassSalt')

    assert data == ({'email': 'test@example.com', 'user': 123}, datetime(2016, 1, 1, 12, 0, 0))


def test_decode_password_reset_token_ok_for_good_token(email_app, data_api_client, password_reset_token):
    with email_app.app_context():
        token = generate_token(password_reset_token, "Key", 'PassSalt')
        assert decode_password_reset_token(token, data_api_client) == password_reset_token
    data_api_client.get_user.assert_called_once_with(123)


def test_decode_password_reset_token_does_not_work_if_bad_token(email_app, data_api_client, password_reset_token):
    token = generate_token(password_reset_token, "Key", 'PassSalt')[1:]

    with email_app.app_context():
        assert decode_password_reset_token(token, data_api_client) == {'error': 'token_invalid'}


def test_decode_password_reset_token_does_not_work_if_token_expired(email_app, data_api_client, password_reset_token):
    with freeze_time('2015-01-02 03:04:05'):
        # Token was generated a year before current time
        token = generate_token(password_reset_token, "Key", 'PassSalt')

    with freeze_time('2016-01-02 03:04:05'):
        with email_app.app_context():
            assert decode_password_reset_token(token, data_api_client) == {'error': 'token_invalid'}


def test_decode_password_reset_token_does_not_work_if_password_changed_later_than_token(
    email_app, data_api_client, password_reset_token
):
    with freeze_time('2016-01-01T11:00:00.30Z'):
        # Token was generated an hour earlier than password was changed
        token = generate_token(password_reset_token, "Key", 'PassSalt')

    with freeze_time('2016-01-01T13:00:00.30Z'):
        # Token is two hours old; password was changed an hour ago
        with email_app.app_context():
            assert decode_password_reset_token(token, data_api_client) == {'error': 'token_invalid'}


def test_decode_invitation_token_decodes_ok(email_app):
    with email_app.app_context():
        # works with arbitrary fields
        data = {
            'email_address': 'test-user@email.com',
            'supplier_id': 1234,
            'foo': 'bar',
            'role': 'supplier'
        }
        token = generate_token(data, 'Key', 'Salt')
        assert decode_invitation_token(token) == data


def test_decode_invitation_token_returns_an_error_if_token_invalid(email_app):
    with email_app.app_context():
        data = {
            'email_address': 'test-user@email.com',
            'supplier_id': 1234,
            'supplier_name': 'A. Supplier',
            'role': 'supplier'
        }
        token = generate_token(data, email_app.config['SHARED_EMAIL_KEY'], email_app.config['INVITE_EMAIL_SALT'])[1:]

        assert decode_invitation_token(token) == {'error': 'token_invalid'}


def test_decode_invitation_token_returns_an_error_and_role_if_token_expired(email_app):
    with freeze_time('2015-01-02 03:04:05'):
        data = {
            'email_address': 'test-user@email.com',
            'supplier_id': 1234,
            'supplier_name': 'A. Supplier',
            'role': 'supplier'
        }
        token = generate_token(data, email_app.config['SHARED_EMAIL_KEY'], email_app.config['INVITE_EMAIL_SALT'])
    with email_app.app_context():

        assert decode_invitation_token(token) == {'error': 'token_expired', 'role': 'supplier'}


def test_decode_invitation_token_adds_the_role_key_to_expired_old_style_buyer_tokens(email_app):
    with freeze_time('2015-01-02 03:04:05'):
        data = {'email_address': 'test-user@email.com'}
        token = generate_token(data, 'Key', 'Salt')

    with email_app.app_context():
        assert decode_invitation_token(token) == {
            'error': 'token_expired',
            'role': 'buyer'
        }


def test_decode_invitation_token_adds_the_role_key_to_expired_old_style_supplier_tokens(email_app):
    with freeze_time('2015-01-02 03:04:05'):
        data = {
            'email_address': 'test-user@email.com',
            'supplier_id': 1234,
            'supplier_name': 'A. Supplier',
        }
        token = generate_token(data, 'Key', 'Salt')

    with email_app.app_context():
        assert decode_invitation_token(token) == {
            'error': 'token_expired',
            'role': 'supplier'
        }
