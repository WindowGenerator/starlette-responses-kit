# Copied from starllete
import os
from pathlib import Path
from typing import AsyncIterator, Callable

import anyio
import pytest
from starlette import status
from starlette.background import BackgroundTask
from starlette.datastructures import Headers
from starlette.testclient import TestClient
from starlette.types import Message, Receive, Scope, Send

from starlette_responses_kit.file import FileResponse

TestClientFactory = Callable[..., TestClient]


def test_file_response(tmpdir: Path, test_client_factory: TestClientFactory) -> None:
    path = os.path.join(tmpdir, 'xyz')
    content = b'<file content>' * 1000
    with open(path, 'wb') as file:
        file.write(content)

    filled_by_bg_task = ''

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        async def numbers(minimum: int, maximum: int) -> AsyncIterator[str]:
            for i in range(minimum, maximum + 1):
                yield str(i)
                if i != maximum:
                    yield ', '
                await anyio.sleep(0)

        async def numbers_for_cleanup(start: int = 1, stop: int = 5) -> None:
            nonlocal filled_by_bg_task
            async for thing in numbers(start, stop):
                filled_by_bg_task = filled_by_bg_task + thing

        cleanup_task = BackgroundTask(numbers_for_cleanup, start=6, stop=9)

        response = FileResponse(path=path, filename='example.png', background=cleanup_task)
        await response(scope, receive, send)

    assert filled_by_bg_task == ''
    client = test_client_factory(app)
    response = client.get('/')
    expected_disposition = 'attachment; filename="example.png"'
    assert response.status_code == status.HTTP_200_OK
    assert response.content == content
    assert response.headers['content-type'] == 'image/png'
    assert response.headers['content-disposition'] == expected_disposition
    assert 'content-length' in response.headers
    assert 'last-modified' in response.headers
    assert 'etag' in response.headers
    assert filled_by_bg_task == '6, 7, 8, 9'


@pytest.mark.anyio
async def test_file_response_on_head_method(tmpdir: Path) -> None:
    path = os.path.join(tmpdir, 'xyz')
    content = b'<file content>' * 1000
    with open(path, 'wb') as file:
        file.write(content)

    app = FileResponse(path=path, filename='example.png')

    async def receive() -> Message:  # type: ignore[empty-body]
        ...  # pragma: no cover

    async def send(message: Message) -> None:
        if message['type'] == 'http.response.start':
            assert message['status'] == status.HTTP_200_OK
            headers = Headers(raw=message['headers'])
            assert headers['content-type'] == 'image/png'
            assert 'content-length' in headers
            assert 'content-disposition' in headers
            assert 'last-modified' in headers
            assert 'etag' in headers
        elif message['type'] == 'http.response.body':
            assert message['body'] == b''
            assert message['more_body'] is False

    # Since the TestClient drops the response body on HEAD requests, we need to test
    # this directly.
    await app({'type': 'http', 'method': 'head'}, receive, send)


def test_file_response_with_directory_raises_error(tmpdir: Path, test_client_factory: TestClientFactory) -> None:
    app = FileResponse(path=tmpdir, filename='example.png')
    client = test_client_factory(app)
    with pytest.raises(RuntimeError) as exc_info:
        client.get('/')
    assert 'is not a file' in str(exc_info.value)


def test_file_response_with_missing_file_raises_error(tmpdir: Path, test_client_factory: TestClientFactory) -> None:
    path = os.path.join(tmpdir, '404.txt')
    app = FileResponse(path=path, filename='404.txt')
    client = test_client_factory(app)
    with pytest.raises(RuntimeError) as exc_info:
        client.get('/')
    assert 'does not exist' in str(exc_info.value)


def test_file_response_with_chinese_filename(tmpdir: Path, test_client_factory: TestClientFactory) -> None:
    content = b'file content'
    filename = '你好.txt'  # probably "Hello.txt" in Chinese
    path = os.path.join(tmpdir, filename)
    with open(path, 'wb') as f:
        f.write(content)
    app = FileResponse(path=path, filename=filename)
    client = test_client_factory(app)
    response = client.get('/')
    expected_disposition = "attachment; filename*=utf-8''%E4%BD%A0%E5%A5%BD.txt"
    assert response.status_code == status.HTTP_200_OK
    assert response.content == content
    assert response.headers['content-disposition'] == expected_disposition


def test_file_response_with_inline_disposition(tmpdir: Path, test_client_factory: TestClientFactory) -> None:
    content = b'file content'
    filename = 'hello.txt'
    path = os.path.join(tmpdir, filename)
    with open(path, 'wb') as f:
        f.write(content)
    app = FileResponse(path=path, filename=filename, content_disposition_type='inline')
    client = test_client_factory(app)
    response = client.get('/')
    expected_disposition = 'inline; filename="hello.txt"'
    assert response.status_code == status.HTTP_200_OK
    assert response.content == content
    assert response.headers['content-disposition'] == expected_disposition


@pytest.mark.anyio
async def test_file_response_with_pathsend(tmpdir: Path) -> None:
    path = os.path.join(tmpdir, 'xyz')
    content = b'<file content>' * 1000
    with open(path, 'wb') as file:
        file.write(content)

    app = FileResponse(path=path, filename='example.png')

    async def receive() -> Message:  # type: ignore[empty-body]
        ...  # pragma: no cover

    async def send(message: Message) -> None:
        if message['type'] == 'http.response.start':
            assert message['status'] == status.HTTP_200_OK
            headers = Headers(raw=message['headers'])
            assert headers['content-type'] == 'image/png'
            assert 'content-length' in headers
            assert 'content-disposition' in headers
            assert 'last-modified' in headers
            assert 'etag' in headers
        elif message['type'] == 'http.response.pathsend':
            assert message['path'] == str(path)

    # Since the TestClient doesn't support `pathsend`, we need to test this directly.
    await app(
        {'type': 'http', 'method': 'get', 'extensions': {'http.response.pathsend': {}}},
        receive,
        send,
    )


def test_file_response_known_size(tmpdir: Path, test_client_factory: TestClientFactory) -> None:
    path = os.path.join(tmpdir, 'xyz')
    content = b'<file content>' * 1000
    with open(path, 'wb') as file:
        file.write(content)

    app = FileResponse(path=path, filename='example.png')
    client: TestClient = test_client_factory(app)
    response = client.get('/')
    assert response.headers['content-length'] == str(len(content))
